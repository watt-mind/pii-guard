"""Tests for CLI browser-handoff provisioning and bundle encoding (LAB-1708)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.projects.cli_auth import (
    CLI_BUNDLE_PREFIX,
    CLI_ENDPOINT_NAME,
    decode_cli_bundle,
    encode_cli_bundle,
    provision_cli_session,
)
from pii_guard.projects.store import InvalidProjectConfigError

API_TOKEN = "test-api-token-not-a-secret"  # noqa: S105 - fictional
OWNER = {"X-PII-Guard-Token": API_TOKEN}


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        detectors=("rules",),
        ner_fallback="off",
        tenant_key="38" * 32,
        api_token=API_TOKEN,
        project_state_path=str(tmp_path / "state" / "projects.sqlite3"),
    )
    app = create_app(settings)
    with TestClient(app) as tc:
        yield tc


def test_encode_and_decode_cli_bundle_roundtrip() -> None:
    bundle = encode_cli_bundle(
        {
            "v": 1,
            "dashboard_url": "https://guard.watt-mind.com/",
            "project_id": "prj_123",
            "project_name": "Default project",
            "endpoint_id": "ep_456",
            "endpoint_key": "pg_ep_aaa",
            "telemetry_level": "stats",
        }
    )
    assert bundle.startswith(CLI_BUNDLE_PREFIX)
    decoded = decode_cli_bundle(bundle)
    assert decoded == {
        "dashboard_url": "https://guard.watt-mind.com",
        "project_id": "prj_123",
        "project_name": "Default project",
        "endpoint_id": "ep_456",
        "endpoint_key": "pg_ep_aaa",
        "telemetry_level": "stats",
    }


@pytest.mark.parametrize(
    "bad_bundle",
    [
        "not_a_bundle",
        "pg_cli_",
        "pg_cli_!!!not-base64!!!",
        f"pg_cli_{base64.urlsafe_b64encode(b'[1, 2, 3]').decode('ascii').rstrip('=')}",
        encode_cli_bundle({"dashboard_url": "https://guard.watt-mind.com"}),
        encode_cli_bundle(
            {
                "dashboard_url": "https://guard.watt-mind.com",
                "project_id": "prj_1",
                "project_name": "Proj",
                "endpoint_id": "ep_1",
                "endpoint_key": "pg_ep_aaa",
                "telemetry_level": "raw",
            }
        ),
    ],
)
def test_decode_cli_bundle_rejects_invalid_tokens(bad_bundle: str) -> None:
    with pytest.raises(ValueError):
        decode_cli_bundle(bad_bundle)


def test_put_cli_session_provisions_default_and_reuses_endpoint(client: TestClient) -> None:
    res = client.put(
        "/v1/projects/default/endpoints",
        headers=OWNER,
        json={"telemetry_level": "masked", "key_name": "CLI laptop"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["project"]["name"] == "Default project"
    assert body["endpoint"]["name"] == CLI_ENDPOINT_NAME
    assert body["key"]["key"].startswith("pg_ep_")
    assert body["telemetry_level"] == "masked"
    assert body["gateway_url"].endswith(f"/e/{body['endpoint']['id']}/v1")
    assert body["dashboard_url"].endswith("/#logs")

    decoded = decode_cli_bundle(body["bundle"])
    assert decoded["project_id"] == body["project"]["id"]
    assert decoded["endpoint_id"] == body["endpoint"]["id"]
    assert decoded["endpoint_key"] == body["key"]["key"]
    assert decoded["telemetry_level"] == "masked"

    # A second CLI login in the same project reuses the existing CLI endpoint and issues a fresh key
    res2 = client.put(
        f"/v1/projects/{body['project']['id']}/endpoints",
        headers=OWNER,
        json={"telemetry_level": "stats"},
    )
    assert res2.status_code == 201, res2.text
    body2 = res2.json()
    assert body2["endpoint"]["id"] == body["endpoint"]["id"]
    assert body2["key"]["key"] != body["key"]["key"]
    assert body2["telemetry_level"] == "stats"


def test_put_cli_session_reuses_non_cli_enabled_endpoint_when_present(client: TestClient) -> None:
    proj = client.post(
        "/v1/projects",
        headers=OWNER,
        json={"name": "Custom Endpoint Project"},
    ).json()
    ep_res = client.post(
        f"/v1/projects/{proj['id']}/endpoints",
        headers=OWNER,
        json={
            "name": "Existing Gateway Endpoint",
            "policy_version_id": proj["default_policy_version_id"],
            "provider": "openai",
            "api_key": "synthetic-openai-key",
            "enabled": True,
        },
    )
    assert ep_res.status_code == 201, ep_res.text
    ep = ep_res.json()
    res = client.put(
        f"/v1/projects/{proj['id']}/endpoints",
        headers=OWNER,
        json={"telemetry_level": "masked"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["endpoint"]["id"] == ep["id"]


def test_put_cli_session_creates_new_project(client: TestClient) -> None:
    res = client.put(
        "/v1/projects/new/endpoints",
        headers=OWNER,
        json={"project_name": "Agent Telemetry", "telemetry_level": "stats"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["project"]["name"] == "Agent Telemetry"
    assert body["telemetry_level"] == "stats"
    decoded = decode_cli_bundle(body["bundle"])
    assert decoded["project_name"] == "Agent Telemetry"
    assert decoded["telemetry_level"] == "stats"


def test_put_cli_session_new_project_requires_name(client: TestClient) -> None:
    res = client.put(
        "/v1/projects/new/endpoints",
        headers=OWNER,
        json={"telemetry_level": "masked"},
    )
    assert res.status_code == 422

    res_blank = client.put(
        "/v1/projects/new/endpoints",
        headers=OWNER,
        json={"project_name": "   ", "telemetry_level": "masked"},
    )
    assert res_blank.status_code == 422


def test_provision_cli_session_rejects_unknown_telemetry_level(client: TestClient) -> None:
    store = client.app.state.projects.store  # type: ignore[attr-defined]
    with pytest.raises(InvalidProjectConfigError):
        provision_cli_session(
            store,
            "local",
            project_id="default",
            telemetry_level="raw",  # type: ignore[arg-type]
            origin="http://127.0.0.1:8080",
        )


def test_put_cli_session_requires_owner_auth(client: TestClient) -> None:
    res = client.put(
        "/v1/projects/default/endpoints",
        json={"telemetry_level": "masked"},
    )
    assert res.status_code in (401, 403)
