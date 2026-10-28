"""Gateway: inline ``image_url`` parts are masked before forwarding; remote URLs are refused.

Synthetic only (ADR 0005): a Pillow-drawn image, fictional values, SAM answers from an
``httpx.MockTransport`` in the observed Responses API format, a mock upstream.
"""

from __future__ import annotations

import base64
import io
import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway_helpers import (
    TEST_TENANT_KEY,
    UPSTREAM_KEY,
    UPSTREAM_URL,
    FakeLlm,
    MockUpstream,
)
from PIL import Image, ImageDraw

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway import Gateway, GatewayConfig, Mode, build_mode_detectors, collect_texts
from pii_guard.gateway.request import UnsupportedContentError
from pii_guard.vault import Vault
from pii_guard.visual import OcrWord, SamClient
from pii_guard.visual.regions import Box

W, H = 300, 200
FACE = Box(20, 30, 109, 149)
TAJ_BOX = Box(175, 40, 279, 59)
TAJ_VALUE = "123 456 788"  # fictional
WORDS = [
    OcrWord("TAJ:", Box(130, 40, 169, 59), (0,)),
    OcrWord("123", Box(175, 40, 205, 59), (0,)),
    OcrWord("456", Box(211, 40, 241, 59), (0,)),
    OcrWord("788", Box(247, 40, 279, 59), (0,)),
]


def png() -> bytes:
    img = Image.new("RGB", (W, H), (230, 236, 248))
    d = ImageDraw.Draw(img)
    d.ellipse(FACE.to_list(), fill=(240, 200, 170))
    d.text((130, 40), f"TAJ: {TAJ_VALUE}", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def data_url(data: bytes, media: str = "image/png") -> str:
    return f"data:{media};base64," + base64.b64encode(data).decode()


class Sam:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.prompts: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["input"][0]["content"][0]["text"]
        self.prompts.append(prompt)
        if self.fail:
            return httpx.Response(500)
        text = ""
        if prompt == "face":
            b = FACE
            text = f"<0f>0<|box;x1={b.x1};y1={b.y1};x2={b.x2};y2={b.y2};w={W};h={H}|>"
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            },
        )


class FakeOcr:
    name = "fake-ocr"

    def words(self, image: Image.Image) -> list[OcrWord]:
        return list(WORDS)


def make_app(
    upstream: MockUpstream,
    sam: Sam,
    *,
    ocr: object = "fake",
    config: GatewayConfig | None = None,
    policy_overrides: str | None = None,
    require_ocr: bool = True,
) -> FastAPI:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
        policy_overrides=policy_overrides,
        image_render="opaque",  # solid boxes; labels: tests/visual/test_labelled_images.py
        image_require_ocr=require_ocr,
    )
    config = config or GatewayConfig(mode=Mode.AUDIT)
    app = create_app(settings)
    app.state.gateway = Gateway(
        settings=settings,
        vault=Vault.from_settings(settings),
        config=config,
        detectors=build_mode_detectors(settings, config, llm_detector=FakeLlm()),
        transport=upstream.transport(),
        sam=SamClient(api_key="test-key", transport=httpx.MockTransport(sam), max_retries=0),
        ocr=FakeOcr() if ocr == "fake" else ocr,  # type: ignore[arg-type]
    )
    return app


def messages_with(url: Any, text: str = "Mit látsz a képen? Teszt Elek kérdezi.") -> list:
    image_url = url if isinstance(url, dict) else {"url": url}
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": image_url},
            ],
        }
    ]


def forwarded_image(upstream: MockUpstream) -> Image.Image:
    url = upstream.bodies[0]["messages"][0]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")


def filled(img: Image.Image, box: Box) -> bool:
    crop = img.crop((box.x1, box.y1, box.x2 + 1, box.y2 + 1))
    return crop.getextrema() == ((0, 0), (0, 0), (0, 0))


@pytest.mark.parametrize("media", ["image/png", "image/jpeg"])
def test_inline_image_is_masked_before_forwarding(media: str) -> None:
    upstream, sam = MockUpstream(), Sam()
    data = png()
    if media == "image/jpeg":
        buf = io.BytesIO()
        Image.open(io.BytesIO(data)).save(buf, format="JPEG", quality=95)
        data = buf.getvalue()
    with TestClient(make_app(upstream, sam)) as http:
        response = http.post(
            "/v1/chat/completions",
            json={
                "model": "m",
                "messages": messages_with({"url": data_url(data, media), "detail": "high"}),
            },
        )
    assert response.status_code == 200, response.text
    assert len(upstream.requests) == 1
    img = forwarded_image(upstream)
    assert filled(img, FACE)
    assert filled(img, TAJ_BOX)
    part = upstream.bodies[0]["messages"][0]["content"][1]
    assert part["image_url"]["detail"] == "high"
    assert "Teszt Elek" not in upstream.requests[0].content.decode()  # text still masked too
    assert response.headers["X-PII-Guard-Images"] == "1"
    assert response.headers["X-PII-Guard-Image-Regions-Masked"] == "2"
    assert response.headers["X-PII-Guard-Image-OCR"] == "on"
    assert "face" in sam.prompts


