"""``POST /v1/mask/image`` with a mock SAM transport and a fake OCR engine.

Everything is synthetic (ADR 0005): the image is drawn with Pillow (an ellipse face, a
scribble), the identifiers are fictional, and SAM answers come from an ``httpx.MockTransport``
in the observed Meta Responses API format. Nothing leaves the process.
"""

from __future__ import annotations

import base64
import io
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from api_helpers import TEST_TENANT_KEY
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from pii_guard.api.app import create_app
from pii_guard.api.routes.image_masking import (
    ImageMasker,
    _grow_face,
    decode_base64_image,
    sniff_media_type,
)
from pii_guard.config import Settings
from pii_guard.policy import PolicySet
from pii_guard.types import DetectionError, EntityType
from pii_guard.visual import OcrWord, SamClient
from pii_guard.visual.regions import Box

W, H = 400, 260
FACE = Box(30, 40, 129, 169)
SIGNATURE = Box(200, 190, 369, 229)
HANDWRITING = Box(205, 185, 372, 232)  # mostly the same scribble: merged with SIGNATURE
STAMP = Box(300, 20, 379, 99)
TAJ_VALUE = "123 456 788"  # fictional, passes the checksum
NAME_VALUE = "Teszt Elek"
FAKE_KEY = "test-key-not-a-secret"

TAJ_WORDS = [
    OcrWord("TAJ:", Box(160, 60, 199, 79), (0,)),
    OcrWord("123", Box(205, 60, 239, 79), (0,)),
    OcrWord("456", Box(245, 60, 279, 79), (0,)),
    OcrWord("788", Box(285, 60, 319, 79), (0,)),
    OcrWord("Teszt", Box(160, 100, 214, 119), (1,)),
    OcrWord("Elek", Box(220, 100, 259, 119), (1,)),
]
TAJ_BOX = Box(205, 60, 319, 79)
# SAM's face box is grown (hair, ears) before masking: (30, 40, 129, 169) -> this.
FACE_COVERED = Box(20, 0, 139, 175)


def card_image(fmt: str = "PNG") -> bytes:
    img = Image.new("RGB", (W, H), (230, 236, 248))
    d = ImageDraw.Draw(img)
    d.ellipse(FACE.to_list(), fill=(240, 200, 170))
    d.text((160, 60), f"TAJ: {TAJ_VALUE}", fill="black")
    d.text((160, 100), NAME_VALUE, fill="black")
    d.line([(205, 210), (250, 195), (300, 225), (365, 200)], fill=(10, 20, 120), width=3)
    d.ellipse(STAMP.to_list(), outline=(150, 30, 60), width=3)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def sam_text(*boxes: Box) -> str:
    objects = [
        f"{i}<|box;x1={b.x1};y1={b.y1};x2={b.x2};y2={b.y2};w={W};h={H}|>"
        for i, b in enumerate(boxes)
    ]
    return "<0f>" + ",".join(objects) if objects else ""


def sam_response(text: str) -> dict[str, Any]:
    return {
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
    }


class SamStub:
    """Answers per concept prompt; records the prompts it was asked."""

    def __init__(self, by_prompt: dict[str, Any] | None = None) -> None:
        self.by_prompt = (
            by_prompt
            if by_prompt is not None
            else {
                "face": sam_text(FACE),
                "signature": sam_text(SIGNATURE),
                "squiggly line": sam_text(HANDWRITING),
                "stamp": sam_text(STAMP),
            }
        )
        self.prompts: list[str] = []
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        prompt = body["input"][0]["content"][0]["text"]
        self.prompts.append(prompt)
        answer = self.by_prompt.get(prompt, "")
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=sam_response(answer))

    def client(self, **kwargs: Any) -> SamClient:
        kwargs.setdefault("api_key", FAKE_KEY)
        return SamClient(transport=httpx.MockTransport(self), max_retries=0, **kwargs)


class FakeOcr:
    name = "fake-ocr"

    def __init__(self, words: list[OcrWord] | None = None, error: Exception | None = None):
        self.words_ = TAJ_WORDS if words is None else words
        self.error = error
        self.calls = 0

    def words(self, image: Image.Image) -> list[OcrWord]:
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.words_)


