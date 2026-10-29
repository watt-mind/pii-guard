"""Endpoint-key admission with ``PII_GUARD_API_TOKEN`` set (LAB-1562).

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

API_TOKEN = "test-api-token-not-a-secret"  # noqa: S105 - fictional
PROVIDER_KEY = "synthetic-provider-secret"
EMAIL = "jane.placeholder@example.com"
OWNER = {"X-PII-Guard-Token": API_TOKEN}


@pytest.fixture
def gateway(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        detectors=("rules",),
        ner_fallback="off",
        tenant_key="38" * 32,
        api_token=API_TOKEN,
        project_state_path=str(tmp_path / "state" / "projects.sqlite3"),
    )
    app = create_app(settings)
    sent: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        sent.append(request)
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
                        "message": {
                            "role": "assistant",
                            "content": body["messages"][-1]["content"],
                        },
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
        project = client.get("/v1/projects", headers=OWNER).json()["projects"][0]
        policy = client.get(f"/v1/projects/{project['id']}/policies", headers=OWNER).json()[
            "policies"
        ][0]
        response = client.post(
            f"/v1/projects/{project['id']}/endpoints",
            headers=OWNER,
            json={
                "name": "Synthetic endpoint",
                "provider": "openai",
                "model": "synthetic-pinned",
                "api_key": PROVIDER_KEY,
                "policy_version_id": policy["policy_version_id"],
            },
        )
        assert response.status_code == 201, response.text
        resource = response.json()
        issued = client.post(
            f"/v1/projects/{project['id']}/endpoints/{resource['id']}/keys",
            headers=OWNER,
            json={"name": "Synthetic client"},
        )
        assert issued.status_code == 201, issued.text
        yield client, resource, issued.json()["key"], sent


def _chat(client: TestClient, resource: dict[str, Any], headers: dict[str, str]):
    return client.post(
        resource["base_path"] + "/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": EMAIL}]},
    )


def test_valid_endpoint_key_still_works_with_api_token_set(gateway):
    client, resource, key, sent = gateway
    result = _chat(client, resource, {"Authorization": "Bearer " + key})
    assert result.status_code == 200, result.text
    assert len(sent) == 1
    assert sent[0].headers["authorization"] == "Bearer " + PROVIDER_KEY
    assert key not in str(dict(sent[0].headers))


@pytest.mark.parametrize(
    "credential",
    [
        "pg_ep_synthetic-fake",
        "PG_EP_synthetic-fake",
        "Pg_Ep_synthetic-fake",
    ],
)
def test_fake_endpoint_key_is_403_and_never_reaches_the_provider(gateway, credential):
    client, resource, _, sent = gateway
    result = _chat(client, resource, {"Authorization": "Bearer " + credential})
    assert result.status_code == 403, result.text
    assert result.json()["error"]["code"] == "project_access_denied"
    assert not sent
    assert credential not in result.text


def test_cased_prefix_of_the_real_key_is_403(gateway):
    client, resource, key, sent = gateway
    cased = "PG_EP_" + key[len("pg_ep_") :]
    result = _chat(client, resource, {"Authorization": "Bearer " + cased})
    assert result.status_code == 403, result.text
    assert not sent


@pytest.mark.parametrize(
    "headers",
    [
        {"X-PII-Guard-Token": API_TOKEN},
        {"Authorization": "Bearer " + API_TOKEN},
    ],
)
def test_api_token_alone_does_not_load_an_endpoint_snapshot(gateway, headers):
    # With an API token configured, a routed /e/ call must resolve its endpoint
    # snapshot from an endpoint key; the token alone is not endpoint admission.
    client, resource, _, sent = gateway
    result = _chat(client, resource, headers)
    assert result.status_code == 403, result.text
    assert not sent
