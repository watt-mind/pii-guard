"""Management contract tests with synthetic metadata and no detector/provider work."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from pii_guard.api.errors import install_error_handlers
from pii_guard.api.routes.projects import router
from pii_guard.config import Settings
from pii_guard.policy import PolicySet
from pii_guard.projects.store import ProjectStore


@pytest.fixture
def management(tmp_path):
    store = ProjectStore(
        str(tmp_path / "private" / "projects.sqlite3"), b"s" * 32, PolicySet(), "standard"
    )
    app = FastAPI()
    app.state.settings = Settings()
    app.state.projects = SimpleNamespace(store=store)

    @app.middleware("http")
    async def authorized_owner(request: Request, call_next):
        # This harness supplies the result of authentication; production middleware owns it.
        request.state.project_owner_id = request.headers.get("test-owner", "synthetic-owner")
        method = request.headers.get("test-auth", "google")
        request.state.hosted_principal = SimpleNamespace(
            id=request.state.project_owner_id,
            authenticated=method != "guest",
            auth_method=method,
        )
        return await call_next(request)

    install_error_handlers(app)
    app.include_router(router)
    with TestClient(app) as client:
        yield client, app, store
    store.close()


def default_project(client):
    response = client.get("/v1/projects")
    assert response.status_code == 200
    return response.json()["projects"][0]


def policy(client, project_id, **values):
    response = client.post(
        f"/v1/projects/{project_id}/policies", json={"name": "Synthetic policy", **values}
    )
    assert response.status_code == 201
    return response.json()


def endpoint(client, project_id, version_id, **values):
    response = client.post(
        f"/v1/projects/{project_id}/endpoints",
        json={
            "name": "Synthetic endpoint",
            "provider": "custom",
            "base_url": "http://127.0.0.1:8081/v1",
            "model": "synthetic-model",
            "api_key": "synthetic-provider-credential",
            "policy_version_id": version_id,
            **values,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def test_default_project_is_stable_and_new_projects_have_distinct_ownership(management):
    client, _, _ = management
    first = default_project(client)
    assert default_project(client) == first
    response = client.post("/v1/projects", json={"name": "Second synthetic project"})
    assert response.status_code == 201
    assert response.json()["id"] != first["id"]
    assert (
        client.get(f"/v1/projects/{first['id']}", headers={"test-owner": "other"}).status_code
        == 404
    )


def test_policy_revision_keeps_endpoint_pinned_and_original_version_unchanged(management):
    client, _, store = management
    project = default_project(client)
    prefix = f"/v1/projects/{project['id']}"
    first = policy(client, project["id"], entity_policies={"EMAIL": "block"})
    bound = endpoint(client, project["id"], first["policy_version_id"])
    revised = client.put(
        f"{prefix}/policies/{first['policy_id']}",
        json={"name": "Revised policy", "entity_policies": {"EMAIL": "keep"}},
    )
    assert revised.status_code == 201
    assert revised.json()["version"] == first["version"] + 1
    original = client.get(f"{prefix}/policies/versions/{first['policy_version_id']}")
    assert original.json()["entity_policies"]["EMAIL"] == "block"
    snapshot = store.endpoint_snapshot("synthetic-owner", project["id"], bound["id"])
    assert snapshot.policy_version_id == first["policy_version_id"]


def test_endpoint_credential_is_write_only_and_omission_preserves_it(management):
    client, _, store = management
    project = default_project(client)
    created = endpoint(client, project["id"], project["default_policy_version_id"])
    prefix = f"/v1/projects/{project['id']}/endpoints"
    assert "synthetic-provider-credential" not in client.get(prefix).text
    assert "api_key" not in created
    updated = client.put(
        f"{prefix}/{created['id']}",
        json={
            "name": "Renamed endpoint",
            "provider": "custom",
            "base_url": created["base_url"],
            "model": created["model"],
            "policy_version_id": created["policy_version_id"],
        },
    )
    assert updated.status_code == 200
    snapshot = store.endpoint_snapshot("synthetic-owner", project["id"], created["id"])
    assert snapshot.api_key.get_secret_value() == "synthetic-provider-credential"


def test_endpoint_keys_reveal_once_and_revoke(management):
    client, _, store = management
    project = default_project(client)
    created = endpoint(client, project["id"], project["default_policy_version_id"])
    prefix = f"/v1/projects/{project['id']}/endpoints/{created['id']}/keys"
    issued = client.post(prefix, json={"name": "Synthetic integration"})
    assert issued.status_code == 201
    key = issued.json()["key"]
    assert store.resolve_key(key, created["id"]) is not None
    assert key not in client.get(prefix).text
    assert client.delete(f"{prefix}/{issued.json()['id']}").status_code == 204
    assert store.resolve_key(key, created["id"]) is None


@pytest.mark.parametrize("method", ["api_key", "endpoint_key", "guest"])
def test_hosted_management_requires_google_owner(management, method):
    client, app, _ = management
    app.state.settings = Settings(hosted=True)
    response = client.get("/v1/projects", headers={"test-auth": method})
    assert response.status_code == 403


def test_hosted_validation_is_strict_and_preflight_has_no_credentials(management, monkeypatch):
    client, app, _ = management
    app.state.settings = Settings(hosted=True)
    checked = []

    async def validate_destination(url):
        checked.append(url)
        return url

    monkeypatch.setattr("pii_guard.api.routes.projects.validate_destination", validate_destination)
    project = default_project(client)
    prefix = f"/v1/projects/{project['id']}"
    assert (
        client.post(f"{prefix}/policies", json={"name": "Audit", "mode": "audit"}).status_code
        == 422
    )
    valid = endpoint(
        client,
        project["id"],
        project["default_policy_version_id"],
        provider="openai",
        base_url="https://api.openai.com/v1",
    )
    assert valid["provider"] == "openai"
    assert checked == ["https://api.openai.com/v1"]
    assert (
        client.post(
            f"{prefix}/policies", json={"name": "Visual", "entity_policies": {"FACE": "keep"}}
        ).status_code
        == 422
    )
    secret = "synthetic-credential-must-not-echo"  # noqa: S105 - fictional test value
    invalid = client.post(
        f"{prefix}/endpoints", json={"name": "Extra", "api_key": secret, "unexpected": secret}
    )
    assert invalid.status_code == 422
    assert secret not in invalid.text
    for body in (
        {"name": "Unknown field", secret: secret},
        {"name": "Unknown entity", "entity_policies": {secret: secret}},
        {"name": "Unknown action", "entity_policies": {"EMAIL": secret}},
    ):
        invalid = client.post(f"{prefix}/policies", json=body)
        assert invalid.status_code == 422
        assert secret not in invalid.text


def test_cross_project_policy_and_url_credentials_are_rejected(management):
    client, _, _ = management
    first = default_project(client)
    second = client.post("/v1/projects", json={"name": "Another project"}).json()
    body = {
        "name": "Wrong project",
        "provider": "custom",
        "base_url": "http://127.0.0.1:8081/v1",
        "model": "synthetic-model",
        "api_key": "synthetic-provider-credential",
        "policy_version_id": first["default_policy_version_id"],
    }
    assert client.post(f"/v1/projects/{second['id']}/endpoints", json=body).status_code == 422
    body["policy_version_id"] = second["default_policy_version_id"]
    body["base_url"] = "https://synthetic-user:synthetic-secret@example.com/v1"
    response = client.post(f"/v1/projects/{second['id']}/endpoints", json=body)
    assert response.status_code == 422
    assert "synthetic-secret" not in response.text
