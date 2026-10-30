"""Rotated, skewed and small-text images (LAB-1210): OCR reads them upright and maps back.

CI has no Tesseract, so most tests stand a fake ``pytesseract`` in for it: it "reads" a red
bar drawn on a white page and scores the reading by the bar's orientation, the way Tesseract
reads an upright page confidently and a turned one poorly. The tests at the end run the real
Tesseract on the fictional card and the synthetic screenshots of
``eval/fixtures/visual/robustness.json``, where it is installed.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw
from visual_helpers import FICTIONAL_TAJ, FICTIONAL_TAX_ID, _font, render_id_card

from pii_guard.detect.rules import RuleDetector
from pii_guard.types import EntityType
from pii_guard.visual import Box, OcrWord, tesseract_available, text_regions
from pii_guard.visual.ocr import (
    OcrPage,
    PageFrame,
    TesseractOcr,
    _merge_boxes,
    estimate_skew,
    ocr_text,
)

ROBUSTNESS = (
    Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "visual" / "robustness.json"
)
RED = (255, 0, 0)


def ink_box(image: Image.Image, colour: tuple[int, int, int] = RED) -> Box | None:
    """The bounding box of the pixels of ``colour`` (exactly) in ``image``."""
    mask = Image.new("L", image.size, 0)
    rgb = image.convert("RGB")
    px, out = rgb.load(), mask.load()
    assert px is not None and out is not None
    for y in range(rgb.height):
        for x in range(rgb.width):
            if px[x, y] == colour:
                out[x, y] = 255
    bbox = mask.getbbox()
    return None if bbox is None else Box(bbox[0], bbox[1], bbox[2] - 1, bbox[3] - 1)


# --- PageFrame -------------------------------------------------------------------------------


@pytest.mark.parametrize("angle", [90, 180, 270, -90, 450])
def test_quarter_turns_map_boxes_back_exactly(angle: int) -> None:
    page = Image.new("RGB", (400, 250), "white")
    ImageDraw.Draw(page).rectangle([50, 60, 120, 90], fill=RED)
    frame = PageFrame.of(page.size, angle)
    turned = frame.render(page)
    assert turned.size == frame.size
    seen = ink_box(turned)
    assert seen is not None
    assert frame.to_source(seen) == Box(50, 60, 120, 90)


@pytest.mark.parametrize("angle", [3.5, -10, 15, 105])
def test_a_skewed_frame_maps_a_box_to_one_that_covers_it(angle: float) -> None:
    page = Image.new("RGB", (400, 250), "white")
    ImageDraw.Draw(page).rectangle([50, 60, 120, 90], fill=RED)
    frame = PageFrame.of(page.size, angle)
    turned = frame.render(page)
    assert turned.size == frame.size
    seen = ink_box(turned)
    assert seen is not None
    back = frame.to_source(seen)
    assert back.x1 <= 51 and back.y1 <= 61 and back.x2 >= 119 and back.y2 >= 89
    # The cover grows with the angle, not without bound.
    assert back.width <= 70 + 60 and back.height <= 30 + 70


def test_the_identity_frame_changes_nothing() -> None:
    page = Image.new("RGB", (10, 10), "white")
    frame = PageFrame.of(page.size, 360)
    assert frame.identity and frame.render(page) is page
    assert frame.to_source(Box(1, 2, 3, 4)) == Box(1, 2, 3, 4)
    words = [OcrWord("a", Box(1, 1, 2, 2), (0,))]
    assert OcrPage(words, frame).source_words() == words
    assert "words=1" in repr(OcrPage(words, frame))


def test_boxes_are_clamped_to_the_source() -> None:
    frame = PageFrame.of((100, 50), 90)
    assert frame.to_source(Box(0, 0, 49, 99)) == Box(0, 0, 99, 49)
    assert frame.to_source(Box(0, 0, 200, 300)) == Box(0, 0, 99, 49)


def test_merge_boxes_joins_overlaps_only() -> None:
    merged = _merge_boxes([Box(0, 0, 10, 10), Box(30, 30, 40, 40), Box(5, 5, 20, 20)])
    assert merged == [Box(0, 0, 20, 20), Box(30, 30, 40, 40)]
    # A chain that only overlaps once merged.
    chain = _merge_boxes([Box(0, 0, 10, 10), Box(20, 0, 30, 10), Box(9, 0, 21, 10)])
    assert chain == [Box(0, 0, 30, 10)]


# --- skew ------------------------------------------------------------------------------------


def lines_page(size: tuple[int, int] = (900, 600)) -> Image.Image:
    page = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(page)
    for y in range(60, size[1] - 60, 36):
        for x in range(60, size[0] - 120, 90):
            draw.rectangle([x, y, x + 70, y + 14], fill="black")
    return page


@pytest.mark.parametrize("angle", [3.0, -5.0, 8.0, -12.0, 15.0])
def test_estimate_skew_finds_the_angle_that_straightens_the_lines(angle: float) -> None:
    page = lines_page().rotate(angle, Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    assert estimate_skew(page) == pytest.approx(-angle, abs=0.5)


def test_estimate_skew_leaves_straight_and_blank_pages_alone() -> None:
    assert estimate_skew(lines_page()) == 0.0
    assert estimate_skew(lines_page().rotate(0.5, fillcolor="white")) == 0.0
    assert estimate_skew(Image.new("RGB", (300, 200), "white")) == 0.0
    big = lines_page((2400, 1600))
    assert estimate_skew(big) == 0.0


# --- the fake Tesseract ----------------------------------------------------------------------


class FakeTesseract:
    """``pytesseract`` reading one red bar as ``TAJ: 123 456 788``.

    A bar lying flat with its notch (a white gap) on the left reads confidently; upside down
    (notch on the right) it reads as junk. A bar standing up reads like Tesseract reads
    sideways text in place: confidently when its notch is at the top, poorly otherwise, with
    tall word boxes either way. A bar under ``small`` pixels high reads at middling confidence
    (small print); enlarged it reads cleanly.
    """

    class Output:
        DICT = "dict"

    def __init__(self, small: int = 0) -> None:
        self.small = small
        #: How many words of an upside-down reading come back confident (2: a middling read).
        self.upside_good = 0
        #: What ``image_to_osd`` answers: ``None`` works it out, an exception is raised.
        self.osd: int | Exception | None = None
        self.calls: list[tuple[int, int]] = []
        self.osd_calls = 0

    def image_to_osd(self, image: Image.Image, **kwargs: Any) -> dict[str, Any]:
        self.osd_calls += 1
        if isinstance(self.osd, Exception):
            raise self.osd
        if self.osd is not None:
            return {"rotate": self.osd, "orientation_conf": 3.0}
        box = ink_box(image)
        assert box is not None
        rgb = image.convert("RGB")
        notch_left = rgb.getpixel((box.x1 + box.width // 10, (box.y1 + box.y2) // 2)) != RED
        return {"rotate": 0 if notch_left else 180, "orientation_conf": 3.0}

    def image_to_data(self, image: Image.Image, **kwargs: Any) -> dict[str, list[Any]]:
        self.calls.append(image.size)
        box = ink_box(image)
        data: dict[str, list[Any]] = {
            k: []
            for k in (
                *("text", "conf", "left", "top", "width", "height"),
                *("page_num", "block_num", "par_num", "line_num"),
            )
        }
        if box is None:
            return data
        flat = box.width >= box.height
        rgb = image.convert("RGB")
        if flat:
            mid = (box.y1 + box.y2) // 2
            left_gap = rgb.getpixel((box.x1 + box.width // 10, mid)) != RED
            good = left_gap
        else:
            mid = (box.x1 + box.x2) // 2
            good = rgb.getpixel((mid, box.y1 + box.height // 10)) != RED
        conf = 95.0 if good else 15.0
        if good and flat and self.small and box.height < self.small:
            conf = 50.0
        confs = [conf] * 4
        if not good and flat:
            confs = [15.0] + [95.0 if i < self.upside_good else 15.0 for i in range(3)]
        texts = ["TAJ:", *FICTIONAL_TAJ.split()] if good else ["~#", "1Z3", "4S6", "7B8"]
        n = len(texts)
        for i, text in enumerate(texts):
            if flat:
                w = box.width // n
                left, top, width, height = box.x1 + i * w, box.y1, w - 2, box.height
            else:
                h = box.height // n
                left, top, width, height = box.x1, box.y1 + i * h, box.width, h - 2
            for key, value in zip(
                data,
                (text, confs[i], left, top, width, height, 1, 1, 1, 1),
                strict=True,
            ):
                data[key].append(value)
        return data


@pytest.fixture
def fake_tesseract(monkeypatch: pytest.MonkeyPatch) -> FakeTesseract:
    fake = FakeTesseract()
    module = types.ModuleType("pytesseract")
    module.Output = FakeTesseract.Output  # type: ignore[attr-defined]
    module.image_to_data = fake.image_to_data  # type: ignore[attr-defined]
    module.image_to_osd = fake.image_to_osd  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pytesseract", module)
    return fake


def bar_page(size: tuple[int, int] = (600, 300), height: int = 30) -> Image.Image:
    """A white page with one red bar (a notch at its left end) lying flat."""
    page = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(page)
    draw.rectangle([100, 100, 400, 100 + height - 1], fill=RED)
    draw.rectangle([110, 100 + height // 4, 150, 100 + 3 * height // 4], fill="white")
    return page


def taj_box(regions: list[Any]) -> Box:
    found = [r for r in regions if r.entity_type is EntityType.NATIONAL_ID_HU_TAJ]
    assert found, "TAJ not found"
    return found[0].box


def test_an_upright_page_is_read_once(fake_tesseract: FakeTesseract) -> None:
    regions = text_regions(bar_page(), [RuleDetector()], ocr=TesseractOcr(upscale_to=None))
    assert len(fake_tesseract.calls) == 1
    box = taj_box(regions)
    assert box.x1 >= 100 and box.x2 <= 400 and box.y1 >= 100 and box.y2 <= 130


@pytest.mark.parametrize("angle", [90, 180, 270])
def test_a_turned_page_is_read_upright_and_mapped_back(
    fake_tesseract: FakeTesseract, angle: int
) -> None:
    page = bar_page().rotate(angle, expand=True)
    bar = ink_box(page)
    assert bar is not None
    ocr = TesseractOcr(upscale_to=None, deskew=False)
    found = ocr_text(page, [RuleDetector()], ocr=ocr)
    box = taj_box([f.region for f in found.findings])
    # The cover lies on the bar in the input, wherever the bar was turned to.
    assert bar.x1 - 1 <= box.x1 and box.x2 <= bar.x2 + 1
    assert bar.y1 - 1 <= box.y1 and box.y2 <= bar.y2 + 1
    assert all(bar.x1 - 1 <= w.box.x1 and w.box.x2 <= bar.x2 + 1 for w in found.words), (
        "words are in input coordinates"
    )
    assert ocr.read(page).frame.angle == (360 - angle) % 360


def test_a_middling_reading_asks_osd(fake_tesseract: FakeTesseract) -> None:
    fake_tesseract.upside_good = 2  # upside down, two of three words read confidently
    page = bar_page().rotate(180)
    read = TesseractOcr(upscale_to=None, deskew=False).read(page)
    assert fake_tesseract.osd_calls == 1
    assert read.frame.angle == 180.0
    assert [w.text for w in read.words] == ["TAJ:", *FICTIONAL_TAJ.split()]


@pytest.mark.parametrize("answer", [0, 45])
def test_osd_saying_upright_costs_no_pass(fake_tesseract: FakeTesseract, answer: int) -> None:
    fake_tesseract.upside_good = 2
    fake_tesseract.osd = answer
    read = TesseractOcr(upscale_to=None, deskew=False, suppress=False).read(bar_page().rotate(180))
    # 0: upright, no second pass. 45: OSD can't be trusted, so upside down is read too.
    assert read.frame.identity == (answer == 0)
    assert len(fake_tesseract.calls) == (1 if answer == 0 else 2)


def test_osd_failing_falls_back_to_upside_down(fake_tesseract: FakeTesseract) -> None:
    fake_tesseract.upside_good = 2
    fake_tesseract.osd = RuntimeError("Too few characters. Skipping this page")
    read = TesseractOcr(deskew=False).read(bar_page().rotate(180))
    assert read.frame.angle == 180.0
    fake_tesseract.osd = ValueError("odd output")
    assert TesseractOcr(deskew=False).read(bar_page().rotate(180)).frame.angle == 180.0


def test_osd_running_out_of_time_fails_closed(fake_tesseract: FakeTesseract) -> None:
    from pii_guard.visual.ocr import OcrTimeoutError

    fake_tesseract.upside_good = 2
    fake_tesseract.osd = RuntimeError("Tesseract process timeout")
    with pytest.raises(OcrTimeoutError):
        TesseractOcr(deskew=False).read(bar_page().rotate(180))


def test_orientation_can_be_turned_off(fake_tesseract: FakeTesseract) -> None:
    page = bar_page().rotate(180, expand=True)
    regions = text_regions(page, [RuleDetector()], ocr=TesseractOcr(orient=False, suppress=False))
    assert not regions
    assert len(fake_tesseract.calls) == 1


def test_a_page_that_reads_poorly_every_way_keeps_the_upright_reading(
    fake_tesseract: FakeTesseract, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.modules["pytesseract"], "image_to_data", lambda image, **k: _junk())
    page = TesseractOcr(upscale_to=None).read(bar_page())
    assert page.frame.identity
    assert [w.text for w in page.words] == ["~#"]


def _junk() -> dict[str, list[Any]]:
    return {
        "text": ["~#"],
        "conf": [10.0],
        "left": [5],
        "top": [5],
        "width": [20],
        "height": [10],
        "page_num": [1],
        "block_num": [1],
        "par_num": [1],
        "line_num": [1],
    }


def test_a_skewed_page_is_straightened(fake_tesseract: FakeTesseract) -> None:
    page = lines_page()
    ImageDraw.Draw(page).rectangle([100, 520, 400, 549], fill=RED)
    ImageDraw.Draw(page).rectangle([110, 527, 150, 542], fill="white")
    skewed = page.rotate(9, Image.Resampling.NEAREST, expand=True, fillcolor="white")
    read = TesseractOcr(upscale_to=None).read(skewed)
    assert read.frame.angle == pytest.approx(360 - 9, abs=0.5)
    regions = text_regions(skewed, [RuleDetector()], ocr=TesseractOcr(upscale_to=None))
    bar = ink_box(skewed)
    assert bar is not None
    box = taj_box(regions)
    # The cover (the number: the bar's right three quarters) reaches the tilted bar's
    # raised right end and its top.
    assert box.x2 >= bar.x2 - 2 and box.y1 <= bar.y1 + 2
    assert box.x1 > bar.x1 + bar.width // 5


def test_small_text_is_read_again_enlarged(fake_tesseract: FakeTesseract) -> None:
    fake_tesseract.small = 30
    page = bar_page(size=(2600, 1400), height=9)
    ocr = TesseractOcr(deskew=False, orient=False)
    read = ocr.read(page)
    assert len(fake_tesseract.calls) == 2  # the page, then one enlarged tile
    tile = fake_tesseract.calls[1]
    assert tile[1] > 4 * 9  # enlarged
    assert [w.text for w in read.words] == ["TAJ:", *FICTIONAL_TAJ.split()]
    assert read.words[0].line[0] == -1  # the tile's own line
    for word in read.words:
        assert word.box.x1 >= 100 and word.box.x2 <= 400 and 99 <= word.box.y1 <= 110


def test_small_text_reading_worse_keeps_the_first_reading(
    fake_tesseract: FakeTesseract,
) -> None:
    fake_tesseract.small = 10_000  # enlarged or not, it reads at middling confidence
    page = bar_page(size=(2600, 1400), height=9)
    read = TesseractOcr(deskew=False, orient=False).read(page)
    assert len(fake_tesseract.calls) == 2
    assert all(w.line[0] != -1 for w in read.words)


def test_small_text_can_be_turned_off(fake_tesseract: FakeTesseract) -> None:
    page = bar_page(size=(2600, 1400), height=9)
    TesseractOcr(small_text=False, deskew=False, orient=False).read(page)
    assert len(fake_tesseract.calls) == 1


def test_an_engine_without_read_is_used_as_it_is() -> None:
    class WordsOnly:
        name = "words-only"

        def words(self, image: Image.Image) -> list[OcrWord]:
            return [
                OcrWord("TAJ:", Box(10, 10, 40, 20), (1,)),
                *(
                    OcrWord(part, Box(50 + 40 * i, 10, 80 + 40 * i, 20), (1,))
                    for i, part in enumerate(FICTIONAL_TAJ.split())
                ),
            ]

    regions = text_regions(Image.new("RGB", (300, 40), "white"), [RuleDetector()], ocr=WordsOnly())
    assert taj_box(regions) == Box(50, 10, 160, 20)


def test_an_engine_returning_something_else_fails_closed() -> None:
    from pii_guard.types import DetectionError

    class Odd:
        name = "odd"

        def read(self, image: Image.Image) -> list[str]:
            return ["x"]

        def words(self, image: Image.Image) -> list[OcrWord]:
            return []

    with pytest.raises(DetectionError):
        text_regions(Image.new("RGB", (10, 10)), [RuleDetector()], ocr=Odd())


def test_captions_and_fields_are_mapped_back(fake_tesseract: FakeTesseract) -> None:
    """Every box of the OCR result (words, findings, caption values) is in input pixels."""

    class Turned:
        name = "turned"

        def __init__(self, page: OcrPage) -> None:
            self.page = page

        def read(self, image: Image.Image) -> OcrPage:
            return self.page

        def words(self, image: Image.Image) -> list[OcrWord]:
            return self.page.source_words()

    upright = [
        OcrWord("Name:", Box(10, 10, 60, 24), (1,)),
        OcrWord("Teszt", Box(70, 10, 120, 24), (1,)),
        OcrWord("Elek", Box(130, 10, 170, 24), (1,)),
        OcrWord("Expiry:", Box(10, 40, 70, 54), (2,)),
        OcrWord("2030-01-01", Box(80, 40, 180, 54), (2,)),
    ]
    frame = PageFrame.of((100, 300), 90)  # the input stands up; the frame lies flat
    found = ocr_text(
        Image.new("RGB", (100, 300), "white"), [RuleDetector()], ocr=Turned(OcrPage(upright, frame))
    )
    for word in found.words:
        assert word.box.x2 < 100 and word.box.y2 < 300
        assert word.box.height > word.box.width  # standing up, as in the input
    for value in found.fields:
        assert value.box.height >= value.box.width
        assert all(w.box.height > w.box.width for w in value.words)
    for finding in found.findings:
        assert finding.region.box.height >= finding.region.box.width


# --- real Tesseract --------------------------------------------------------------------------

needs_tesseract = pytest.mark.skipif(not tesseract_available(), reason="tesseract not installed")


def robustness() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(ROBUSTNESS.read_text(encoding="utf-8"))
    return data


def test_the_robustness_fixtures_are_fictional_and_well_formed() -> None:
    spec = robustness()
    assert spec["version"] == 1
    assert 0 in spec["transforms"] and {90, 180, 270} <= set(spec["transforms"])
    assert any(abs(a) % 90 for a in spec["transforms"]), "a skewed transform"
    for shot in spec["screenshots"]:
        assert shot["id"] and len(shot["size"]) == 2
        for line in shot["lines"]:
            assert len(line) == 3
    values = {v for shot in spec["screenshots"] for v in shot["values"]}
    assert {FICTIONAL_TAJ, FICTIONAL_TAX_ID} <= values


def render_screenshot(shot: dict[str, Any]) -> Image.Image:
    image = Image.new("RGB", tuple(shot["size"]), "white")
    draw = ImageDraw.Draw(image)
    for x, y, text in shot["lines"]:
        draw.text((x, y), text, fill="black", font=_font(shot["font_size"]))
    return image


@needs_tesseract
@pytest.mark.slow
@pytest.mark.parametrize("angle", robustness()["transforms"])
def test_tesseract_masks_the_turned_card(angle: float) -> None:
    card = render_id_card()
    page = (
        card
        if not angle
        else card.rotate(angle, Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    )
    regions = text_regions(page, [RuleDetector()], ocr=TesseractOcr("hun+eng"))
    types_found = {r.entity_type for r in regions}
    assert {EntityType.NATIONAL_ID_HU_TAJ, EntityType.NATIONAL_ID_HU_TAX} <= types_found


@needs_tesseract
@pytest.mark.slow
@pytest.mark.parametrize("shot", robustness()["screenshots"], ids=lambda s: s["id"])
def test_tesseract_masks_small_text_in_large_screenshots(shot: dict[str, Any]) -> None:
    regions = text_regions(render_screenshot(shot), [RuleDetector()], ocr=TesseractOcr("hun+eng"))
    types_found = {r.entity_type for r in regions}
    assert {EntityType.NATIONAL_ID_HU_TAJ, EntityType.NATIONAL_ID_HU_TAX} <= types_found