def make_app(
    *,
    sam: SamStub | None = None,
    ocr: object = "fake",
    policy_overrides: str | None = None,
    **state: Any,
) -> FastAPI:
    settings = Settings(tenant_key=TEST_TENANT_KEY, policy_overrides=policy_overrides)
    app = create_app(settings)
    app.state.sam_client = (sam or SamStub()).client()
    app.state.ocr_engine = FakeOcr() if ocr == "fake" else ocr
    for key, value in state.items():
        setattr(app.state, key, value)
    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(make_app(), raise_server_exceptions=False) as http:
        yield http


def post_png(http: TestClient, data: bytes | None = None, **kwargs: Any) -> httpx.Response:
    return http.post(
        "/v1/mask/image",
        content=card_image() if data is None else data,
        headers={"Content-Type": "image/png"},
        **kwargs,
    )


def decode(body: dict[str, Any]) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(body["image"]))).convert("RGB")


def is_filled(img: Image.Image, box: Box) -> bool:
    """Every pixel inside ``box`` is the solid fill (black)."""
    crop = img.crop((box.x1, box.y1, box.x2 + 1, box.y2 + 1))
    return crop.getextrema() == ((0, 0), (0, 0), (0, 0))


# --- happy path --------------------------------------------------------------------------


def test_raw_png_upload_masks_sam_and_ocr_regions(client: TestClient) -> None:
    response = post_png(client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["media_type"] == "image/png"
    assert (body["width"], body["height"]) == (W, H)
    masked = decode(body)
    assert masked.size == (W, H)
    assert is_filled(masked, FACE)
    assert is_filled(masked, SIGNATURE)
    assert is_filled(masked, TAJ_BOX)
    assert not is_filled(masked, STAMP)  # STAMP is keep by default: reported, left visible

    by_type = {r["entity_type"]: r for r in body["regions"]}
    assert is_filled(masked, FACE_COVERED)
    assert by_type["FACE"] == {
        "entity_type": "FACE",
        "box": FACE_COVERED.to_list(),
        "source": "sam",
        "detector": "sam",
        "score": None,
        "policy": "mask",
    }
    assert by_type["NATIONAL_ID_HU_TAJ"]["source"] == "ocr"
    assert by_type["NATIONAL_ID_HU_TAJ"]["detector"] == "rules"
    assert by_type["NATIONAL_ID_HU_TAJ"]["box"] == TAJ_BOX.to_list()
    assert by_type["STAMP"]["policy"] == "keep"
    # "signature" and "squiggly line" prompts found the same scribble: one merged region, the union.
    signatures = [r for r in body["regions"] if r["entity_type"] == "SIGNATURE"]
    assert len(signatures) == 1
    assert signatures[0]["box"] == SIGNATURE.union(HANDWRITING).to_list()

    assert {m["entity_type"]: m["count"] for m in body["masked"]} == {
        "FACE": 1,
        "NATIONAL_ID_HU_TAJ": 1,
        "SIGNATURE": 1,
    }
    assert body["kept"] == [{"entity_type": "STAMP", "count": 1}]
    assert body["analysis"] == {
        "sam": {"model": "sam-3.1", "entity_types": ["FACE", "SIGNATURE", "ID_PHOTO", "STAMP"]},
        "ocr": {
            "ran": True,
            "engine": "fake-ocr",
            "detectors": ["rules"],
            "models": {},
            "reason": None,
        },
    }


def test_response_never_contains_values(client: TestClient) -> None:
    raw = post_png(client).text
    for value in (TAJ_VALUE, "123456788", NAME_VALUE, "Teszt"):
        assert value not in raw


def test_one_sam_request_per_prompt_with_store_false() -> None:
    sam = SamStub()
    with TestClient(make_app(sam=sam)) as http:
        assert post_png(http).status_code == 200
    expected = ["face", "signature", "squiggly line", "id photo", "stamp"]
    assert sorted(sam.prompts) == sorted(expected)
    assert all(body["store"] is False for body in sam.bodies)
    assert all(body["model"] == "sam-3.1" for body in sam.bodies)


@pytest.mark.parametrize("data_url", [False, True])
def test_json_base64_body(client: TestClient, data_url: bool) -> None:
    encoded = base64.b64encode(card_image()).decode()
    if data_url:
        encoded = "data:image/png;base64," + encoded
    response = client.post("/v1/mask/image", json={"image": encoded, "language": "hu"})
    assert response.status_code == 200, response.text
    assert is_filled(decode(response.json()), FACE)


def test_jpeg_input_returns_png(client: TestClient) -> None:
    response = client.post(
        "/v1/mask/image", content=card_image("JPEG"), headers={"Content-Type": "image/jpeg"}
    )
    assert response.status_code == 200, response.text
    assert base64.b64decode(response.json()["image"]).startswith(b"\x89PNG")


def test_output_is_reencoded_without_metadata(client: TestClient) -> None:
    img = Image.open(io.BytesIO(card_image()))
    buf = io.BytesIO()
    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "fictional-secret-marker")
    img.save(buf, format="PNG", pnginfo=info)
    response = post_png(client, buf.getvalue())
    assert response.status_code == 200
    assert b"fictional-secret-marker" not in base64.b64decode(response.json()["image"])


