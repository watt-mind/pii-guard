"""Account isolation and curated-demo contracts; every input is synthetic."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from pii_guard.api.errors import install_error_handlers
from pii_guard.config import Settings
from pii_guard.detect.rules import RuleDetector
from pii_guard.gateway.config import GatewayConfig, Mode
from pii_guard.gateway.detection import ModeDetector
from pii_guard.gateway.service import Gateway
from pii_guard.hosted import routes
from pii_guard.hosted.connections import ConnectionStore
from pii_guard.hosted.identity import ApiKeyStore, Principal
from pii_guard.hosted.quotas import DEMO_MAX_OUTPUT_TOKENS, QuotaLedger
from pii_guard.policy import PolicySet
from pii_guard.vault import Vault


@pytest.fixture
def route_app(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, list[dict[str, Any]]]:
    async def validate(url: str) -> str:
        return url

    app = FastAPI()
    app.state.settings = Settings(_env_file=None, detectors=("rules",))
    app.state.hosted = SimpleNamespace(
        settings=SimpleNamespace(hosted_max_output_tokens=8192, hosted_models=("muse-spark-1.3",)),
        keys=ApiKeyStore(),
        connections=ConnectionStore(validator=validate),
        quotas=QuotaLedger(),
        sponsored_enabled=False,
    )
    upstream_bodies: list[dict[str, Any]] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        upstream_bodies.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": body["messages"][0]["content"]},
                    }
                ]
            },
        )

    vault = Vault(b"s" * 32)
    gateway = Gateway(
        settings=Settings(
            _env_file=None,
            upstream_base_url="https://provider.example/v1",
            upstream_api_key=SecretStr("synthetic-upstream-key"),
            ner_fallback="off",
        ),
        vault=vault,
        config=GatewayConfig(_env_file=None),
        detectors={Mode.FAST: ModeDetector(Mode.FAST, RuleDetector(), "rules", PolicySet())},
        transport=httpx.MockTransport(upstream),
    )
    monkeypatch.setattr(routes, "get_gateway", lambda request: gateway)
    monkeypatch.setattr(routes, "get_vault", lambda request: vault)

    @app.middleware("http")
    async def principal(request: Request, call_next: Any) -> Any:
        owner = request.headers.get("x-test-owner", "guest")
        request.state.hosted_principal = Principal(
            owner, owner != "guest", "guest" if owner == "guest" else "google"
        )
        return await call_next(request)

    install_error_handlers(app)
    app.include_router(routes.router)
    return app, upstream_bodies


def test_account_hides_guest_identity_and_secrets(route_app: tuple[FastAPI, list[Any]]) -> None:
    app, _ = route_app
    with TestClient(app) as client:
        account = client.get("/v1/account").json()
    assert account["principal"] is None
    assert account["authenticated"] is False
    assert account["connections"] == []
    assert account["state"] == {"persistence": "ephemeral", "restart_loses_sessions": True}


def test_account_links_return_to_the_dashboard(route_app: tuple[FastAPI, list[Any]]) -> None:
    app, _ = route_app
    with TestClient(app) as client:
        account = client.get("/v1/account").json()
    assert account["login_url"] == "/.auth/login/google?post_login_redirect_uri=%2F%23overview"
    assert account["logout_url"] == "/.auth/logout?post_logout_redirect_uri=%2F"
    assert account["limits"]["sponsored_enabled"] is False


def test_account_names_the_included_model(route_app: tuple[FastAPI, list[Any]]) -> None:
    """The public page names the free runs' model from the API, never hard-coded (LAB-1466)."""
    app, _ = route_app
    with TestClient(app) as client:
        account = client.get("/v1/account").json()
    assert account["included_model"] == app.state.hosted.settings.hosted_models[0]


def test_key_revealed_once_owner_scoped_and_revoked(route_app: tuple[FastAPI, list[Any]]) -> None:
    app, _ = route_app
    a, b = {"x-test-owner": "user-a"}, {"x-test-owner": "user-b"}
    with TestClient(app) as client:
        denied = client.post("/v1/account/api-keys", json={"name": "test"})
        assert denied.status_code == 401
        created = client.post("/v1/account/api-keys", json={"name": "test"}, headers=a)
        assert created.status_code == 201
        item = created.json()
        listing = client.get("/v1/account/api-keys", headers=a).json()
        assert listing == [{key: value for key, value in item.items() if key != "key"}]
        assert item["key"] not in json.dumps(listing)
        assert client.get("/v1/account/api-keys", headers=b).json() == []
        path = "/v1/account/api-keys/" + item["id"]
        assert client.delete(path, headers=b).status_code == 404
        assert app.state.hosted.keys.resolve(item["key"]) is not None
        assert client.delete(path, headers=a).status_code == 204
        assert app.state.hosted.keys.resolve(item["key"]) is None
        assert client.delete(path, headers=a).status_code == 404


