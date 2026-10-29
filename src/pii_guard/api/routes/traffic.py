"""The traffic log and latency metrics of the gateway (see ``docs/operations.md``).

- ``GET /v1/traffic?limit=50&after=<seq>``: the most recent events, oldest first.
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
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Query, Request
from starlette.responses import PlainTextResponse, StreamingResponse

from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import v1_router
from pii_guard.observability import Observability, TrafficLog
from pii_guard.observability.traffic import TrafficFeedView
from pii_guard.types import PiiGuardError

__all__ = ["router"]

router = v1_router()
router.tags = ["observability"]

_KEEPALIVE_SECONDS = 15.0


class TrafficLogDisabledError(PiiGuardError):
    code = "traffic_log_disabled"
    status_code = 404


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


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> PlainTextResponse:
    obs = _observability(request)
    if obs.metrics is None:
        raise MetricsDisabledError("metrics are off; set PII_GUARD_METRICS=true")
    return PlainTextResponse(obs.metrics.render(), media_type="text/plain; version=0.0.4")
