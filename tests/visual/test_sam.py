"""SamClient against recorded SAM 3.1 responses (Meta Responses API, synthetic image only).

The fixtures in ``tests/fixtures/visual/`` are live responses to the synthetic ID card in
``visual_helpers.py``. The ``live`` test calls the real API and is skipped without
``META_API_KEY``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from visual_helpers import FACE_BOX, HEIGHT, WIDTH, id_card_png

from pii_guard.types import DetectionError, EntityType
from pii_guard.visual import Region, SamClient, parse_sam_output
from pii_guard.visual.sam import DEFAULT_BASE_URL, DEFAULT_MODEL

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "visual"
LIVE_KEY = os.environ.get("META_API_KEY")
FAKE_KEY = "test-key-not-a-secret"


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def fixture_text(name: str) -> str:
    return fixture(name)["output"][0]["content"][0]["text"]


class Recorder:
    """A mock transport that answers per prompt and records every request body."""

    def __init__(self, by_prompt: dict[str, Any] | None = None, default: Any = None) -> None:
        self.by_prompt = by_prompt or {}
        self.default = default if default is not None else fixture("sam_signature")
        self.requests: list[httpx.Request] = []

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        prompt = json.loads(request.content)["input"][0]["content"][0]["text"]
        answer = self.by_prompt.get(prompt, self.default)
        if isinstance(answer, httpx.Response):
            return answer
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(200, json=answer)

    def client(self, **kwargs: Any) -> SamClient:
        kwargs.setdefault("api_key", FAKE_KEY)
        return SamClient(transport=httpx.MockTransport(self), **kwargs)


# --- parsing the observed format ---------------------------------------------------------


def test_parse_face_fixture_matches_the_drawn_face() -> None:
    regions = parse_sam_output(fixture_text("sam_face"), EntityType.FACE, (WIDTH, HEIGHT))
    assert len(regions) == 1
    region = regions[0]
    assert region.entity_type is EntityType.FACE
    assert region.source == "sam"
    assert region.score is None
    box = region.box
    # SAM's box sits on the drawn ellipse within a couple of pixels.
    assert abs(box.x1 - FACE_BOX.x1) <= 3 and abs(box.y1 - FACE_BOX.y1) <= 3
    assert abs(box.x2 - FACE_BOX.x2) <= 3 and abs(box.y2 - FACE_BOX.y2) <= 3
    assert region.mask is not None
    assert (region.mask.height, region.mask.width) == (box.height, box.width)
    assert "data=<" in repr(region.mask)


def test_parse_multiple_objects() -> None:
    regions = parse_sam_output(fixture_text("sam_eye"), EntityType.FACE, (WIDTH, HEIGHT))
    assert [r.box.to_list() for r in regions] == [[95, 150, 110, 162], [130, 150, 145, 162]]


def test_parse_empty_output_means_nothing_found() -> None:
    assert fixture_text("sam_signature") == ""
    assert parse_sam_output("", EntityType.SIGNATURE, (WIDTH, HEIGHT)) == []
    assert parse_sam_output("\n", EntityType.SIGNATURE, (WIDTH, HEIGHT)) == []


def test_parse_rescales_when_api_reports_another_size() -> None:
    text = "<0f>0<|box;x1=10;y1=10;x2=19;y2=19;w=100;h=100|>"
    (region,) = parse_sam_output(text, EntityType.FACE, (200, 50))
    assert region.box.to_list() == [20, 5, 39, 9]
    assert region.mask is None


def test_parse_clips_to_image() -> None:
    text = "<0f>0<|box;x1=-5;y1=0;x2=700;y2=399;w=640;h=400|>"
    (region,) = parse_sam_output(text, EntityType.FACE, (WIDTH, HEIGHT))
    assert region.box.to_list() == [0, 0, 639, 399]


@pytest.mark.parametrize(
    "text",
    [
        "I found a face",
        "<0f>0<|box;x1=1;y1=2|>",
        "<0f>0<|box;x1=a;y1=2;x2=3;y2=4;w=10;h=10|>",
        "<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=0;h=10|>",
        "<0f>0<|box;x1=9;y1=2;x2=3;y2=4;w=10;h=10|>",
        "<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=10|> trailing junk",
        "<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=10|><|mask;x=0;y=0;data=garbage|>",
        "<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=10|><|mask;x=z;y=0;data=3,3,~!!!|>",
    ],
)
def test_parse_unexpected_format_fails_closed(text: str) -> None:
    with pytest.raises(DetectionError):
        parse_sam_output(text, EntityType.FACE, (WIDTH, HEIGHT))


# --- requests ----------------------------------------------------------------------------


def test_segment_sends_store_false_and_one_request_per_prompt() -> None:
    rec = Recorder({"face": fixture("sam_face")})
    regions = rec.client().segment(id_card_png())

    assert [r.entity_type for r in regions] == [EntityType.FACE]
    assert all(isinstance(r, Region) for r in regions)
    prompts = [b["input"][0]["content"][0]["text"] for b in rec.bodies]
    assert prompts == ["face", "signature", "squiggly line", "photo of a person"]
    for request, body in zip(rec.requests, rec.bodies, strict=True):
        assert body["store"] is False
        assert body["model"] == DEFAULT_MODEL
        assert str(request.url) == f"{DEFAULT_BASE_URL}/responses"
        assert request.headers["Authorization"] == f"Bearer {FAKE_KEY}"
        image_part = body["input"][0]["content"][1]
        assert image_part["type"] == "input_image"
        assert image_part["image_url"].startswith("data:image/png;base64,")


def test_segment_selected_types_and_custom_prompts() -> None:
    rec = Recorder({"eye": fixture("sam_eye")})
    client = rec.client(prompts={EntityType.FACE: ["eye"], EntityType.STAMP: ["stamp"]})
    regions = client.segment(id_card_png(), ["FACE", EntityType.STAMP])
    assert len(regions) == 2
    assert [b["input"][0]["content"][0]["text"] for b in rec.bodies] == ["eye", "stamp"]


def test_segment_type_without_prompt_fails() -> None:
    rec = Recorder()
    client = rec.client(prompts={EntityType.FACE: ["face"]})
    with pytest.raises(DetectionError, match="SIGNATURE"):
        client.segment(id_card_png(), [EntityType.SIGNATURE])
    assert rec.requests == []


def test_settings_and_env_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_SAM_URL", "http://sam.internal:9000/v1/")
    monkeypatch.setenv("PII_GUARD_SAM_MODEL", "sam-3.1-selfhosted")
    monkeypatch.setenv("META_API_KEY", "from-meta-env")
    from pii_guard.config import Settings

    client = SamClient(settings=Settings())
    assert client.url == "http://sam.internal:9000/v1/responses"
    assert client.model == "sam-3.1-selfhosted"
    assert "from-meta-env" not in repr(client)

    monkeypatch.setenv("PII_GUARD_SAM_API_KEY", "sam-specific")
    rec = Recorder()
    SamClient(settings=Settings(), transport=httpx.MockTransport(rec)).segment(
        id_card_png(), [EntityType.FACE]
    )
    assert rec.requests[0].headers["Authorization"] == "Bearer sam-specific"


def test_empty_sam_key_disables_sam_despite_meta_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicitly emptied PII_GUARD_SAM_API_KEY keeps SAM unconfigured (LAB-1255): the
    smoke stack is offline by contract even when META_API_KEY (or the repo .env) has a key."""
    from pii_guard.config import Settings

    monkeypatch.setenv("META_API_KEY", "from-meta-env")
    monkeypatch.setenv("PII_GUARD_SAM_API_KEY", "")
    client = SamClient(settings=Settings())
    assert not client.configured
    with pytest.raises(DetectionError, match="no API key"):
        client.segment(id_card_png(), [EntityType.FACE])


