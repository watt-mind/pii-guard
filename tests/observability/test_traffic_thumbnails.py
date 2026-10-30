"""Traffic events keep a small thumbnail of each masked image, never the original (LAB-1188).

Synthetic only (ADR 0005): Pillow-drawn images, no real documents or values.
"""

from __future__ import annotations

import base64
import io
import json
import os
from typing import Any

import pytest
from PIL import Image

from pii_guard.gateway.config import Mode
from pii_guard.gateway.service import RequestStats
from pii_guard.gateway.trace import CallTrace
from pii_guard.observability import Observability, ObservabilitySettings, RequestTimer, thumbnails
from pii_guard.observability.thumbnails import (
    MAX_SIDE,
    MAX_THUMBNAIL_CHARS,
    MAX_THUMBNAILS,
    masked_thumbnails,
)


def _png(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def _noise_png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.frombytes("RGB", (width, height), os.urandom(width * height * 3)).save(buf, "PNG")
    return buf.getvalue()


def _url(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def _body(*urls: str) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"type": "text", "text": "What is in the picture?"}]
    parts += [{"type": "image_url", "image_url": {"url": u}} for u in urls]
    return {"model": "test-model", "messages": [{"role": "user", "content": parts}]}


def _decoded(thumb: dict[str, Any]) -> Image.Image:
    head, _, payload = thumb["data"].partition(",")
    assert head == "data:image/webp;base64"
    return Image.open(io.BytesIO(base64.b64decode(payload)))


def _event(level: str, original: dict[str, Any], masked: dict[str, Any]) -> dict[str, Any]:
    obs = Observability(ObservabilitySettings(traffic_log=level))
    trace = CallTrace(obs, RequestTimer(), original)
    trace.stats = RequestStats(mode=Mode.FAST)
    trace.masked_request = json.dumps(masked).encode()
    trace.finish()
    (event,) = obs.traffic.recent()
    return event


def test_masked_event_carries_a_downscaled_masked_thumbnail_and_no_original_bytes() -> None:
    original = _png(1200, 800, (200, 30, 30))  # stands in for the unmasked image
    masked = _png(1200, 800, (0, 0, 0))
    event = _event("masked", _body(_url(original)), _body(_url(masked)))
    dumped = json.dumps(event)
    assert base64.b64encode(original).decode() not in dumped
    assert base64.b64encode(masked).decode() not in dumped
    (thumb,) = event["request"]["thumbnails"]
    assert thumb["index"] == 0
    assert max(thumb["width"], thumb["height"]) <= MAX_SIDE
    assert len(thumb["data"]) <= MAX_THUMBNAIL_CHARS
    image = _decoded(thumb)
    assert image.size == (thumb["width"], thumb["height"]) == (320, 213)
    assert max(image.convert("RGB").getpixel((10, 10))) < 16  # the masked (black) pixels
    # The masked body itself still only holds the summary.
    content = event["request"]["masked"]["messages"][0]["content"]
    assert content[1]["image_url"]["url"].startswith("[inline image/png")


def test_full_event_thumbnails_the_masked_image_only() -> None:
    original = _png(400, 300, (200, 30, 30))
    masked = _png(400, 300, (0, 0, 0))
    event = _event("full", _body(_url(original)), _body(_url(masked)))
    (thumb,) = event["request"]["thumbnails"]
    assert max(_decoded(thumb).convert("RGB").getpixel((5, 5))) < 16
    assert "thumbnails" not in (event["request"]["original"] or {})
    assert base64.b64encode(original).decode() not in json.dumps(event)


def test_index_counts_remote_images_and_the_per_event_cap_holds() -> None:
    small = _url(_png(64, 64, (0, 0, 0)))
    body = _body("https://example.test/a.png", *([small] * (MAX_THUMBNAILS + 1)))
    thumbs = masked_thumbnails(json.dumps(body).encode())
    assert [t["index"] for t in thumbs] == list(range(1, MAX_THUMBNAILS + 2))
    assert all("data" in t for t in thumbs[:MAX_THUMBNAILS])
    assert thumbs[-1] == {"index": MAX_THUMBNAILS + 1, "omitted": "limit"}


def test_noisy_image_falls_back_to_a_smaller_side() -> None:
    (thumb,) = masked_thumbnails(json.dumps(_body(_url(_noise_png(800, 800)))).encode())
    assert thumb["width"] < MAX_SIDE
    assert len(thumb["data"]) <= MAX_THUMBNAIL_CHARS


def test_image_that_never_fits_is_omitted_not_kept_oversized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(thumbnails, "MAX_THUMBNAIL_CHARS", 64)
    thumbs = masked_thumbnails(json.dumps(_body(_url(_noise_png(400, 400)))).encode())
    assert thumbs == [{"index": 0, "omitted": "too_large"}]


def test_no_images_or_unreadable_data_gives_no_thumbnail() -> None:
    assert masked_thumbnails(None) == []
    assert masked_thumbnails(json.dumps(_body()).encode()) == []
    bad = masked_thumbnails(json.dumps(_body("data:image/png;base64,AAAA")).encode())
    assert bad == [{"index": 0, "omitted": "invalid"}]
    event = _event("masked", _body(), _body())
    assert "thumbnails" not in event["request"]


def test_off_level_records_nothing() -> None:
    obs = Observability(ObservabilitySettings(traffic_log="off"))
    trace = CallTrace(obs, RequestTimer(), _body())
    trace.masked_request = json.dumps(_body(_url(_png(32, 32, (0, 0, 0))))).encode()
    trace.finish()
    assert obs.traffic.recent() == []
