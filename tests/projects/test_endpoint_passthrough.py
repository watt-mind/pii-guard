"""Local endpoint gateway with an optional model (LAB-1451): pinned vs pass-through.

All keys, models and texts are synthetic; the provider is an ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.detect.rules import RuleDetector
from pii_guard.gateway.config import Mode
from pii_guard.gateway.detection import ModeDetector
from pii_guard.policy import PolicySet

PROVIDER_KEY = "synthetic-provider-secret"
EMAIL = "jane.placeholder@example.com"


@pytest.fixture
def gateway(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        detectors=("rules",),
        ner_fallback="off",
        tenant_key="38" * 32,
        project_state_path=str(tmp_path / "state" / "projects.sqlite3"),
    )
    app = create_app(settings)
    sent: list[httpx.Request] = []
    catalog: dict[str, Any] = {"status": 200}

    def provider(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method == "GET":
            if catalog["status"] != 200:
                return httpx.Response(catalog["status"], json={"error": "synthetic-leak"})
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "synthetic-a", "owned_by": "synthetic", "price": 1},
                        {"id": "synthetic-b"},
                        {"no_id": True},
                    ]
                },
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

    app.state.gateway_transport = httpx.MockTransport(provider)
    app.state.gateway_detectors = {
        Mode.FAST: ModeDetector(
            Mode.FAST, DetectionPipeline([RuleDetector()]), "rules", PolicySet()
        )
    }
    with TestClient(app) as client:
        project = client.get("/v1/projects").json()["projects"][0]
        policy = client.get(f"/v1/projects/{project['id']}/policies").json()["policies"][0]

        def endpoint(**fields: Any) -> tuple[dict[str, Any], str]:
            response = client.post(
                f"/v1/projects/{project['id']}/endpoints",
                json={
                    "name": "Synthetic endpoint",
                    "provider": "openai",
                    "api_key": PROVIDER_KEY,
                    "policy_version_id": policy["policy_version_id"],
                    **fields,
                },
            )
            assert response.status_code == 201, response.text
            resource = response.json()
            issued = client.post(
                f"/v1/projects/{project['id']}/endpoints/{resource['id']}/keys",
                json={"name": "Synthetic client"},
            )
            assert issued.status_code == 201, issued.text
            return resource, issued.json()["key"]

        yield client, project, endpoint, sent, catalog


def _chat(client: TestClient, resource: dict[str, Any], key: str, **body: Any) -> httpx.Response:
    return client.post(
        resource["base_path"] + "/chat/completions",
        headers={"Authorization": "Bearer " + key},
        json={"messages": [{"role": "user", "content": EMAIL}], **body},
    )


@pytest.mark.parametrize("fields", [{}, {"model": ""}, {"model": None}])
def test_endpoint_without_model_is_pass_through_in_the_api(gateway, fields):
    client, project, endpoint, _, _ = gateway
    resource, _ = endpoint(**fields)
    assert resource["model"] is None
    listed = client.get(f"/v1/projects/{project['id']}/endpoints").json()["endpoints"]
    assert [item["model"] for item in listed] == [None]


@pytest.mark.parametrize("model", ["synthetic-codex-model", "synthetic/muse-code:latest"])
def test_pass_through_forwards_the_client_model_unchanged(gateway, model):
    client, _, endpoint, sent, _ = gateway
    resource, key = endpoint()
    result = _chat(client, resource, key, model=model)
    assert result.status_code == 200, result.text
    assert result.json()["choices"][0]["message"]["content"] == EMAIL
    forwarded = json.loads(sent[-1].content)
    assert forwarded["model"] == model
    assert EMAIL not in json.dumps(forwarded)
    assert sent[-1].headers["authorization"] == "Bearer " + PROVIDER_KEY


@pytest.mark.parametrize(
    "body", [{}, {"model": ""}, {"model": "  "}, {"model": 7}, {"model": None}]
)
def test_pass_through_without_a_model_is_400_before_the_provider(gateway, body):
    client, _, endpoint, sent, _ = gateway
    resource, key = endpoint()
    result = _chat(client, resource, key, **body)
    assert result.status_code == 400, result.text
    error = result.json()["error"]
    assert error["code"] == "invalid_request"
    assert "model" in error["message"]
    assert not sent


def test_pinned_endpoint_still_injects_and_refuses_other_models(gateway):
    client, _, endpoint, sent, _ = gateway
    resource, key = endpoint(model="synthetic-pinned")
    assert resource["model"] == "synthetic-pinned"
    assert _chat(client, resource, key).status_code == 200
    assert json.loads(sent[-1].content)["model"] == "synthetic-pinned"
    assert _chat(client, resource, key, model="synthetic-pinned").status_code == 200
    count = len(sent)
    assert _chat(client, resource, key, model="synthetic-other").status_code == 403
    assert len(sent) == count


def test_models_lists_the_provider_catalog_for_pass_through(gateway):
    client, _, endpoint, sent, _ = gateway
    resource, key = endpoint()
    listing = client.get(
        resource["base_path"] + "/models", headers={"Authorization": "Bearer " + key}
    )
    assert listing.status_code == 200, listing.text
    assert listing.json() == {
        "object": "list",
        "data": [
            {"id": "synthetic-a", "object": "model", "created": 0, "owned_by": "synthetic"},
            {"id": "synthetic-b", "object": "model", "created": 0, "owned_by": ""},
        ],
    }
    assert str(sent[-1].url) == "https://api.openai.com/v1/models"
    assert sent[-1].headers["authorization"] == "Bearer " + PROVIDER_KEY
    assert key not in listing.text and PROVIDER_KEY not in listing.text


def test_models_lists_only_the_pinned_model_without_asking_the_provider(gateway):
    client, _, endpoint, sent, _ = gateway
    resource, key = endpoint(model="synthetic-pinned")
    listing = client.get(
        resource["base_path"] + "/models", headers={"Authorization": "Bearer " + key}
    )
    assert [item["id"] for item in listing.json()["data"]] == ["synthetic-pinned"]
    assert not sent


def test_provider_catalog_failure_is_generic(gateway):
    client, _, endpoint, _, catalog = gateway
    resource, key = endpoint()
    catalog["status"] = 401
    listing = client.get(
        resource["base_path"] + "/models", headers={"Authorization": "Bearer " + key}
    )
    assert listing.status_code == 502
    assert "synthetic-leak" not in listing.text and PROVIDER_KEY not in listing.text


def test_connect_snippets_show_a_placeholder_for_pass_through(gateway):
    client, _, endpoint, _, _ = gateway
    resource, _ = endpoint()
    body = client.get("/v1/connect/snippets", params={"endpoint": resource["id"]}).json()
    assert body["model"] is None and body["endpoint"]["model"] is None
    assert body["models"] == []
    curl = next(t for t in body["tools"] if t["id"] == "curl")
    assert "<model-id>" in curl["code"]
    pinned, _ = endpoint(model="synthetic-pinned")
    body = client.get("/v1/connect/snippets", params={"endpoint": pinned["id"]}).json()
    assert body["model"] == "synthetic-pinned"
    assert "synthetic-pinned" in next(t for t in body["tools"] if t["id"] == "curl")["code"]


def _catalog(client: TestClient, project: dict[str, Any], **body: Any) -> httpx.Response:
    return client.post(f"/v1/projects/{project['id']}/endpoints/models", json=body)


def test_form_catalog_asks_the_provider_with_a_typed_key_it_never_stores(gateway):
    client, project, _, sent, _ = gateway
    result = _catalog(client, project, provider="openai", api_key="synthetic-typed-key")
    assert result.status_code == 200, result.text
    assert result.json() == {"models": ["synthetic-a", "synthetic-b"]}
    assert str(sent[-1].url) == "https://api.openai.com/v1/models"
    assert sent[-1].headers["authorization"] == "Bearer synthetic-typed-key"
    assert "synthetic-typed-key" not in result.text
    assert client.get(f"/v1/projects/{project['id']}/endpoints").json()["endpoints"] == []


def test_form_catalog_reuses_an_endpoint_key_only_for_its_own_provider(gateway):
    client, project, endpoint, sent, _ = gateway
    resource, _ = endpoint(model="synthetic-pinned")
    result = _catalog(client, project, provider="openai", endpoint_id=resource["id"])
    assert result.status_code == 200, result.text
    assert sent[-1].headers["authorization"] == "Bearer " + PROVIDER_KEY
    count = len(sent)
    other = _catalog(client, project, provider="openrouter", endpoint_id=resource["id"])
    assert other.status_code == 422
    assert _catalog(client, project, provider="openai").status_code == 422
    assert _catalog(client, project, provider="sponsored").status_code == 422
    assert len(sent) == count


def test_form_catalog_failure_is_generic(gateway):
    client, project, _, _, catalog = gateway
    catalog["status"] = 403
    result = _catalog(client, project, provider="openai", api_key="synthetic-typed-key")
    assert result.status_code == 502
    assert "synthetic-leak" not in result.text and "synthetic-typed-key" not in result.text


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "upstream_credential_rejected"),
        (403, "upstream_credential_rejected"),
        (404, "upstream_unavailable"),
        (500, "upstream_unavailable"),
    ],
)
def test_form_catalog_names_a_refused_key_without_provider_detail(gateway, status, code):
    client, project, endpoint, _, catalog = gateway
    catalog["status"] = status
    result = _catalog(client, project, provider="openai", api_key="synthetic-typed-key")
    assert result.status_code == 502
    assert result.json()["error"]["code"] == code
    assert "synthetic-leak" not in result.text and "synthetic-typed-key" not in result.text
    resource, key = endpoint()
    listing = client.get(
        resource["base_path"] + "/models", headers={"Authorization": "Bearer " + key}
    )
    assert listing.status_code == 502 and listing.json()["error"]["code"] == code
