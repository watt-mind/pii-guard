"""Inline images in hosted chat (LAB-1439) through the real ASGI app.

Opt-in by the operator; signed-in Google owners on their own connection only, never the
sponsored route; the same local pipeline (in-process fakes for the model work) and one-job
pool as ``/v1/mask/image``; a body limit sized for images; and an admission charge where each
image reserves a fixed provider input price, never its bytes as text tokens. Every image,
identity and value is synthetic (ADR 0005); the upstream is a mock transport.
"""

from __future__ import annotations

import base64
import io
import json
import random
import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway.service import UPSTREAM_PAYLOAD_LIMIT, check_upstream_payload
from pii_guard.hosted.images import IMAGE_ANNOTATION_BYTES, chat_body_limit, chat_image_charge
from pii_guard.hosted.quotas import QuotaLedger, QuotaLimits, upstream_payload_bound
from pii_guard.types import DetectionError, EntityType, PayloadTooLargeError
from pii_guard.visual import OcrWord
from pii_guard.visual.ocr import TesseractOcr
from pii_guard.visual.regions import Box, Region
from pii_guard.visual.segment import LocalSegmenter
from pii_guard.visual.segmenters import LocalSignatureSegmenter, SignatureDetector

ORIGIN = "https://guard.example"
TAJ_VALUE = "123 456 788"  # fictional, passes the checksum
W, H = 400, 260
FACE = Box(30, 40, 129, 169)
WORDS = [
    OcrWord("TAJ:", Box(160, 60, 199, 79), (0,)),
    OcrWord("123", Box(205, 60, 239, 79), (0,)),
    OcrWord("456", Box(245, 60, 279, 79), (0,)),
    OcrWord("788", Box(285, 60, 319, 79), (0,)),
]
MODEL = "muse-spark-1.3"


def auth(subject: str = "synthetic-one", **extra: str) -> dict[str, str]:
    encoded = base64.b64encode(
        json.dumps({"auth_typ": "google", "claims": [{"typ": "sub", "val": subject}]}).encode()
    ).decode()
    return {"x-ms-client-principal": encoded, "origin": ORIGIN, **extra}


def settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        **{
            "hosted": True,
            "hosted_public_origin": ORIGIN,
            "hosted_trust_easy_auth": True,
            "hosted_single_process": True,
            "tenant_key": bytes(range(32)).hex(),
            "allowed_hosts": ("guard.example",),
            "detectors": ("rules",),
            "ner_fallback": "off",
            "upstream_api_key": "synthetic-sponsored-key",
            "hosted_chat_images": True,
            **overrides,
        },
    )


def card() -> bytes:
    image = Image.new("RGB", (W, H), (230, 236, 248))
    draw = ImageDraw.Draw(image)
    draw.ellipse(FACE.to_list(), fill=(240, 200, 170))
    draw.text((160, 60), f"TAJ: {TAJ_VALUE}", fill="black")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def data_url(data: bytes | None = None) -> str:
    return "data:image/png;base64," + base64.b64encode(card() if data is None else data).decode()


class Calls:
    def __init__(self) -> None:
        self.ocr = 0


def local_pipeline(app: FastAPI, calls: Calls) -> None:
    """The real hosted component types, with their model work replaced in-process."""
    faces = LocalSegmenter(detector=object())

    def segment(image: bytes, entity_types: Any = None) -> list[Region]:
        return [Region(EntityType.FACE, FACE, 0.9, "yunet")]

    def words(image: Image.Image) -> list[OcrWord]:
        calls.ocr += 1
        return list(WORDS)

    faces.segment = segment  # type: ignore[method-assign]
    segmenter = LocalSignatureSegmenter(
        faces, signatures=lambda: SignatureDetector(boxes=lambda i: [])
    )
    ocr = TesseractOcr()
    ocr.read = None  # type: ignore[assignment,method-assign]
    ocr.words = words  # type: ignore[method-assign]
    app.state.sam_client = segmenter
    app.state.ocr_engine = ocr


