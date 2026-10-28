"""The hosted review blockers of PR #159 (LAB-1412), each reproduced and shown fixed.

Every probe from the review runs against the real ASGI app with a mocked upstream; all
identities, keys and addresses are synthetic.
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import itertools
import json
import logging
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway.service import UPSTREAM_PAYLOAD_LIMIT, check_upstream_payload
from pii_guard.hosted.abuse import AbuseAdmission
from pii_guard.hosted.egress import EgressPolicyError, _check_addresses
from pii_guard.hosted.identity import ApiKeyStore, IdentityError, Principal
from pii_guard.hosted.quotas import (
    DEFAULT_INPUT_MICRODOLLARS_PER_TOKEN,
    DEFAULT_OUTPUT_MICRODOLLARS_PER_TOKEN,
    DEMO_MAX_OUTPUT_TOKENS,
    QuotaLedger,
    QuotaLimits,
    upstream_payload_bound,
)
from pii_guard.hosted.runtime import HostedCapacityError, HostedService
from pii_guard.types import PayloadTooLargeError

ORIGIN = "https://guard.example"
EMAIL = "synthetic.one@example.com"
SPONSORED_KEY = "synthetic-sponsored-key-0123456789"


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
            "upstream_api_key": SPONSORED_KEY,
            **overrides,
        },
    )


def funded(limits: QuotaLimits | None = None) -> QuotaLedger:
    """The default limits with a one-time sponsored allocation, as a deployment claims one."""
    return QuotaLedger(
        limits or QuotaLimits(),
        sponsored_allocation_microdollars=1_000_000_000,
        allocation_expires_at=time.time() + 3600,
        claim_allocation=lambda: True,
    )


def ticking() -> AbuseAdmission:
    """Abuse admission whose clock advances a second per call, so bursts refill."""
    counter = itertools.count(100)
    return AbuseAdmission(clock=lambda: float(next(counter)))


def echo(request: httpx.Request) -> httpx.Response:
    if request.method == "GET":
        return httpx.Response(200, json={"data": [{"id": "synthetic-model"}]})
    body = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "id": "synthetic-completion",
            "object": "chat.completion",
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": body["messages"][0]["content"]},
                }
            ],
        },
    )


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    clients: list[TestClient] = []

    def build(handler: Any = echo, **overrides: Any) -> TestClient:
        monkeypatch.setattr(
            "pii_guard.hosted.runtime.SecureTransport", lambda: httpx.MockTransport(handler)
        )
        client = TestClient(create_app(settings(**overrides)), base_url=ORIGIN)
        client.__enter__()
        client.app.state.hosted.quotas = funded()
        client.app.state.hosted.abuse = ticking()
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def chat(client: TestClient, content: str, headers: dict[str, str]) -> httpx.Response:
    return client.post(
        "/v1/chat/completions",
        json={"model": "muse-spark-1.3", "messages": [{"role": "user", "content": content}]},
        headers=headers,
    )


# --- Blocker 1: guest capacity DoS ------------------------------------------------------


def test_cookieless_account_calls_cannot_lock_out_a_signed_in_user(make_client: Any) -> None:
    # The review probe: three cookieless OPTIONS/HEAD/POST /v1/account calls with three
    # runtimes in all used to answer the next signed-in user with 429 hosted_capacity.
    client = make_client(hosted_max_principals=3)
    service = client.app.state.hosted
    for _ in range(4):
        for method in ("OPTIONS", "HEAD", "POST", "GET"):
            client.cookies.clear()
            response = client.request(method, "/v1/account", headers={"origin": ORIGIN})
            assert response.status_code in {200, 405}, (method, response.text)
    # No /v1/account method admits, reserves or takes a runtime.
    assert service._runtimes == {}
    assert service.quotas._users == {}
    assert service.quotas._requests == 0
    assert service._ingress == 0
    response = client.get("/v1/traffic", headers=auth())
    assert response.status_code == 200, response.text


def test_guest_runtimes_are_a_separate_pool_released_after_the_demo(make_client: Any) -> None:
    client = make_client(hosted_max_principals=1, hosted_max_guest_runtimes=1)
    service: HostedService = client.app.state.hosted
    guest = service.acquire(Principal("g_synthetic-guest-one", False, "guest"))
    # The guest pool is full; another guest is refused...
    with pytest.raises(HostedCapacityError):
        service.acquire(Principal("g_synthetic-guest-two", False, "guest"))
    # ...but a signed-in owner still gets the runtime reserved for owners.
    owner = service.acquire(Principal("u_synthetic-owner", True, "google"))
    service.release(owner)
    # An idle guest runtime is dropped at once: nothing of the demo outlives it.
    service.release(guest)
    assert list(service._runtimes) == ["u_synthetic-owner"]
    assert guest.vault._tenant_key == b""
    client.cookies.clear()
    demo = client.post("/v1/demo", json={"sample_id": "en-support"}, headers={"origin": ORIGIN})
    assert demo.status_code == 200, demo.text
    assert list(service._runtimes) == ["u_synthetic-owner"]


def test_guest_non_demo_methods_take_no_runtime_or_budget(make_client: Any) -> None:
    client = make_client()
    service = client.app.state.hosted
    for method in ("OPTIONS", "GET", "HEAD"):
        client.cookies.clear()
        response = client.request(method, "/v1/demo", headers={"origin": ORIGIN})
        assert response.status_code == 405, (method, response.text)
    assert service._runtimes == {}
    assert service.quotas._requests == 0


# --- Blocker 2: an API key minting keys and connections ---------------------------------


def test_api_key_cannot_manage_keys_or_connections(make_client: Any) -> None:
    client = make_client()
    issued = client.post("/v1/account/api-keys", json={"name": "synthetic"}, headers=auth())
    assert issued.status_code == 201, issued.text
    bearer = {"authorization": "Bearer " + issued.json()["key"]}
    probes = [
        ("POST", "/v1/account/api-keys", {"name": "successor"}),
        ("GET", "/v1/account/api-keys", None),
        ("DELETE", "/v1/account/api-keys/" + issued.json()["id"], None),
        ("POST", "/v1/account/connections", {"provider": "openai", "api_key": "sk-synthetic"}),
        ("DELETE", "/v1/account/connections/conn_synthetic", None),
    ]
    for method, path, body in probes:
        response = client.request(method, path, json=body, headers=bearer)
        assert response.status_code == 401, (method, path, response.text)
        assert response.json()["error"]["code"] == "unauthorized"
    # The key still works for data routes, and the signed-in session still sees one key.
    assert client.post("/v1/mask", json={"text": EMAIL}, headers=bearer).status_code == 200
    assert len(client.get("/v1/account/api-keys", headers=auth()).json()) == 1


def test_key_store_refuses_non_session_principals() -> None:
    keys = ApiKeyStore()
    for principal in (
        Principal("u_synthetic", True, "api_key"),
        Principal("g_synthetic", False, "guest"),
    ):
        with pytest.raises(IdentityError):
            keys.issue(principal, "successor")
        with pytest.raises(IdentityError):
            keys.list(principal)
        with pytest.raises(IdentityError):
            keys.revoke(principal, "key_synthetic")


# --- Blocker 3: reads spending quota, streams holding slots -----------------------------


def test_console_reads_do_not_spend_the_daily_request_quota(make_client: Any) -> None:
    # The review probe: 100 x GET /v1/traffic, then /v1/mask answered 429 for the day.
    client = make_client()
    for index in range(150):
        path = ("/v1/traffic", "/v1/status", "/v1/vault/sessions")[index % 3]
        response = client.get(path, headers=auth())
        assert response.status_code == 200, (index, path, response.text)
    service = client.app.state.hosted
    owner = next(iter(service._runtimes))
    assert service.quotas.usage(owner)["requests_today"] == 0
    response = client.post("/v1/mask", json={"text": EMAIL}, headers=auth())
    assert response.status_code == 200, response.text
    assert service.quotas.usage(owner)["requests_today"] == 1


def test_traffic_stream_holds_no_inference_slot() -> None:
    app = create_app(settings())
    app.router.routes[:] = [
        route for route in app.router.routes if getattr(route, "path", None) != "/v1/traffic/stream"
    ]

    async def scenario() -> None:
        opened = asyncio.Semaphore(0)

        @app.get("/v1/traffic/stream")
        async def stream(request: Request) -> StreamingResponse:
            assert request.state.hosted_runtime is not None

            async def chunks() -> Any:
                opened.release()
                yield b": synthetic\n\n"
                await asyncio.Event().wait()

            return StreamingResponse(chunks(), media_type="text/event-stream")

        app.router.routes.insert(0, app.router.routes.pop())
        service = app.state.hosted
        # One inference slot in all: a stream holding it would block every mask below.
        service.quotas = QuotaLedger(QuotaLimits(principal_concurrency=1, global_concurrency=1))
        service.abuse = ticking()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=ORIGIN
        ) as client:
            streams = [
                asyncio.create_task(client.get("/v1/traffic/stream", headers=auth()))
                for _ in range(2)
            ]
            for _ in streams:
                await asyncio.wait_for(opened.acquire(), 2)
            assert service.quotas._active == 0
            assert service._ingress == 0
            masked = await client.post("/v1/mask", json={"text": EMAIL}, headers=auth())
            assert masked.status_code == 200, masked.text
            # Streams are bounded on their own: a third for the same owner is refused.
            third = await client.get("/v1/traffic/stream", headers=auth())
            assert third.status_code == 429
            assert third.json()["error"]["code"] == "hosted_capacity"
            for task in streams:
                task.cancel()
            for task in streams:
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert service._streams == {}
            assert service.quotas.usage(next(iter(service._runtimes)))["requests_today"] == 1
        await service.close()

    asyncio.run(scenario())


# --- Blocker 4: the unrealistic pre-charge ----------------------------------------------


def test_guest_gets_the_documented_five_demos_with_default_limits(make_client: Any) -> None:
    # The review probe: a guest's demos came back [200, 200, 429, 429, 429].
    client = make_client()
    service = client.app.state.hosted
    limits = QuotaLimits()
    statuses = [
        client.post(
            "/v1/demo", json={"sample_id": "en-support"}, headers={"origin": ORIGIN}
        ).status_code
        for _ in range(limits.guest_requests + 1)
    ]
    assert statuses == [200] * limits.guest_requests + [429]
    # One demo reserves a request-sized amount (it used to be 4,505,600 microdollars): the
    # payload bound plus DEMO_MAX_OUTPUT_TOKENS, sized so the reasoning model can answer.
    per_demo = service.quotas._spent_today // limits.guest_requests
    assert per_demo < 150_000
    assert service.quotas.usage(next(iter(service.quotas._users)))["tokens_today"] <= (
        limits.guest_tokens
    )
    assert client.get("/v1/account").json()["limits"]["requests_per_day"] == 5


def test_a_28_kb_chat_is_admitted_for_a_fresh_user(make_client: Any) -> None:
    client = make_client()
    content = ("Synthetic support thread. Contact " + EMAIL + " about the delivery date. ") * 330
    assert 28_000 <= len(content.encode()) <= 30_000
    response = chat(client, content, auth("synthetic-fresh"))
    assert response.status_code == 200, response.text
    restored = response.json()["choices"][0]["message"]["content"]
    assert restored == content
    service = client.app.state.hosted
    usage = service.quotas.usage(next(iter(service._runtimes)))
    assert usage["requests_today"] == 1
    # Input is bounded by the request size; output by the hosted output cap.
    assert usage["tokens_today"] <= upstream_payload_bound(30_000) + 8192


def test_output_reservation_follows_the_requested_limit(make_client: Any) -> None:
    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "muse-spark-1.3",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 100,
        },
        headers=auth(),
    )
    assert response.status_code == 200, response.text
    service = client.app.state.hosted
    usage = service.quotas.usage(next(iter(service._runtimes)))
    assert usage["tokens_today"] < 100 + upstream_payload_bound(200)


def test_payload_beyond_the_admitted_bound_is_refused() -> None:
    check_upstream_payload(b"x" * 10_000)  # no bound outside hosted admission
    token = UPSTREAM_PAYLOAD_LIMIT.set(100)
    try:
        check_upstream_payload(b"x" * 100)
        with pytest.raises(PayloadTooLargeError):
            check_upstream_payload(b"x" * 101)
    finally:
        UPSTREAM_PAYLOAD_LIMIT.reset(token)


def test_masking_that_outgrows_its_charge_never_reaches_the_upstream(
    monkeypatch: pytest.MonkeyPatch, make_client: Any
) -> None:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return echo(request)

    client = make_client(record)
    # Shrink the allowance so a request whose masking more than doubles it exceeds the bound.
    monkeypatch.setattr("pii_guard.hosted.middleware.upstream_payload_bound", lambda n: n)
    response = chat(client, " ".join(["a" + str(i) + "@ex.co" for i in range(40)]), auth())
    assert response.status_code == 413, response.text
    assert response.json()["error"]["code"] == "payload_too_large"
    assert seen == []


# --- Minor items ------------------------------------------------------------------------


def test_rate_defaults_have_one_source() -> None:
    configured = Settings(_env_file=None)
    assert configured.hosted_input_microdollars_per_token == DEFAULT_INPUT_MICRODOLLARS_PER_TOKEN
    assert configured.hosted_output_microdollars_per_token == DEFAULT_OUTPUT_MICRODOLLARS_PER_TOKEN
    limits = QuotaLimits()
    assert limits.input_microdollars_per_token == DEFAULT_INPUT_MICRODOLLARS_PER_TOKEN
    assert limits.output_microdollars_per_token == DEFAULT_OUTPUT_MICRODOLLARS_PER_TOKEN
    service = HostedService(settings())
    assert service.quotas.limits.input_microdollars_per_token == limits.input_microdollars_per_token
    assert (
        service.quotas.limits.output_microdollars_per_token == limits.output_microdollars_per_token
    )
    assert configured.hosted_max_output_tokens >= DEMO_MAX_OUTPUT_TOKENS


def test_refused_upstream_response_counts_as_unreachable(
    make_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    def compressed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=gzip.compress(b"{}"),
            headers={"content-encoding": "gzip", "content-type": "application/json"},
        )

    client = make_client(compressed)
    with caplog.at_level(logging.INFO, logger="pii_guard.gateway"):
        response = chat(client, "Hello", auth())
    assert response.status_code == 502, response.text
    assert any("upstream_unreachable" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("address", ["64:ff9b::a9fe:a9fe", "64:ff9b::a00:1", "64:ff9b:1::1"])
def test_nat64_addresses_are_refused(address: str) -> None:
    with pytest.raises(EgressPolicyError):
        _check_addresses((address,))


def test_owner_traffic_log_scrubs_the_sponsored_key(make_client: Any) -> None:
    client = make_client()
    response = chat(client, "Please repeat " + SPONSORED_KEY, auth())
    assert response.status_code == 200, response.text
    traffic = client.get("/v1/traffic", headers=auth())
    assert traffic.status_code == 200
    assert traffic.json()["events"]
    assert SPONSORED_KEY not in traffic.text


def test_kill_switch_file_disables_sponsored_work(make_client: Any, tmp_path: Path) -> None:
    switch = tmp_path / "kill-sponsored"
    client = make_client(hosted_sponsored_kill_switch_path=str(switch))
    service = client.app.state.hosted
    assert chat(client, "Hello", auth()).status_code == 200
    service.purge_expired()
    assert not service.quotas.sponsored_killed
    switch.touch()
    refused = chat(client, "Hello", auth())
    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == "sponsored_unavailable"
    assert service.quotas.sponsored_killed
    # Removing the file does not re-enable sponsorship in this process.
    switch.unlink()
    service.purge_expired()
    assert service.quotas.sponsored_killed
    assert client.get("/v1/account").json()["limits"]["sponsored_enabled"] is False


def test_relative_kill_switch_path_cannot_start() -> None:
    with pytest.raises(ValueError):
        HostedService(settings(hosted_sponsored_kill_switch_path="relative/kill"))


def test_hosted_chat_under_local_only_profile(make_client: Any) -> None:
    from pii_guard.api.routes.chat import get_gateway
    from pii_guard.detection_profile import is_local_only

    client = make_client(detection_profile="local-only")
    response = chat(client, "Contact " + EMAIL, auth())
    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"] == "Contact " + EMAIL
    # The hosted gateway keeps the profile, so the local-only gateway check holds for it.
    service = client.app.state.hosted
    runtime = service.acquire(Principal("u_synthetic-profile", True, "google"))
    request = Request(
        {
            "type": "http",
            "app": client.app,
            "headers": [],
            "state": {"hosted_runtime": runtime},
        }
    )
    try:
        gateway = get_gateway(request)
        assert is_local_only(gateway.settings)
    finally:
        service.release(runtime)


def test_deeply_nested_chat_json_is_refused_not_a_500(make_client: Any) -> None:
    client = make_client()
    body = b"[" * 12_000 + b"]" * 12_000
    response = client.post(
        "/v1/chat/completions",
        content=body,
        headers={**auth(), "content-type": "application/json"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "hosted_request_denied"


# --- LAB-1372: measured reasoning budget and provider-billed tools ------------------------


def test_demo_output_budget_leaves_room_for_reasoning() -> None:
    # muse-spark-1.3 answered nothing at 512 and at most 2,994 completion tokens were used
    # by an answered call (eval/results/2026-10-28-lab-1372-meta-reasoning).
    assert DEMO_MAX_OUTPUT_TOKENS >= 4096
    with pytest.raises(ValueError):
        Settings(_env_file=None, hosted_max_output_tokens=DEMO_MAX_OUTPUT_TOKENS - 1)
    # Five demos stay inside the guest token budget.
    per_demo = upstream_payload_bound(64) + DEMO_MAX_OUTPUT_TOKENS
    limits = QuotaLimits()
    assert per_demo * limits.guest_requests <= limits.guest_tokens


@pytest.mark.parametrize(
    ("path", "extra"),
    [
        ("/v1/chat/completions", {"web_search_options": {}}),
        ("/v1/chat/completions", {"tools": [{"type": "web_search"}]}),
        ("/v1/chat/completions", {"tools": "web_search"}),
        ("/v1/responses", {"tools": [{"type": "web_search_preview"}]}),
        ("/v1/responses", {"tools": [{"type": "function", "name": "f"}, {"type": "mcp"}]}),
    ],
)
def test_sponsored_requests_cannot_ask_for_provider_billed_tools(
    make_client: Any, path: str, extra: dict[str, Any]
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return echo(request)

    client = make_client(handler)
    body: dict[str, Any] = {"model": "muse-spark-1.3", **extra}
    if path == "/v1/responses":
        body["input"] = "Hello"
    else:
        body["messages"] = [{"role": "user", "content": "Hello"}]
    response = client.post(path, json=body, headers=auth())
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "hosted_request_denied"
    assert calls == []
    assert client.app.state.hosted.quotas._spent_today == 0


def test_sponsored_requests_keep_client_side_function_tools(make_client: Any) -> None:
    client = make_client()
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "muse-spark-1.3",
            "messages": [{"role": "user", "content": "Hello"}],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "lookup", "parameters": {"type": "object"}},
                }
            ],
        },
        headers=auth(),
    )
    assert response.status_code == 200, response.text
