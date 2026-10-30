"""``POST /v1/messages``: a clear ``unsupported_api`` answer, and a Logs entry (LAB-1313).

Claude Code speaks the Anthropic Messages API, which the gateway does not serve yet. Pointed
at the gateway it used to get a bare 405 (which it reports as a model problem) and nothing
showed up in Logs. Now the route answers ``400 unsupported_api``, names the OpenAI-compatible
routes and the Connect page, never forwards anything, and records one ``refused`` traffic
event without the request text. All values are fictional (ADR 0005).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway_helpers import TEST_TENANT_KEY, UPSTREAM_KEY, UPSTREAM_URL, MockUpstream

from pii_guard.api.app import create_app
from pii_guard.api.errors import ERROR_CODES
from pii_guard.config import Settings
from pii_guard.observability import ObservabilitySettings

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

PERSONAL_TEXT = "Kovács Anna, anna.kovacs@example.com"
BODY: dict[str, Any] = {
    "model": "claude-test-model",
    "max_tokens": 64,
    "stream": True,
    "messages": [{"role": "user", "content": PERSONAL_TEXT}],
}


def make(upstream: MockUpstream, traffic: str = "masked") -> FastAPI:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL, upstream_api_key=UPSTREAM_KEY
    )
    app = create_app(settings, ObservabilitySettings(traffic_log=traffic))
    app.state.gateway_transport = upstream.transport()
    return app


@pytest.mark.parametrize("path", ["/v1/messages", "/v1/messages/count_tokens"])
def test_messages_answers_unsupported_api_and_forwards_nothing(path: str) -> None:
    upstream = MockUpstream()
    with TestClient(make(upstream)) as client:
        r = client.post(path, json=BODY, headers={"x-api-key": "0" * 32})
    assert r.status_code == 400
    error = r.json()["error"]
    assert error["code"] == "unsupported_api"
    assert "/v1/chat/completions" in error["message"]
    assert "/v1/responses" in error["message"]
    assert "Connect" in error["message"]
    assert PERSONAL_TEXT not in r.text
    # This answer will not change on a retry.
    assert r.headers["x-should-retry"] == "false"
    assert upstream.requests == []


def test_messages_attempt_shows_in_logs_without_the_request_text() -> None:
    with TestClient(make(MockUpstream(), traffic="full")) as client:
        r = client.post("/v1/messages", json=BODY)
        (event,) = client.get("/v1/traffic").json()["events"]
    assert event["id"] == r.headers["x-pii-guard-request-id"]
    assert event["outcome"] == "refused"
    assert event["error"] == {"code": "unsupported_api", "status": 400}
    assert event["model"] == "claude-test-model"
    assert event["stream"] is True
    assert event["request"] is None or PERSONAL_TEXT not in str(event["request"])
    assert PERSONAL_TEXT not in str(event)


def test_messages_with_a_broken_body_still_answers_unsupported_api() -> None:
    with TestClient(make(MockUpstream())) as client:
        r = client.post(
            "/v1/messages", content=b"{not json", headers={"content-type": "application/json"}
        )
        (event,) = client.get("/v1/traffic").json()["events"]
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_api"
    assert event["model"] is None


def test_messages_with_the_traffic_log_off_still_answers() -> None:
    with TestClient(make(MockUpstream(), traffic="off")) as client:
        r = client.post("/v1/messages", json=BODY)
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_api"


def test_unsupported_api_is_a_documented_error_code() -> None:
    assert ERROR_CODES["unsupported_api"][0] == 400
