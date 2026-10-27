"""Gateway resource limits (LAB-1207): body size without Content-Length, detector threads.

Fictional values only (ADR 0005); a mock upstream and a fake LLM detector.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import httpx
from gateway_helpers import FakeLlm, MockUpstream, make_app

from pii_guard.gateway import GatewayConfig
from pii_guard.types import Span

CHAT = "/v1/chat/completions"


async def _asgi_post(app: Any, body: bytes, *, chunk: int = 64 * 1024) -> tuple[int, int, bytes]:
    """POST ``body`` as a chunked request (no Content-Length): (status, bytes pulled, body)."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": CHAT,
        "raw_path": CHAT.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"localhost"),
            (b"content-type", b"application/json"),
            (b"transfer-encoding", b"chunked"),
        ],
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 80),
    }
    parts = [body[i : i + chunk] for i in range(0, len(body), chunk)]
    pulled = 0
    out: dict[str, Any] = {"body": b""}

    async def receive() -> dict[str, Any]:
        nonlocal pulled
        if parts:
            part = parts.pop(0)
            pulled += len(part)
            return {"type": "http.request", "body": part, "more_body": bool(parts)}
        await asyncio.sleep(3600)  # pragma: no cover - the app never waits past the body
        return {"type": "http.disconnect"}  # pragma: no cover

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
        elif message["type"] == "http.response.body":
            out["body"] += message.get("body", b"")

    await app(scope, receive, send)
    return out["status"], pulled, out["body"]


def _padded(size: int) -> bytes:
    """A valid chat body of about ``size`` bytes: whitespace padding, no long text slot."""
    head = b'{"model":"m","messages":[{"role":"user","content":"hi"}]'
    return head + b" " * max(0, size - len(head) - 1) + b"}"


def test_a_chunked_body_over_the_limit_is_refused_without_buffering_it() -> None:
    # No room for images: the route limit is 1000 chars * 12 + 16 KiB ~ 28 KiB.
    app = make_app(MockUpstream(), config=GatewayConfig(max_images=0))
    app.state.max_text_chars = 1000
    body = _padded(2 * 1024 * 1024)
    status, pulled, payload = asyncio.run(_asgi_post(app, body))
    assert status == 413, payload
    assert b"payload_too_large" in payload
    assert pulled < 128 * 1024  # stopped right after the limit, not after 2 MiB


def test_a_chunked_body_under_the_limit_still_works() -> None:
    upstream = MockUpstream()
    app = make_app(upstream, config=GatewayConfig(max_images=0))
    app.state.max_text_chars = 1000
    status, _, payload = asyncio.run(_asgi_post(app, _padded(8 * 1024), chunk=1024))
    assert status == 200, payload
    assert len(upstream.requests) == 1


class _HungLlm(FakeLlm):
    """An audit-mode LLM detector that hangs until released."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        self.release.wait(10)
        return super().detect(text, language)


def test_timed_out_audit_detections_do_not_starve_fast_mode() -> None:
    """The probe: a burst of audit requests to a hung detector, then one fast request.

    Before LAB-1207 the timed-out threads filled the shared executor and the fast request
    failed with 503 ``detection_failed`` after its own timeout."""
    llm = _HungLlm()
    app = make_app(MockUpstream(), llm=llm, config=GatewayConfig(detection_timeout=0.3))

    async def main() -> tuple[set[int], httpx.Response, float]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:

            def body(i: object) -> dict[str, Any]:
                text = f"üzenet {i}: teszt.elek@example.com"
                return {"model": "m", "messages": [{"role": "user", "content": text}]}

            burst = await asyncio.gather(
                *(
                    client.post(CHAT, json=body(i), headers={"X-PII-Guard-Mode": "audit"})
                    for i in range(40)
                )
            )
            started = time.perf_counter()
            fast = await client.post(CHAT, json=body("fast"), headers={"X-PII-Guard-Mode": "fast"})
            return {r.status_code for r in burst}, fast, time.perf_counter() - started

    try:
        statuses, fast, elapsed = asyncio.run(main())
    finally:
        llm.release.set()
    assert statuses == {503}
    assert fast.status_code == 200, fast.text
    assert elapsed < 0.3


def test_timed_out_detections_keep_their_slots() -> None:
    """Hung threads are not replaced by new ones: the audit pool stays at its size."""
    llm = _HungLlm()
    config = GatewayConfig(detection_timeout=0.2, concurrency=2)
    app = make_app(MockUpstream(), llm=llm, config=config)

    async def main() -> int:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            for i in range(4):
                body = {"model": "m", "messages": [{"role": "user", "content": f"szöveg {i}"}]}
                response = await client.post(CHAT, json=body, headers={"X-PII-Guard-Mode": "audit"})
                assert response.status_code == 503
        gateway = app.state.gateway
        return sum(w.running for w in gateway._detect_workers.values())

    try:
        running = asyncio.run(main())
    finally:
        llm.release.set()
    assert running == 2  # never more than the configured concurrency
