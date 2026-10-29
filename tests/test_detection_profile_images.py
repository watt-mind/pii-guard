"""Local-only images cannot reach SAM, including constructor and cached-object overrides.

All images are generated blank synthetic PNGs; model calls use controlled local fakes.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from starlette.requests import Request

from pii_guard.api.app import create_app
from pii_guard.api.routes.image import get_image_masker
from pii_guard.config import Settings
from pii_guard.detection_profile import DetectionProfileError
from pii_guard.types import DetectionError, EntityType
from pii_guard.visual.ocr import TesseractOcr
from pii_guard.visual.sam import SamClient
from pii_guard.visual.segment import LocalSegmenter
from pii_guard.visual.segmenters import HybridSegmenter, OffSegmenter, build_segmenter


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("local image processing attempted network access")

    async def async_blocked(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("local image processing attempted network access")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_blocked)


def settings(**kwargs: Any) -> Settings:
    return Settings(
        _env_file=None,
        detection_profile="local-only",
        detectors=("rules",),
        ner_fallback="off",
        tenant_key="ab" * 32,
        image_render="opaque",
        **kwargs,
    )


def png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(output, format="PNG")
    return output.getvalue()


def local_segmenter() -> LocalSegmenter:
    # Unsupported types are rejected before this trusted fake backend can be used.
    return LocalSegmenter(detector=object())


def app_with(segmenter: object, *, ocr: object = None, **kwargs: Any) -> Any:
    app = create_app(settings(segmenter="local", **kwargs))
    app.state.sam_client = segmenter
    app.state.ocr_engine = TesseractOcr() if ocr is None else ocr
    return app


def request_for(app: Any) -> Request:
    return Request({"type": "http", "app": app, "method": "POST", "path": "/v1/mask/image"})


@pytest.mark.parametrize("mode", ["hybrid", "sam-api"])
def test_factory_explicit_remote_mode_refused_before_local_or_sam_build(mode: str) -> None:
    def unavailable() -> LocalSegmenter:
        raise AssertionError("must reject profile before constructing any model")

    with pytest.raises(DetectionProfileError):
        build_segmenter(
            settings(segmenter="local", meta_api_key="synthetic-key"), mode=mode, local=unavailable
        )


def test_unused_hybrid_default_does_not_prevent_text_app_startup() -> None:
    configured = settings()
    assert configured.segmenter == "hybrid"
    app = create_app(configured)
    with TestClient(app) as client:
        response = client.post("/v1/analyze", json={"text": "synthetic@example.com"})
    assert response.status_code == 200
    with pytest.raises(DetectionProfileError):
        build_segmenter(configured)


@pytest.mark.parametrize("mode", ["local", "off"])
def test_factory_allows_only_explicit_local_modes(mode: str) -> None:
    local = local_segmenter()
    result = build_segmenter(settings(segmenter=mode), local=lambda: local)
    assert result is local if mode == "local" else type(result) is OffSegmenter


@pytest.mark.parametrize("url", ["https://api.example.com/v1", "http://127.0.0.1:8788/v1"])
def test_direct_sam_constructor_refuses_url_key_model_transport_overrides(url: str) -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError("SAM transport must not run")

    with pytest.raises(DetectionProfileError):
        SamClient(
            settings=settings(),
            base_url=url,
            api_key="synthetic-key",
            model="synthetic-model",
            transport=httpx.MockTransport(forbidden),
        )


def test_direct_sam_default_settings_honor_local_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    from pii_guard.visual import sam

    monkeypatch.setattr(sam, "get_settings", lambda: settings())
    with pytest.raises(DetectionProfileError):
        SamClient(api_key="synthetic-key")


def test_sam_send_rechecks_its_explicit_settings_reference() -> None:
    configured = Settings(_env_file=None, detection_profile="standard")
    sam = SamClient(settings=configured, api_key="synthetic-key")
    configured.detection_profile = "local-only"
    with httpx.Client() as client, pytest.raises(DetectionProfileError):
        sam._request(client, "signature", "data:image/png;base64,synthetic")


@pytest.mark.parametrize("hybrid", [False, True])
def test_rest_rejects_cached_remote_instance_even_created_under_standard_profile(
    hybrid: bool,
) -> None:
    sam = SamClient(settings=Settings(_env_file=None), api_key="synthetic-key")
    candidate = HybridSegmenter(sam=sam, local=local_segmenter()) if hybrid else sam
    app = app_with(candidate)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/mask/image", content=png(), headers={"Content-Type": "image/png"}
            )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "detection_profile_denied"
        assert "image" not in response.json()
    finally:
        if isinstance(candidate, HybridSegmenter):
            candidate._pool.shutdown()


def test_rest_rejects_segmenter_that_only_claims_to_be_local() -> None:
    impersonator = SimpleNamespace(name="local", model="yunet", segment=lambda *args: [])
    with pytest.raises(DetectionProfileError):
        get_image_masker(request_for(app_with(impersonator)))


@pytest.mark.parametrize("unsafe_ocr", [False, "missing", "foreign"])
def test_rest_requires_builtin_ocr_and_checked_text(unsafe_ocr: bool | str) -> None:
    app = app_with(local_segmenter(), image_require_ocr=unsafe_ocr is not False)
    if unsafe_ocr == "missing":
        app.state.ocr_engine = None
    elif unsafe_ocr == "foreign":
        app.state.ocr_engine = SimpleNamespace(name="tesseract", words=lambda image: [])
    with pytest.raises(DetectionProfileError):
        get_image_masker(request_for(app))


@pytest.mark.parametrize("signature_policy", ["mask", "block"])
def test_local_signature_protection_is_never_silently_relaxed(signature_policy: str) -> None:
    app = app_with(local_segmenter(), policy_overrides=f"SIGNATURE={signature_policy}")
    with TestClient(app) as client:
        response = client.post(
            "/v1/mask/image", content=png(), headers={"Content-Type": "image/png"}
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "detection_failed"
    assert "SIGNATURE" in response.json()["error"]["message"]
    assert "image" not in response.json()


def test_local_stamp_protection_is_never_silently_relaxed() -> None:
    app = app_with(local_segmenter(), policy_overrides="SIGNATURE=keep,STAMP=mask")
    with TestClient(app) as client:
        response = client.post(
            "/v1/mask/image", content=png(), headers={"Content-Type": "image/png"}
        )
    assert response.status_code == 503
    assert "STAMP" in response.json()["error"]["message"]


def test_explicit_signature_keep_retains_only_supported_visual_types() -> None:
    masker = get_image_masker(
        request_for(app_with(local_segmenter(), policy_overrides="SIGNATURE=keep"))
    )
    assert set(masker.entity_types) == {EntityType.FACE, EntityType.ID_PHOTO}
    assert type(masker.ocr) is TesseractOcr


def test_missing_local_model_does_not_fallback_or_download(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace())
    monkeypatch.setenv("PII_GUARD_MODEL_DIR", str(tmp_path))
    with pytest.raises(DetectionError, match=r"model .* is missing"):
        build_segmenter(settings(segmenter="local", meta_api_key="synthetic-key"))
    assert list(tmp_path.iterdir()) == []


def test_rest_lazy_default_remote_segmenter_is_refused() -> None:
    app = create_app(settings())
    app.state.ocr_engine = TesseractOcr()
    with TestClient(app) as client:
        response = client.post(
            "/v1/mask/image", content=png(), headers={"Content-Type": "image/png"}
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "detection_profile_denied"
    assert not hasattr(app.state, "sam_client")


def test_explicit_keep_allows_builtin_local_pipeline_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pii_guard.visual.ocr import OcrPage, PageFrame

    local = local_segmenter()
    ocr = TesseractOcr()
    calls: list[list[EntityType]] = []

    def segment(image: bytes, entity_types: list[EntityType]) -> list[Any]:
        calls.append(list(entity_types))
        assert set(entity_types) == {EntityType.FACE, EntityType.ID_PHOTO}
        return []

    # Controlled inference doubles on the exact built-in objects; the application boundary,
    # requested policies, OCR orchestration and image encoding all run normally.
    monkeypatch.setattr(local, "segment", segment)
    monkeypatch.setattr(ocr, "read", lambda image: OcrPage([], PageFrame.of(image.size, 0.0)))
    app = app_with(local, ocr=ocr, policy_overrides="SIGNATURE=keep")
    with TestClient(app) as client:
        response = client.post(
            "/v1/mask/image", content=png(), headers={"Content-Type": "image/png"}
        )
    assert response.status_code == 200
    assert response.json()["media_type"] == "image/png"
    assert response.json()["analysis"]["ocr"]["engine"] == "tesseract"
    assert len(calls) == 1