@pytest.mark.parametrize("name", [" ", "bad\nname", "x" * 65])
def test_key_name_errors_never_echo_inputs(route_app: tuple[FastAPI, list[Any]], name: str) -> None:
    app, _ = route_app
    with TestClient(app) as client:
        response = client.post(
            "/v1/account/api-keys", json={"name": name}, headers={"x-test-owner": "user-a"}
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert "bad\\nname" not in response.text


def test_connection_metadata_and_deletion_owner_scoped(
    route_app: tuple[FastAPI, list[Any]],
) -> None:
    app, _ = route_app
    a, b = {"x-test-owner": "user-a"}, {"x-test-owner": "user-b"}
    with TestClient(app) as client:
        request = {
            "provider": "custom",
            "api_key": "synthetic-provider-secret",
            "base_url": "https://provider.example/v1",
        }
        assert client.post("/v1/account/connections", json=request).status_code == 401
        response = client.post("/v1/account/connections", json=request, headers=a)
        assert response.status_code == 201
        item = response.json()
        assert set(item) == {"id", "provider", "origin", "expires_at"}
        assert "synthetic-provider-secret" not in response.text
        assert item["origin"] == "https://provider.example"
        assert client.get("/v1/account", headers=a).json()["connections"] == [item]
        assert client.get("/v1/account", headers=b).json()["connections"] == []
        path = "/v1/account/connections/" + item["id"]
        assert client.delete(path, headers=b).status_code == 404
        assert client.delete(path, headers=a).status_code == 204
        assert client.get("/v1/account", headers=a).json()["connections"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"sample_id": "hu-support", "text": "Arbitrary synthetic prompt"},
        {"sample_id": "hu-support", "model": "arbitrary-model"},
        {"sample_id": "hu-support", "language": "en"},
        {"sample_id": "arbitrary-sample"},
    ],
)
def test_demo_rejects_arbitrary_input_before_upstream(
    route_app: tuple[FastAPI, list[Any]], body: dict[str, Any]
) -> None:
    app, calls = route_app
    with TestClient(app) as client:
        response = client.post("/v1/demo", json=body)
    assert response.status_code == 422
    assert calls == []
    assert "Arbitrary synthetic prompt" not in response.text


@pytest.mark.parametrize("sample", ["hu-support", "en-support"])
def test_demo_real_masking_and_exact_roundtrip(
    route_app: tuple[FastAPI, list[Any]], sample: str
) -> None:
    app, calls = route_app
    with TestClient(app) as client:
        response = client.post("/v1/demo", json={"sample_id": sample})
    assert response.status_code == 200, response.text
    result = response.json()
    assert set(result) == {
        "sample_id",
        "language",
        "original",
        "masked",
        "answer",
        "restored",
        "entities",
        "model",
        "session_id",
        "request_id",
    }
    assert result["original"] == routes.DEMO_SAMPLES[sample][1]
    assert result["masked"] == calls[0]["messages"][0]["content"]
    assert result["answer"] == result["masked"]
    assert result["restored"] == result["original"]
    assert calls[0]["max_completion_tokens"] == DEMO_MAX_OUTPUT_TOKENS
    assert calls[0]["stream"] is False
    assert result["entities"]
    for entity in result["entities"]:
        value = result["original"][entity["start"] : entity["end"]]
        assert value not in result["masked"]
        assert entity["type"] == "EMAIL"
    assert result["session_id"]
    assert result["request_id"]


@pytest.mark.parametrize(
    "status,payload",
    [
        (502, {"error": {"message": "untrusted upstream details"}}),
        (200, {"choices": []}),
        (
            200,
            {
                "pii_guard": {
                    "masked_messages": [{"content": "masked"}],
                    "masked_answer": [{"content": ""}],
                },
                "choices": [{"message": {"content": ""}}],
            },
        ),
    ],
)
def test_failed_demo_discards_session_and_sanitizes_error(
    route_app: tuple[FastAPI, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    payload: dict[str, Any],
) -> None:
    from starlette.responses import JSONResponse

    app, _ = route_app
    vault = Vault(b"t" * 32)

    class FailedGateway:
        async def chat_completions(self, *args: Any, **kwargs: Any) -> tuple[Any, None]:
            return JSONResponse(
                payload, status_code=status, headers={"X-PII-Guard-Request-Id": "synthetic-id"}
            ), None

    monkeypatch.setattr(routes, "get_gateway", lambda request: FailedGateway())
    monkeypatch.setattr(routes, "get_vault", lambda request: vault)
    with TestClient(app) as client:
        response = client.post("/v1/demo", json={"sample_id": "en-support"})
    assert response.status_code == 502
    assert "untrusted upstream details" not in response.text
    assert "jane.placeholder@example.com" not in response.text
    assert len(vault) == 0


def test_demo_offsets_refuse_mismatched_masking() -> None:
    from pii_guard.gateway.service import UpstreamError

    vault = Vault(b"v" * 32)
    session = vault.session()
    with pytest.raises(UpstreamError, match="did not round-trip"):
        routes._demo_entities("synthetic source", "different output", session)
