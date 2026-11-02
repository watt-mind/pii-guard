"""MuseOcr (Muse Spark Open OCR, LAB-1796) against a mocked Chat Completions endpoint.

Offline: every request goes to an ``httpx.MockTransport``. Images are blank synthetic canvases
and every OCR text is fictional (a reserved example domain).
"""

from __future__ import annotations

import base64
import io
import json
import time
from typing import Any

import httpx
import pytest
from PIL import Image

from pii_guard.config import Settings
from pii_guard.detect.rules import RuleDetector
from pii_guard.detection_profile import (
    DetectionProfileError,
    is_self_hosted_url,
    require_local_ocr,
)
from pii_guard.types import DetectionError
from pii_guard.visual.masking import default_ocr_engine
from pii_guard.visual.ocr import OcrTimeoutError, TesseractOcr, deadline, text_regions
from pii_guard.visual.ocr_muse import (
    DEFAULT_MODEL,
    MAX_SIDE,
    PAD_SHARE,
    SYSTEM_PROMPT,
    USER_PROMPT,
    MuseOcr,
    _NoJson,
    muse_configured,
    parse_lines,
)
from pii_guard.visual.regions import Box

FAKE_KEY = "synthetic-key-not-a-secret"
W, H = 1000, 600
EMAIL = "teszt.elek@example.com"


@pytest.fixture(autouse=True)
def no_env_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PII_GUARD_OCR_API_KEY", raising=False)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)


def settings(**kwargs: Any) -> Settings:
    return Settings(_env_file=None, **kwargs)


def canvas(width: int = W, height: int = H) -> Image.Image:
    return Image.new("RGB", (width, height), "white")


def png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def reply(content: Any) -> dict[str, Any]:
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]}


def lines(*items: tuple[str, list[float]]) -> str:
    return json.dumps({"lines": [{"text": t, "box": b} for t, b in items]})