def _reply(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/responses"):
        return httpx.Response(
            200,
            json={
                "id": "synthetic-response",
                "object": "response",
                "status": "completed",
                "model": MODEL,
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Seen."}],
                    }
                ],
            },
        )
    return httpx.Response(
        200,
        json={
            "id": "synthetic-completion",
            "object": "chat.completion",
            "model": MODEL,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Seen."}}],
        },
    )


Hosted = tuple[TestClient, list[httpx.Request], Calls]


def _client(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> Iterator[Hosted]:
    seen: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _reply(request)

    monkeypatch.setattr(
        "pii_guard.hosted.runtime.SecureTransport", lambda: httpx.MockTransport(upstream)
    )
    app = create_app(settings(**overrides))
    app.state.hosted.quotas = QuotaLedger(
        QuotaLimits(global_daily_microdollars=1_000_000_000),
        sponsored_allocation_microdollars=1_000_000_000,
        allocation_expires_at=time.time() + 3600,
        claim_allocation=lambda: True,
    )
    calls = Calls()
    local_pipeline(app, calls)
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, seen, calls


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch) -> Iterator[Hosted]:
    yield from _client(monkeypatch)


def connect(client: TestClient, subject: str = "synthetic-one") -> dict[str, str]:
    async def validated(url: str) -> str:
        return url

    client.app.state.hosted.connections._validator = validated
    created = client.post(
        "/v1/account/connections",
        json={
            "provider": "custom",
            "api_key": "synthetic-own-upstream-key",
            "base_url": "https://provider.example/v1",
        },
        headers=auth(subject),
    )
    assert created.status_code == 201, created.text
    return auth(subject, **{"x-pii-guard-connection": created.json()["id"]})


def chat_body(*urls: str, text: str = "What is on this card?") -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    parts += [{"type": "image_url", "image_url": {"url": url}} for url in urls]
    return {"model": MODEL, "messages": [{"role": "user", "content": parts}]}


def usage(client: TestClient) -> Any:
    users = list(client.app.state.hosted.quotas._users.values())
    assert len(users) == 1
    return users[0]


