"""CLI login: one-time code handoff and telemetry-only keys, self-hosted (LAB-1708).

Keys, tokens and host names are synthetic (ADR 0005).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.observability import ObservabilitySettings, TrafficLevel
from pii_guard.policy import PolicySet
from pii_guard.projects import store as store_module
from pii_guard.projects.cli_auth import (
    CLI_ENDPOINT_NAME,
    InvalidCliCodeError,
    create_cli_code,
    exchange_cli_code,
)
from pii_guard.projects.store import (
    CLI_CODE_TTL_SECONDS,
    CLI_CODES_PER_OWNER,
    InvalidProjectConfigError,
    ProjectStore,
)

API_TOKEN = "test-api-token-not-a-secret"  # noqa: S105 - fictional
OWNER = {"X-PII-Guard-Token": API_TOKEN}
MASTER = bytes(range(32))
EVENT = {"events": [{"level": "masked"}]}


def _app(tmp_path: Path, **overrides: Any) -> Any:
    settings = Settings(
        _env_file=None,
        detectors=("rules",),
        ner_fallback="off",
        tenant_key="38" * 32,
        project_state_path=str(tmp_path / "state" / "projects.sqlite3"),
        **overrides,
    )
    return create_app(
        settings, observability=ObservabilitySettings(traffic_log=TrafficLevel.MASKED)
    )


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(_app(tmp_path, api_token=API_TOKEN)) as tc:
        yield tc


def _code(client: TestClient, project: str = "default", **body: Any) -> dict[str, Any]:
    res = client.post(
        f"/v1/projects/{project}/cli-codes",
        headers=OWNER,
        json={"telemetry_level": "masked", **body},
    )
    assert res.status_code == 201, res.text
    return dict(res.json())


def _exchange(client: TestClient, code: str) -> Any:
    return client.post("/v1/cli/token", json={"code": code})


def test_code_exchange_mints_a_telemetry_key_on_the_cli_endpoint(client: TestClient) -> None:
    issued = _code(client, hostname="synthetic-laptop", telemetry_level="stats")
    assert issued["expires_in"] == CLI_CODE_TTL_SECONDS
    assert len(issued["code"]) >= 43  # 32 random bytes, URL-safe base64
    # The exchange takes no API token: the code is the credential.
    res = _exchange(client, issued["code"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {
        "dashboard_url",
        "project_id",
        "project_name",
        "endpoint_id",
        "key",
        "telemetry_level",
    }
    assert body["project_name"] == "Default project"
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", body["endpoint_id"])
    assert body["key"].startswith("pg_ep_")
    assert body["telemetry_level"] == "stats"
    assert body["dashboard_url"] == str(client.base_url).rstrip("/")
    endpoints = client.get(f"/v1/projects/{body['project_id']}/endpoints", headers=OWNER).json()
    (endpoint,) = endpoints["endpoints"]
    assert endpoint["id"] == body["endpoint_id"] and endpoint["name"] == CLI_ENDPOINT_NAME
    listing_path = f"/v1/projects/{body['project_id']}/endpoints/{body['endpoint_id']}/keys"
    listed = client.get(listing_path, headers=OWNER).json()["keys"]
    assert [(k["name"], k["scope"]) for k in listed] == [("CLI (synthetic-laptop)", "telemetry")]

    # Single use: the second exchange of the same code fails.
    again = _exchange(client, issued["code"])
    assert again.status_code == 400 and again.json()["error"]["code"] == "invalid_code"

    # A second login reuses the CLI endpoint and issues another key.
    second = _exchange(client, _code(client)["code"]).json()
    assert second["endpoint_id"] == body["endpoint_id"] and second["key"] != body["key"]


def test_cli_endpoint_is_never_another_enabled_endpoint(client: TestClient) -> None:
    project = client.post("/v1/projects", headers=OWNER, json={"name": "Has endpoint"}).json()
    own = client.post(
        f"/v1/projects/{project['id']}/endpoints",
        headers=OWNER,
        json={
            "name": "Own provider endpoint",
            "policy_version_id": project["default_policy_version_id"],
            "provider": "openai",
            "api_key": "synthetic-openai-key",
            "model": "synthetic-model",
        },
    )
    assert own.status_code == 201, own.text
    body = _exchange(client, _code(client, project["id"])["code"]).json()
    assert body["project_id"] == project["id"]
    assert body["endpoint_id"] != own.json()["id"]
    names = {
        e["name"]
        for e in client.get(f"/v1/projects/{project['id']}/endpoints", headers=OWNER).json()[
            "endpoints"
        ]
    }
    assert names == {"Own provider endpoint", CLI_ENDPOINT_NAME}


def test_telemetry_key_posts_traffic_only_and_revokes_itself(client: TestClient) -> None:
    body = _exchange(client, _code(client)["code"]).json()
    bearer = {"Authorization": f"Bearer {body['key']}"}
    base = f"/e/{body['endpoint_id']}/v1"
    ingest = client.post(f"{base}/traffic", headers=bearer, json=EVENT)
    assert ingest.status_code == 200, ingest.text
    chat = client.post(
        f"{base}/chat/completions",
        headers=bearer,
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert chat.status_code == 403
    assert client.get(f"{base}/models", headers=bearer).status_code == 403

    # Logout: the key revokes itself, then fails everywhere.
    assert client.delete("/v1/cli/token", headers=bearer).status_code == 204
    assert client.post(f"{base}/traffic", headers=bearer, json=EVENT).status_code == 403
    assert client.delete("/v1/cli/token", headers=bearer).status_code == 401


def test_logout_refuses_full_keys_and_garbage(client: TestClient) -> None:
    body = _exchange(client, _code(client)["code"]).json()
    full = client.post(
        f"/v1/projects/{body['project_id']}/endpoints/{body['endpoint_id']}/keys",
        headers=OWNER,
        json={"name": "Full key"},
    ).json()
    assert full["scope"] == "full"
    assert (
        client.delete("/v1/cli/token", headers={"Authorization": f"Bearer {full['key']}"})
    ).status_code == 401
    assert client.delete("/v1/cli/token").status_code == 401
    assert client.delete("/v1/cli/token", headers=OWNER).status_code == 401


def test_code_creation_requires_owner_access(client: TestClient) -> None:
    res = client.post("/v1/projects/default/cli-codes", json={"telemetry_level": "masked"})
    assert res.status_code == 401
    res = client.post(
        "/v1/projects/default/cli-codes", headers=OWNER, json={"telemetry_level": "raw"}
    )
    assert res.status_code == 422
    res = client.post(
        "/v1/projects/unknown-project/cli-codes", headers=OWNER, json={"telemetry_level": "stats"}
    )
    assert res.status_code == 404


def test_exchange_refuses_malformed_bodies(client: TestClient) -> None:
    assert client.post("/v1/cli/token", json={}).status_code == 422
    assert client.post("/v1/cli/token", json={"code": "short"}).status_code == 422
    unknown = _exchange(client, "x" * 43)
    assert unknown.status_code == 400 and unknown.json()["error"]["code"] == "invalid_code"


def test_dashboard_url_prefers_the_configured_public_origin(tmp_path: Path) -> None:
    app = _app(tmp_path, api_token=API_TOKEN, hosted_public_origin="https://guard.self.example")
    with TestClient(app) as tc:
        body = _exchange(tc, _code(tc)["code"]).json()
    assert body["dashboard_url"] == "https://guard.self.example"


@pytest.fixture
def store() -> ProjectStore:
    return ProjectStore.memory(MASTER, PolicySet(), "standard")


def test_expired_code_is_refused_and_deleted(store: ProjectStore) -> None:
    project = store.default_project("owner-a")
    issued = store.create_cli_code("owner-a", project["id"], "masked", None, now=1000.0)
    assert store.redeem_cli_code(issued["code"], now=1000.0 + CLI_CODE_TTL_SECONDS) is None
    # Deleted on that first (expired) use: it is gone even for an earlier clock.
    assert store.redeem_cli_code(issued["code"], now=1000.0) is None


def test_only_digests_are_stored(store: ProjectStore) -> None:
    project = store.default_project("owner-a")
    code = store.create_cli_code("owner-a", project["id"], "masked", None)["code"]
    assert code.encode() not in store.serialized()


def test_live_codes_per_owner_are_bounded(store: ProjectStore) -> None:
    project = store.default_project("owner-a")
    codes = [
        store.create_cli_code("owner-a", project["id"], "stats", None, now=1000.0 + i)["code"]
        for i in range(CLI_CODES_PER_OWNER + 2)
    ]
    # The oldest are evicted; the newest few still redeem.
    assert store.redeem_cli_code(codes[0], now=1010.0) is None
    assert store.redeem_cli_code(codes[1], now=1010.0) is None
    assert store.redeem_cli_code(codes[-1], now=1010.0) is not None


def test_codes_are_bound_to_the_owner_project(store: ProjectStore) -> None:
    other = store.default_project("owner-b")
    with pytest.raises(store_module.ProjectNotFoundError):
        store.create_cli_code("owner-a", other["id"], "masked", None)
    with pytest.raises(InvalidProjectConfigError):
        store.create_cli_code("owner-a", "default", "raw", None)


def test_exchange_retires_the_oldest_cli_key_at_the_key_limit(store: ProjectStore) -> None:
    keys = []
    for _ in range(33):
        code = create_cli_code(
            store, "owner-a", project_id="default", telemetry_level="masked", hostname="h"
        )
        keys.append(exchange_cli_code(store, code["code"], origin="https://d.example")["key"])
    body = exchange_cli_code(
        store,
        create_cli_code(
            store, "owner-a", project_id="default", telemetry_level="masked", hostname=None
        )["code"],
        origin="https://d.example",
    )
    assert store.resolve_key(keys[0], body["endpoint_id"]) is None
    assert store.resolve_key(keys[-1], body["endpoint_id"]) is not None
    with pytest.raises(InvalidCliCodeError):
        exchange_cli_code(store, "y" * 43, origin="https://d.example")


def test_previous_schema_snapshot_is_upgraded() -> None:
    old = ProjectStore.memory(MASTER, PolicySet(), "standard")
    project = old.default_project("owner-a")
    raw = old.serialized()
    # Rebuild that snapshot on the exact previous schema, as deployed stores hold it.
    db = sqlite3.connect(":memory:")
    db.deserialize(raw)
    db.executescript("DROP TABLE cli_codes; DROP TABLE endpoint_key_scopes;")
    db.execute("VACUUM")
    previous = db.serialize()
    db.close()
    upgraded = ProjectStore.memory(MASTER, PolicySet(), "standard", previous)
    assert upgraded.get_project("owner-a", project["id"])["id"] == project["id"]
    assert upgraded.create_cli_code("owner-a", project["id"], "masked", None)["code"]