def test_full_url_is_kept() -> None:
    assert SamClient(base_url="http://x/v1/responses").url == "http://x/v1/responses"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"prompts": {EntityType.PERSON: ["person"]}},
        {"prompts": {EntityType.FACE: []}},
        {"prompts": {EntityType.FACE: ["  "]}},
        {"timeout": 0},
        {"max_retries": -1},
    ],
)
def test_invalid_configuration(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        SamClient(api_key=FAKE_KEY, **kwargs)


# --- fail closed -------------------------------------------------------------------------


def test_missing_key_fails_closed() -> None:
    rec = Recorder()
    client = SamClient(transport=httpx.MockTransport(rec))
    with pytest.raises(DetectionError, match="API key"):
        client.segment(id_card_png())
    assert rec.requests == []


def test_undecodable_image_fails_closed() -> None:
    rec = Recorder()
    with pytest.raises(DetectionError, match="decoded"):
        rec.client().segment(b"not an image")
    assert rec.requests == []


def test_retry_then_success() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("no route to host")
        return httpx.Response(200, json=fixture("sam_face"))

    client = SamClient(api_key=FAKE_KEY, transport=httpx.MockTransport(handler))
    regions = client.segment(id_card_png(), [EntityType.FACE])
    assert len(regions) == 1 and len(calls) == 2


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (httpx.Response(503), "HTTP 503"),
        (httpx.Response(429), "HTTP 429"),
        (httpx.ReadTimeout("slow"), "timed out"),
        (httpx.ConnectError("down"), "transport error"),
    ],
)
def test_retryable_errors_exhaust_and_fail_closed(answer: Any, message: str) -> None:
    rec = Recorder(default=answer)
    with pytest.raises(DetectionError, match=message):
        rec.client(max_retries=2).segment(id_card_png(), [EntityType.FACE])
    assert len(rec.requests) == 3


