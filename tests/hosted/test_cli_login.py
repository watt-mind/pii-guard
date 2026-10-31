"""Hosted CLI login: one-time codes and telemetry-only keys (LAB-1708).

``POST /v1/projects/{id}/cli-codes`` is signed-in Google owners only, same origin;
``POST /v1/cli/token`` takes the code alone (no session), JSON only, bounded and rate
limited; the minted key may only ``POST /e/<id>/v1/traffic`` and ``DELETE /v1/cli/token``.
Identities, keys and host names are synthetic (ADR 0005).
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.hosted.abuse import AbuseAdmissionError
from pii_guard.hosted.quotas import QuotaLedger, QuotaLimits

ORIGIN = "https://guard.example"
EVENT = {"events": [{"level": "masked"}]}


def auth(subject: str = "synthetic-one", **extra: str) -> dict[str, str]:
    encoded = base64.b64encode(
        json.dumps({"auth_typ": "google", "claims": [{"typ": "sub", "val": subject}]}).encode()
    ).decode()
    return {"x-ms-client-principal": encoded, "origin": ORIGIN, **extra}


@pytest.fixture
def app(tmp_path: Path) -> Any:
    application = create_app(
        Settings(
            _env_file=None,
            hosted=True,
            hosted_public_origin=ORIGIN,
            hosted_trust_easy_auth=True,
            hosted_single_process=True,
            hosted_images=False,
            tenant_key=bytes(range(32)).hex(),
            allowed_hosts=("guard.example",),
            detectors=("rules",),
            ner_fallback="off",
            upstream_api_key="synthetic-sponsored-key",
            project_state_path=str(tmp_path / "hosted-projects.sqlite3"),
        )
    )
    application.state.hosted.quotas = QuotaLedger(
        QuotaLimits(global_daily_microdollars=1_000_000_000),
        sponsored_allocation_microdollars=1_000_000_000,
        allocation_expires_at=time.time() + 3600,
        claim_allocation=lambda: True,
    )
    return application


@pytest.fixture
def client(app: Any) -> Iterator[TestClient]:
    with TestClient(app, base_url=ORIGIN) as test_client:
        yield test_client


def _code(client: TestClient, project: str = "default", **body: Any) -> str:
    res = client.post(
        f"/v1/projects/{project}/cli-codes",
        json={"telemetry_level": "masked", "hostname": "synthetic-host", **body},
        headers=auth(),
    )
    assert res.status_code == 201, res.text
    assert res.json()["expires_in"] == 300
    return str(res.json()["code"])


def _login(client: TestClient) -> dict[str, Any]:
    res = client.post("/v1/cli/token", json={"code": _code(client)})
    assert res.status_code == 200, res.text
    return dict(res.json())


def test_signed_in_owner_creates_a_code_and_the_cli_exchanges_it(client: TestClient) -> None:
    body = _login(client)
    assert body["dashboard_url"] == ORIGIN
    assert body["telemetry_level"] == "masked"
    assert body["key"].startswith("pg_ep_")
    project = client.get(f"/v1/projects/{body['project_id']}", headers=auth())
    assert project.status_code == 200
    keys = client.get(
        f"/v1/projects/{body['project_id']}/endpoints/{body['endpoint_id']}/keys", headers=auth()
    ).json()["keys"]
    assert [(k["name"], k["scope"]) for k in keys] == [("CLI (synthetic-host)", "telemetry")]


def test_guest_cannot_create_a_code(client: TestClient) -> None:
    res = client.post(
        "/v1/projects/default/cli-codes",
        json={"telemetry_level": "masked"},
        headers={"origin": ORIGIN},
    )
    assert res.status_code == 401


def test_guard_api_key_cannot_create_a_code(client: TestClient) -> None:
    issued = client.post("/v1/account/api-keys", json={"name": "Synthetic key"}, headers=auth())
    assert issued.status_code == 201, issued.text
    res = client.post(
        "/v1/projects/default/cli-codes",
        json={"telemetry_level": "masked"},
        headers={"authorization": "Bearer " + issued.json()["key"], "origin": ORIGIN},
    )
    assert res.status_code == 401


def test_endpoint_key_cannot_create_a_code(client: TestClient) -> None:
    body = _login(client)
    bearer = {"authorization": "Bearer " + body["key"], "origin": ORIGIN}
    res = client.post(
        f"/v1/projects/{body['project_id']}/cli-codes",
        json={"telemetry_level": "masked"},
        headers=bearer,
    )
    assert res.status_code == 401


@pytest.mark.parametrize("origin", [None, "https://evil.example"])
def test_code_creation_requires_the_same_origin(client: TestClient, origin: str | None) -> None:
    headers = auth()
    del headers["origin"]
    if origin is not None:
        headers["origin"] = origin
    res = client.post(
        "/v1/projects/default/cli-codes", json={"telemetry_level": "stats"}, headers=headers
    )
    assert res.status_code == 403


def test_code_is_single_use(client: TestClient) -> None:
    code = _code(client)
    assert client.post("/v1/cli/token", json={"code": code}).status_code == 200
    again = client.post("/v1/cli/token", json={"code": code})
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "invalid_code"


def test_expired_code_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    code = _code(client)
    later = time.time() + 301
    monkeypatch.setattr("pii_guard.projects.store.time.time", lambda: later)
    res = client.post("/v1/cli/token", json={"code": code})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_code"


def test_exchange_is_json_only_bounded_and_same_origin(client: TestClient) -> None:
    code = _code(client)
    as_form = client.post("/v1/cli/token", data={"code": code})
    assert as_form.status_code == 403
    huge = client.post("/v1/cli/token", json={"code": code, "pad": "x" * 4096})
    assert huge.status_code == 403
    cross = client.post(
        "/v1/cli/token", json={"code": code}, headers={"origin": "https://evil.example"}
    )
    assert cross.status_code == 403
    assert client.get("/v1/cli/token").status_code == 403
    # None of those consumed it.
    assert client.post("/v1/cli/token", json={"code": code}).status_code == 200


def test_exchange_spends_no_inference_quota(client: TestClient) -> None:
    code = _code(client)
    before = client.get("/v1/account", headers=auth()).json()["usage"]["requests_today"]
    assert client.post("/v1/cli/token", json={"code": code}).status_code == 200
    after = client.get("/v1/account", headers=auth()).json()["usage"]["requests_today"]
    assert after == before


def test_exchange_is_rate_limited_by_the_abuse_bucket(
    app: Any, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    code = _code(client)
    calls: list[dict[str, Any]] = []

    def admit(headers: Any, **kwargs: Any) -> None:
        calls.append(kwargs)
        raise AbuseAdmissionError(7)

    monkeypatch.setattr(app.state.hosted.abuse, "admit", admit)
    res = client.post("/v1/cli/token", json={"code": code})
    assert res.status_code == 429
    assert calls == [
        {
            "principal_id": "cli-token-exchange",
            "authenticated": False,
            "anonymous_sponsored": True,
        }
    ]


def test_telemetry_key_may_only_post_traffic(client: TestClient) -> None:
    body = _login(client)
    bearer = {"authorization": "Bearer " + body["key"]}
    base = f"/e/{body['endpoint_id']}/v1"
    ingest = client.post(f"{base}/traffic", json=EVENT, headers=bearer)
    assert ingest.status_code == 200, ingest.text
    chat = client.post(
        f"{base}/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers=bearer,
    )
    assert chat.status_code == 403
    responses = client.post(f"{base}/responses", json={"input": "hello"}, headers=bearer)
    assert responses.status_code == 403
    assert client.get(f"{base}/models", headers=bearer).status_code == 403
    assert client.get("/muse-code/models", headers=bearer).status_code == 403
    assert client.get(f"/e/{body['endpoint_id']}/muse-code/models", headers=bearer).status_code == (
        403
    )


def test_telemetry_key_revokes_itself(client: TestClient) -> None:
    body = _login(client)
    bearer = {"authorization": "Bearer " + body["key"]}
    assert client.delete("/v1/cli/token", headers=bearer).status_code == 204
    ingest = client.post(f"/e/{body['endpoint_id']}/v1/traffic", json=EVENT, headers=bearer)
    assert ingest.status_code == 401
    assert client.delete("/v1/cli/token", headers=bearer).status_code == 401
    assert client.delete("/v1/cli/token").status_code == 401


def test_full_endpoint_key_cannot_use_logout(client: TestClient) -> None:
    body = _login(client)
    full = client.post(
        f"/v1/projects/{body['project_id']}/endpoints/{body['endpoint_id']}/keys",
        json={"name": "Full"},
        headers=auth(),
    ).json()
    res = client.delete("/v1/cli/token", headers={"authorization": "Bearer " + full["key"]})
    assert res.status_code == 401
