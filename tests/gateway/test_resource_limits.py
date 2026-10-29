"""Gateway resource limits (LAB-1207): body size without Content-Length, detector threads.

Fictional values only (ADR 0005); a mock upstream and a fake LLM detector.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import TEST_TENANT_KEY, FakeLlm, MockUpstream, completion, make_app
from starlette.requests import Request

import pii_guard.api.routes._common as common
import pii_guard.gateway.stream as stream_module
from pii_guard.gateway import GatewayConfig
from pii_guard.gateway.stream import SseRestorer, iter_sse_data
from pii_guard.types import Span
from pii_guard.vault import Vault

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

    async def main() -> tuple[set[int], httpx.Response]:
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
            fast = await client.post(CHAT, json=body("fast"), headers={"X-PII-Guard-Mode": "fast"})
            return {r.status_code for r in burst}, fast

    try:
        statuses, fast = asyncio.run(main())
    finally:
        llm.release.set()
    assert statuses == {503}
    # Starved, the fast request would wait out its own 0.3 s timeout and answer 503, so the
    # status is the proof; no wall-clock bound (LAB-1275: it flaked under load).
    assert fast.status_code == 200, fast.text


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


# --- LAB-1566: upstream body/stream bounds, body-read deadline, disconnect ----------------


class _HugeUpstream(MockUpstream):
    """Answers 200 with a body far past a small configured response limit."""

    def handler(self, request: httpx.Request) -> httpx.Response:  # type: ignore[override]
        self.requests.append(request)
        return httpx.Response(200, json=completion("x" * 5000))


def test_oversized_nonstreamed_upstream_body_fails_closed() -> None:
    config = GatewayConfig(upstream_max_response_bytes=1024)
    app = make_app(_HugeUpstream(), config=config)
    body = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    with TestClient(app) as http:
        chat = http.post(CHAT, json=body)
        responses = http.post(
            "/v1/responses",
            json={"model": "m", "input": [{"type": "message", "role": "user", "content": "hi"}]},
        )
    for response in (chat, responses):
        assert response.status_code == 502, response.text
        assert response.json()["error"]["code"] == "upstream_unavailable"
        assert "x" * 100 not in response.text  # sanitised: no upstream body text


async def _collect_sse(lines: list[str]) -> list[str]:
    async def source() -> Any:
        for line in lines:
            yield line

    return [data async for data in iter_sse_data(source())]


def test_sse_event_buffer_is_capped(monkeypatch: Any) -> None:
    monkeypatch.setattr(stream_module, "MAX_SSE_EVENT_CHARS", 16)
    with pytest.raises(stream_module.StreamTooLargeError):
        asyncio.run(_collect_sse(["data: " + "x" * 32, "data: more"]))  # no blank line


def _restorer(monkeypatch: Any, **caps: int) -> Any:
    for name, value in caps.items():
        monkeypatch.setattr(stream_module, name, value)
    return SseRestorer(Vault(bytes.fromhex(TEST_TENANT_KEY)).session())


def test_masked_content_retention_is_capped_but_stream_continues(monkeypatch: Any) -> None:
    restorer = _restorer(monkeypatch, MAX_MASKED_CONTENT_CHARS=10)
    chunk = {"choices": [{"index": 0, "delta": {"content": "hello world, more text"}}]}
    out = restorer.process(json.dumps(chunk))
    assert "hello world" in out[0]  # the client still gets the (masked) text
    assert restorer.masked_content() == {}  # only the cache-seeding copy is dropped


def test_unmasker_count_is_capped(monkeypatch: Any) -> None:
    restorer = _restorer(monkeypatch, MAX_UNMASKERS=1)
    chunk = {
        "choices": [
            {"index": 0, "delta": {"content": "a"}},
            {"index": 1, "delta": {"content": "b"}},
        ]
    }
    with pytest.raises(stream_module.StreamTooLargeError):
        restorer.process(json.dumps(chunk))


def test_body_read_has_a_time_deadline(monkeypatch: Any) -> None:
    monkeypatch.setattr(common, "BODY_READ_TIMEOUT_SECONDS", 0.05)
    scope = {"type": "http", "method": "POST", "headers": []}

    async def slow_receive() -> dict[str, Any]:
        await asyncio.sleep(5)
        return {"type": "http.request", "body": b"{}", "more_body": False}  # pragma: no cover

    request = Request(scope, slow_receive)
    with pytest.raises(common.BodyReadTimeoutError):
        asyncio.run(common._read_body_capped(request, 10**6))


def test_ensure_connected_refuses_a_gone_client() -> None:
    class Gone:
        async def is_disconnected(self) -> bool:
            return True

    with pytest.raises(common.ClientDisconnectedError) as caught:
        asyncio.run(common.ensure_connected(Gone()))  # type: ignore[arg-type]
    assert caught.value.status_code == 499
