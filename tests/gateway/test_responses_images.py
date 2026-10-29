"""Gateway ``/v1/responses``: inline ``input_image`` parts are masked like chat images (LAB-1285).

The request shape is the one Muse Code sends for ``muse exec --image <PATH>`` (captured against
a local recording server): the image between ``<image ...>`` / ``</image>`` text parts, as a
string ``image_url`` data URL with ``detail``. Synthetic only (ADR 0005): the Pillow-drawn
fictional card, SAM and OCR fakes and the mock upstream of ``test_image_parts``.
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
from gateway_helpers import TEST_TENANT_KEY, UPSTREAM_KEY, UPSTREAM_URL, FakeLlm
from PIL import Image
from test_image_parts import FACE, TAJ_BOX, TAJ_VALUE, FakeOcr, Sam, data_url, filled, png
from test_responses import ResponsesUpstream

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway import Gateway, GatewayConfig, Mode, build_mode_detectors
from pii_guard.gateway.request import UnsupportedContentError
from pii_guard.gateway.responses_request import collect_response_texts
from pii_guard.vault import Vault
from pii_guard.visual import SamClient

NAME = "Teszt Elek"  # fictional


def make_app(
    upstream: ResponsesUpstream,
    sam: Sam,
    *,
    ocr: object = "fake",
    render: str = "opaque",
    config: GatewayConfig | None = None,
) -> FastAPI:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
        image_render=render,  # type: ignore[arg-type]
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


def image_part(url: str, **extra: Any) -> dict[str, Any]:
    return {"type": "input_image", "image_url": url, "detail": "high", **extra}


def muse_image_body(part: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """What Muse Code sends for ``muse exec --image card.png "<prompt>"``."""
    return {
        "model": "test-model",
        "store": False,
        "stream": False,
        "instructions": "You are a coding agent.",
        "input": [
            {"type": "message", "role": "developer", "content": "Follow the rules."},
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": '<image name=[Image #1] path="card.png">'},
                    part or image_part(data_url(png())),
                    {"type": "input_text", "text": "</image>"},
                    {"type": "input_text", "text": f"[Image #1] What is on it? {NAME} asks."},
                ],
            },
        ],
        **extra,
    }


def decoded(url: str) -> Image.Image:
    assert url.startswith("data:image/png;base64,")
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")


def post(app: FastAPI, body: dict[str, Any]) -> httpx.Response:
    with TestClient(app) as http:
        return http.post("/v1/responses", json=body)


@pytest.mark.parametrize("media", ["image/png", "image/jpeg"])
def test_muse_image_is_masked_before_forwarding(media: str) -> None:
    upstream, sam = ResponsesUpstream(), Sam()
    data = png()
    if media == "image/jpeg":
        buf = io.BytesIO()
        Image.open(io.BytesIO(data)).save(buf, format="JPEG", quality=95)
        data = buf.getvalue()
    response = post(make_app(upstream, sam), muse_image_body(image_part(data_url(data, media))))
    assert response.status_code == 200, response.text
    assert len(upstream.requests) == 1
    forwarded = upstream.bodies[0]
    parts = forwarded["input"][1]["content"]
    assert [p["type"] for p in parts] == ["input_text", "input_image", "input_text", "input_text"]
    assert parts[1]["detail"] == "high"
    img = decoded(parts[1]["image_url"])
    assert filled(img, FACE) and filled(img, TAJ_BOX)
    raw = upstream.requests[0].content.decode()
    assert NAME not in raw  # the texts are still masked
    assert response.headers["X-PII-Guard-Images"] == "1"
    assert response.headers["X-PII-Guard-Image-Regions-Masked"] == "2"
    assert response.headers["X-PII-Guard-Image-OCR"] == "on"
    assert "face" in sam.prompts
    # The answer echoes every placeholder the upstream saw; the client gets the values back.
    assert NAME in response.text


def test_labels_add_the_masked_transcript_as_an_input_text_part() -> None:
    upstream = ResponsesUpstream()
    response = post(make_app(upstream, Sam(), render="labels"), muse_image_body())
    assert response.status_code == 200, response.text
    parts = upstream.bodies[0]["input"][1]["content"]
    types = [p["type"] for p in parts]
    assert types == ["input_text", "input_image", "input_text", "input_text", "input_text"]
    transcript = parts[2]["text"]
    assert "TAJ:" in transcript
    assert TAJ_VALUE not in json.dumps(upstream.bodies[0], ensure_ascii=False)
    assert parts[3]["text"] == "</image>"


def test_image_in_a_tool_output_is_masked() -> None:
    upstream = ResponsesUpstream()
    body = muse_image_body()
    body["input"].extend(
        [
            {"type": "function_call", "call_id": "call_1", "name": "view_image", "arguments": "{}"},
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": [image_part(data_url(png()))],
            },
        ]
    )
    response = post(make_app(upstream, Sam()), body)
    assert response.status_code == 200, response.text
    assert response.headers["X-PII-Guard-Images"] == "2"
    output = upstream.bodies[0]["input"][3]["output"]
    assert filled(decoded(output[0]["image_url"]), TAJ_BOX)


def test_without_ocr_the_image_is_refused_and_nothing_is_forwarded() -> None:
    upstream, sam = ResponsesUpstream(), Sam()
    response = post(make_app(upstream, sam, ocr=None), muse_image_body())
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "ocr_unavailable"
    assert upstream.requests == [] and sam.prompts == []


def test_sam_failure_blocks_the_request_and_drops_the_session() -> None:
    upstream = ResponsesUpstream()
    app = make_app(upstream, Sam(fail=True))
    response = post(app, muse_image_body())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "detection_failed"
    assert upstream.requests == []
    assert len(app.state.gateway.vault) == 0


def test_image_limits() -> None:
    upstream, sam = ResponsesUpstream(), Sam()
    two = muse_image_body()
    two["input"][1]["content"].append(image_part(data_url(png())))
    response = post(make_app(upstream, sam, config=GatewayConfig(max_images=1)), two)
    assert response.status_code == 413
    small = GatewayConfig(max_image_bytes=100)
    response = post(make_app(upstream, sam, config=small), muse_image_body())
    assert response.status_code == 413
    assert upstream.requests == [] and sam.prompts == []


@pytest.mark.parametrize(
    ("part", "fragment"),
    [
        (image_part("https://example.com/card.png"), "remote image URLs"),
        (image_part("http://127.0.0.1:8080/internal.png"), "remote image URLs"),
        (image_part("data:image/gif;base64,R0lGODlhAQABAAAAACw="), "PNG and JPEG"),
        ({"type": "input_image", "file_id": "file_0"}, "file_id"),
        (image_part(data_url(png()), file_id="file_0"), "file_id"),
        ({"type": "input_image", "image_url": {"url": data_url(png())}}, "inline data URL"),
        (image_part(data_url(png()), extra=1), "extra"),
        (image_part(data_url(b"GIF89a-not-a-png")), "not a PNG or JPEG"),
        ({"type": "input_file", "file_data": "data:application/pdf;base64,AAAA"}, "input_file"),
        ({"type": "input_audio", "input_audio": {"data": "AAAA", "format": "wav"}}, "input_audio"),
    ],
)
def test_unmaskable_media_is_rejected(part: dict[str, Any], fragment: str) -> None:
    with pytest.raises(UnsupportedContentError, match=fragment):
        collect_response_texts(muse_image_body(part))
    upstream, sam = ResponsesUpstream(), Sam()
    response = post(make_app(upstream, sam), muse_image_body(part))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_content"
    assert upstream.requests == [] and sam.prompts == []


def test_personal_data_in_detail_is_rejected() -> None:
    body = muse_image_body(image_part(data_url(png()), detail="jane.placeholder@example.com"))
    response = post(make_app(ResponsesUpstream(), Sam()), body)
    assert response.status_code == 400


def test_collect_queues_one_image_slot() -> None:
    collected = collect_response_texts(muse_image_body())
    assert len(collected.images) == 1
    assert collected.images[0].where == "input.1.content.1"
    assert collected.images[0].data == png()


def test_large_image_passes_the_responses_route_at_a_small_text_limit() -> None:
    # LAB-1566: /v1/responses uses the gateway route class, so a ~60 KB+ image body is
    # not 413'd by the text body limit before image validation (max_text_chars=1000).
    import random

    raw = random.Random(4711).randbytes(300 * 200 * 3)  # noqa: S311 - synthetic noise
    noisy = Image.frombytes("RGB", (300, 200), raw)
    buf = io.BytesIO()
    noisy.save(buf, format="PNG")
    data = buf.getvalue()
    assert len(data) > 60_000
    upstream, sam = ResponsesUpstream(), Sam()
    app = make_app(upstream, sam)
    app.state.max_text_chars = 1000
    response = post(app, muse_image_body(image_part(data_url(data))))
    assert response.status_code == 200, response.text
    assert len(upstream.requests) == 1  # reached the gateway and the upstream, not a 413