def noisy_card() -> bytes:
    """The same card with incompressible noise in a corner: a much larger PNG."""
    image = Image.open(io.BytesIO(card())).convert("RGB")
    noise = Image.frombytes("RGB", (200, 120), random.Random(7).randbytes(200 * 120 * 3))  # noqa: S311
    image.paste(noise, (190, 130))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_owner_connection_gets_a_masked_image_and_a_fixed_image_charge(hosted: Hosted) -> None:
    client, seen, calls = hosted
    headers = connect(client)
    before = usage(client).tokens
    body = chat_body(data_url())
    response = client.post("/v1/chat/completions", json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert calls.ocr == 1 and len(seen) == 1
    sent = json.loads(seen[0].content)
    parts = sent["messages"][-1]["content"]
    urls = [p["image_url"]["url"] for p in parts if p["type"] == "image_url"]
    assert len(urls) == 1 and urls[0] != body["messages"][0]["content"][1]["image_url"]["url"]
    assert urls[0].startswith("data:image/png;base64,")
    # The value in the image never leaves; its transcript is masked text after the image.
    assert TAJ_VALUE not in seen[0].content.decode()
    assert any(p["type"] == "text" and "[pii-guard: image 1" in p["text"] for p in parts)
    # One image counted; tokens are the text bound plus the image's fixed charge.
    used = usage(client)
    assert used.images == 1
    charged = used.tokens - before
    image_chars = len(base64.b64encode(card()))
    text = upstream_payload_bound(len(json.dumps(body).encode()) - image_chars)
    output = client.app.state.hosted.settings.hosted_max_output_tokens
    expected = text + IMAGE_ANNOTATION_BYTES + 16_384 + output
    # The middleware adds the output field before measuring: a few bytes, twice.
    assert expected - 512 < charged <= expected + 512
    # A much larger image costs the same: its bytes are never charged as text tokens.
    large = noisy_card()
    assert len(large) > 20 * len(card())
    again = client.post("/v1/chat/completions", json=chat_body(data_url(large)), headers=headers)
    assert again.status_code == 200, again.text
    assert abs((usage(client).tokens - before - charged) - charged) < 512


def test_responses_input_image_works_the_same(hosted: Hosted) -> None:
    client, seen, calls = hosted
    headers = connect(client)
    body = {
        "model": MODEL,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Describe it."},
                    {"type": "input_image", "image_url": data_url()},
                ],
            }
        ],
    }
    response = client.post("/v1/responses", json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert calls.ocr == 1 and len(seen) == 1
    assert TAJ_VALUE not in seen[0].content.decode()
    assert usage(client).images == 1


def test_sponsored_route_refuses_images_before_any_work(hosted: Hosted) -> None:
    client, seen, calls = hosted
    response = client.post("/v1/chat/completions", json=chat_body(data_url()), headers=auth())
    assert response.status_code == 403
    assert "own connection" in response.json()["error"]["message"]
    assert calls.ocr == 0 and not seen
    assert client.app.state.hosted.quotas._users == {}


def test_more_images_than_allowed_refused_before_admission(hosted: Hosted) -> None:
    client, seen, calls = hosted
    headers = connect(client)
    response = client.post(
        "/v1/chat/completions", json=chat_body(data_url(), data_url()), headers=headers
    )
    assert response.status_code == 403
    assert "at most 1 inline images" in response.json()["error"]["message"]
    assert calls.ocr == 0 and not seen


def test_text_only_body_keeps_the_text_limit(hosted: Hosted) -> None:
    client, seen, _ = hosted
    headers = connect(client)
    limit = client.app.state.hosted.settings.hosted_max_body_bytes
    body = chat_body(text="x" * (limit + 10))
    response = client.post("/v1/chat/completions", json=body, headers=headers)
    assert response.status_code == 403
    assert "too large" in response.json()["error"]["message"]
    assert not seen


def test_tiny_image_does_not_lift_the_text_limit(hosted: Hosted) -> None:
    client, seen, calls = hosted
    headers = connect(client)
    limit = client.app.state.hosted.settings.hosted_max_body_bytes
    pixel = io.BytesIO()
    Image.new("RGB", (1, 1)).save(pixel, format="PNG")
    body = chat_body(data_url(pixel.getvalue()), text="x" * (limit + 10))
    assert len(json.dumps(body)) < chat_body_limit(client.app.state.hosted.settings)
    response = client.post("/v1/chat/completions", json=body, headers=headers)
    assert response.status_code == 403
    assert "too large" in response.json()["error"]["message"]
    assert calls.ocr == 0 and not seen
    assert all(u.images == 0 for u in client.app.state.hosted.quotas._users.values())


def test_ocr_unavailable_refuses_before_forwarding(hosted: Hosted) -> None:
    client, seen, calls = hosted
    headers = connect(client)
    client.app.state.ocr_engine = None
    response = client.post("/v1/chat/completions", json=chat_body(data_url()), headers=headers)
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "ocr_unavailable"
    assert calls.ocr == 0 and not seen


@pytest.mark.parametrize(
    ("segmenter", "code"),
    [("missing", "detection_failed"), ("not-local", "detection_profile_denied")],
)
def test_missing_segmenter_refuses_before_forwarding(
    hosted: Hosted, monkeypatch: pytest.MonkeyPatch, segmenter: str, code: str
) -> None:
    client, seen, calls = hosted
    headers = connect(client)
    if segmenter == "missing":
        # No segmenter on the app, and the on-device one cannot be built (no face model).
        client.app.state.sam_client = None

        def unbuildable(*args: Any, **kwargs: Any) -> Any:
            raise DetectionError("the on-device face model is not installed")

        monkeypatch.setattr("pii_guard.hosted.images.build_segmenter", unbuildable)
    else:
        client.app.state.sam_client = object()
    response = client.post("/v1/chat/completions", json=chat_body(data_url()), headers=headers)
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == code
    assert calls.ocr == 0 and not seen


def test_image_pipeline_timeout_refuses_before_forwarding(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, seen, calls in _client(monkeypatch, hosted_image_timeout=0.2):
        headers = connect(client)
        release = threading.Event()
        ocr = client.app.state.ocr_engine

        def stuck(
            image: Image.Image, calls: Calls = calls, release: threading.Event = release
        ) -> list[OcrWord]:
            calls.ocr += 1
            release.wait(10)
            return list(WORDS)

        ocr.words = stuck  # type: ignore[method-assign]
        try:
            response = client.post(
                "/v1/chat/completions", json=chat_body(data_url()), headers=headers
            )
        finally:
            release.set()
        assert response.status_code == 503, response.text
        assert response.json()["error"]["code"] == "detection_failed"
        assert "timed out" in response.json()["error"]["message"]
        assert calls.ocr == 1 and not seen


def test_body_beyond_the_image_limit_refused(hosted: Hosted) -> None:
    client, seen, calls = hosted
    headers = connect(client)
    limit = chat_body_limit(client.app.state.hosted.settings)
    body = chat_body(data_url(b"\x89PNG" + b"0" * limit))
    response = client.post("/v1/chat/completions", json=body, headers=headers)
    assert response.status_code == 403
    assert calls.ocr == 0 and not seen


def test_daily_image_count_applies_to_chat(hosted: Hosted) -> None:
    client, seen, calls = hosted
    headers = connect(client)
    quotas = client.app.state.hosted.quotas
    quotas.limits = QuotaLimits(global_daily_microdollars=1_000_000_000, user_images=1)
    assert (
        client.post("/v1/chat/completions", json=chat_body(data_url()), headers=headers)
    ).status_code == 200
    second = client.post("/v1/chat/completions", json=chat_body(data_url()), headers=headers)
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "quota_exceeded"
    assert calls.ocr == 1 and len(seen) == 1


def test_busy_image_slot_is_429_and_charges_nothing(hosted: Hosted) -> None:
    client, seen, calls = hosted
    headers = connect(client)
    workers = client.app.state.hosted.image_workers
    release = threading.Event()
    started = threading.Event()

    def hold() -> None:
        started.set()
        release.wait(10)

    import asyncio

    loop = asyncio.new_event_loop()
    task = threading.Thread(target=lambda: loop.run_until_complete(workers.run(hold)))
    task.start()
    try:
        assert started.wait(5)
        response = client.post("/v1/chat/completions", json=chat_body(data_url()), headers=headers)
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "hosted_capacity"
        assert calls.ocr == 0 and not seen
        assert all(u.images == 0 for u in client.app.state.hosted.quotas._users.values())
    finally:
        release.set()
        task.join(10)
        loop.close()


def test_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, seen, calls in _client(monkeypatch, hosted_chat_images=False):
        headers = connect(client)
        response = client.post("/v1/chat/completions", json=chat_body(data_url()), headers=headers)
        assert response.status_code in {403, 413}
        assert calls.ocr == 0 and not seen


def test_guard_api_key_cannot_send_chat_images(hosted: Hosted) -> None:
    client, seen, calls = hosted
    headers = connect(client)
    created = client.post("/v1/account/api-keys", json={"name": "synthetic"}, headers=auth())
    assert created.status_code == 201, created.text
    key = created.json()["key"]
    keyed = {
        "authorization": f"Bearer {key}",
        "x-pii-guard-connection": headers["x-pii-guard-connection"],
    }
    response = client.post("/v1/chat/completions", json=chat_body(data_url()), headers=keyed)
    assert response.status_code in {403, 413}
    assert calls.ocr == 0 and not seen


def test_gateway_payload_check_leaves_masked_image_bytes_out() -> None:
    token = UPSTREAM_PAYLOAD_LIMIT.set(100)
    try:
        check_upstream_payload(b"x" * 1000, image_bytes=950)
        with pytest.raises(PayloadTooLargeError):
            check_upstream_payload(b"x" * 1000, image_bytes=850)
        with pytest.raises(PayloadTooLargeError):
            check_upstream_payload(b"x" * 1000, image_bytes=-5000)
    finally:
        UPSTREAM_PAYLOAD_LIMIT.reset(token)


def test_image_charge_is_fixed_per_image() -> None:
    config = settings(hosted_image_input_tokens=20_000)
    charge = chat_image_charge(config, 2, 5_000)
    assert charge.payload_bytes == 5_000 + 2 * IMAGE_ANNOTATION_BYTES
    assert charge.input_tokens == charge.payload_bytes + 40_000
    assert chat_body_limit(config) > config.hosted_max_body_bytes