def test_without_ocr_only_sam_runs_and_the_response_says_so() -> None:
    with TestClient(make_app(ocr=None)) as http:
        body = post_png(http).json()
    assert body["analysis"]["ocr"] == {
        "ran": False,
        "engine": None,
        "detectors": [],
        "models": {},
        "reason": "tesseract_unavailable",
    }
    assert {r["source"] for r in body["regions"]} == {"sam"}
    assert not is_filled(decode(body), TAJ_BOX)


def test_nothing_found_returns_the_same_pixels() -> None:
    with TestClient(make_app(sam=SamStub({}), ocr=FakeOcr(words=[]))) as http:
        body = post_png(http).json()
    assert body["regions"] == [] and body["masked"] == [] and body["kept"] == []
    original = Image.open(io.BytesIO(card_image())).convert("RGB")
    assert decode(body).tobytes() == original.tobytes()


# --- policies ----------------------------------------------------------------------------


def test_keep_override_leaves_faces_visible_and_reports_them() -> None:
    with TestClient(make_app(policy_overrides="FACE=keep")) as http:
        body = post_png(http).json()
    face = next(r for r in body["regions"] if r["entity_type"] == "FACE")
    assert face["policy"] == "keep"
    assert not is_filled(decode(body), FACE)
    assert {"entity_type": "FACE", "count": 1} in body["kept"]


def test_stamp_mask_override_fills_the_stamp() -> None:
    with TestClient(make_app(policy_overrides="STAMP=mask")) as http:
        body = post_png(http).json()
    assert is_filled(decode(body), STAMP)


@pytest.mark.parametrize("override", ["FACE=block", "NATIONAL_ID_HU_TAJ=block"])
def test_block_policy_refuses_the_image(override: str) -> None:
    with TestClient(make_app(policy_overrides=override), raise_server_exceptions=False) as http:
        response = post_png(http)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "blocked_entity"
    assert "image" not in body


# --- fail closed -------------------------------------------------------------------------


