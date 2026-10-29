"""Streaming timing and outcome (LAB-1212).

A slow-reading client must not count as pii-guard overhead, and a client that goes away
mid-stream must be recorded as ``client_disconnected`` without seeding the detection cache with
the partial answer. These drive the ASGI app directly: a test client reads as fast as it can and
cannot hold a stream open or vanish half-way through it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from gateway_helpers import TEST_TENANT_KEY, UPSTREAM_KEY, UPSTREAM_URL, FakeLlm
from starlette.requests import ClientDisconnect
from timing_helpers import VirtualClock
from timing_helpers import install as install_clock

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway import GatewayConfig, Mode, build_mode_detectors
from pii_guard.observability import ObservabilitySettings
from pii_guard.observability.timing import OWN_STAGES

CHUNK = b'data: {"choices":[{"index":0,"delta":{"content":"tok "}}]}\n\n'


def _app(transport: httpx.AsyncBaseTransport) -> FastAPI:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL, upstream_api_key=UPSTREAM_KEY
    )
    app = create_app(settings, ObservabilitySettings(traffic_log="masked", metrics=True))
    config = GatewayConfig(mode=Mode.AUDIT)
    app.state.gateway_config = config
    app.state.gateway_transport = transport
    app.state.gateway_detectors = build_mode_detectors(settings, config, llm_detector=FakeLlm())
    return app


def _scope(body: bytes, spec_version: str) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/chat/completions",
        "raw_path": b"/v1/chat/completions",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"localhost"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 80),
    }


def _body(content: str = "hi") -> bytes:
    return json.dumps(
        {"model": "m", "stream": True, "messages": [{"role": "user", "content": content}]}
    ).encode()


class _Stream(httpx.AsyncByteStream):
    """``count`` SSE chunks, ``delay`` seconds apart, then ``[DONE]``. Records ``aclose``."""

    def __init__(self, count: int, delay: float = 0.0) -> None:
        self.count, self.delay = count, delay
        self.pulled = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(self.count):
            self.pulled += 1
            yield CHUNK
            if self.delay:
                await asyncio.sleep(self.delay)
        yield b"data: [DONE]\n\n"

    async def aclose(self) -> None:
        self.closed = True


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self, stream: _Stream) -> None:
        self.stream = stream

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=self.stream
        )


def _event(app: FastAPI) -> dict[str, Any]:
    events = app.state.observability.traffic.recent()
    assert len(events) == 1
    return events[-1]


def _stream_once(app: FastAPI, delay: float, clock: VirtualClock | None = None) -> None:
    """One streamed call whose client takes ``delay`` seconds to read each body message.

    With a ``clock`` the read is a jump of virtual time (LAB-1275), not a sleep."""
    body = _body()
    sent = {"request": False}

    async def receive() -> dict[str, Any]:
        if not sent["request"]:
            sent["request"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            # the client's read speed / network backpressure
            if clock is not None:
                clock.skip(delay)
                await asyncio.sleep(0)
            else:
                await asyncio.sleep(delay)

    asyncio.run(app(_scope(body, "2.4"), receive, send))


def test_slow_client_reads_are_not_overhead(monkeypatch: pytest.MonkeyPatch) -> None:
    """20 events, each taking the client 1 s to read: that is ``client`` time, not overhead.

    The client's reads are jumps of a virtual clock (LAB-1275), so the 20 s are exact and the
    bounds below cannot be broken by scheduler latency on a loaded machine."""
    clock = install_clock(monkeypatch)
    delay = 1.0
    app = _app(_Transport(_Stream(20)))
    _stream_once(app, 0.0)  # warm-up: first-call costs (imports, compiled rules) are not the point
    _stream_once(app, delay, clock)
    events = app.state.observability.traffic.recent()
    assert len(events) == 2
    event = events[-1]
    assert event["outcome"] == "ok"
    timing = event["timing"]
    stages = timing["stages_ms"]
    assert stages["client"] >= 20 * delay * 1000 * 0.9
    expected = timing["total_ms"] - timing["upstream_ms"] - stages["client"]
    assert abs(timing["overhead_ms"] - expected) < 0.01
    # What is left is pii-guard's own stages plus scheduling slack, nowhere near the ~20 s the
    # client spent reading (before LAB-1212 it was all counted as overhead).
    own = sum(stages[name] for name in OWN_STAGES)
    assert own * 0.9 <= timing["overhead_ms"] < stages["client"] / 4


def _run_disconnect(stream: _Stream, *, spec_version: str, after: int) -> FastAPI:
    """The client reads ``after`` body messages, then disconnects."""
    app = _app(_Transport(stream))
    body = _body("hi teszt.elek@example.com")
    gone = asyncio.Event()
    state = {"request": False, "bodies": 0}

    async def receive() -> dict[str, Any]:
        if not state["request"]:
            state["request"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] != "http.response.body":
            return
        if gone.is_set():
            raise OSError("client went away")  # what a server does on a closed socket
        state["bodies"] += 1
        if state["bodies"] >= after:
            gone.set()

    async def main() -> None:
        # Starlette re-raises a failed send as ClientDisconnect (ASGI 2.4).
        with contextlib.suppress(OSError, ClientDisconnect):
            await asyncio.wait_for(app(_scope(body, spec_version), receive, send), 10)
        await asyncio.sleep(0.1)  # let the stream's finaliser record its event

    asyncio.run(main())
    return app


def _assert_disconnected(app: FastAPI, stream: _Stream) -> None:
    event = _event(app)
    assert event["outcome"] == "client_disconnected"
    assert event["error"] == {"code": "client_disconnected"}
    # The partial answer is not what the client will send back as history: no seeding.
    assert event["cache"]["seeded"] == 0
    gateway = app.state.gateway
    assert len(gateway.cache) == 1  # only the request's own message, detected before forwarding
    assert stream.closed and stream.pulled < stream.count
    # The disconnect closed the upstream *response*; the shared client stays open (LAB-1176).
    assert gateway._client is not None and not gateway._client.is_closed
    metrics = app.state.observability.metrics.render()
    assert 'pii_guard_gateway_requests_total{mode="audit",outcome="client_disconnected"} 1' in (
        metrics
    )
    assert 'outcome="ok"' not in metrics


def test_disconnect_between_events_is_recorded_and_not_seeded() -> None:
    """The client vanishes while the stream waits in ``yield`` (the generator is closed)."""
    stream = _Stream(1000, delay=0.005)
    app = _run_disconnect(stream, spec_version="2.4", after=3)
    _assert_disconnected(app, stream)


def test_disconnect_while_waiting_on_the_upstream_is_recorded_and_not_seeded() -> None:
    """The client vanishes while the stream awaits the upstream (the task is cancelled)."""
    stream = _Stream(1000, delay=0.2)
    app = _run_disconnect(stream, spec_version="2.3", after=2)
    _assert_disconnected(app, stream)


def test_trickling_stream_hits_the_total_deadline() -> None:
    """LAB-1566: per-read timeouts still pass chunk by chunk, but the whole stream
    has a total deadline; past it the client gets the generic stream error."""
    import time

    stream = _Stream(1000, delay=0.05)  # ~50 s of trickle if unbounded
    app = _app(_Transport(stream))
    app.state.gateway_config = GatewayConfig(mode=Mode.AUDIT, upstream_stream_timeout=0.2)

    async def main() -> bytes:
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(
                transport=transport, base_url="http://localhost", timeout=10
            ) as client,
            client.stream("POST", "/v1/chat/completions", content=_body()) as response,
        ):
            assert response.status_code == 200
            return b"".join([part async for part in response.aiter_bytes()])

    started = time.perf_counter()
    body = asyncio.run(main())
    elapsed = time.perf_counter() - started
    assert b"stream_failed" in body
    assert elapsed < 5  # ended by the 0.2 s deadline, not by reading the whole trickle
    assert stream.pulled < stream.count
