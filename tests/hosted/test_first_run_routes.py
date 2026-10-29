"""``POST /v1/account/first-run`` (LAB-1455): a ready default endpoint straight after sign-in.

Sponsored on: the endpoint answers through the server-owned sponsored route. Sponsored off: it
needs the owner's own Meta key, which is sent only to Meta and never replaced by sponsored
inference. Identities, keys and hosts are synthetic (ADR 0005).
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.hosted.abuse import AbuseAdmission
from pii_guard.hosted.quotas import QuotaLedger, QuotaLimits

ORIGIN = "https://guard.example"
SPONSORED_KEY = "synthetic-sponsored-key-0123456789"
OWN_KEY = "synthetic-own-meta-key-9876543210"
MODEL = "muse-spark-1.3"


def auth(subject: str = "synthetic-one") -> dict[str, str]:
    encoded = base64.b64encode(
        json.dumps({"auth_typ": "google", "claims": [{"typ": "sub", "val": subject}]}).encode()
    ).decode()
    return {"x-ms-client-principal": encoded, "origin": ORIGIN}


def settings() -> Settings:
    return Settings(
        _env_file=None,
        hosted=True,
        hosted_public_origin=ORIGIN,
        hosted_trust_easy_auth=True,
        hosted_single_process=True,
        tenant_key=bytes(range(32)).hex(),
        allowed_hosts=("guard.example",),
        detectors=("rules",),
        ner_fallback="off",
        upstream_api_key=SPONSORED_KEY,
    )


class Upstream:
    """Records where each upstream call went and with which key; echoes the masked prompt."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((str(request.url), request.headers.get("authorization", "")))
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
                        "message": {
                            "role": "assistant",
                            "content": body["messages"][-1]["content"],
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch, upstream: Upstream) -> Iterator[Any]:
    monkeypatch.setattr(
        "pii_guard.hosted.egress.SecureTransport", lambda: httpx.MockTransport(upstream)
    )
    monkeypatch.setattr(
        "pii_guard.hosted.runtime.SecureTransport", lambda: httpx.MockTransport(upstream)
    )

    async def public(url: str) -> str:
        return url

    monkeypatch.setattr("pii_guard.hosted.routes.validate_destination", public)
    clients: list[TestClient] = []

    def build(*, sponsored: bool) -> TestClient:
        client = TestClient(create_app(settings()), base_url=ORIGIN)
        client.__enter__()
        hosted = client.app.state.hosted
        if sponsored:
            hosted.quotas = QuotaLedger(
                QuotaLimits(),
                sponsored_allocation_microdollars=1_000_000_000,
                allocation_expires_at=time.time() + 3600,
                claim_allocation=lambda: True,
            )
        counter = iter(range(100, 100_000))
        hosted.abuse = AbuseAdmission(clock=lambda: float(next(counter)))
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def first_run(client: TestClient, subject: str = "synthetic-one", **body: Any) -> httpx.Response:
    return client.post("/v1/account/first-run", json=body, headers=auth(subject))


def test_sponsored_first_run_is_ready_with_a_key_shown_once(make_client: Any) -> None:
    client = make_client(sponsored=True)
    assert client.get("/v1/account", headers=auth()).json()["limits"]["sponsored_enabled"]
    res = first_run(client, issue_key=True)
    assert res.status_code == 200, res.text
    body = res.json()
    endpoint = body["endpoint"]
    assert body["state"] == "ready" and body["created"] is True
    assert body["sponsored_enabled"] is True
    assert endpoint["provider"] == "sponsored" and endpoint["model"] == MODEL
    assert body["gateway_url"] == f"{ORIGIN}/e/{endpoint['id']}/v1"
    assert body["key"]["key"].startswith("pg_ep_") and body["active_keys"] == 1

    again = first_run(client, issue_key=True).json()
    assert again["key"] is None and again["created"] is False
    assert again["endpoint"]["id"] == endpoint["id"]
    projects = client.get("/v1/projects", headers=auth()).json()
    endpoints = client.get(
        f"/v1/projects/{projects['default_project_id']}/endpoints", headers=auth()
    ).json()["endpoints"]
    assert [e["id"] for e in endpoints] == [endpoint["id"]]


def test_snippets_point_at_the_default_endpoint(make_client: Any) -> None:
    client = make_client(sponsored=True)
    endpoint = first_run(client).json()["endpoint"]
    res = client.get(f"/v1/connect/snippets?endpoint={endpoint['id']}", headers=auth())
    assert res.status_code == 200, res.text
    tools = {t["id"]: t for t in res.json()["tools"]}
    url = f"{ORIGIN}/e/{endpoint['id']}/v1"
    for tool in ("codex", "pi", "python", "curl"):
        assert url in tools[tool]["code"] and MODEL in tools[tool]["code"]
        assert "PII_GUARD_ENDPOINT_KEY" in tools[tool]["code"]