def _assert_failed_closed(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert TAJ_VALUE not in response.text and NAME_VALUE not in response.text


@pytest.mark.parametrize(
    "answer",
    [httpx.Response(500), httpx.Response(401), "<0f>garbage that is not a SAM object"],
)
def test_sam_failure_is_503(answer: Any) -> None:
    sam = SamStub({"face": answer})
    with TestClient(make_app(sam=sam), raise_server_exceptions=False) as http:
        _assert_failed_closed(post_png(http), 503, "detection_failed")


def test_sam_without_key_is_503() -> None:
    app = make_app()
    app.state.sam_client = SamClient(
        api_key="", transport=httpx.MockTransport(SamStub()), settings=Settings()
    )
    with TestClient(app, raise_server_exceptions=False) as http:
        _assert_failed_closed(post_png(http), 503, "detection_failed")


def test_ocr_failure_is_503() -> None:
    ocr = FakeOcr(error=RuntimeError(f"tesseract crashed reading {NAME_VALUE}"))
    with TestClient(make_app(ocr=ocr), raise_server_exceptions=False) as http:
        _assert_failed_closed(post_png(http), 503, "detection_failed")


def test_text_detector_failure_is_503() -> None:
    class Crash:
        def analyze(self, text: str, language: str) -> list:
            raise DetectionError("llm detector timed out")

    with TestClient(make_app(analyzer=Crash()), raise_server_exceptions=False) as http:
        _assert_failed_closed(post_png(http), 503, "detection_failed")


@pytest.mark.parametrize(
    ("content", "content_type", "status", "code"),
    [
        (b"GIF89a" + b"\x00" * 32, "image/png", 415, "unsupported_media_type"),
        (b"just text", "text/plain", 415, "unsupported_media_type"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png", 422, "invalid_image"),
        (b"", "image/png", 422, "invalid_image"),
        (b"{not json", "application/json", 422, "invalid_image"),
        (b'{"image": "%%%"}', "application/json", 422, "invalid_image"),
        (b'{"img": "AAAA"}', "application/json", 422, "invalid_image"),
        (b'{"image": "data:image/png,AAAA"}', "application/json", 422, "invalid_image"),
    ],
)
def test_bad_input_is_rejected_before_detection(
    content: bytes, content_type: str, status: int, code: str
) -> None:
    sam = SamStub()
    with TestClient(make_app(sam=sam), raise_server_exceptions=False) as http:
        response = http.post(
            "/v1/mask/image", content=content, headers={"Content-Type": content_type}
        )
    _assert_failed_closed(response, status, code)
    assert sam.prompts == []


def test_image_over_the_limit_is_413() -> None:
    sam = SamStub()
    app = make_app(sam=sam, max_image_bytes=1024)
    with TestClient(app, raise_server_exceptions=False) as http:
        raw = post_png(http)
        encoded = http.post(
            "/v1/mask/image", json={"image": base64.b64encode(card_image()).decode()}
        )
    _assert_failed_closed(raw, 413, "payload_too_large")
    _assert_failed_closed(encoded, 413, "payload_too_large")
    assert sam.prompts == []


def test_image_larger_than_the_text_limit_is_accepted() -> None:
    # The text body limit is ~2.4 MB at defaults; images get their own limit.
    with TestClient(make_app(max_text_chars=10)) as http:
        assert post_png(http).status_code == 200


def test_language_query_parameter_is_validated(client: TestClient) -> None:
    assert post_png(client, params={"language": "en"}).status_code == 200
    assert post_png(client, params={"language": "x"}).status_code == 422


# --- units -------------------------------------------------------------------------------


def test_sniff_and_decode_helpers() -> None:
    assert sniff_media_type(card_image()) == "image/png"
    assert sniff_media_type(card_image("JPEG")) == "image/jpeg"
    data = card_image()
    assert decode_base64_image(base64.b64encode(data).decode()) == data
    assert decode_base64_image("data:image/png;base64," + base64.b64encode(data).decode()) == data


def test_image_masker_validates_its_configuration() -> None:
    sam = SamStub().client()
    with pytest.raises(ValueError):
        ImageMasker(sam=sam, policies=PolicySet(), ocr=FakeOcr())
    with pytest.raises(ValueError):
        ImageMasker(sam=sam, policies=PolicySet(), entity_types=[])
    masker = ImageMasker(sam=sam, policies=PolicySet(), entity_types=[EntityType.FACE])
    assert "ImageMasker(" in repr(masker)
    outcome = masker.mask(card_image())
    assert [r.entity_type for r in outcome.regions] == [EntityType.FACE]
    assert "bytes" in repr(outcome) and TAJ_VALUE not in repr(outcome)


def test_face_boxes_grow_to_cover_hair_and_ears_clamped_to_the_image() -> None:
    from pii_guard.visual import Region

    grown = _grow_face(Region(EntityType.FACE, Box(100, 100, 199, 199), None, "sam"), 400, 260)
    assert grown.box == Box(90, 60, 209, 204)
    edge = _grow_face(Region(EntityType.FACE, Box(0, 5, 99, 255), None, "sam"), 400, 260)
    assert edge.box == Box(0, 0, 109, 259)
    other = Region(EntityType.SIGNATURE, Box(1, 1, 5, 5), None, "sam")
    assert _grow_face(other, 400, 260) is other


def test_model_backed_detectors_are_reported_for_labels() -> None:
    class Llm:
        name = "llm"
        model = "muse-spark-1.3"

    class Analyzer:
        def __init__(self) -> None:
            self.detectors = [Llm()]

        def analyze(self, text: str, language: str) -> list:
            return []

    with TestClient(make_app(analyzer=Analyzer())) as http:
        body = post_png(http).json()
    assert body["analysis"]["ocr"]["models"] == {"llm": "muse-spark-1.3"}
