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
import json
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import Query, Request
from starlette.responses import PlainTextResponse, StreamingResponse

from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import v1_router
from pii_guard.observability import (
    Observability,
    RemoteTrafficLevel,
    TrafficLog,
    sanitize_for_remote,
)
from pii_guard.observability.traffic import TrafficFeedView
from pii_guard.types import PiiGuardError

__all__ = ["TrafficIngestError", "TrafficLogDisabledError", "router"]

router = v1_router()
router.tags = ["observability"]

_KEEPALIVE_SECONDS = 15.0
_MAX_INGEST_EVENTS = 50
_VALID_OUTCOMES = frozenset(
    {"ok", "upstream_error", "upstream_failed", "blocked", "refused", "error"}
)


class TrafficLogDisabledError(PiiGuardError):
    code = "traffic_log_disabled"
    status_code = 404


class TrafficIngestError(PiiGuardError):
    code = "invalid_request"
    status_code = 422


class MetricsDisabledError(PiiGuardError):
    code = "metrics_disabled"
    status_code = 404


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
    "traffic_log_disabled", "invalid_request", "payload_too_large"
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
        clean["outcome"] = "ok"
    clean["stream"] = bool(clean.get("stream", False))
    clean["session_new"] = bool(clean.get("session_new", False))
    detectors = clean.get("detectors")
    clean["detectors"] = (
        [d for d in detectors if isinstance(d, str) and len(d) <= 64][:16]
        if isinstance(detectors, list)
        else []
    )
    return clean


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
    for event in validated:
        obs.traffic.publish(event)
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
    return total


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> PlainTextResponse:
    state = request.app.state
    obs = (
        _observability(request)
        if getattr(getattr(state, "settings", None), "hosted", False)
        else getattr(state, "observability", None) or _observability(request)
    )
    if obs.metrics is None:
        raise MetricsDisabledError("metrics are off; set PII_GUARD_METRICS=true")
    warmup = getattr(state, "ner_warmup", None)
    body = obs.metrics.render(
        active_sessions=_live_session_count(state),
        ner_state=getattr(warmup, "state", None),
    )
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4")
