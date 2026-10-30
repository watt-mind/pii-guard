"""``POST /v1/messages`` against an upstream without a Messages API: ``unsupported_api``.

LAB-1313 made the route answer ``400 unsupported_api`` (not a bare 405, which Claude Code
reports as a model problem) and log the attempt. Since LAB-1605 the route is a real adapter;
the same error now means the *upstream* has no ``/messages`` (an OpenAI-only provider answers
404/405 there). Only the masked request reached that upstream; the client gets the error with
``x-should-retry: false``, and the call is one ``refused`` traffic event without the request
text. All values are fictional (ADR 0005).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway_helpers import TEST_TENANT_KEY, UPSTREAM_KEY, UPSTREAM_URL, leaked_values

from pii_guard.api.app import create_app
from pii_guard.api.errors import ERROR_CODES
from pii_guard.config import Settings
from pii_guard.gateway import GatewayConfig, Mode
from pii_guard.gateway.trace import MODEL_WITHHELD
from pii_guard.observability import ObservabilitySettings

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

PERSONAL_TEXT = "Write to teszt.elek@example.com"
BODY: dict[str, Any] = {
    "model": "claude-test-model",
    "max_tokens": 64,
    "stream": True,
    "messages": [{"role": "user", "content": PERSONAL_TEXT}],
}


class OpenAiOnly:
    """An OpenAI-compatible upstream: ``/messages`` is not a route there."""

    def __init__(self, status: int = 404) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={"error": {"message": "Not Found"}})


def make(upstream: OpenAiOnly, traffic: str = "masked") -> FastAPI:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL, upstream_api_key=UPSTREAM_KEY
    )
    app = create_app(settings, ObservabilitySettings(traffic_log=traffic))
    app.state.gateway_config = GatewayConfig(mode=Mode.FAST)
    app.state.gateway_transport = httpx.MockTransport(upstream.handler)
    return app


@pytest.mark.parametrize("status", [404, 405])
@pytest.mark.parametrize("path", ["/v1/messages", "/v1/messages/count_tokens"])
def test_upstream_without_messages_api_answers_unsupported_api(path: str, status: int) -> None:
    upstream = OpenAiOnly(status)
    with TestClient(make(upstream)) as client:
        r = client.post(path, json=BODY, headers={"x-api-key": "0" * 32})
    assert r.status_code == 400
    error = r.json()["error"]
    assert error["code"] == "unsupported_api"
    assert "Anthropic Messages API" in error["message"]
    assert "/v1/chat/completions" in error["message"]
    assert "Connect" in error["message"]
    assert PERSONAL_TEXT not in r.text
    # This answer will not change on a retry.
    assert r.headers["x-should-retry"] == "false"
    # Only the masked request went out.
    (request,) = upstream.requests
    assert request.url.path == "/v1" + path[3:]
    assert leaked_values(request.content) == []
    assert b"teszt.elek@example.com" not in request.content


def test_the_attempt_shows_in_logs_without_the_request_text() -> None:
    with TestClient(make(OpenAiOnly(), traffic="masked")) as client:
        r = client.post("/v1/messages", json=BODY)
        (event,) = client.get("/v1/traffic").json()["events"]
    assert event["id"] == r.headers["x-pii-guard-request-id"]
    assert event["outcome"] == "refused"
    error = dict(event["error"])
    assert error.pop("message")  # the API error message, types and counts only (LAB-1314)
    assert error == {"code": "unsupported_api", "status": 400}
    # The model was checked before anything went out, so the event may name it.
    assert event["model"] in ("claude-test-model", MODEL_WITHHELD)
    assert event["stream"] is True
    assert PERSONAL_TEXT not in str(event)


def test_with_the_traffic_log_off_it_still_answers() -> None:
    with TestClient(make(OpenAiOnly(), traffic="off")) as client:
        r = client.post("/v1/messages", json=BODY)
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_api"


def test_unsupported_api_is_a_documented_error_code() -> None:
    assert ERROR_CODES["unsupported_api"][0] == 400
