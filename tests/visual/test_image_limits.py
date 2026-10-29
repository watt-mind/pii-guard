"""Image work limits (LAB-1207): deadlines, staged session writes, pixel budget, one pool.

Synthetic card from :mod:`visual_helpers` (fictional values), a fake SAM client and a fake
OCR engine that can be made slow; the Tesseract test is skipped without Tesseract.
"""

from __future__ import annotations

import base64
import threading
import time
from typing import ClassVar

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from visual_helpers import FakeOcr, card_words, id_card_png, png_bytes

from pii_guard.api.app import create_app
from pii_guard.api.deps import PayloadTooLargeError
from pii_guard.config import Settings
from pii_guard.detect.rules import RuleDetector
from pii_guard.gateway import Gateway, GatewayConfig
from pii_guard.gateway.detection import build_mode_detectors
from pii_guard.policy import PolicySet
from pii_guard.types import EntityType
from pii_guard.vault import Vault
from pii_guard.visual.masking import ImageMasker
from pii_guard.visual.ocr import (
    OcrTimeoutError,
    OcrWord,
    TesseractOcr,
    check_deadline,
    deadline,
    tesseract_available,
)
from pii_guard.visual.regions import Region

TENANT_KEY = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"


class NoSam:
    model = "fake-sam"
    prompts: ClassVar[dict[EntityType, tuple[str, ...]]] = {EntityType.FACE: ("face",)}

    def segment(self, image: bytes, entity_types: object = None) -> list[Region]:
        return []


class SlowOcr(FakeOcr):
    """The perfect fake OCR, but each image takes ``delay`` seconds (records start/end)."""

    def __init__(self, delay: float, *, gate: threading.Event | None = None) -> None:
        super().__init__(card_words())
        self.delay = delay
        self.gate = gate  # when set, OCR blocks on it instead of sleeping (the test releases it)
        self.events: list[str] = []
        self.done = threading.Event()

    def words(self, image: Image.Image) -> list[OcrWord]:
        self.events.append("start")
        if self.gate is not None:
            self.gate.wait(30)
        else:
            time.sleep(self.delay)
        self.events.append("end")
        self.done.set()
        return super().words(image)


def _settings(**kwargs: object) -> Settings:
    return Settings(
        tenant_key=TENANT_KEY,
        upstream_base_url="http://upstream.invalid/v1",
        upstream_api_key="test-upstream-key",
        **kwargs,  # type: ignore[arg-type]
    )


def _gateway_app(ocr: FakeOcr, *, image_timeout: float) -> tuple[FastAPI, Vault]:
    settings = _settings()
    config = GatewayConfig(mode="fast", image_timeout=image_timeout)
    vault = Vault.from_settings(settings)
    answer = {"choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}]}
    app = create_app(settings)
    app.state.gateway = Gateway(
        settings=settings,
        vault=vault,
        config=config,
        detectors=build_mode_detectors(settings, config),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=answer)),
        sam=NoSam(),  # type: ignore[arg-type]
        ocr=ocr,
    )
    return app, vault


def _data_url(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode()


def test_a_timed_out_image_registers_nothing_and_stops_early() -> None:
    """The probe: four slow images on an existing session, a 0.5 s image timeout.

    Before LAB-1207 OCR kept going after the 503 and registered the card's values in the
    caller's session (0 -> 3 entities)."""
    ocr = SlowOcr(delay=0.8)
    app, vault = _gateway_app(ocr, image_timeout=0.5)
    image = {"type": "image_url", "image_url": {"url": _data_url(id_card_png())}}
    with TestClient(app) as http:
        first = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": "szia"}]},
        )
        sid = first.headers["X-PII-Guard-Session"]
        response = http.post(
            "/v1/chat/completions",
            headers={"X-PII-Guard-Session": sid},
            json={"model": "m", "messages": [{"role": "user", "content": [image] * 4}]},
        )
        assert response.status_code == 503, response.text
        assert response.json()["error"]["code"] == "detection_failed"
        assert ocr.done.wait(5)
        time.sleep(0.3)  # long enough for a second image to start, if one were going to
    assert ocr.events == ["start", "end"]  # the deadline stopped the rest
    assert vault.session(sid).entities() == []


def test_a_successful_image_request_commits_its_values() -> None:
    app, vault = _gateway_app(FakeOcr(card_words()), image_timeout=30)
    image = {"type": "image_url", "image_url": {"url": _data_url(id_card_png())}}
    with TestClient(app) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": [image]}]},
        )
    assert response.status_code == 200, response.text
    session = vault.session(response.headers["X-PII-Guard-Session"])
    assert session.entities()  # the card's values, committed from the fork


