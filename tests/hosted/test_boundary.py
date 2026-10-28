"""Adversarial hosted boundaries through the real ASGI app; all identities are synthetic."""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.hosted.identity import Principal
from pii_guard.hosted.quotas import QuotaLedger, QuotaLimits
from pii_guard.hosted.runtime import HostedCapacityError

ORIGIN = "https://guard.example"
EMAIL = "synthetic.one@example.com"


def auth(subject: str = "synthetic-one", **extra: str) -> dict[str, str]:
    encoded = base64.b64encode(
        json.dumps({"auth_typ": "google", "claims": [{"typ": "sub", "val": subject}]}).encode()
    ).decode()
    return {"x-ms-client-principal": encoded, "origin": ORIGIN, **extra}


def settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        **{
            "hosted": True,
            "hosted_public_origin": ORIGIN,
            "hosted_trust_easy_auth": True,
            "hosted_single_process": True,
            "tenant_key": bytes(range(32)).hex(),
            "allowed_hosts": ("guard.example",),
            "detectors": ("rules",),
            "ner_fallback": "off",
            "upstream_api_key": "synthetic-sponsored-key",
            **overrides,
        },
    )


@pytest.fixture
def boundary(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, list[httpx.Request]]]:
    seen: list[httpx.Request] = []

    def echo(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"data": [{"id": "synthetic-model", "private_field": "must-be-dropped"}]},
            )
        body = json.loads(request.content)
        if request.url.path.endswith("/responses"):
            return httpx.Response(
                200,
                json={
                    "id": "synthetic-response",
                    "object": "response",
                    "status": "completed",
                    "model": body["model"],
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": body["input"]}],
                        }
                    ],
                },
            )
        text = body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "id": "synthetic-completion",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
            },
        )

    monkeypatch.setattr(
        "pii_guard.hosted.runtime.SecureTransport", lambda: httpx.MockTransport(echo)
    )
    monkeypatch.setattr(
        "pii_guard.hosted.egress.secure_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(echo), **kwargs),
    )
    app = create_app(settings())
    # An injected one-time durable allocator stands in for the deployment mount. The real
    # ledger still admits every request and retains reservations after failure.
    app.state.hosted.quotas = QuotaLedger(
        QuotaLimits(global_daily_microdollars=1_000_000_000),
        sponsored_allocation_microdollars=1_000_000_000,
        allocation_expires_at=time.time() + 3600,
        claim_allocation=lambda: True,
    )
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, seen


def chat(
    client: TestClient, headers: dict[str, str], path: str = "/v1/chat/completions"
) -> httpx.Response:
    return client.post(
        path,
        json={"model": "muse-spark-1.3", "messages": [{"role": "user", "content": EMAIL}]},
        headers=headers,
    )


def test_same_explicit_session_is_owner_scoped(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    client, seen = boundary
    one = chat(client, auth(), "/s/shared-synthetic/v1/chat/completions")
    two = chat(client, auth("synthetic-two"), "/s/shared-synthetic/v1/chat/completions")
    assert one.status_code == two.status_code == 200, (one.text, two.text)
    assert one.headers["x-pii-guard-session"] == two.headers["x-pii-guard-session"]
    masked_one = json.loads(seen[0].content)["messages"][0]["content"]
    masked_two = json.loads(seen[1].content)["messages"][0]["content"]
    assert EMAIL not in masked_one + masked_two
    assert masked_one != masked_two
    body = {"session_id": "shared-synthetic", "text": masked_one}
    own = client.post("/v1/unmask", json=body, headers=auth())
    other = client.post("/v1/unmask", json=body, headers=auth("synthetic-two"))
    assert own.status_code == other.status_code == 200
    assert own.json()["text"] == EMAIL
    assert other.json()["text"] == masked_one
    assert other.json()["unresolved"]
    stranger = client.post("/v1/unmask", json=body, headers=auth("synthetic-three"))
    assert stranger.status_code == 404


def test_vault_traffic_and_deletion_cannot_cross_owners(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    client, _ = boundary
    result = chat(client, auth())
    assert result.status_code == 200, result.text
    listing = client.get("/v1/vault/sessions", headers=auth()).json()["sessions"]
    assert len(listing) == 1
    ref = listing[0]["ref"]
    assert client.get("/v1/vault/sessions", headers=auth("synthetic-two")).json()["sessions"] == []
    for method in ("GET", "DELETE"):
        denied = client.request(method, f"/v1/vault/sessions/{ref}", headers=auth("synthetic-two"))
        assert denied.status_code == 404
    own_traffic = client.get("/v1/traffic", headers=auth()).json()["events"]
    assert len(own_traffic) == 1
    assert client.get("/v1/traffic", headers=auth("synthetic-two")).json()["events"] == []
    reveal = client.get(f"/v1/vault/sessions/{ref}?reveal=true", headers=auth())
    assert reveal.status_code == 403
    assert EMAIL not in json.dumps(listing) + json.dumps(own_traffic) + reveal.text
    assert client.get(f"/v1/vault/sessions/{ref}", headers=auth()).status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/v1/analyze",
        "/v1/mask",
        "/v1/unmask",
        "/v1/sessions",
        "/v1/chat/completions",
        "/v1/responses",
    ],
)
def test_anonymous_data_routes_refused(
    boundary: tuple[TestClient, list[httpx.Request]], path: str
) -> None:
    client, seen = boundary
    response = client.post(path, json={"text": EMAIL}, headers={"origin": ORIGIN})
    assert response.status_code == 401
    assert not seen


