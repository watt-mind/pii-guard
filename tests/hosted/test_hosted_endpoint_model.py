"""Hosted endpoints with an optional model (LAB-1451).

Sponsored endpoints keep a pinned, allow-listed model; own-key (BYOK) endpoints may pass the
client's model through. Identities, keys, hosts and models are synthetic (ADR 0005).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings

ORIGIN = "https://guard.example"
PROVIDER_KEY = "synthetic-own-provider-key"
EMAIL = "jane.placeholder@example.com"


def auth(subject: str = "synthetic-one") -> dict[str, str]:
    encoded = base64.b64encode(
        json.dumps({"auth_typ": "google", "claims": [{"typ": "sub", "val": subject}]}).encode()
    ).decode()
    return {"x-ms-client-principal": encoded, "origin": ORIGIN}


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, list[httpx.Request]]]:
    seen: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(
                200, json={"data": [{"id": "synthetic-own-a", "pricing": "dropped"}]}
            )
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
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

    async def public(url: str) -> str:
        return url

    monkeypatch.setattr("pii_guard.api.routes.projects.validate_destination", public)
    monkeypatch.setattr(
        "pii_guard.hosted.egress.SecureTransport", lambda: httpx.MockTransport(provider)
    )
    monkeypatch.setattr(
        "pii_guard.hosted.egress.secure_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(provider), **kwargs),
    )
    settings = Settings(
        _env_file=None,
        hosted=True,
        hosted_public_origin=ORIGIN,
        hosted_trust_easy_auth=True,
        hosted_single_process=True,
        tenant_key=bytes(range(32)).hex(),
        allowed_hosts=("guard.example",),
        detectors=("rules",),
        ner_fallback="off",
        upstream_api_key="synthetic-operator-upstream-key",
    )
    with TestClient(create_app(settings), base_url=ORIGIN) as client:
        yield client, seen


def _project(client: TestClient) -> tuple[str, str]:
    projects = client.get("/v1/projects", headers=auth())
    assert projects.status_code == 200, projects.text
    project = projects.json()["projects"][0]
    return project["id"], project["default_policy_version_id"]


def _create(client: TestClient, **fields: Any) -> httpx.Response:
    project, policy = _project(client)
    return client.post(
        f"/v1/projects/{project}/endpoints",
        json={"name": "Synthetic endpoint", "policy_version_id": policy, **fields},
        headers=auth(),
    )


def _key(client: TestClient, endpoint: dict[str, Any]) -> str:
    issued = client.post(
        f"/v1/projects/{endpoint['project_id']}/endpoints/{endpoint['id']}/keys",
        json={"name": "Synthetic client"},
        headers=auth(),
    )
    assert issued.status_code == 201, issued.text
    return str(issued.json()["key"])


def _chat(client: TestClient, endpoint: dict[str, Any], key: str, **body: Any) -> httpx.Response:
    return client.post(
        endpoint["base_path"] + "/chat/completions",
        json={"messages": [{"role": "user", "content": EMAIL}], **body},
        headers={"authorization": "Bearer " + key},
    )


@pytest.mark.parametrize("model", [None, "", "synthetic-not-allow-listed"])
def test_sponsored_endpoint_requires_an_allow_listed_model(hosted, model):
    client, _ = hosted
    fields: dict[str, Any] = {"provider": "sponsored"}
    if model is not None:
        fields["model"] = model
    result = _create(client, **fields)
    assert result.status_code == 422, result.text
    assert result.json()["error"]["code"] == "invalid_project_config"
    allowed = _create(client, provider="sponsored", model="muse-spark-1.3")
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["model"] == "muse-spark-1.3"


def test_sponsored_endpoint_stays_pinned_at_request_time(hosted):
    client, seen = hosted
    created = _create(client, provider="sponsored", model="muse-spark-1.3")
    endpoint = created.json()
    key = _key(client, endpoint)
    refused = _chat(client, endpoint, key, model="synthetic-not-allow-listed")
    assert refused.status_code == 403, refused.text
    assert not [r for r in seen if r.method == "POST"]
    listing = client.get(
        endpoint["base_path"] + "/models", headers={"authorization": "Bearer " + key}
    )
    assert [m["id"] for m in listing.json()["data"]] == ["muse-spark-1.3"]
    assert not seen


@pytest.mark.parametrize("provider", ["openai", "openrouter", "fireworks", "meta"])
def test_byok_endpoint_without_model_passes_the_client_model_through(hosted, provider):
    client, seen = hosted
    created = _create(client, provider=provider, api_key=PROVIDER_KEY)
    assert created.status_code == 201, created.text
    endpoint = created.json()
    assert endpoint["model"] is None
    key = _key(client, endpoint)
    result = _chat(client, endpoint, key, model="synthetic-client-model")
    assert result.status_code == 200, result.text
    sent = [r for r in seen if r.method == "POST"][-1]
    assert json.loads(sent.content)["model"] == "synthetic-client-model"
    assert EMAIL not in sent.content.decode()
    assert sent.headers["authorization"] == "Bearer " + PROVIDER_KEY


def test_byok_pass_through_without_a_model_is_400(hosted):
    client, seen = hosted
    endpoint = _create(client, provider="openai", api_key=PROVIDER_KEY).json()
    key = _key(client, endpoint)
    result = _chat(client, endpoint, key)
    assert result.status_code == 400, result.text
    assert result.json()["error"]["code"] == "invalid_request"
    assert not seen


def test_byok_pass_through_models_proxy_the_provider_catalog(hosted):
    client, seen = hosted
    endpoint = _create(client, provider="openrouter", api_key=PROVIDER_KEY).json()
    key = _key(client, endpoint)
    listing = client.get(
        endpoint["base_path"] + "/models", headers={"authorization": "Bearer " + key}
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["data"] == [
        {"id": "synthetic-own-a", "object": "model", "created": 0, "owned_by": ""}
    ]
    assert seen[-1].url.path.endswith("/models")
    assert seen[-1].headers["authorization"] == "Bearer " + PROVIDER_KEY
    assert "dropped" not in listing.text and PROVIDER_KEY not in listing.text
