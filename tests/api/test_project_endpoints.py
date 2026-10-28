"""Synthetic vertical checks for durable scoped endpoint admission and isolation."""

from __future__ import annotations

import json
from pathlib import Path

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


@pytest.fixture
def endpoint_client(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        detectors=("rules",),
        ner_fallback="off",
        tenant_key="37" * 32,
        project_state_path=str(tmp_path / "state" / "projects.sqlite3"),
    )
    app = create_app(settings)
    sent = []

    def provider(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append((body, request.headers.get("authorization")))
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": body["messages"][0]["content"]},
                    }
                ],
            },
        )

    app.state.gateway_transport = httpx.MockTransport(provider)
    pipeline = DetectionPipeline([RuleDetector()])
    app.state.gateway_detectors = {
        Mode.FAST: ModeDetector(Mode.FAST, pipeline, "rules", PolicySet())
    }
    with TestClient(app) as client:
        project = client.get("/v1/projects").json()["projects"][0]
        policy = client.get(f"/v1/projects/{project['id']}/policies").json()["policies"][0]

        def endpoint(name="Synthetic endpoint", version=policy["policy_version_id"]):
            response = client.post(
                f"/v1/projects/{project['id']}/endpoints",
                json={
                    "name": name,
                    "provider": "openai",
                    "model": "synthetic-model",
                    "api_key": "synthetic-provider-secret",
                    "policy_version_id": version,
                },
            )
            assert response.status_code == 201, response.text
            resource = response.json()
            response = client.post(
                f"/v1/projects/{project['id']}/endpoints/{resource['id']}/keys",
                json={"name": "Synthetic client"},
            )
            assert response.status_code == 201, response.text
            return resource, response.json()

        yield client, app, project, policy, endpoint, sent


def _chat(client, endpoint, key, **body):
    return client.post(
        endpoint["base_path"] + "/chat/completions",
        headers={"Authorization": "Bearer " + key["key"]},
        json={
            "model": "synthetic-model",
            "messages": [{"role": "user", "content": "jane.placeholder@example.com"}],
            **body,
        },
    )


def test_endpoint_masks_restores_and_never_forwards_guard_key(endpoint_client):
    client, _, _, policy, endpoint, sent = endpoint_client
    resource, key = endpoint()
    result = _chat(client, resource, key)
    assert result.status_code == 200, result.text
    assert result.json()["choices"][0]["message"]["content"] == "jane.placeholder@example.com"
    assert "jane.placeholder@example.com" not in json.dumps(sent[0][0])
    assert sent[0][1] == "Bearer synthetic-provider-secret"
    assert result.headers["x-pii-guard-policy-version"] == policy["policy_version_id"]


@pytest.mark.parametrize(
    "path",
    [
        "/v1/projects",
        "/v1/unmask",
        "/v1/vault/sessions",
        "/v1/traffic",
        "/v1/chat/completions",
        "/s/synthetic/v1/unmask",
        "/s/synthetic/v1/chat/completions",
    ],
)
def test_endpoint_key_cannot_access_other_routes(endpoint_client, path):
    client, _, _, _, endpoint, sent = endpoint_client
    _, key = endpoint()
    result = client.post(path, headers={"Authorization": "Bearer " + key["key"]}, json={})
    assert result.status_code == 403
    assert not sent


def test_revocation_wrong_endpoint_and_model_refuse_before_upstream(endpoint_client):
    client, _, project, _, endpoint, sent = endpoint_client
    first, key = endpoint()
    second, _ = endpoint("Second")
    assert _chat(client, second, key).status_code == 403
    assert _chat(client, first, key, model="other-model").status_code == 403
    assert (
        client.delete(
            f"/v1/projects/{project['id']}/endpoints/{first['id']}/keys/{key['id']}"
        ).status_code
        == 204
    )
    assert _chat(client, first, key).status_code == 403
    assert not sent


def test_policy_version_requires_explicit_endpoint_reassignment(endpoint_client):
    client, _, project, policy, endpoint, sent = endpoint_client
    resource, key = endpoint()
    updated = client.put(
        f"/v1/projects/{project['id']}/policies/{policy['policy_id']}",
        json={"name": "Block mail", "entity_policies": {"EMAIL": "block"}},
    )
    assert updated.status_code == 201, updated.text
    assert _chat(client, resource, key).status_code == 200
    update = client.put(
        f"/v1/projects/{project['id']}/endpoints/{resource['id']}",
        json={
            "name": "Synthetic endpoint",
            "provider": "openai",
            "model": "synthetic-model",
            "policy_version_id": updated.json()["policy_version_id"],
        },
    )
    assert update.status_code == 200, update.text
    response = _chat(client, resource, key)
    assert response.status_code == 422, response.text
    assert len(sent) == 1


def test_catalog_only_lists_assigned_model_and_keys_shown_once(endpoint_client):
    client, _, project, _, endpoint, sent = endpoint_client
    resource, key = endpoint()
    listing = client.get(
        resource["base_path"] + "/models", headers={"Authorization": "Bearer " + key["key"]}
    )
    assert [item["id"] for item in listing.json()["data"]] == ["synthetic-model"]
    keys = client.get(f"/v1/projects/{project['id']}/endpoints/{resource['id']}/keys")
    assert key["key"] not in keys.text and "key" not in keys.json()["keys"][0]
    assert not sent