# --- image deadline (LAB-1234) -------------------------------------------------------------


def test_expired_deadline_sends_nothing_and_fails_closed() -> None:
    """Past the image deadline no SAM prompt is even attempted: the request frees its
    image-pool slot instead of holding it for prompts x timeout x (1 + retries)."""
    import time

    from pii_guard.visual import ocr as ocr_module

    rec = Recorder()
    client = rec.client(timeout=60.0, max_retries=1)
    with ocr_module.deadline(time.monotonic() - 1), pytest.raises(DetectionError, match="deadline"):
        client.segment(id_card_png(), [EntityType.FACE, EntityType.ID_PHOTO])
    assert rec.requests == []


def test_sam_request_timeout_is_capped_at_the_deadline() -> None:
    """Each SAM request gets at most the time the image deadline still has."""
    import time

    from pii_guard.visual import ocr as ocr_module

    rec = Recorder()
    client = rec.client(timeout=60.0, max_retries=0)
    with ocr_module.deadline(time.monotonic() + 7):
        client.segment(id_card_png(), [EntityType.FACE])
    assert len(rec.requests) == 1
    timeout = rec.requests[0].extensions["timeout"]
    capped = max(timeout.values()) if isinstance(timeout, dict) else float(timeout)
    assert capped <= 7.5


def _completed(text: Any) -> dict[str, Any]:
    body = fixture("sam_signature")
    body["output"][0]["content"][0]["text"] = text
    return body


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(400, json={"error": {"message": "bad"}}),
        httpx.Response(401),
        httpx.Response(200, content=b"<html>"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={**fixture("sam_signature"), "status": "failed"}),
        httpx.Response(200, json={**fixture("sam_signature"), "error": {"code": "x"}}),
        httpx.Response(200, json={**fixture("sam_signature"), "output": None}),
        httpx.Response(200, json={**fixture("sam_signature"), "output": []}),
        httpx.Response(200, json=_completed(None)),
        httpx.Response(200, json=_completed("a face, probably")),
    ],
)
def test_bad_responses_fail_closed(answer: httpx.Response) -> None:
    rec = Recorder(default=answer)
    with pytest.raises(DetectionError) as info:
        rec.client().segment(id_card_png(), [EntityType.FACE])
    assert FAKE_KEY not in str(info.value)


def test_later_prompt_failure_discards_earlier_regions() -> None:
    rec = Recorder({"face": fixture("sam_face")}, default=httpx.Response(500))
    with pytest.raises(DetectionError):
        rec.client(max_retries=0).segment(id_card_png())


# --- live --------------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.skipif(not LIVE_KEY, reason="META_API_KEY not set")
def test_live_sam_finds_the_synthetic_face() -> None:
    client = SamClient(api_key=LIVE_KEY, base_url=DEFAULT_BASE_URL, max_retries=3)
    regions = client.segment(id_card_png(), [EntityType.FACE])
    assert regions, "SAM 3.1 found no face on the synthetic card"
    box = regions[0].box
    assert box.x1 >= FACE_BOX.x1 - 5 and box.x2 <= FACE_BOX.x2 + 5
