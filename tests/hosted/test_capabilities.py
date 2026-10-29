"""The shared console's hosted reads (LAB-1431, ADR 0013): ``/v1/status`` and Connect.

One route per API: the hosted owner gets a projection of ``/v1/status`` and owner-scoped
Connect blocks. All identities, keys and hosts are synthetic (ADR 0005).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings

ORIGIN = "https://guard.example"
# What the hosted router forwards as Host: an internal name, never the public origin.
INTERNAL = "https://synthetic-app.internal.example"
UPSTREAM = "https://upstream.internal.example:8443/operator/v1"
UPSTREAM_KEY = "synthetic-operator-upstream-key"


def auth(subject: str = "synthetic-one") -> dict[str, str]:
    encoded = base64.b64encode(
        json.dumps({"auth_typ": "google", "claims": [{"typ": "sub", "val": subject}]}).encode()
    ).decode()
    return {"x-ms-client-principal": encoded, "origin": ORIGIN}


def settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        **{
            "hosted": True,
            "hosted_public_origin": ORIGIN,
            "hosted_trust_easy_auth": True,
            "hosted_single_process": True,
            "tenant_key": bytes(range(32)).hex(),
            "allowed_hosts": ("guard.example", "synthetic-app.internal.example"),
            "detectors": ("rules",),
            "ner_fallback": "off",
            "upstream_base_url": UPSTREAM,
            "upstream_api_key": UPSTREAM_KEY,
            **overrides,
        },
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(settings()), base_url=INTERNAL) as test_client:
        yield test_client


def _endpoint(client: TestClient, subject: str = "synthetic-one") -> str:
    """An endpoint of ``subject``'s default project, written straight to the store."""
    owner = client.get("/v1/account", headers=auth(subject)).json()["principal"]["id"]
    store = client.app.state.projects.store
    project = store.default_project(owner)["id"]
    policy = store.list_policies(owner, project)[0]["policy_version_id"]
    saved = store.save_endpoint(
        owner,
        project,
        {
            "name": "Synthetic hosted endpoint",
            "policy_version_id": policy,
            "provider": "sponsored",
            "base_url": "https://api.meta.ai/v1",
            "model": "muse-spark-1.3",
        },
    )
    return str(saved["id"])


HOSTED_CAPABILITIES = {
    "text": True,
    "chat": True,
    # Signatures are masked on-device (LAB-1444), so the default policies are servable.
    "images": True,
    "logs": True,
    "vault": True,
    "server_policy": False,
    "projects": True,
    "connect": True,
    "evaluation": True,
    "accounts": True,
}


def test_hosted_status_is_the_owner_projection(client: TestClient) -> None:
    res = client.get("/v1/status", headers=auth())
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {
        "version",
        "gateway",
        "ner",
        "policies",
        "default_language",
        "traffic_log",
        "vault_inspect",
        "capabilities",
    }
    assert body["capabilities"] == HOSTED_CAPABILITIES
    # Fast mode only: audit detection is not offered hosted.
    assert body["gateway"]["default_mode"] == "fast"
    assert set(body["gateway"]["modes"]) == {"fast"}
    assert set(body["ner"]) == {"available", "state", "error"}
    assert body["policies"]["PERSON"] == "mask"
    # The owner's own views, not the server's (its traffic log is off here).
    assert body["traffic_log"] == "masked" and body["vault_inspect"] == "masked"


def test_hosted_status_leaks_no_operator_internals(client: TestClient) -> None:
    res = client.get("/v1/status", headers=auth())
    assert res.status_code == 200, res.text
    body = res.json()
    for field in ("upstream", "images", "auth", "rest", "metrics"):
        assert field not in body, field
    for secret in (UPSTREAM_KEY, "upstream.internal.example", "/operator", "segmenter", "sam"):
        assert secret not in res.text, secret
    assert "token_required" not in res.text and "ocr_required" not in res.text


def test_hosted_gateway_url_is_the_public_origin_behind_a_proxy_host(client: TestClient) -> None:
    # The client's base URL is the internal host the router forwards (Host header).
    proxied = client.get("/v1/status", headers=auth()).json()
    assert proxied["gateway"]["url"] == f"{ORIGIN}/v1"
    assert "internal.example" not in json.dumps(proxied)


def test_owned_endpoint_snippets_use_the_public_endpoint_url(client: TestClient) -> None:
    endpoint = _endpoint(client)
    res = client.get("/v1/connect/snippets", params={"endpoint": endpoint}, headers=auth())
    assert res.status_code == 200, res.text
    body = res.json()
    url = f"{ORIGIN}/e/{endpoint}/v1"
    assert body["gateway_url"] == url
    assert body["auth"]["token_env"] == "PII_GUARD_ENDPOINT_KEY"  # noqa: S105 - a name
    assert body["model"] == "muse-spark-1.3"
    assert body["upstream"]["origin"] is None and body["presets"] == []
    supported = [t for t in body["tools"] if t["supported"]]
    assert supported
    for tool in supported:
        assert url in tool["code"], tool["id"]
    assert "$PII_GUARD_ENDPOINT_KEY" in next(t for t in supported if t["id"] == "curl")["code"]
    for secret in (UPSTREAM_KEY, "upstream.internal.example", "api.meta.ai", "/s/"):
        assert secret not in res.text, secret


def test_another_owners_or_an_unknown_endpoint_is_404(client: TestClient) -> None:
    endpoint = _endpoint(client, "synthetic-one")
    foreign = client.get(
        "/v1/connect/snippets", params={"endpoint": endpoint}, headers=auth("synthetic-two")
    )
    unknown = client.get(
        "/v1/connect/snippets", params={"endpoint": "synthetic-unknown"}, headers=auth()
    )
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()
    assert "Synthetic hosted endpoint" not in foreign.text


def test_hosted_connect_requires_an_endpoint(client: TestClient) -> None:
    res = client.get("/v1/connect/snippets", headers=auth())
    assert res.status_code == 422
    assert UPSTREAM_KEY not in res.text and "upstream.internal.example" not in res.text


@pytest.mark.parametrize("path", ["/v1/status", "/v1/connect/snippets"])
def test_anonymous_callers_get_401(client: TestClient, path: str) -> None:
    res = client.get(path, headers={"origin": ORIGIN})
    assert res.status_code == 401
    assert UPSTREAM_KEY not in res.text


@pytest.mark.parametrize("path", ["/v1/status", "/v1/connect/snippets"])
def test_api_keys_are_refused(client: TestClient, path: str) -> None:
    issued = client.post("/v1/account/api-keys", json={"name": "Synthetic key"}, headers=auth())
    assert issued.status_code == 201, issued.text
    key = issued.json()["key"]
    for headers in ({"authorization": f"Bearer {key}"}, {"x-pii-guard-token": key}):
        res = client.get(path, headers=headers)
        assert res.status_code == 401, headers
        assert key not in res.text
    # An endpoint key is refused off its endpoint path, before any lookup.
    endpoint_key = client.get(path, headers={"authorization": "Bearer pg_ep_synthetic"})
    assert endpoint_key.status_code == 401
