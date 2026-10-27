"""REST ``/v1/*`` with the LLM detector but no key: refused locally (LAB-1290).

``PII_GUARD_DETECTORS=rules,llm`` without ``PII_GUARD_LLM_DETECTOR_API_KEY`` must answer
``503 detection_unavailable`` and send nothing: not the text to the detector endpoint, not the
image to SAM. All values are fictional (ADR 0005).
"""

from __future__ import annotations

import io
import socket
from typing import Any

import httpx
import pytest
from api_helpers import SAMPLE_TEXT, TEST_TENANT_KEY
from fastapi.testclient import TestClient
from PIL import Image

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.visual import OcrWord, SamClient
from pii_guard.visual.regions import Box

MESSAGE = "audit mode needs PII_GUARD_LLM_DETECTOR_API_KEY"


class Tripwire:
    """Records any use of httpx's real transports or of a socket."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []

        def sync_send(_self: Any, request: httpx.Request) -> httpx.Response:
            self.calls.append(f"HTTPTransport {request.url.host}")
            raise AssertionError("the HTTP transport must not be invoked")

        def connect(_self: Any, address: Any) -> None:
            self.calls.append(f"socket {address!r}")
            raise AssertionError("no socket may be opened")

        monkeypatch.setattr(httpx.HTTPTransport, "handle_request", sync_send)
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


def client(sam: Sam | None = None, **extra: Any) -> TestClient:
    settings = Settings(
        _env_file=None, tenant_key=TEST_TENANT_KEY, detectors=("rules", "llm"), **extra
    )
    app = create_app(settings)
    app.state.sam_client = SamClient(
        api_key="test-key", transport=httpx.MockTransport(sam or Sam()), max_retries=0
    )
    app.state.ocr_engine = FakeOcr()
    return TestClient(app, raise_server_exceptions=False)


def assert_unavailable(response: httpx.Response) -> None:
    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "detection_unavailable"
    assert MESSAGE in error["message"]
    assert "example.com" not in response.text


@pytest.mark.parametrize("path", ["/v1/mask", "/v1/analyze"])
def test_text_routes_refuse_and_send_nothing(tripwire: Tripwire, path: str) -> None:
    with client() as http:
        response = http.post(path, json={"text": SAMPLE_TEXT})
    assert_unavailable(response)
    assert tripwire.calls == []


def test_image_route_refuses_before_sam(tripwire: Tripwire) -> None:
    """OCR text would reach the keyless LLM: refused before the image goes to SAM."""
    sam = Sam()
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (230, 236, 248)).save(buf, format="PNG")
    with client(sam) as http:
        response = http.post(
            "/v1/mask/image", content=buf.getvalue(), headers={"Content-Type": "image/png"}
        )
    assert_unavailable(response)
    assert sam.requests == []
    assert tripwire.calls == []


def test_rules_only_rest_stack_is_unaffected(tripwire: Tripwire) -> None:
    app = create_app(Settings(_env_file=None, tenant_key=TEST_TENANT_KEY, detectors=("rules",)))
    with TestClient(app) as http:
        response = http.post("/v1/mask", json={"text": SAMPLE_TEXT})
    assert response.status_code == 200, response.text
    assert tripwire.calls == []
