"""The hosted Evaluation page is public (LAB-1533): its data is static, the account data isn't."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pii_guard.app_bundle import Status, create_bundle_app
from pii_guard.config import Settings

ORIGIN = "https://guard.example"
SUMMARY = "assets/benchmarks-summary-abc123.json"


def hosted_settings() -> Settings:
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
        upstream_api_key="synthetic-sponsored-key",
    )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text('<!doctype html><div id="root"></div>', encoding="utf-8")
    (ui / SUMMARY).write_text(json.dumps({"systems": {}, "sets": []}), encoding="utf-8")
    app = create_bundle_app(
        Status(upstream="mock", detectors=["rules"]), hosted_settings(), ui_dir=ui
    )
    return TestClient(app, base_url=ORIGIN)


def test_benchmark_parts_are_served_without_sign_in(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    part = client.get(f"/{SUMMARY}")
    assert part.status_code == 200
    assert part.json() == {"systems": {}, "sets": []}


@pytest.mark.parametrize("path", ["/v1/traffic", "/v1/vault/sessions", "/v1/projects"])
def test_account_data_stays_behind_sign_in(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401