def test_endpoint_namespaces_prevent_restore_from_other_endpoint(endpoint_client):
    client, app, project, _, endpoint, _ = endpoint_client
    first, key = endpoint()
    second, _other = endpoint("Second")
    response = _chat(client, first, key)
    assert response.headers["x-pii-guard-session"]
    first_headers = {"X-PII-Guard-Project": project["id"], "X-PII-Guard-Endpoint": first["id"]}
    second_headers = {**first_headers, "X-PII-Guard-Endpoint": second["id"]}
    listing = client.get("/v1/vault/sessions", headers=first_headers)
    assert listing.status_code == 200, listing.text
    ref = listing.json()["sessions"][0]["ref"]
    assert client.get(f"/v1/vault/sessions/{ref}", headers=first_headers).status_code == 200
    assert client.get(f"/v1/vault/sessions/{ref}", headers=second_headers).status_code == 404
    assert app.state.projects._runtimes


def test_different_policies_use_private_resolvers_around_shared_detectors():
    from pii_guard.projects.runtime import PolicyAnalyzer
    from pii_guard.types import EntityType, Span

    class Overlap:
        name = "synthetic"

        def detect(self, text, language):
            return [
                Span(0, 16, EntityType.PERSON, text[:16], 0.9, self.name),
                Span(0, len(text), EntityType.ORGANIZATION, text, 0.95, self.name),
            ]

    class Analyzer:
        pipeline = DetectionPipeline([Overlap()])

        def analyze(self, text, language):
            return self.pipeline.detect(text, language)

    shared = Analyzer()
    original = shared.pipeline.keep_types
    mask_person = PolicyAnalyzer(shared, PolicySet())
    mask_company = PolicyAnalyzer(shared, PolicySet({"PERSON": "keep", "ORGANIZATION": "mask"}))
    text = "Synthetic Person Labs"
    assert mask_person.analyze(text, "en")[0].entity_type == EntityType.PERSON
    assert mask_company.analyze(text, "en")[0].entity_type == EntityType.ORGANIZATION
    assert shared.pipeline.keep_types == original
    assert mask_company.pipeline.detectors[0] is shared.pipeline.detectors[0]
    assert mask_person.analyze(text, "en")[0].entity_type == EntityType.PERSON


def test_account_session_budget_shared_across_namespaces():
    from pii_guard.hosted.runtime import HostedCapacityError, HostedVault, SessionBudget

    budget = SessionBudget(1)
    first = HostedVault(b"a" * 32, budget=budget)
    second = HostedVault(b"b" * 32, budget=budget)
    session = first.session()
    with pytest.raises(HostedCapacityError):
        second.session()
    first.drop(session.session_id)
    assert second.session()
    first.close()
    second.close()


def test_default_local_project_selection_preserves_legacy_sessions(endpoint_client):
    client, _, project, _, _, _ = endpoint_client
    masked = client.post("/v1/mask", json={"text": "jane.placeholder@example.com"})
    assert masked.status_code == 200, masked.text
    body = masked.json()
    restored = client.post(
        "/v1/unmask",
        headers={"X-PII-Guard-Project": project["id"]},
        json={"session_id": body["session_id"], "text": body["masked_text"]},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["text"] == "jane.placeholder@example.com"


def test_owner_runtime_capacity_cannot_consume_global_namespace_limit(tmp_path):
    from pii_guard.hosted.identity import Principal
    from pii_guard.hosted.runtime import HostedCapacityError, HostedService

    service = HostedService(
        Settings(
            _env_file=None,
            hosted=True,
            hosted_trust_easy_auth=True,
            hosted_single_process=True,
            hosted_public_origin="https://guard.example",
            tenant_key="37" * 32,
            hosted_max_sessions=1,
            hosted_max_principals=3,
            detectors=("rules",),
            project_state_path=str(tmp_path / "runtime-state" / "state.sqlite3"),
        )
    )
    first = Principal("u_synthetic_first", True, "google")
    runtime = service.acquire(first, namespace="project-a:endpoint-a")
    service.release(runtime)
    with pytest.raises(HostedCapacityError):
        service.acquire(first, namespace="project-b:endpoint-b")
    other = service.acquire(Principal("u_synthetic_other", True, "google"), namespace="project-c")
    service.release(other)


def test_endpoint_and_legacy_gateway_share_configured_worker_capacity(endpoint_client):
    from pii_guard.gateway.config import GatewayConfig

    client, app, _, _, endpoint, _ = endpoint_client
    app.state.gateway_config = GatewayConfig(concurrency=2)
    resource, key = endpoint()
    assert _chat(client, resource, key).status_code == 200
    shared = app.state.projects.workers
    assert {pool.size for pool in shared.values()} == {2}
    # The generic route builds its global gateway without sending anything upstream.
    assert client.post("/v1/chat/completions", json={}).status_code in {400, 503}
    assert app.state.gateway._detect_workers is shared
    assert app.state.gateway.config.concurrency == 2
