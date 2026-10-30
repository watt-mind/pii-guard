"""``/robots.txt`` is decided per request host: one image runs dev and prod (docs/hosted.md)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from pii_guard.app_bundle import INDEXED_HOST, Status, create_bundle_app, robots_txt
from pii_guard.config import Settings

DEV_HOST = "guard-dev.watt-mind.com"
ACA_HOST = "pii-guard-dev.example-1234.westeurope.azurecontainerapps.io"
TENANT_KEY = SecretStr(bytes(range(32)).hex())
DISALLOW_ALL = "User-agent: *\nDisallow: /\n"
INDEX = '<!doctype html><html><head><title>pii-guard</title></head><body><div id="root"></div>'


@pytest.fixture
def ui_dir(tmp_path: Path) -> Path:
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text(INDEX, encoding="utf-8")
    # What a build emits: the runtime route must answer instead of this file.
    (ui / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    return ui


def _hosted_client(ui_dir: Path, host: str) -> TestClient:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        hosted=True,
        hosted_public_origin=f"https://{INDEXED_HOST}",
        hosted_trust_easy_auth=True,
        hosted_single_process=True,
        tenant_key=TENANT_KEY,
        allowed_hosts=(INDEXED_HOST, DEV_HOST, ACA_HOST),
        detectors=("rules",),
        ner_fallback="off",
        upstream_api_key=SecretStr("synthetic-sponsored-key"),
    )
    app = create_bundle_app(Status(upstream="mock", detectors=["rules"]), settings, ui_dir=ui_dir)
    return TestClient(app, base_url=f"https://{host}")


def test_production_host_allows_the_landing_but_not_the_api(ui_dir: Path) -> None:
    response = _hosted_client(ui_dir, INDEXED_HOST).get("/robots.txt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    lines = response.text.splitlines()
    assert lines[:2] == ["User-agent: *", "Allow: /"]
    for path in ("/v1/", "/docs", "/openapi.json", "/healthz", "/readyz"):
        assert f"Disallow: {path}" in lines
    assert "Disallow: /" not in lines
    assert not any(line.startswith("Sitemap:") for line in lines)  # the build ships none


@pytest.mark.parametrize("host", [DEV_HOST, ACA_HOST])
def test_every_other_hosted_host_disallows_all(ui_dir: Path, host: str) -> None:
    response = _hosted_client(ui_dir, host).get("/robots.txt")
    assert response.status_code == 200
    assert response.text == DISALLOW_ALL


def test_local_up_disallows_all_and_the_spa_fallback_does_not_shadow_it(ui_dir: Path) -> None:
    settings = Settings(_env_file=None, tenant_key=TENANT_KEY)  # type: ignore[call-arg]
    app = create_bundle_app(Status(upstream="mock", detectors=["rules"]), settings, ui_dir=ui_dir)
    response = TestClient(app, base_url="http://localhost").get("/robots.txt")
    assert response.status_code == 200
    assert response.text == DISALLOW_ALL
    assert "root" not in response.text


def test_sitemap_is_announced_only_when_the_build_has_one() -> None:
    assert f"Sitemap: https://{INDEXED_HOST}/sitemap.xml" in robots_txt(INDEXED_HOST, sitemap=True)
    assert robots_txt(INDEXED_HOST.upper()).startswith("User-agent: *\nAllow: /\n")
    assert robots_txt(DEV_HOST, sitemap=True) == DISALLOW_ALL
    assert robots_txt(None) == DISALLOW_ALL
