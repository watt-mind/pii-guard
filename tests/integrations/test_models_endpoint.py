"""``GET /v1/models``: static list, proxied upstream list, and the failure cases."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.api.routes.models import ModelsConfig, models_url
from pii_guard.config import Settings

UPSTREAM = "https://upstream.test/v1"
KEY = "sk-test-upstream-key-0000"


def _client(handler=None, *, base_url: str | None = UPSTREAM, key: str | None = KEY, **config):
    settings = Settings(upstream_base_url=base_url, upstream_api_key=key)
    app = create_app(settings)
    if handler is not None:
        app.state.gateway_transport = httpx.MockTransport(handler)
    if config:
        app.state.models_config = ModelsConfig(**config)
    return TestClient(app)


def test_models_url_strips_chat_completions() -> None:
    assert models_url("https://x.test/v1") == "https://x.test/v1/models"
    assert models_url("https://x.test/v1/") == "https://x.test/v1/models"
    assert models_url("https://x.test/v1/chat/completions") == "https://x.test/v1/models"


def test_static_list_does_not_call_upstream() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("upstream called")

    client = _client(handler, upstream_models=("m-one", "m-two"))
    response = client.get("/v1/models")
    assert response.status_code == 200
    assert [m["id"] for m in response.json()["data"]] == ["m-one", "m-two"]
    assert response.json()["object"] == "list"


def test_static_list_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_UPSTREAM_MODELS", " a , b,, ")
    response = _client(base_url=None).get("/v1/models")
    assert [m["id"] for m in response.json()["data"]] == ["a", "b"]


def test_proxied_list_keeps_only_standard_fields() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {
                        "id": "muse-spark",
                        "object": "model",
                        "created": 5,
                        "owned_by": "meta",
                        "metadata": {"price": "secret-ish"},
                    },
                    {"id": ""},
                    "not-a-model",
                    {"id": "x" * 300},
                    {"id": "second", "created": True},
                ],
            },
        )

    response = _client(handler).get("/v1/models")
    assert response.status_code == 200
    assert response.json()["data"] == [
        {"id": "muse-spark", "object": "model", "created": 5, "owned_by": "meta"},
        {"id": "second", "object": "model", "created": 0, "owned_by": ""},
    ]
    assert str(seen[0].url) == "https://upstream.test/v1/models"
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"


def test_client_key_passed_through_without_upstream_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    client = _client(handler, key=None)
    assert client.get("/v1/models", headers={"Authorization": "Bearer own"}).status_code == 200
    assert seen[0].headers["authorization"] == "Bearer own"


def test_no_upstream_configured() -> None:
    response = _client(base_url=None).get("/v1/models")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_not_configured"


@pytest.mark.parametrize(("status", "expected"), [(401, 401), (404, 404), (503, 502)])
def test_upstream_error_status_without_its_message(status: int, expected: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "quotes [[PERSON_abcd]]"}})

    response = _client(handler).get("/v1/models")
    assert response.status_code == expected
    assert response.json()["error"]["code"] == "upstream_error"
    assert "PERSON" not in response.text


def test_upstream_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    response = _client(handler).get("/v1/models")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_unavailable"


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"data": 3}'])
def test_upstream_bad_body(body: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    response = _client(handler).get("/v1/models")
    assert response.status_code == 502


def test_token_required_when_configured() -> None:
    settings = Settings(upstream_base_url=UPSTREAM, api_token="t0ken-for-tests")  # noqa: S106 - a test token
    app = create_app(settings)
    app.state.models_config = ModelsConfig(upstream_models=("m",))
    client = TestClient(app)
    assert client.get("/v1/models").status_code == 401
    ok = client.get("/v1/models", headers={"Authorization": "Bearer t0ken-for-tests"})
    assert ok.status_code == 200
