"""The traffic log and latency metrics of the gateway (see ``docs/operations.md``).

- ``GET /v1/traffic?limit=50&after=<seq>``: the most recent events, oldest first.
- ``POST /v1/traffic``: ingest scrubbed ``masked`` or ``stats`` traffic events from a local
  gateway (`PII_GUARD_REMOTE_URL`). Never accepts ``full`` events, ``request.original`` or
  ``response.unmasked``.
- ``GET /v1/traffic/stream``: server-sent events, one ``traffic`` event per gateway call
  (``?replay=N`` sends the last N stored events first), a comment line every 15 s to keep
  proxies from closing the connection.
- ``GET /metrics``: Prometheus text, when ``PII_GUARD_METRICS`` is on.

The traffic routes answer 404 ``traffic_log_disabled`` while ``PII_GUARD_TRAFFIC_LOG=off``
(the default). Events live in memory only (:class:`~pii_guard.observability.TrafficLog`).

Hosted mode: with no endpoint selected, a project's Logs merge its own runtime and every one
of its endpoint runtimes (one owner-wide ``seq``, each endpoint event tagged ``endpoint``);
``X-PII-Guard-Endpoint`` narrows the view to one endpoint (LAB-1492).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import math
import secrets
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from fastapi import Query, Request
from starlette.responses import PlainTextResponse, StreamingResponse

from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import request_metrics, v1_router
from pii_guard.observability import (
    Observability,
    RemoteTrafficLevel,
    TrafficLog,
    sanitize_for_remote,
)
from pii_guard.observability.timing import STAGES
from pii_guard.observability.traffic import TrafficFeedView
from pii_guard.types import EntityType, PiiGuardError

if TYPE_CHECKING:
    from pii_guard.observability.metrics import LatencyMetrics

__all__ = ["TrafficIngestError", "TrafficLogDisabledError", "router"]

router = v1_router()
router.tags = ["observability"]

_KEEPALIVE_SECONDS = 15.0
_MAX_INGEST_EVENTS = 50
_VALID_OUTCOMES = frozenset(
    {"ok", "upstream_error", "upstream_failed", "blocked", "refused", "error"}
)
_VALID_MODES = frozenset({"fast", "audit", "strict", "-"})
_VALID_STAGES = frozenset(STAGES)
_VALID_DETECTORS = frozenset({"rules", "ner", "llm", "known"})
_VALID_ENTITY_TYPES = frozenset(t.value for t in EntityType)
_VALID_OUTBOUND_RESULTS = frozenset({"passed", "blocked"})


class TrafficLogDisabledError(PiiGuardError):
    code = "traffic_log_disabled"
    status_code = 404


class TrafficIngestError(PiiGuardError):
    code = "invalid_request"
    status_code = 422


class TrafficIngestMediaTypeError(PiiGuardError):
    code = "unsupported_media_type"
    status_code = 415


class MetricsDisabledError(PiiGuardError):
    code = "metrics_disabled"
    status_code = 404


class MetricsUnauthorizedError(PiiGuardError):
    code = "unauthorized"
    status_code = 401
    headers: ClassVar[dict[str, str]] = {"WWW-Authenticate": 'Bearer realm="pii-guard"'}


def _observability(request: Request) -> Observability:
    runtime = getattr(getattr(request, "state", None), "hosted_runtime", None)
    if runtime is not None:
        return runtime.observability
    obs = getattr(request.app.state, "observability", None)
    if obs is None:
        obs = Observability()
        request.app.state.observability = obs
    return obs


def _traffic(request: Request) -> TrafficLog | TrafficFeedView:
    # Hosted project Logs with no endpoint selected: the project's runtime and its endpoint
    # runtimes, merged under the owner's one sequence (LAB-1492).
    view = getattr(getattr(request, "state", None), "hosted_traffic", None)
    traffic = view if view is not None else _observability(request).traffic
    if not traffic.enabled:
        raise TrafficLogDisabledError(
            "the traffic log is off; set PII_GUARD_TRAFFIC_LOG=masked (or full, on localhost)"
        )
    return traffic


_TRAFFIC_ERRORS = error_responses("traffic_log_disabled", "invalid_request")
_TRAFFIC_INGEST_ERRORS = error_responses(
    "traffic_log_disabled", "invalid_request", "payload_too_large", "unsupported_media_type"
)


def _validate_ingested_event(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TrafficIngestError("each traffic event must be a JSON object")
    level = raw.get("level")
    if level not in (None, "masked", "stats"):
        raise TrafficIngestError("remote traffic events must have level 'masked' or 'stats'")
    if "original" in raw or "unmasked" in raw:
        raise TrafficIngestError("unmasked payloads are not accepted by remote traffic ingest")
    req_payload = raw.get("request")
    if req_payload is not None and (
        not isinstance(req_payload, dict)
        or "original" in req_payload
        or not set(req_payload).issubset({"masked", "thumbnails"})
    ):
        raise TrafficIngestError(
            "traffic event request payload may only contain 'masked' and 'thumbnails'"
        )
    resp_payload = raw.get("response")
    if resp_payload is not None and (
        not isinstance(resp_payload, dict)
        or "unmasked" in resp_payload
        or not set(resp_payload).issubset({"masked", "chunks"})
    ):
        raise TrafficIngestError(
            "traffic event response payload may only contain 'masked' and 'chunks'"
        )
    remote_level = RemoteTrafficLevel.STATS if level == "stats" else RemoteTrafficLevel.MASKED
    clean = sanitize_for_remote(raw, level=remote_level)
    event_id = clean.get("id")
    if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 128:
        clean["id"] = "req_" + secrets.token_hex(8)
    event_time = clean.get("time")
    if not isinstance(event_time, str) or not event_time.strip() or len(event_time) > 64:
        clean["time"] = datetime.now(UTC).isoformat(timespec="milliseconds")
    route = clean.get("route")
    if not isinstance(route, str) or not route.strip() or len(route) > 128:
        clean["route"] = "/v1/chat/completions"
    outcome = clean.get("outcome")
    if outcome not in _VALID_OUTCOMES:
        clean["outcome"] = "error"  # never show an unknown remote outcome as a success
    # Set here, never taken from the sender: ingested calls are told apart from local ones.
    clean["source"] = "remote"
    clean["stream"] = bool(clean.get("stream", False))
    clean["session_new"] = bool(clean.get("session_new", False))
    detectors = clean.get("detectors")
    clean["detectors"] = (
        [d for d in detectors if isinstance(d, str) and len(d) <= 64][:16]
        if isinstance(detectors, list)
        else []
    )
    return clean


def _finite_ms(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        fval = float(value)
        if math.isfinite(fval) and fval >= 0.0:
            return fval
    return None


def _filter_entity_counts(raw: object) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(k): int(v)
        for k, v in raw.items()
        if k in _VALID_ENTITY_TYPES and isinstance(v, int) and not isinstance(v, bool) and v > 0
    }


def _sanitize_ingested_timing(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key in ("overhead_ms", "total_ms", "upstream_ms", "added_ttft_ms"):
        if (val := _finite_ms(raw.get(key))) is not None:
            out[key] = val
    stages = raw.get("stages_ms")
    if isinstance(stages, Mapping):
        out["stages_ms"] = {
            str(k): ms
            for k, v in stages.items()
            if k in _VALID_STAGES and (ms := _finite_ms(v)) is not None and ms > 0.0
        }
    detectors = raw.get("detectors_ms")
    if isinstance(detectors, Mapping):
        out["detectors_ms"] = {
            str(k): ms
            for k, v in detectors.items()
            if k in _VALID_DETECTORS and (ms := _finite_ms(v)) is not None and ms > 0.0
        }
    return out


def _observe_ingested_event(metrics: LatencyMetrics, event: Mapping[str, Any]) -> None:
    """Record a validated remote telemetry event into Prometheus metrics with bounded labels."""
    raw_mode = event.get("mode")
    mode = raw_mode if isinstance(raw_mode, str) and raw_mode in _VALID_MODES else "-"
    outcome = str(event.get("outcome") or "error")
    timing = _sanitize_ingested_timing(event.get("timing"))
    sanitized_event: dict[str, Any] = {
        "cache": event.get("cache"),
        "upstream": event.get("upstream"),
        "usage": event.get("usage"),
    }
    entities = event.get("entities")
    if isinstance(entities, Mapping):
        images = entities.get("images")
        sanitized_event["entities"] = {
            "detected": _filter_entity_counts(entities.get("detected")),
            "masked": _filter_entity_counts(entities.get("masked")),
            "images": (
                {
                    "masked": _filter_entity_counts(images.get("masked")),
                    "kept": _filter_entity_counts(images.get("kept")),
                }
                if isinstance(images, Mapping)
                else None
            ),
        }
    outbound = event.get("outbound_check")
    if isinstance(outbound, Mapping):
        result = outbound.get("result")
        sanitized_event["outbound_check"] = {
            "result": result if result in _VALID_OUTBOUND_RESULTS else None,
            "hits": _filter_entity_counts(outbound.get("hits")),
        }
    error = event.get("error")
    if isinstance(error, Mapping):
        sanitized_event["error"] = {
            "entity_types": _filter_entity_counts(error.get("entity_types"))
        }
    metrics.observe(mode, outcome, timing, sanitized_event)


@router.get(
    "/v1/traffic",
    summary="Recent gateway traffic events",
    responses={
        200: {
            "description": "`level` (`masked` or `full`), `size` (how many events the log "
            "keeps), `boot` (a random id per server process: when it changes, `seq` restarted "
            "at 1 and an `after` cursor from before is stale) and `events`, oldest first. See "
            "docs/operations.md for an event's fields.",
            "content": {
                "application/json": {
                    "example": {
                        "level": "masked",
                        "size": 200,
                        "boot": "b_3f9c2a7e5d1b8c04",
                        "events": [],
                    },
                }
            },
        },
        **_TRAFFIC_ERRORS,
    },
)
def recent_traffic(
    request: Request,
    limit: int = Query(
        default=50, ge=1, le=10_000, description="Most events to return (the newest ones)."
    ),
    after: int | None = Query(
        default=None, ge=0, description="Only events with a `seq` greater than this one."
    ),
) -> dict[str, Any]:
    """The most recent events of the in-memory traffic log, oldest first.

    404 ``traffic_log_disabled`` while ``PII_GUARD_TRAFFIC_LOG=off`` (the default). At level
    ``masked`` an event keeps what was sent upstream and what came back (placeholders only);
    ``full`` (loopback only) also the original request and the restored answer."""
    traffic = _traffic(request)
    events = traffic.recent(limit, after=after)
    return {
        "level": traffic.level.value,
        "size": traffic.size,
        "boot": traffic.boot,
        "events": events,
    }


@router.post(
    "/v1/traffic",
    summary="Ingest scrubbed traffic events from a local gateway",
    responses={
        200: {
            "description": "Number of scrubbed traffic events accepted into the in-memory log "
            "and the current `boot` identifier.",
            "content": {
                "application/json": {
                    "example": {
                        "accepted": 1,
                        "boot": "b_3f9c2a7e5d1b8c04",
                    }
                }
            },
        },
        **_TRAFFIC_INGEST_ERRORS,
    },
)
async def ingest_traffic(request: Request) -> dict[str, Any]:
    """Ingest one scrubbed traffic event or a batch (``{"events": [...]}``, up to 50 events)
    from a local on-device gateway into the in-memory traffic log and live SSE stream.

    404 ``traffic_log_disabled`` while ``PII_GUARD_TRAFFIC_LOG=off``. Rejects any event with
    ``level="full"``, ``request.original`` or ``response.unmasked`` (422 ``invalid_request``).
    Also reachable at ``POST /e/{endpoint_id}/v1/traffic`` with an endpoint ``pg_ep_`` key."""
    obs = _observability(request)
    if not obs.traffic.enabled:
        raise TrafficLogDisabledError(
            "the traffic log is off; set PII_GUARD_TRAFFIC_LOG=masked (or full, on localhost)"
        )
    # Only application/json: a cross-site page can send text/plain without a CORS preflight,
    # so accepting it would let any website write into a local dashboard (LAB-1704).
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise TrafficIngestMediaTypeError("traffic events must be sent as application/json")
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise TrafficIngestError("invalid JSON request body") from None
    if not isinstance(payload, dict):
        raise TrafficIngestError("request body must be a JSON object")
    if "events" in payload:
        raw_events = payload.get("events")
        if (
            set(payload) != {"events"}
            or not isinstance(raw_events, list)
            or not (1 <= len(raw_events) <= _MAX_INGEST_EVENTS)
        ):
            raise TrafficIngestError(
                f"events must be a list of 1 to {_MAX_INGEST_EVENTS} traffic events"
            )
    else:
        raw_events = [payload]
    validated = [_validate_ingested_event(item) for item in raw_events]
    app_metrics = request_metrics(request)
    for event in validated:
        obs.traffic.publish(event)
        if app_metrics is not None:
            _observe_ingested_event(app_metrics, event)
    return {
        "accepted": len(validated),
        "boot": obs.traffic.boot,
    }


def _sse(event: dict[str, Any]) -> bytes:
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event['seq']}\nevent: traffic\ndata: {data}\n\n".encode()


@router.get(
    "/v1/traffic/stream",
    summary="Live gateway traffic as server-sent events",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "`text/event-stream`: one `traffic` event per gateway call (`id` is "
            "the event's `seq`, `data` its JSON), a comment line every 15 s as keep-alive.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        **_TRAFFIC_ERRORS,
    },
)
async def traffic_stream(
    request: Request,
    replay: int = Query(
        default=0, ge=0, le=10_000, description="Send the last N stored events first."
    ),
) -> StreamingResponse:
    """Server-sent events, one ``traffic`` event per gateway call, until the client leaves.

    404 ``traffic_log_disabled`` while ``PII_GUARD_TRAFFIC_LOG=off`` (the default)."""
    traffic = _traffic(request)

    async def events() -> AsyncIterator[bytes]:
        async with traffic.subscribe() as queue:
            yield f": pii-guard traffic ({traffic.level.value})\n\n".encode()
            last = 0
            for event in traffic.recent(replay) if replay else []:
                last = event["seq"]
                yield _sse(event)
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                except TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield b": keep-alive\n\n"
                    continue
                if event["seq"] > last:
                    yield _sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _live_session_count(state: Any) -> int:
    total = 0
    vault = getattr(state, "vault", None)
    if vault is not None:
        total += len(vault.live_sessions())
    projects = getattr(state, "projects", None)
    if projects is not None:
        total += projects.live_session_count()
    hosted = getattr(state, "hosted", None)
    if hosted is not None:
        total += hosted.live_session_count()
    return total


def _require_metrics_token(request: Request, obs: Observability) -> None:
    token_secret = obs.settings.metrics_token
    if token_secret is None or getattr(request.state, "metrics_authenticated", False):
        return
    expected = token_secret.get_secret_value().strip()
    auth = request.headers.get("authorization")
    header_token = request.headers.get("x-pii-guard-token")
    if auth and header_token:
        provided = ""
    elif auth:
        scheme, _, credential = auth.partition(" ")
        provided = credential.strip() if scheme.lower() == "bearer" else ""
    else:
        provided = header_token.strip() if header_token else ""
    if (
        not expected
        or not provided
        or not hmac.compare_digest(provided.encode(), expected.encode())
    ):
        raise MetricsUnauthorizedError(
            "this endpoint requires PII_GUARD_METRICS_TOKEN: send "
            "'Authorization: Bearer <token>' or 'X-PII-Guard-Token: <token>'"
        )


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> PlainTextResponse:
    state = request.app.state
    obs = getattr(state, "observability", None) or _observability(request)
    if obs.metrics is None:
        raise MetricsDisabledError("metrics are off; set PII_GUARD_METRICS=true")
    _require_metrics_token(request, obs)
    warmup = getattr(state, "ner_warmup", None)
    hosted = getattr(state, "hosted", None)
    body = obs.metrics.render(
        active_sessions=_live_session_count(state),
        ner_state=getattr(warmup, "state", None),
        hosted_stats=hosted.metrics_snapshot() if hosted is not None else None,
    )
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4")