def test_string_image_url_form_is_masked_too() -> None:
    upstream, sam = MockUpstream(), Sam()
    messages = [{"role": "user", "content": [{"type": "image_url", "image_url": data_url(png())}]}]
    with TestClient(make_app(upstream, sam)) as http:
        response = http.post("/v1/chat/completions", json={"model": "m", "messages": messages})
    assert response.status_code == 200, response.text
    url = upstream.bodies[0]["messages"][0]["content"][0]["image_url"]
    img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
    assert filled(img, FACE)


def test_without_ocr_the_image_is_refused_and_nothing_is_forwarded() -> None:
    """Fail closed (ADR 0006, LAB-1209): without OCR the TAJ on the card can't be found, so
    the request is refused with 503 instead of forwarding the card readable."""
    upstream, sam = MockUpstream(), Sam()
    with TestClient(make_app(upstream, sam, ocr=None)) as http:
        response = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": messages_with(data_url(png()))}
        )
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "ocr_unavailable"
    assert upstream.requests == []
    assert sam.prompts == []


def test_tesseract_not_installed_refuses_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shipped-container case: the gateway picks its OCR engine itself and finds none."""
    import pii_guard.visual.masking as image_masking

    monkeypatch.setattr(image_masking, "tesseract_available", lambda: False)
    upstream = MockUpstream()
    settings = Settings(
        tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL, upstream_api_key=UPSTREAM_KEY
    )
    config = GatewayConfig(mode=Mode.AUDIT)
    app = create_app(settings)
    app.state.gateway = Gateway(
        settings=settings,
        vault=Vault.from_settings(settings),
        config=config,
        detectors=build_mode_detectors(settings, config, llm_detector=FakeLlm()),
        transport=upstream.transport(),
        sam=SamClient(api_key="test-key", transport=httpx.MockTransport(Sam()), max_retries=0),
    )
    with TestClient(app) as http:
        response = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": messages_with(data_url(png()))}
        )
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "ocr_unavailable"
    assert upstream.requests == []


def test_text_only_requests_need_no_ocr() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream, Sam(), ocr=None)) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": "Szia, Teszt Elek!"}]},
        )
    assert response.status_code == 200, response.text


def test_without_ocr_and_opted_out_header_says_off() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream, Sam(), ocr=None, require_ocr=False)) as http:
        response = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": messages_with(data_url(png()))}
        )
    assert response.status_code == 200
    assert response.headers["X-PII-Guard-Image-OCR"] == "off"
    assert filled(forwarded_image(upstream), FACE)
    assert not filled(forwarded_image(upstream), TAJ_BOX)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/card.png",
        "http://127.0.0.1:8080/internal.png",
        "file:///etc/passwd",
        "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
        "data:image/png,not-base64-flagged",
    ],
)
def test_remote_or_unsupported_image_urls_are_rejected(url: str) -> None:
    upstream, sam = MockUpstream(), Sam()
    with TestClient(make_app(upstream, sam)) as http:
        response = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": messages_with(url)}
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_content"
    assert upstream.requests == [] and sam.prompts == []


def test_bad_base64_is_invalid_request() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream, Sam())) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": messages_with("data:image/png;base64,%%%")},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert upstream.requests == []


def test_sam_failure_blocks_the_request() -> None:
    upstream = MockUpstream()
    app = make_app(upstream, Sam(fail=True))
    with TestClient(app) as http:
        response = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": messages_with(data_url(png()))}
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "detection_failed"
    assert upstream.requests == []
    assert len(app.state.gateway.vault) == 0  # the new session was dropped


def test_block_policy_on_an_image_region_refuses_the_request() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream, Sam(), policy_overrides="FACE=block")) as http:
        response = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": messages_with(data_url(png()))}
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "blocked_entity"
    assert upstream.requests == []


def test_image_limits() -> None:
    upstream, sam = MockUpstream(), Sam()
    config = GatewayConfig(max_images=1, max_image_bytes=len(png()) + 10)
    two = messages_with(data_url(png()))
    two[0]["content"].append({"type": "image_url", "image_url": {"url": data_url(png())}})
    with TestClient(make_app(upstream, sam, config=config)) as http:
        too_many = http.post("/v1/chat/completions", json={"model": "m", "messages": two})
        assert too_many.status_code == 413
        small = GatewayConfig(max_images=1, max_image_bytes=100)
        http.app.state.gateway.config = small  # type: ignore[attr-defined]
        too_big = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": messages_with(data_url(png()))}
        )
        assert too_big.status_code == 413
    assert upstream.requests == [] and sam.prompts == []


def test_image_bodies_larger_than_the_text_limit_are_accepted() -> None:
    upstream = MockUpstream()
    app = make_app(upstream, Sam())
    app.state.max_text_chars = 50
    with TestClient(app) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": messages_with(data_url(png()), text="Szia")},
        )
    assert response.status_code == 200, response.text


def test_collect_texts_returns_image_slots_without_bytes_in_repr() -> None:
    body = {"model": "m", "messages": messages_with(data_url(png()))}
    collected = collect_texts(body)
    assert len(collected.images) == 1
    slot = collected.images[0]
    assert slot.data == png()
    assert "bytes=" in repr(slot) and "base64" not in repr(slot)
    slot.write("data:image/png;base64,AAAA")
    assert body["messages"][0]["content"][1]["image_url"]["url"] == "data:image/png;base64,AAAA"


def test_image_part_without_url_is_unsupported() -> None:
    with pytest.raises(UnsupportedContentError):
        collect_texts(
            {"model": "m", "messages": [{"role": "user", "content": [{"type": "image_url"}]}]}
        )