class Endpoint:
    """Answers each request with the next queued answer and records every request."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, httpx.Response):
            return answer
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(200, json=reply(answer))

    def ocr(self, **kwargs: Any) -> MuseOcr:
        kwargs.setdefault("api_key", FAKE_KEY)
        kwargs.setdefault("settings", settings())
        return MuseOcr(transport=httpx.MockTransport(self), **kwargs)


# --- parse_lines ---------------------------------------------------------------------------


def test_lines_scale_to_the_image_unpadded_in_reading_order() -> None:
    words = parse_lines(
        lines(("Surname", [100, 100, 300, 150]), (EMAIL, [100, 200, 600, 250])), (W, H)
    )
    assert [w.text for w in words] == ["Surname", EMAIL]
    assert words[0].box == Box(100, 60, 300, 90)
    assert words[1].box == Box(100, 120, 600, 150)
    assert words[0].line != words[1].line  # one line each: joined with a newline


def test_fenced_or_wrapped_json_is_accepted() -> None:
    body = lines(("Name", [0, 0, 100, 100]))
    assert len(parse_lines("```json\n" + body + "\n```", (W, H))) == 1
    assert len(parse_lines("Here is the layout:\n" + body, (W, H))) == 1


def test_boxes_are_clamped_and_ordered_and_empty_lines_dropped() -> None:
    words = parse_lines(
        lines(("a", [-50, 900, 1200, 2000]), ("b", [500, 500, 400, 400]), ("  ", [0, 0, 9, 9])),
        (W, H),
    )
    assert [w.text for w in words] == ["a", "b"]
    assert words[0].box == Box(0, 540, W - 1, H - 1)
    assert words[1].box == Box(400, 240, 500, 300)


@pytest.mark.parametrize(
    "text",
    [
        "I can't help with reading this identity document.",
        '{"lines": "none"}',
        '{"lines": [{"text": "a"}]}',
        '{"lines": [{"text": "a", "box": [1, 2, 3]}]}',
        '{"lines": [{"text": 7, "box": [1, 2, 3, 4]}]}',
        '{"lines": [{"text": "a", "box": [true, 2, 3, 4]}]}',
        '{"lines": [{"text": "a", "box": [1, 2, 3, 4]}',  # cut off
        "",
    ],
)
def test_a_reply_without_valid_json_is_rejected(text: str) -> None:
    with pytest.raises(_NoJson):
        parse_lines(text, (W, H))


def test_an_empty_line_list_is_a_page_without_text() -> None:
    assert parse_lines('{"lines": []}', (W, H)) == []


# --- requests ------------------------------------------------------------------------------


def test_request_is_the_spike_prompt_with_the_image_and_low_reasoning() -> None:
    endpoint = Endpoint(lines(("Name", [0, 0, 100, 100])))
    endpoint.ocr().words(canvas())
    (request,) = endpoint.requests
    assert str(request.url) == "https://inference.baseten.co/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    body = endpoint.bodies[0]
    assert body["model"] == DEFAULT_MODEL == "meta-models/muse-spark-open-1026"
    assert body["reasoning_effort"] == "low"
    assert body["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    text, image = body["messages"][1]["content"]
    assert text == {"type": "text", "text": USER_PROMPT}
    url = image["image_url"]["url"]
    assert image["type"] == "image_url" and url.startswith("data:image/png;base64,")
    sent = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert sent.size == (W, H)
    # The layout framing, never personal data or redaction (those prompts are refused).
    assert "personal" not in (SYSTEM_PROMPT + USER_PROMPT).lower()
    assert "redact" not in (SYSTEM_PROMPT + USER_PROMPT).lower()


def test_settings_choose_url_model_and_key() -> None:
    endpoint = Endpoint(lines())
    custom = settings(
        ocr_url="http://muse:8000/v1/", ocr_model="synthetic-model", ocr_api_key="from-settings"
    )
    MuseOcr(settings=custom, transport=httpx.MockTransport(endpoint)).words(canvas())
    (request,) = endpoint.requests
    assert str(request.url) == "http://muse:8000/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer from-settings"
    assert endpoint.bodies[0]["model"] == "synthetic-model"


def test_large_images_are_downscaled_before_sending() -> None:
    endpoint = Endpoint(lines(("Name", [0, 0, 500, 500])))
    words = endpoint.ocr().words(canvas(4096, 1024))
    url = endpoint.bodies[0]["messages"][1]["content"][1]["image_url"]["url"]
    sent = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert max(sent.size) == MAX_SIDE
    assert words[0].box == Box(0, 0, 2048, 512)  # still in the original image's pixels


def test_a_refusal_is_retried_once_with_the_same_prompt() -> None:
    endpoint = Endpoint("I can't help with that.", lines(("Name", [0, 0, 100, 100])))
    words = endpoint.ocr().words(canvas())
    assert [w.text for w in words] == ["Name"]
    assert len(endpoint.requests) == 2
    assert endpoint.bodies[0] == endpoint.bodies[1]


def test_a_second_refusal_fails_closed() -> None:
    endpoint = Endpoint("I can't help with that.")
    with pytest.raises(DetectionError, match="no valid JSON"):
        endpoint.ocr().words(canvas())
    assert len(endpoint.requests) == 2


def test_an_empty_or_missing_message_counts_as_a_refusal() -> None:
    endpoint = Endpoint(None)
    with pytest.raises(DetectionError, match="no valid JSON"):
        endpoint.ocr().words(canvas())


def test_retryable_status_is_retried_then_fails_closed_without_the_key() -> None:
    endpoint = Endpoint(httpx.Response(503))
    with pytest.raises(DetectionError) as excinfo:
        endpoint.ocr(max_retries=1).words(canvas())
    assert "HTTP 503" in str(excinfo.value)
    assert FAKE_KEY not in str(excinfo.value)
    assert len(endpoint.requests) == 2


def test_a_client_error_fails_closed_at_once() -> None:
    endpoint = Endpoint(httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(DetectionError, match="HTTP 401"):
        endpoint.ocr().words(canvas())
    assert len(endpoint.requests) == 1


def test_transport_errors_and_bad_bodies_fail_closed() -> None:
    with pytest.raises(DetectionError, match="transport error"):
        Endpoint(httpx.ConnectError("down")).ocr(max_retries=0).words(canvas())
    with pytest.raises(DetectionError, match="not JSON"):
        Endpoint(httpx.Response(200, content=b"<html>")).ocr().words(canvas())
    with pytest.raises(DetectionError, match="unexpected format"):
        Endpoint(httpx.Response(200, json={"choices": []})).ocr().words(canvas())


def test_the_image_deadline_stops_before_any_request() -> None:
    endpoint = Endpoint(lines())
    with deadline(time.monotonic() - 1), pytest.raises(OcrTimeoutError):
        endpoint.ocr().words(canvas())
    assert endpoint.requests == []


def test_repr_never_shows_the_key() -> None:
    assert FAKE_KEY not in repr(Endpoint(lines()).ocr())


# --- keys ----------------------------------------------------------------------------------


def test_without_a_key_nothing_is_sent() -> None:
    endpoint = Endpoint(lines())
    ocr = MuseOcr(settings=settings(), transport=httpx.MockTransport(endpoint))
    assert not ocr.configured
    with pytest.raises(DetectionError, match="no API key"):
        ocr.words(canvas())
    assert endpoint.requests == []


def test_the_key_falls_back_to_baseten_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASETEN_API_KEY", "synthetic-baseten")
    assert muse_configured(settings())
    monkeypatch.setenv("PII_GUARD_OCR_API_KEY", "synthetic-own")
    assert settings().ocr_api_key.get_secret_value() == "synthetic-own"  # type: ignore[union-attr]


def test_an_emptied_ocr_key_disables_it_even_with_a_baseten_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BASETEN_API_KEY", "synthetic-baseten")
    monkeypatch.setenv("PII_GUARD_OCR_API_KEY", "")
    assert not muse_configured(settings())
    assert not MuseOcr(settings=settings()).configured


def test_a_self_hosted_endpoint_may_go_keyless() -> None:
    endpoint = Endpoint(lines())
    local = settings(ocr_url="http://127.0.0.1:8000/v1")
    assert muse_configured(local)
    MuseOcr(settings=local, transport=httpx.MockTransport(endpoint)).words(canvas())
    assert "authorization" not in endpoint.requests[0].headers


# --- engine selection and the local-only profile -------------------------------------------


def test_default_engine_is_muse_with_a_key_and_none_without() -> None:
    assert settings().ocr_engine == "muse"
    assert default_ocr_engine(settings()) is None
    assert type(default_ocr_engine(settings(ocr_api_key=FAKE_KEY))) is MuseOcr


def test_tesseract_stays_selectable(monkeypatch: pytest.MonkeyPatch) -> None:
    import pii_guard.visual.masking as masking

    monkeypatch.setattr(masking, "tesseract_available", lambda: True)
    assert type(default_ocr_engine(settings(ocr_engine="tesseract"))) is TesseractOcr
    monkeypatch.setattr(masking, "tesseract_available", lambda: False)
    assert default_ocr_engine(settings(ocr_engine="tesseract", ocr_api_key=FAKE_KEY)) is None


@pytest.mark.parametrize(
    ("url", "self_hosted"),
    [
        ("http://localhost:8000/v1", True),
        ("http://127.0.0.1:8000/v1", True),
        ("http://[::1]:8000/v1", True),
        ("http://10.1.2.3/v1", True),
        ("http://192.168.0.7/v1", True),
        ("http://muse:8000/v1", True),
        ("https://muse.internal/v1", True),
        ("https://gpu.cluster.local/v1", True),
        ("https://inference.baseten.co/v1", False),
        ("https://api.meta.ai/v1", False),
        ("http://8.8.8.8/v1", False),
        ("https://muse.example.com/v1", False),
        ("", False),
        (None, False),
    ],
)
def test_self_hosted_urls(url: str | None, self_hosted: bool) -> None:
    assert is_self_hosted_url(url) is self_hosted


def local_only(**kwargs: Any) -> Settings:
    return settings(
        detection_profile="local-only", detectors=("rules",), ner_fallback="off", **kwargs
    )


def test_local_only_refuses_muse_on_a_remote_endpoint() -> None:
    with pytest.raises(DetectionProfileError, match="remote OCR"):
        MuseOcr(settings=local_only(), api_key=FAKE_KEY)
    with pytest.raises(DetectionProfileError, match="remote OCR"):
        default_ocr_engine(local_only(ocr_api_key=FAKE_KEY))
    remote = MuseOcr(settings=settings(), api_key=FAKE_KEY)
    with pytest.raises(DetectionProfileError, match="self-hosted"):
        require_local_ocr(local_only(), remote)


def test_local_only_accepts_muse_on_a_self_hosted_endpoint() -> None:
    profile = local_only(ocr_url="http://muse:8000/v1")
    ocr = default_ocr_engine(profile)
    assert type(ocr) is MuseOcr
    require_local_ocr(profile, ocr)
    require_local_ocr(profile, TesseractOcr())


# --- end to end ----------------------------------------------------------------------------


def test_a_detected_value_masks_its_whole_line_grown_by_two_percent_of_the_width() -> None:
    endpoint = Endpoint(
        lines(("Contact", [100, 100, 300, 140]), (f"E-mail: {EMAIL}", [100, 200, 700, 240]))
    )
    ocr = endpoint.ocr()
    assert ocr.region_pad_share == PAD_SHARE
    regions = text_regions(png(canvas()), [RuleDetector()], ocr=ocr, captions=False)
    (region,) = regions
    pad = round(PAD_SHARE * W)  # 20 px on every side, the y padding too
    assert region.box == Box(100 - pad, 120 - pad, 700 + pad, 144 + pad)
    assert region.source == "rules"  # the detector that found the e-mail


def test_line_padding_is_clamped_to_the_image() -> None:
    endpoint = Endpoint(lines((EMAIL, [0, 0, 1000, 30])))
    (region,) = text_regions(png(canvas()), [RuleDetector()], ocr=endpoint.ocr(), captions=False)
    assert region.box == Box(0, 0, W - 1, 18 + round(PAD_SHARE * W))


def test_a_refused_image_raises_from_the_pipeline() -> None:
    endpoint = Endpoint("Sorry, I can't read identity documents.")
    with pytest.raises(DetectionError):
        text_regions(png(canvas()), [RuleDetector()], ocr=endpoint.ocr())