def test_sponsored_test_request_through_the_default_endpoint(
    make_client: Any, upstream: Upstream
) -> None:
    client = make_client(sponsored=True)
    key = first_run(client, issue_key=True).json()
    res = client.post(
        f"/e/{key['endpoint']['id']}/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Write to jane.placeholder@example.net"}]},
        headers={"authorization": f"Bearer {key['key']['key']}"},
    )
    assert res.status_code == 200, res.text
    url, authorization = upstream.calls[-1]
    assert url.startswith("https://api.meta.ai/v1/") and authorization == f"Bearer {SPONSORED_KEY}"
    assert "jane.placeholder@example.net" not in json.dumps(upstream.calls)


def test_sponsorship_off_needs_one_meta_key_then_never_uses_sponsored(
    make_client: Any, upstream: Upstream
) -> None:
    client = make_client(sponsored=False)
    pending = first_run(client, issue_key=True).json()
    assert pending["state"] == "needs_key" and pending["sponsored_enabled"] is False
    # The guard key comes with first sign-in, before the Meta key.
    guard_key = pending["key"]["key"]
    assert guard_key.startswith("pg_ep_")

    # A request through the needs-key endpoint is refused before any upstream call.
    session = auth()
    refused = client.post(
        f"/e/{pending['endpoint']['id']}/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Hello"}]},
        headers=session,
    )
    assert refused.status_code == 503 and refused.json()["error"]["code"] == "sponsored_unavailable"
    assert upstream.calls == []

    ready = first_run(client, issue_key=True, meta_api_key=OWN_KEY)
    assert ready.status_code == 200, ready.text
    body = ready.json()
    assert OWN_KEY not in ready.text
    assert body["state"] == "ready" and body["endpoint"]["id"] == pending["endpoint"]["id"]
    assert body["endpoint"]["provider"] == "meta"
    # The key shown at sign-in keeps working after the conversion; no second key is minted.
    assert body["key"] is None and body["active_keys"] == 1

    res = client.post(
        f"/e/{body['endpoint']['id']}/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Write to jane.placeholder@example.net"}]},
        headers={"authorization": f"Bearer {guard_key}"},
    )
    assert res.status_code == 200, res.text
    url, authorization = upstream.calls[-1]
    assert url.startswith("https://api.meta.ai/v1/") and authorization == f"Bearer {OWN_KEY}"
    assert SPONSORED_KEY not in json.dumps(upstream.calls)

    # A second key cannot replace it through first run.
    assert first_run(client, meta_api_key="synthetic-other-key").status_code == 422


def test_first_run_spends_no_daily_request(make_client: Any) -> None:
    client = make_client(sponsored=False)
    before = client.get("/v1/account", headers=auth()).json()["usage"]["requests_today"]
    for _ in range(3):
        assert first_run(client).status_code == 200
    after = client.get("/v1/account", headers=auth()).json()["usage"]["requests_today"]
    assert after == before


def test_first_run_requires_a_signed_in_google_owner(make_client: Any) -> None:
    client = make_client(sponsored=True)
    assert client.post("/v1/account/first-run", json={}).status_code == 401
    api_key = client.post("/v1/account/api-keys", json={"name": "synthetic"}, headers=auth())
    assert api_key.status_code == 201, api_key.text
    res = client.post(
        "/v1/account/first-run",
        json={"issue_key": True},
        headers={"authorization": f"Bearer {api_key.json()['key']}"},
    )
    assert res.status_code == 401
    # Cross-origin writes are refused like every other owner mutation.
    cross = client.post(
        "/v1/account/first-run",
        json={},
        headers={**auth(), "origin": "https://attacker.example"},
    )
    assert cross.status_code == 403


def test_first_run_is_owner_scoped_over_http(make_client: Any) -> None:
    client = make_client(sponsored=True)
    one = first_run(client, "synthetic-one", issue_key=True).json()
    two = first_run(client, "synthetic-two", issue_key=True).json()
    assert one["endpoint"]["id"] != two["endpoint"]["id"]
    foreign = client.get(
        f"/v1/connect/snippets?endpoint={one['endpoint']['id']}", headers=auth("synthetic-two")
    )
    assert foreign.status_code == 404
    stolen = client.post(
        f"/e/{one['endpoint']['id']}/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Hello"}]},
        headers={"authorization": f"Bearer {two['key']['key']}"},
    )
    assert stolen.status_code == 401


def test_first_run_rejects_unknown_fields(make_client: Any) -> None:
    client = make_client(sponsored=True)
    assert first_run(client, provider="custom").status_code == 422
    assert first_run(client, meta_api_key="").status_code == 422
