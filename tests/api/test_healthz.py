"""``/healthz`` reports OCR availability (LAB-1219)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings

KEY = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"


def _client(monkeypatch, ocr: bool, required: bool = True) -> TestClient:
    import pii_guard.visual.ocr as ocr_module

    monkeypatch.setattr(ocr_module, "tesseract_available", lambda: ocr)
    settings = Settings(tenant_key=KEY, detectors=("rules",), image_require_ocr=required)
    return TestClient(create_app(settings))


def test_healthz_reports_ocr_on_when_tesseract_present(monkeypatch) -> None:
    body = _client(monkeypatch, True).get("/healthz").json()
    assert body["status"] == "ok" and body["ocr"] == "on"
    assert body["image_require_ocr"] is True


def test_healthz_reports_ocr_off_and_whether_it_is_required(monkeypatch) -> None:
    missing = _client(monkeypatch, False).get("/healthz").json()
    assert missing["ocr"] == "off" and missing["image_require_ocr"] is True
    optional = _client(monkeypatch, False, required=False).get("/healthz").json()
    assert optional["ocr"] == "off" and optional["image_require_ocr"] is False
