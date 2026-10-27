"""Audit mode without an LLM detector key is refused locally (LAB-1290).

The gateway builds its real :class:`~pii_guard.detect.llm.LlmDetector` from settings with no
``PII_GUARD_LLM_DETECTOR_API_KEY``. Every audit request (header or server default, chat or
responses, text or image) must get ``503 detection_unavailable`` while nothing is sent: not to
the detector endpoint, not to SAM, not upstream. Fast mode is unchanged. All values are
fictional (ADR 0005).
"""

from __future__ import annotations

import base64
import io
import socket
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway_helpers import (
    TEST_TENANT_KEY,
    UPSTREAM_KEY,
    UPSTREAM_URL,
    MockUpstream,
    conversation_turn_one,
)
from PIL import Image

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.detect.llm import LlmDetector
from pii_guard.detect.rules import RuleDetector
from pii_guard.gateway import Gateway, GatewayConfig, Mode, build_mode_detectors
from pii_guard.vault import Vault
from pii_guard.visual import OcrWord, SamClient
from pii_guard.visual.regions import Box

MESSAGE = "audit mode needs PII_GUARD_LLM_DETECTOR_API_KEY"


class Tripwire:
    """Records any use of httpx's real transports or of a socket (the LLM detector has no
    injected transport here, so a keyless request would go through them)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []

        def sync_send(_self: Any, request: httpx.Request) -> httpx.Response:
            self.calls.append(f"HTTPTransport {request.url.host}")
            raise AssertionError("the HTTP transport must not be invoked")

        async def async_send(_self: Any, request: httpx.Request) -> httpx.Response:
            self.calls.append(f"AsyncHTTPTransport {request.url.host}")
            raise AssertionError("the HTTP transport must not be invoked")

        def connect(_self: Any, address: Any) -> None:
            self.calls.append(f"socket {address!r}")
            raise AssertionError("no socket may be opened")

        monkeypatch.setattr(httpx.HTTPTransport, "handle_request", sync_send)
        monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_send)
        monkeypatch.setattr(socket.socket, "connect", connect)


@pytest.fixture
def tripwire(monkeypatch: pytest.MonkeyPatch) -> Tripwire:
    return Tripwire(monkeypatch)


class Sam:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(500)


class FakeOcr:
    name = "fake-ocr"

    def words(self, image: Image.Image) -> list[OcrWord]:
        return [OcrWord("TAJ:", Box(10, 10, 40, 20), (0,))]


def settings(**extra: Any) -> Settings:
    return Settings(
        _env_file=None,
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
        **extra,
    )


def make_app(
    upstream: MockUpstream, *, mode: Mode = Mode.FAST, sam: Sam | None = None, **extra: Any
) -> FastAPI:
    s = settings(**extra)
    config = GatewayConfig(mode=mode)
    app = create_app(s)
    app.state.gateway = Gateway(
        settings=s,
        vault=Vault.from_settings(s),
        config=config,
        # The real keyless LlmDetector, built from the settings as in production.
        detectors=build_mode_detectors(s, config, base=[RuleDetector()]),
        transport=upstream.transport(),
        sam=SamClient(api_key="test-key", transport=httpx.MockTransport(sam or Sam())),
        ocr=FakeOcr(),  # type: ignore[arg-type]
    )
    return app


def assert_unavailable(response: httpx.Response) -> None:
    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "detection_unavailable"
    assert MESSAGE in error["message"]
    assert "Teszt" not in response.text


def png() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (230, 236, 248)).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def chat(http: TestClient, messages: list[dict[str, Any]], **headers: str) -> httpx.Response:
    return http.post(
        "/v1/chat/completions", json={"model": "m", "messages": messages}, headers=headers
    )


def test_the_audit_mode_detector_is_marked_unavailable() -> None:
    detectors = build_mode_detectors(settings(), GatewayConfig(), base=[RuleDetector()])
    assert detectors[Mode.FAST].unavailable is None
    assert MESSAGE in (detectors[Mode.AUDIT].unavailable or "")


def test_audit_header_without_key_is_refused_and_nothing_is_sent(tripwire: Tripwire) -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = chat(http, conversation_turn_one(), **{"X-PII-Guard-Mode": "audit"})
    assert_unavailable(response)
    assert upstream.requests == []
    assert tripwire.calls == []


def test_deprecated_strict_header_is_refused_too(tripwire: Tripwire) -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = chat(http, conversation_turn_one(), **{"X-PII-Guard-Mode": "strict"})
    assert_unavailable(response)
    assert upstream.requests == []
    assert tripwire.calls == []


def test_audit_server_default_without_key_is_refused(tripwire: Tripwire) -> None:
    """``PII_GUARD_GATEWAY_MODE=audit``: every request without a header is refused."""
    upstream = MockUpstream()
    with TestClient(make_app(upstream, mode=Mode.AUDIT)) as http:
        response = chat(http, conversation_turn_one())
    assert_unavailable(response)
    assert upstream.requests == []
    assert tripwire.calls == []


def test_audit_streaming_request_is_refused(tripwire: Tripwire) -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one(), "stream": True},
            headers={"X-PII-Guard-Mode": "audit"},
        )
    assert_unavailable(response)
    assert upstream.requests == []
    assert tripwire.calls == []


def test_audit_image_only_request_is_refused_before_sam(tripwire: Tripwire) -> None:
    """No text slot to detect, only an image: still refused before SAM or OCR + LLM run."""
    upstream, sam = MockUpstream(), Sam()
    messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": png()}}]}]
    with TestClient(make_app(upstream, sam=sam)) as http:
        response = chat(http, messages, **{"X-PII-Guard-Mode": "audit"})
    assert_unavailable(response)
    assert sam.requests == []
    assert upstream.requests == []
    assert tripwire.calls == []


def test_audit_responses_api_is_refused(tripwire: Tripwire) -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post(
            "/v1/responses",
            json={"model": "m", "input": "Szia! Teszt Elek vagyok."},
            headers={"X-PII-Guard-Mode": "audit"},
        )
    assert_unavailable(response)
    assert upstream.requests == []
    assert tripwire.calls == []


def test_fast_mode_still_works_without_a_key(tripwire: Tripwire) -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = chat(http, conversation_turn_one())
    assert response.status_code == 200, response.text
    assert len(upstream.requests) == 1
    assert "teszt.elek@example.com" not in upstream.requests[0].content.decode()
    assert tripwire.calls == []


def test_keyed_audit_mode_is_available() -> None:
    detectors = build_mode_detectors(
        settings(llm_detector_api_key="test-key"), GatewayConfig(), base=[RuleDetector()]
    )
    assert detectors[Mode.AUDIT].unavailable is None
    llm = LlmDetector(settings=settings(llm_detector_api_key="test-key"))
    assert llm.unavailable_reason is None