def _image_app(ocr: FakeOcr, **settings: object) -> FastAPI:
    app = create_app(_settings(**settings))
    app.state.sam_client = NoSam()
    app.state.ocr_engine = ocr
    return app


def _post_image(http: TestClient, data: bytes, **fields: object) -> httpx.Response:
    return http.post("/v1/mask/image", json={"image": base64.b64encode(data).decode(), **fields})


def test_mask_image_endpoint_has_a_timeout_and_leaves_the_session_alone() -> None:
    """The endpoint answers at its timeout while OCR is still running (LAB-1322).

    OCR is held on a gate the test controls, so "answered at the timeout, not when OCR finished"
    is checked structurally -- the 503 arrives while OCR has not finished -- not by a wall-clock
    bound that scheduler latency on a loaded machine can break. If the endpoint waited for OCR,
    it would block until the gate's 30 s cap, and OCR would be done by the time it answered."""
    gate = threading.Event()
    ocr = SlowOcr(delay=0, gate=gate)
    app = _image_app(ocr, image_timeout=0.3)
    app.state.vault = Vault.from_settings(app.state.settings)
    session = app.state.vault.session()  # an existing conversation
    with TestClient(app) as http:
        try:
            response = _post_image(
                http, id_card_png(), render="labels", session_id=session.session_id
            )
            ocr_finished_before_answer = ocr.done.is_set()
        finally:
            gate.set()
        assert response.status_code == 503, response.text
        assert response.json()["error"]["code"] == "detection_failed"
        assert not ocr_finished_before_answer  # answered at the timeout, not when OCR finished
        assert ocr.done.wait(5)
    assert session.entities() == []


def _big_png(width: int, height: int) -> bytes:
    img = Image.new("L", (width, height), 255)
    ImageDraw.Draw(img).text((5, 5), "minta", fill=0)
    return png_bytes(img, optimize=True)


def test_images_over_the_pixel_budget_are_refused_before_decoding() -> None:
    masker = ImageMasker(
        sam=NoSam(),  # type: ignore[arg-type]
        policies=PolicySet(),
        ocr=FakeOcr([]),
        text_detector=RuleDetector(),
        max_pixels=100 * 100,
    )
    with pytest.raises(PayloadTooLargeError, match="pixels"):
        masker.mask(_big_png(200, 100))
    assert masker.mask(_big_png(100, 100)).width == 100


def test_the_endpoint_applies_the_pixel_budget_setting() -> None:
    ocr = FakeOcr([])
    app = _image_app(ocr, image_max_pixels=5000, image_render="opaque")
    with TestClient(app) as http:
        response = _post_image(http, _big_png(100, 100))
    assert response.status_code == 413, response.text
    assert response.json()["error"]["code"] == "payload_too_large"
    assert ocr.calls == 0


def test_default_pixel_budget_is_below_the_decoder_cap() -> None:
    assert Settings().image_max_pixels == 16_000_000


def test_the_gateway_and_the_endpoint_share_one_image_pool() -> None:
    settings = _settings(image_concurrency=3)
    app = create_app(settings)
    app.state.sam_client = NoSam()
    app.state.ocr_engine = FakeOcr([])
    with TestClient(app) as http:
        http.post("/v1/mask/image", json={"image": base64.b64encode(_big_png(40, 40)).decode()})
        http.post("/v1/chat/completions", json={"model": "m", "messages": []})
    workers = app.state.image_workers
    assert workers.size == 3
    assert app.state.gateway._image_workers is workers


def test_check_deadline() -> None:
    check_deadline()  # no deadline: nothing to check
    with deadline(time.monotonic() + 60):
        check_deadline()
    with deadline(time.monotonic() - 1), pytest.raises(OcrTimeoutError):
        check_deadline()


@pytest.mark.skipif(not tesseract_available(), reason="Tesseract is not installed")
def test_tesseract_is_killed_at_the_deadline() -> None:
    img = Image.new("L", (3000, 2000), 255)
    draw = ImageDraw.Draw(img)
    for y in range(0, 2000, 40):
        draw.text((10, y), "lorem ipsum dolor sit amet " * 8, fill=0)
    started = time.perf_counter()
    with deadline(time.monotonic() + 0.3), pytest.raises(OcrTimeoutError):
        TesseractOcr(lang="eng").words(img.convert("RGB"))
    assert time.perf_counter() - started < 3
