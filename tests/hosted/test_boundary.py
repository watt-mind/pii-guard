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
from pii_guard.hosted.abuse import AbuseAdmission
from pii_guard.hosted.identity import Principal
from pii_guard.hosted.quotas import QuotaLedger, QuotaLimits
from pii_guard.hosted.runtime import HostedCapacityError
from pii_guard.hosted.spend import DurableSpend
from pii_guard.observability import ObservabilitySettings

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
        text = body["messages"][-1]["content"]
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


def test_unavailable_durable_accounting_keeps_account_and_owned_byok_operational(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    client, seen = boundary
    service = client.app.state.hosted
    service.spend = DurableSpend(None, None, daily_ceiling=10_000_000)

    async def public_endpoint(url):
        return url

    service.connections._validator = public_endpoint
    denied = chat(client, auth())
    assert denied.status_code == 503
    assert denied.json()["error"]["code"] == "sponsored_unavailable"
    assert not seen
    account = client.get("/v1/account", headers=auth())
    assert account.status_code == 200
    assert account.json()["limits"]["sponsored_enabled"] is False
    connection = client.post(
        "/v1/account/connections",
        json={"provider": "openai", "api_key": "synthetic-owned-key"},
        headers=auth(),
    )
    assert connection.status_code == 201, connection.text
    byok = chat(client, auth(**{"x-pii-guard-connection": connection.json()["id"]}))
    assert byok.status_code == 200, byok.text
    assert len(seen) == 1
    assert seen[0].headers["authorization"] == "Bearer synthetic-owned-key"
    assert service.quotas._spent_allocation == 0
    assert service._ingress == service.quotas._active == 0


def test_real_demo_cookie_rotation_hits_network_burst_then_allows_sign_in(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    client, seen = boundary
    service = client.app.state.hosted
    service.abuse = AbuseAdmission("aca_xff_rightmost", clock=lambda: 100.0)
    for index in range(30):
        client.cookies.clear()
        response = client.post(
            "/v1/demo",
            json={"sample_id": "en-support"},
            headers={
                "origin": ORIGIN,
                "x-forwarded-for": f"198.51.100.{index + 1}, 192.0.2.1",
                "forwarded": "for=203.0.113.1",
                "x-real-ip": "203.0.113.2",
            },
        )
        assert response.status_code == 200, response.text
    assert len(seen) == 30
    client.cookies.clear()
    denied = client.post(
        "/v1/demo",
        json={"sample_id": "en-support"},
        headers={"origin": ORIGIN, "x-forwarded-for": "203.0.113.1, 192.0.2.1"},
    )
    assert denied.status_code == 429
    assert denied.json()["error"]["code"] == "abuse_throttled"
    assert denied.headers["retry-after"] == "2"
    assert len(seen) == 30
    spent = service.quotas._spent_allocation
    assert client.get("/v1/account").status_code == 200
    # Sign-in has an independent allowance and still charges the SAME total allocation.
    signed_in = client.post("/v1/demo", json={"sample_id": "en-support"}, headers=auth())
    assert signed_in.status_code == 200, signed_in.text
    assert service.quotas._spent_allocation > spent
    assert len(seen) == 31
    assert service._ingress == service.quotas._active == 0
    assert all(
        header not in request.headers
        for request in seen
        for header in ("x-forwarded-for", "forwarded", "x-real-ip")
    )


def test_real_demo_keeps_five_request_guest_cap_and_shared_network_allowance(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    client, seen = boundary
    service = client.app.state.hosted
    service.abuse = AbuseAdmission("aca_xff_rightmost", clock=lambda: 100.0)
    service.quotas = QuotaLedger(
        QuotaLimits(guest_tokens=1_000_000, global_daily_microdollars=1_000_000_000),
        sponsored_allocation_microdollars=1_000_000_000,
        allocation_expires_at=time.time() + 3600,
        claim_allocation=lambda: True,
    )
    for _ in range(2):
        client.cookies.clear()
        for _ in range(5):
            response = client.post(
                "/v1/demo",
                json={"sample_id": "en-support"},
                headers={"origin": ORIGIN, "x-forwarded-for": "192.0.2.1"},
            )
            assert response.status_code == 200, response.text
        denied = client.post(
            "/v1/demo",
            json={"sample_id": "en-support"},
            headers={"origin": ORIGIN, "x-forwarded-for": "192.0.2.1"},
        )
        assert denied.status_code == 429
        assert denied.json()["error"]["code"] == "quota_exceeded"
    assert len(seen) == 10
    assert len(service.abuse._networks) == 1


def test_same_explicit_session_is_owner_scoped(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    client, seen = boundary
    one = chat(client, auth(), "/s/shared-synthetic/v1/chat/completions")
    two = chat(client, auth("synthetic-two"), "/s/shared-synthetic/v1/chat/completions")
    assert one.status_code == two.status_code == 200, (one.text, two.text)
    assert one.headers["x-pii-guard-session"] == two.headers["x-pii-guard-session"]
    masked_one = json.loads(seen[0].content)["messages"][-1]["content"]
    masked_two = json.loads(seen[1].content)["messages"][-1]["content"]
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


# Hosted images (LAB-1390) are admitted for signed-in owners: see test_images.py.
@pytest.mark.parametrize("path", ["/metrics", "/docs", "/redoc", "/openapi.json"])
def test_operator_routes_refused(
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
    # A guest runtime holds only the ephemeral demo, so it is gone once the demo is (LAB-1412).
    assert service._runtimes == {}
    client.cookies.clear()
    second = client.post("/v1/demo", json={"sample_id": "en-support"}, headers={"origin": ORIGIN})
    assert second.status_code == 200, second.text
    assert service._runtimes == {}
    assert second.json()["session_id"] != payload["session_id"]
    assert second.json()["masked"] != payload["masked"]


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
    "extra",
    [
        {"model": "unapproved"},
        {"max_tokens": 0},
        {"max_completion_tokens": -1},
        {"max_tokens": True},
        {"max_output_tokens": "100"},
        {"max_tokens": 1.5},
        {"n": 2},
    ],
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


@pytest.mark.parametrize(
    ("route", "extra", "field", "expected"),
    [
        # LAB-1651: OpenCode asks for 32000, pi 16384, Muse 32000; clamped, not refused.
        ("/v1/chat/completions", {"max_tokens": 32000}, "max_completion_tokens", 8192),
        ("/v1/chat/completions", {"max_completion_tokens": 16384}, "max_completion_tokens", 8192),
        ("/v1/chat/completions", {"max_tokens": 10**12}, "max_completion_tokens", 8192),
        ("/v1/chat/completions", {"max_tokens": 900}, "max_completion_tokens", 900),
        (
            "/v1/chat/completions",
            {"max_tokens": 32000, "max_completion_tokens": 700},
            "max_completion_tokens",
            700,
        ),
        ("/v1/responses", {"max_output_tokens": 32000}, "max_output_tokens", 8192),
    ],
)
def test_output_limit_above_the_hosted_cap_is_clamped(
    boundary: tuple[TestClient, list[httpx.Request]],
    route: str,
    extra: dict[str, Any],
    field: str,
    expected: int,
) -> None:
    client, seen = boundary
    content = {"messages": [{"role": "user", "content": EMAIL}]}
    if route == "/v1/responses":
        content = {"input": EMAIL}
    response = client.post(
        route, json={"model": "muse-spark-1.3", **content, **extra}, headers=auth()
    )
    assert response.status_code == 200, response.text
    sent = json.loads(seen[-1].content)
    assert sent[field] == expected
    others = {"max_tokens", "max_completion_tokens", "max_output_tokens"} - {field}
    assert not others & sent.keys()


def test_cancelled_stream_releases_runtime_and_stream_slot_without_charge() -> None:
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
            # A live stream is a read (LAB-1412): no inference slot, no ingress slot, no
            # daily request; it holds one of its own bounded stream slots instead.
            assert service.quotas._active == 0
            assert service._ingress == 0
            assert service._streams == {owner: 1}
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert runtime.active == 0
            assert service._streams == {}
            assert service.quotas.usage(owner)["requests_today"] == 0
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


class _ObservedUpstreamStream(httpx.AsyncByteStream):
    """Expose resource cleanup and consumption without opening a network connection."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.reads = 0
        self.closed = False

    async def __aiter__(self) -> Any:
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def _custom_profile(client: TestClient) -> dict[str, str]:
    async def validated_destination(url: str) -> str:
        assert url == "https://provider.example/v1"
        return url

    client.app.state.hosted.connections._validator = validated_destination
    created = client.post(
        "/v1/account/connections",
        json={
            "provider": "custom",
            "api_key": "synthetic-own-upstream-key",
            "base_url": "https://provider.example/v1",
        },
        headers=auth(),
    )
    assert created.status_code == 201, created.text
    return auth(**{"x-pii-guard-connection": created.json()["id"]})


def _assert_hosted_work_released(client: TestClient) -> None:
    service = client.app.state.hosted
    assert service.quotas._active == 0
    assert all(runtime.active == 0 for runtime in service._runtimes.values())
    # Connection creation plus the failed upstream call; failures never refund admission.
    assert client.get("/v1/account", headers=auth()).json()["usage"]["requests_today"] == 2


@pytest.mark.parametrize("path", ["/v1/chat/completions", "/v1/responses"])
@pytest.mark.parametrize("prefetched", [False, True])
@pytest.mark.parametrize("stream", [False, True])
def test_custom_upstream_size_cap_covers_whole_prefetched_and_sse(
    boundary: tuple[TestClient, list[httpx.Request]],
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    prefetched: bool,
    stream: bool,
) -> None:
    client, _ = boundary
    headers = _custom_profile(client)
    # Deliberately exceed 2 MiB cumulatively with chunks below the cap individually.
    # An SSE line without a newline must also be bounded before the parser buffers it.
    padding = b"x" * (1024 * 1024)
    if stream:
        chunks = [b"data: " + padding, padding, b"\n\n"]
        content_type = "text/event-stream"
    else:
        chunks = [b'{"synthetic_padding":"' + padding, padding, b'"}']
        content_type = "application/json"
    observed = _ObservedUpstreamStream(chunks)
    upstream_responses: list[httpx.Response] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "provider.example"
        assert request.headers["authorization"] == "Bearer synthetic-own-upstream-key"
        response = httpx.Response(
            200,
            headers={"content-type": content_type},
            **({"content": b"".join(chunks)} if prefetched else {"stream": observed}),
        )
        upstream_responses.append(response)
        return response

    monkeypatch.setattr(
        "pii_guard.hosted.runtime.SecureTransport", lambda: httpx.MockTransport(upstream)
    )
    body: dict[str, Any] = {"model": "synthetic-model", "stream": stream}
    body.update(
        {"input": EMAIL}
        if path == "/v1/responses"
        else {"messages": [{"role": "user", "content": EMAIL}]}
    )
    result = client.post(path, json=body, headers=headers)
    if stream and not prefetched:
        assert result.status_code == 200, result.text
        assert "stream_failed" in result.text
        assert result.headers["content-type"].startswith("text/event-stream")
    else:
        assert result.status_code == 502, result.text
        assert result.json()["error"]["code"] == "upstream_unavailable"
    assert len(result.content) < 4096
    assert b"x" * 100 not in result.content
    assert len(upstream_responses) == 1
    assert upstream_responses[0].is_closed
    if not prefetched:
        assert observed.closed
        assert observed.reads == 2  # The over-limit chunk ends consumption; no trailing read.
    _assert_hosted_work_released(client)


@pytest.mark.parametrize("path", ["/v1/chat/completions", "/v1/responses"])
@pytest.mark.parametrize("prefetched", [False, True])
@pytest.mark.parametrize("stream", [False, True])
def test_compressed_custom_upstream_is_refused_before_consumption(
    boundary: tuple[TestClient, list[httpx.Request]],
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    prefetched: bool,
    stream: bool,
) -> None:
    import gzip

    client, _ = boundary
    headers = _custom_profile(client)
    # Small, safe fixture: the policy blocks compression itself, not merely expansion size.
    compressed = gzip.compress(b'{"synthetic":"small"}')
    observed = _ObservedUpstreamStream([compressed])
    upstream_responses: list[httpx.Response] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(
            200,
            headers={
                "content-encoding": "gzip",
                "content-type": "text/event-stream" if stream else "application/json",
            },
            **({"content": compressed} if prefetched else {"stream": observed}),
        )
        upstream_responses.append(response)
        return response

    monkeypatch.setattr(
        "pii_guard.hosted.runtime.SecureTransport", lambda: httpx.MockTransport(upstream)
    )
    body: dict[str, Any] = {"model": "synthetic-model", "stream": stream}
    body.update(
        {"input": EMAIL}
        if path == "/v1/responses"
        else {"messages": [{"role": "user", "content": EMAIL}]}
    )
    result = client.post(path, json=body, headers=headers)
    assert result.status_code == 502, result.text
    assert result.json()["error"]["code"] == "upstream_unavailable"
    assert len(result.content) < 4096
    assert upstream_responses[0].is_closed
    if not prefetched:
        assert observed.closed
        assert observed.reads == 0
    _assert_hosted_work_released(client)


# --- Sponsored-route attribution headers (LAB-1461) ---------------------------------------


def _attribution_free(request: httpx.Request) -> None:
    assert "x-pii-guard-source" not in request.headers
    assert not request.headers.get("user-agent", "").startswith("pii-guard/")


def test_sponsored_upstream_calls_carry_only_fixed_attribution_headers(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    from pii_guard import __version__

    client, seen = boundary
    subject = "synthetic-attribution-subject"
    assert chat(client, auth(subject)).status_code == 200
    assert (
        client.post(
            "/v1/responses", json={"model": "muse-spark-1.3", "input": EMAIL}, headers=auth(subject)
        ).status_code
        == 200
    )
    assert len(seen) == 2
    principal = client.get("/v1/account", headers=auth(subject)).json()["principal"]["id"]
    for request in seen:
        assert request.headers["x-pii-guard-source"] == "pii-guard-hosted-demo"
        assert request.headers["user-agent"] == (
            f"pii-guard/{__version__} (+https://github.com/watt-mind/pii-guard)"
        )
        assert request.headers["authorization"] == "Bearer synthetic-sponsored-key"
        # Neither header (nor any other) names the user, their principal or their session.
        for value in request.headers.values():
            assert subject not in value and principal not in value and EMAIL not in value


def test_own_connection_upstream_calls_carry_no_source_header(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    client, seen = boundary
    headers = _custom_profile(client)
    # A client-supplied tag never reaches an own endpoint either.
    headers["x-pii-guard-source"] = "spoofed-by-client"
    assert chat(client, headers).status_code == 200
    assert seen[-1].url.host == "provider.example"
    _attribution_free(seen[-1])


def test_project_endpoints_tag_only_the_sponsored_route(
    boundary: tuple[TestClient, list[httpx.Request]], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, recorded = boundary

    def project_upstream(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        text = json.loads(request.content)["messages"][-1]["content"]
        return httpx.Response(
            200,
            json={
                "id": "synthetic-completion",
                "object": "chat.completion",
                "model": "synthetic-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
            },
        )

    monkeypatch.setattr(
        "pii_guard.hosted.egress.SecureTransport", lambda: httpx.MockTransport(project_upstream)
    )
    owner = client.get("/v1/account", headers=auth()).json()["principal"]["id"]
    store = client.app.state.projects.store
    project = store.default_project(owner)["id"]
    policy = store.list_policies(owner, project)[0]["policy_version_id"]
    sponsored = store.save_endpoint(
        owner,
        project,
        {
            "name": "Synthetic sponsored endpoint",
            "policy_version_id": policy,
            "provider": "sponsored",
            "base_url": "https://api.meta.ai/v1",
            "model": "muse-spark-1.3",
        },
    )
    own = store.save_endpoint(
        owner,
        project,
        {
            "name": "Synthetic own Meta key",
            "policy_version_id": policy,
            "provider": "meta",
            "base_url": "https://api.meta.ai/v1",
            "model": "muse-spark-1.3",
            "api_key": "synthetic-own-meta-key",
        },
    )
    body = {"model": "muse-spark-1.3", "messages": [{"role": "user", "content": EMAIL}]}
    tagged = client.post(f"/e/{sponsored['id']}/v1/chat/completions", json=body, headers=auth())
    assert tagged.status_code == 200, tagged.text
    assert recorded[-1].headers["x-pii-guard-source"] == "pii-guard-hosted-demo"
    assert recorded[-1].headers["user-agent"].startswith("pii-guard/")
    untagged = client.post(f"/e/{own['id']}/v1/chat/completions", json=body, headers=auth())
    assert untagged.status_code == 200, untagged.text
    assert recorded[-1].headers["authorization"] == "Bearer synthetic-own-meta-key"
    _attribution_free(recorded[-1])


# --- Multi-tenant Prometheus scrape boundary and aggregation -------------------------------


def test_hosted_metrics_requires_dedicated_scrape_token_and_aggregates_all_runtimes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def echo(request: httpx.Request) -> httpx.Response:
        text = json.loads(request.content)["messages"][-1]["content"]
        return httpx.Response(
            200,
            json={
                "id": "synthetic-completion",
                "object": "chat.completion",
                "model": "muse-spark-1.3",
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
            },
        )

    monkeypatch.setattr(
        "pii_guard.hosted.runtime.SecureTransport", lambda: httpx.MockTransport(echo)
    )
    monkeypatch.setattr(
        "pii_guard.hosted.egress.SecureTransport", lambda: httpx.MockTransport(echo)
    )
    obs = ObservabilitySettings(metrics=True, metrics_token="synthetic-scrape-token")  # noqa: S106
    app = create_app(settings(), obs)
    app.state.hosted.quotas = QuotaLedger(
        QuotaLimits(global_daily_microdollars=1_000_000_000),
        sponsored_allocation_microdollars=1_000_000_000,
        allocation_expires_at=time.time() + 3600,
        claim_allocation=lambda: True,
    )
    with TestClient(app, base_url=ORIGIN) as client:
        # Anonymous, Google session, and owner API key must all be denied on /metrics.
        assert client.get("/metrics").status_code == 403
        assert client.get("/metrics", headers=auth()).status_code == 403
        assert (
            client.get("/metrics", headers={"Authorization": "Bearer wrong-token"}).status_code
            == 403
        )
        key_res = client.post(
            "/v1/account/api-keys", json={"name": "Synthetic key"}, headers=auth()
        )
        assert key_res.status_code == 201
        api_key = key_res.json()["key"]
        assert (
            client.get("/metrics", headers={"Authorization": f"Bearer {api_key}"}).status_code
            == 403
        )
        # Conversely, the scrape token cannot be used as an API key on tenant routes.
        assert (
            client.post(
                "/v1/mask",
                json={"text": EMAIL},
                headers={"Authorization": "Bearer synthetic-scrape-token"},
            ).status_code
            == 401
        )

        # Generate traffic across two owners, REST /v1/mask, a project endpoint, and remote ingest.
        assert chat(client, auth("synthetic-one")).status_code == 200
        assert (
            client.post("/v1/mask", json={"text": EMAIL}, headers=auth("synthetic-two")).status_code
            == 200
        )
        owner = client.get("/v1/account", headers=auth("synthetic-one")).json()["principal"]["id"]
        store = client.app.state.projects.store
        project = store.default_project(owner)["id"]
        policy = store.list_policies(owner, project)[0]["policy_version_id"]
        endpoint = store.save_endpoint(
            owner,
            project,
            {
                "name": "Synthetic sponsored endpoint",
                "policy_version_id": policy,
                "provider": "sponsored",
                "base_url": "https://api.meta.ai/v1",
                "model": "muse-spark-1.3",
            },
        )
        body = {"model": "muse-spark-1.3", "messages": [{"role": "user", "content": EMAIL}]}
        assert (
            client.post(
                f"/e/{endpoint['id']}/v1/chat/completions",
                json=body,
                headers=auth("synthetic-one"),
            ).status_code
            == 200
        )
        ingest_res = client.post(
            f"/e/{endpoint['id']}/v1/traffic",
            json={
                "events": [
                    {
                        "id": "req_remote_1",
                        "outcome": "ok",
                        "mode": "fast",
                        "detectors": ["rules"],
                        "entities": {
                            "detected": {"EMAIL": 2},
                            "masked": {"EMAIL": 2},
                            "blocked": {},
                            "unmasked": 1,
                        },
                        "upstream": {"unresolved_placeholders": 1},
                        "outbound_check": {"result": "passed", "hits": {}},
                        "timing": {
                            "overhead_ms": 4.2,
                            "upstream_ms": 120.0,
                            "stages_ms": {"detect": 2.0, "mask": 1.2, "unmask": 1.0},
                            "detectors_ms": {"rules": 2.0},
                        },
                        "usage": {"prompt_tokens": 20, "completion_tokens": 10},
                    }
                ]
            },
            headers=auth("synthetic-one"),
        )
        assert ingest_res.status_code == 200, ingest_res.text

        # Scrape with Authorization: Bearer <metrics_token> and X-PII-Guard-Token: <metrics_token>.
        scraped = client.get("/metrics", headers={"Authorization": "Bearer synthetic-scrape-token"})
        assert scraped.status_code == 200
        alt = client.get("/metrics", headers={"X-PII-Guard-Token": "synthetic-scrape-token"})
        assert alt.status_code == 200
        text = scraped.text

    # 2 gateway chat completions + 1 remote ingested event = 3 gateway requests
    assert 'pii_guard_gateway_requests_total{mode="fast",outcome="ok"} 3' in text
    # 1 EMAIL in owner chat + 1 in /v1/mask + 1 in endpoint chat + 2 in remote ingest = 5
    assert 'pii_guard_entities_detected_total{entity_type="EMAIL"} 5' in text
    assert 'pii_guard_entities_masked_total{entity_type="EMAIL"} 5' in text
    assert "pii_guard_unresolved_placeholders_total 1" in text
    assert 'pii_guard_upstream_tokens_total{direction="input"} 42' in text
    assert 'pii_guard_upstream_tokens_total{direction="output"} 24' in text
    assert "pii_guard_vault_active_sessions 3" in text
    assert 'pii_guard_hosted_active_runtimes{kind="owner"} 3' in text
    assert 'pii_guard_hosted_active_runtimes{kind="guest"} 0' in text
    assert "pii_guard_hosted_active_streams 0" in text
    assert "pii_guard_hosted_sponsored_available 1" in text
    # Verify no tenant identifiers or PII appear in the metrics payload.
    assert EMAIL not in text
    assert "synthetic-one" not in text and "synthetic-two" not in text
    assert owner not in text