@pytest.mark.parametrize("path", ["/metrics", "/docs", "/redoc", "/openapi.json", "/v1/mask/image"])
def test_operator_and_image_routes_refused(
    boundary: tuple[TestClient, list[httpx.Request]], path: str
) -> None:
    client, _ = boundary
    assert client.get(path, headers=auth()).status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"sample_id": "hu-support", "text": EMAIL},
        {"sample_id": "hu-support", "model": "arbitrary"},
        {"sample_id": "arbitrary"},
        {"sample_id": "hu-support", "language": "en"},
    ],
)
def test_demo_never_accepts_free_text(
    boundary: tuple[TestClient, list[httpx.Request]], body: dict[str, str]
) -> None:
    client, seen = boundary
    response = client.post("/v1/demo", json=body, headers={"origin": ORIGIN})
    assert response.status_code == 422, response.text
    assert not seen
    assert EMAIL not in response.text


def test_api_key_owner_revocation_and_no_credential_forwarding(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    client, seen = boundary
    issued = client.post("/v1/account/api-keys", json={"name": "Synthetic key"}, headers=auth())
    assert issued.status_code == 201, issued.text
    key = issued.json()
    key_headers = {"authorization": "Bearer " + key["key"]}
    by_key = client.get("/v1/account", headers=key_headers).json()
    by_google = client.get("/v1/account", headers=auth()).json()
    assert by_key["principal"] == by_google["principal"]
    assert key["key"] not in client.get("/v1/account/api-keys", headers=auth()).text
    other = client.delete(f"/v1/account/api-keys/{key['id']}", headers=auth("synthetic-two"))
    assert other.status_code == 404
    result = chat(client, key_headers)
    assert result.status_code == 200, result.text
    assert seen[-1].headers["authorization"] == "Bearer synthetic-sponsored-key"
    assert key["key"] not in str(seen[-1].headers)
    assert not any(name.startswith("x-ms-") for name in seen[-1].headers)
    assert "cookie" not in seen[-1].headers
    assert client.delete(f"/v1/account/api-keys/{key['id']}", headers=auth()).status_code == 204
    assert client.get("/v1/account", headers=key_headers).status_code == 401
    assert client.get("/v1/account", headers=auth()).json()["authenticated"] is True


@pytest.mark.parametrize("origin", [None, "https://cross-site.example", "null"])
def test_cookie_identity_mutations_require_exact_origin(
    boundary: tuple[TestClient, list[httpx.Request]], origin: str | None
) -> None:
    client, _ = boundary
    headers = auth()
    headers.pop("origin")
    if origin is not None:
        headers["origin"] = origin
    assert client.post("/v1/sessions", json={}, headers=headers).status_code == 403


def test_duplicate_identity_spoofs_and_cross_site_fetch_refused(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    client, _ = boundary
    one = auth()["x-ms-client-principal"]
    two = auth("synthetic-two")["x-ms-client-principal"]
    assert (
        client.get(
            "/v1/account", headers=[("x-ms-client-principal", one), ("x-ms-client-principal", two)]
        ).status_code
        == 403
    )
    assert (
        client.get("/v1/account", headers={"x-ms-client-principal": "invalid"}).status_code == 401
    )
    assert (
        client.get(
            "/v1/account",
            headers={
                "x-ms-client-principal-name": "synthetic",
                "x-ms-client-principal-id": "synthetic",
            },
        ).json()["authenticated"]
        is False
    )
    assert (
        client.post(
            "/v1/sessions", json={}, headers=auth(**{"sec-fetch-site": "cross-site"})
        ).status_code
        == 403
    )


def test_runtime_pinning_expiry_and_capacity() -> None:
    app = create_app(settings(hosted_max_principals=1))
    service = app.state.hosted
    one = Principal("u_synthetic-one", True, "google")
    two = Principal("u_synthetic-two", True, "google")
    runtime = service.acquire(one)
    session = runtime.vault.session()
    runtime.touched -= 1000
    with pytest.raises(HostedCapacityError):
        service.acquire(two)
    service.release(runtime)
    runtime.touched -= service.settings.hosted_runtime_ttl + 1
    next_runtime = service.acquire(two)
    assert next_runtime is not runtime
    assert runtime.vault._tenant_key == b""
    assert runtime.vault._sessions == {}
    assert session._closed
    service.release(next_runtime)
    asyncio.run(service.close())


def test_stream_holds_runtime_until_response_finishes() -> None:
    app: FastAPI = create_app(settings(hosted_max_principals=1))
    entered, finish = threading.Event(), threading.Event()
    app.router.routes[:] = [
        route for route in app.router.routes if getattr(route, "path", None) != "/v1/traffic/stream"
    ]

    @app.get("/v1/traffic/stream")
    async def stream() -> StreamingResponse:
        async def chunks() -> Any:
            entered.set()
            yield b"synthetic"
            await asyncio.to_thread(finish.wait, 5)
            yield b"done"

        return StreamingResponse(chunks())

    app.router.routes.insert(0, app.router.routes.pop())
    with TestClient(app, base_url=ORIGIN) as client, ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.get, "/v1/traffic/stream", headers=auth())
        try:
            assert entered.wait(3)
            service = app.state.hosted
            runtime = next(iter(service._runtimes.values()))
            assert runtime.active == 1
            runtime.touched -= service.settings.hosted_runtime_ttl + 1
            with pytest.raises(HostedCapacityError):
                service.acquire(Principal("u_synthetic-two", True, "google"))
        finally:
            finish.set()
        response = pending.result(timeout=5)
        assert response.status_code == 200
        assert runtime.active == 0


def test_curated_demo_success_and_guest_identity_isolation(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    client, seen = boundary
    first = client.post("/v1/demo", json={"sample_id": "en-support"}, headers={"origin": ORIGIN})
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["sample_id"] == "en-support"
    assert payload["language"] == "en"
    assert payload["masked"] != payload["original"]
    assert payload["restored"] == payload["original"]
    assert payload["answer"] == payload["masked"]
    assert "jane.placeholder@example.com" not in seen[0].content.decode()
    assert payload["entities"]
    assert first.headers["set-cookie"].startswith("__Host-pii-guard-guest=")
    service = client.app.state.hosted
    guest_one = next(iter(service._runtimes))
    client.cookies.clear()
    second = client.post("/v1/demo", json={"sample_id": "en-support"}, headers={"origin": ORIGIN})
    assert second.status_code == 200, second.text
    assert len(service._runtimes) == 2
    assert second.json()["session_id"] != payload["session_id"]
    assert second.json()["masked"] != payload["masked"]
    assert guest_one in service._runtimes


def test_connection_owner_selection_deletion_and_no_sponsored_fallback(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    client, seen = boundary

    async def validated_destination(url: str) -> str:
        assert url == "https://provider.example/v1"
        return url

    client.app.state.hosted.connections._validator = validated_destination
    response = client.post(
        "/v1/account/connections",
        json={
            "provider": "custom",
            "api_key": "synthetic-own-upstream-key",
            "base_url": "https://provider.example/v1",
        },
        headers=auth(),
    )
    assert response.status_code == 201, response.text
    connection = response.json()
    assert set(connection) == {"id", "provider", "origin", "expires_at"}
    assert "synthetic-own-upstream-key" not in response.text
    assert client.get("/v1/account", headers=auth()).json()["connections"] == [connection]
    assert client.get("/v1/account", headers=auth("synthetic-two")).json()["connections"] == []
    chosen = {"x-pii-guard-connection": connection["id"]}
    rejected = chat(client, auth("synthetic-two", **chosen))
    assert rejected.status_code == 404
    assert not seen
    forwarded = chat(client, auth(**chosen))
    assert forwarded.status_code == 200, forwarded.text
    assert seen[-1].url.host == "provider.example"
    assert seen[-1].headers["authorization"] == "Bearer synthetic-own-upstream-key"
    assert "synthetic-sponsored-key" not in str(seen[-1].headers)
    for catalog in ("/v1/models", "/muse-code/models"):
        own_models = client.get(catalog, headers=auth(**chosen))
        assert own_models.status_code == 200, own_models.text
        assert own_models.json()["data"][0]["id"] == "synthetic-model"
        assert "private_field" not in own_models.text
        assert seen[-1].url.host == "provider.example"
        assert seen[-1].headers["authorization"] == "Bearer synthetic-own-upstream-key"
        assert client.get(catalog, headers=auth("synthetic-two", **chosen)).status_code == 404
    wrong_delete = client.delete(
        f"/v1/account/connections/{connection['id']}", headers=auth("synthetic-two")
    )
    assert wrong_delete.status_code == 404
    assert (
        client.delete(f"/v1/account/connections/{connection['id']}", headers=auth()).status_code
        == 204
    )
    assert chat(client, auth(**chosen)).status_code == 404
    assert len(seen) == 3


def test_account_inspection_remains_available_after_budget_exhaustion(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    client, seen = boundary
    client.app.state.hosted.quotas = QuotaLedger(QuotaLimits(user_requests=1))
    assert client.post("/v1/sessions", json={}, headers=auth()).status_code == 201
    assert client.post("/v1/sessions", json={}, headers=auth()).status_code == 429
    account = client.get("/v1/account", headers=auth())
    assert account.status_code == 200
    assert account.json()["usage"]["requests_today"] == 1
    assert account.json()["limits"]["sponsored_enabled"] is False
    assert not seen


@pytest.mark.parametrize(
    "override", [{"hosted_trust_easy_auth": False}, {"hosted_single_process": False}]
)
def test_hosted_startup_requires_explicit_trust_and_single_process(
    override: dict[str, bool],
) -> None:
    with pytest.raises(ValueError):
        create_app(settings(**override))


def test_responses_and_model_catalogs_use_hosted_boundary(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    client, seen = boundary
    for catalog in ("/v1/models", "/muse-code/models"):
        assert client.get(catalog).status_code == 401
        response = client.get(catalog, headers=auth())
        assert response.status_code == 200, response.text
        assert [model["id"] for model in response.json()["data"]] == ["muse-spark-1.3"]
    assert not seen
    one = client.post(
        "/s/synthetic-responses/v1/responses",
        json={"model": "muse-spark-1.3", "input": EMAIL},
        headers=auth(),
    )
    assert one.status_code == 200, one.text
    assert one.json()["output"][0]["content"][0]["text"] == EMAIL
    assert EMAIL not in seen[0].content.decode()
    sent = json.loads(seen[0].content)
    assert sent["max_output_tokens"] == 8192
    assert seen[0].headers["authorization"] == "Bearer synthetic-sponsored-key"
    assert (
        client.post(
            "/v1/unmask",
            json={"session_id": one.headers["x-pii-guard-session"], "text": sent["input"]},
            headers=auth("synthetic-two"),
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "extra", [{"model": "unapproved"}, {"max_tokens": 32769}, {"max_tokens": True}, {"n": 2}]
)
def test_sponsored_model_and_output_limits_admit_no_upstream_work(
    boundary: tuple[TestClient, list[httpx.Request]], extra: dict[str, Any]
) -> None:
    client, seen = boundary
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "muse-spark-1.3",
            "messages": [{"role": "user", "content": EMAIL}],
            **extra,
        },
        headers=auth(),
    )
    assert response.status_code == 403
    assert not seen
    assert client.get("/v1/account", headers=auth()).json()["usage"]["requests_today"] == 0


def test_cancelled_stream_releases_runtime_and_admission_but_keeps_charge() -> None:
    app = create_app(settings(hosted_max_principals=1))
    app.router.routes[:] = [
        route for route in app.router.routes if getattr(route, "path", None) != "/v1/traffic/stream"
    ]

    async def scenario() -> None:
        entered = asyncio.Event()

        @app.get("/v1/traffic/stream")
        async def stream() -> StreamingResponse:
            async def chunks() -> Any:
                entered.set()
                yield b"synthetic"
                await asyncio.Event().wait()

            return StreamingResponse(chunks())

        app.router.routes.insert(0, app.router.routes.pop())
        service = app.state.hosted
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=ORIGIN
        ) as client:
            pending = asyncio.create_task(client.get("/v1/traffic/stream", headers=auth()))
            await asyncio.wait_for(entered.wait(), 2)
            owner, runtime = next(iter(service._runtimes.items()))
            assert runtime.active == 1
            assert service.quotas._active == 1
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert runtime.active == 0
            assert service.quotas._active == 0
            assert service.quotas.usage(owner)["requests_today"] == 1
        await service.close()

    asyncio.run(scenario())


def test_session_capacity_refuses_growth_without_evicting_existing_values(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    client, _ = boundary
    client.app.state.hosted.settings.hosted_max_sessions = 1
    first = client.post("/v1/mask", json={"text": EMAIL}, headers=auth())
    assert first.status_code == 200, first.text
    second = client.post("/v1/sessions", json={}, headers=auth())
    assert second.status_code == 429, second.text
    restored = client.post(
        "/v1/unmask",
        json={"session_id": first.json()["session_id"], "text": first.json()["masked_text"]},
        headers=auth(),
    )
    assert restored.status_code == 200
    assert restored.json()["text"] == EMAIL
