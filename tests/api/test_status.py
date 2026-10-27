"""``GET /v1/status`` (LAB-1287): configuration only, never a key or a value."""

from __future__ import annotations

import pytest
from api_helpers import TEST_TENANT_KEY
from fastapi.testclient import TestClient
from pydantic import SecretStr

from pii_guard.api.app import create_app
from pii_guard.api.routes.status import upstream_origin
from pii_guard.app_bundle import Status
from pii_guard.config import Settings
from pii_guard.types import EntityType

# Fictional secrets: the response must never contain them.
UPSTREAM_KEY = "fictional-upstream-key"
DETECTOR_KEY = "fictional-detector-key"
API_TOKEN = "fictional-api-token"  # noqa: S105 - a fictional test token


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings), base_url="http://localhost:8787")


def test_status_reports_configuration(api: TestClient) -> None:
    res = api.get("/v1/status", headers={"host": "localhost:8787"})
    assert res.status_code == 200
    body = res.json()
    assert body["gateway"]["default_mode"] == "fast"
    assert body["gateway"]["url"] == "http://localhost:8787/v1"
    fast = body["gateway"]["modes"]["fast"]
    assert "rules" in fast["detectors"] and fast["available"] is True
    audit = body["gateway"]["modes"]["audit"]
    assert audit["detectors"][-1] == "llm"
    # No detector key in the test settings: audit refuses (LAB-1290), and says why.
    assert audit["available"] is False and "PII_GUARD_LLM_DETECTOR_API_KEY" in audit["reason"]
    assert body["ner"]["available"] == ("ner" in fast["detectors"])
    assert set(body["policies"]) == {t.value for t in EntityType}
    assert body["policies"]["ORGANIZATION"] == "keep" and body["policies"]["PERSON"] == "mask"
    assert body["traffic_log"] == "off"
    assert body["upstream"] == {"configured": False, "mock": False, "origin": None}
    assert body["auth"] == {"token_required": False}


def test_status_reflects_policy_overrides() -> None:
    overrides = "EMAIL=block,ORGANIZATION=mask"
    settings = Settings(tenant_key=TEST_TENANT_KEY, policy_overrides=overrides)
    body = _client(settings).get("/v1/status").json()
    assert body["policies"]["EMAIL"] == "block"
    assert body["policies"]["ORGANIZATION"] == "mask"


def test_status_never_returns_secrets() -> None:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url="https://user:pass@models.example.com:8443/openai/v1?x=1",
        upstream_api_key=SecretStr(UPSTREAM_KEY),
        llm_detector_api_key=SecretStr(DETECTOR_KEY),
        api_token=SecretStr(API_TOKEN),
    )
    res = _client(settings).get("/v1/status", headers={"authorization": f"Bearer {API_TOKEN}"})
    assert res.status_code == 200
    text = res.text
    for secret in (UPSTREAM_KEY, DETECTOR_KEY, API_TOKEN, TEST_TENANT_KEY, "pass", "/openai"):
        assert secret not in text
    body = res.json()
    assert body["upstream"] == {
        "configured": True,
        "mock": False,
        "origin": "https://models.example.com:8443",
    }
    assert body["auth"] == {"token_required": True}
    assert body["gateway"]["modes"]["audit"]["available"] is True


def test_status_needs_the_token_when_one_is_set() -> None:
    settings = Settings(tenant_key=TEST_TENANT_KEY, api_token=SecretStr(API_TOKEN))
    assert _client(settings).get("/v1/status").status_code == 401


def test_status_reports_the_up_mock_upstream() -> None:
    app = create_app(
        Settings(tenant_key=TEST_TENANT_KEY, upstream_base_url="http://127.0.0.1:9/v1")
    )
    app.state.up_status = Status(upstream="mock", detectors=["rules"])
    body = TestClient(app, base_url="http://localhost:8787").get("/v1/status").json()
    assert body["upstream"] == {"configured": True, "mock": True, "origin": None}


def test_status_reports_the_traffic_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_TRAFFIC_LOG", "masked")
    body = _client(Settings(tenant_key=TEST_TENANT_KEY)).get("/v1/status").json()
    assert body["traffic_log"] == "masked"


@pytest.mark.parametrize(
    ("url", "origin"),
    [
        (None, None),
        ("", None),
        ("http://127.0.0.1:8790/v1", "http://127.0.0.1:8790"),
        ("https://u:p@api.example.com/v1", "https://api.example.com"),
        ("http://[::1]:9000/v1", "http://[::1]:9000"),
        ("not a url", None),
    ],
)
def test_upstream_origin(url: str | None, origin: str | None) -> None:
    assert upstream_origin(url) == origin
