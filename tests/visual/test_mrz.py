"""Machine-readable zones found by their layout in OCR words (one region per zone).

Every zone is fictional: the ICAO 9303 specimens of ``tests/detect/rules/test_id_documents_hu.py``
(Utopia, ``UTO``) and a TD2 zone built the same way. The words carry synthetic boxes on a
monospace grid, so the expected region is exactly the union of the zone's word boxes.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageDraw, ImageFont
from visual_helpers import FakeOcr, png_bytes

from pii_guard.policy import Policy, PolicySet
from pii_guard.types import EntityType, Span
from pii_guard.visual import (
    Box,
    OcrWord,
    SamClient,
    TesseractOcr,
    mask_image,
    tesseract_available,
    text_regions,
)
from pii_guard.visual.mrz import SOURCE, mrz_regions

TD3 = (
    "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
    "L898902C36UTO7408122F1204159ZE184226B<<<<<10",
)
TD1 = (
    "I<UTOD231458907<<<<<<<<<<<<<<<",
    "7408122F1204159UTO<<<<<<<<<<<6",
    "ERIKSSON<<ANNA<MARIA<<<<<<<<<<",
)
TD2 = (
    "I<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<",
    "D231458907UTO7408122F1204159<<<<<<<6",
)
ZONES = {"TD3": TD3, "TD1": TD1, "TD2": TD2}

CHAR_W, LINE_H, LINE_PITCH, LEFT, TOP = 12, 20, 30, 40, 300
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "visual"


def ocr_words(lines: tuple[str, ...] | list[str], *, top: int = TOP, first_line: int = 0):
    """Words of ``lines`` (split at spaces) on a monospace grid, one OCR line per text line."""
    words: list[OcrWord] = []
    for row, text in enumerate(lines):
        y = top + row * LINE_PITCH
        pos = 0
        for word in text.split(" "):
            if word:
                start = text.index(word, pos)
                pos = start + len(word)
                x1 = LEFT + start * CHAR_W
                box = Box(x1, y, x1 + len(word) * CHAR_W - 1, y + LINE_H - 1)
                words.append(OcrWord(word, box, (1, 1, 1, first_line + row)))
    return words


def union(words: list[OcrWord]) -> Box:
    box = words[0].box
    for word in words[1:]:
        box = box.union(word.box)
    return box


def assert_one_zone(words: list[OcrWord]) -> None:
    regions = mrz_regions(words)
    assert len(regions) == 1, regions
    (region,) = regions
    assert region.entity_type is EntityType.ID_DOCUMENT
    assert region.box == union(words)
    assert region.source == SOURCE == "rules"
    assert region.score == 0.9


# --- clean zones -------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(ZONES))
def test_a_clean_zone_is_one_region_covering_all_its_words(name: str) -> None:
    lines = ZONES[name]
    assert {len(line) for line in lines} == {{"TD3": 44, "TD1": 30, "TD2": 36}[name]}
    assert_one_zone(ocr_words(lines))


def test_two_zones_on_one_image_are_two_regions() -> None:
    words = ocr_words(TD1) + ocr_words(TD3, top=TOP + 200, first_line=10)
    regions = mrz_regions(words)
    assert [r.box for r in regions] == [union(ocr_words(TD1)), union(ocr_words(TD3, top=500))]


def test_region_repr_carries_no_mrz_text() -> None:
    (region,) = mrz_regions(ocr_words(TD3))
    assert "ERIKSSON" not in repr(region) and "L898902C36" not in repr(region)


# --- OCR noise ---------------------------------------------------------------------------


def split(line: str, *cuts: int) -> str:
    for cut in sorted(cuts, reverse=True):
        line = line[:cut] + " " + line[cut:]
    return line


def wrong_char(line: str, index: int) -> str:
    return line[:index] + ("X" if line[index] != "X" else "Y") + line[index + 1 :]


@pytest.mark.parametrize("name", list(ZONES))
def test_words_split_at_spaces(name: str) -> None:
    lines = [split(line, 2, 5, 13) for line in ZONES[name]]
    assert lines[0].startswith(("P< UTO ERIKSSON", "I< UTO "))
    assert_one_zone(ocr_words(lines))


@pytest.mark.parametrize("name", list(ZONES))
@pytest.mark.parametrize("glyph", ["«", "\u2039", "K", "c"])
def test_filler_read_as_another_glyph(name: str, glyph: str) -> None:
    lines = [line.replace("<", glyph) for line in ZONES[name]]
    if glyph in "Kc":  # OCR misreads some fillers, not all of them
        lines = [line.replace(glyph, "<", 4) for line in lines]
    assert_one_zone(ocr_words(lines))


@pytest.mark.parametrize("name", list(ZONES))
def test_one_wrong_character_per_line(name: str) -> None:
    assert_one_zone(ocr_words([wrong_char(line, 7) for line in ZONES[name]]))


@pytest.mark.parametrize("name", list(ZONES))
@pytest.mark.parametrize("dropped", [1, 2])
def test_last_line_shorter(name: str, dropped: int) -> None:
    lines = list(ZONES[name])
    lines[-1] = lines[-1][:-dropped]
    assert_one_zone(ocr_words(lines))


def test_all_noise_at_once() -> None:
    lines = [split(wrong_char(line.replace("<", "«", 6), 9), 2, 5) for line in TD1]
    lines[-1] = lines[-1][:-2]
    assert_one_zone(ocr_words(lines))


def test_td3_with_its_second_line_missing_is_still_one_region() -> None:
    assert_one_zone(ocr_words(TD3[:1]))


def test_td1_with_a_line_missing_is_one_region_of_the_other_two() -> None:
    words = ocr_words([TD1[0], TD1[2]])
    assert_one_zone(words)


def test_junk_at_the_line_ends_is_ignored() -> None:
    words = ocr_words(["| " + TD3[0], "~— " + TD3[1] + " ."])
    regions = mrz_regions(words)
    assert len(regions) == 1
    junk_free = [w for w in words if w.text not in {"|", "~—", "."}]
    assert regions[0].box == union(junk_free)


def test_an_ocr_line_key_order_does_not_matter() -> None:
    words = ocr_words(TD1)
    by_line = sorted(words, key=lambda w: -w.line[-1])  # bottom line first
    assert mrz_regions(by_line)[0].box == union(words)


# --- negatives ---------------------------------------------------------------------------

NEGATIVE_LINES = [
    "ERIKSSON ANNA MARIA",
    "KOVÁCS JÁNOS PÉTER ISTVÁN ZOLTÁN FERENC",
    "KOVACS JANOS PETER ISTVAN ZOLTAN FERENC GABOR",
    "SZABÓNÉ NAGY ERZSÉBET MÁRIA",
    "HU42 1177 3016 1111 1018 0000 0000",
    "HU42117730161111101800000000",
    "DE89 3704 0044 0532 0130 00",
    "ABC-123",
    "AA BB 123",
    "SZEMÉLYI IGAZOLVÁNY",
    "IDENTITY CARD REPUBLIC OF HUNGARY",
    "PERSONALAUSWEIS REPUBLIK OSTERREICH",
    "PASSPORT PASSEPORT UTLEVEL HUNGARY",
    "EUROPEAN UNION MAGYARORSZÁG HUNGARY",
    "Document No: 123456AB",
    "123456AB",
    "IGAZOLVÁNY SZÁMA 123456AB",
    "123456789012345678901234567890",
    "0123 4567 8901 2345 6789 0123 4567 89",
    "1234567890123456789012345678901234567890123",
    "SURNAME / NOM / NACHNAME",
    "DATE OF BIRTH 1980-01-01 PLACE OF BIRTH BUDAPEST",
    "TAJ 123 456 788 ADÓAZONOSÍTÓ JEL 8123456786",
    "<< BACK",
    "~— | .",
    "Teszt Elek, 1051 Budapest, Fő utca 1. 2. em. 3.",
]


def test_ordinary_document_text_has_no_zone() -> None:
    assert len(NEGATIVE_LINES) >= 20
    assert mrz_regions(ocr_words(NEGATIVE_LINES)) == []


@pytest.mark.parametrize("line", NEGATIVE_LINES)
def test_each_negative_line_alone_has_no_zone(line: str) -> None:
    assert mrz_regions(ocr_words([line])) == []


def test_negative_lines_next_to_a_zone_stay_out_of_it() -> None:
    above = ocr_words(NEGATIVE_LINES[:8])
    zone = ocr_words(TD1, top=TOP + 8 * LINE_PITCH, first_line=20)
    below = ocr_words(NEGATIVE_LINES[8:], top=TOP + 11 * LINE_PITCH, first_line=40)
    assert [r.box for r in mrz_regions(above + zone + below)] == [union(zone)]


def test_short_filler_runs_are_not_a_zone() -> None:
    assert mrz_regions(ocr_words(["SMITH<<JOHN<<<<<<<<<<<<"])) == []
    assert mrz_regions([]) == []


def test_side_by_side_lines_are_not_one_zone() -> None:
    left = ocr_words([TD1[0]])
    right = [
        OcrWord(w.text, Box(w.box.x1 + 1000, w.box.y1 + 25, w.box.x2 + 1000, w.box.y2 + 25), (9,))
        for w in ocr_words([TD1[2]])
    ]
    regions = mrz_regions(left + right)
    assert sorted(r.box.x1 for r in regions) == [LEFT, LEFT + 1000]


# --- the OCR pipeline --------------------------------------------------------------------


class SilentDetector:
    """A text detector that finds nothing: the zone must come from its layout alone."""

    name = "silent"

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        return []


def zone_image() -> tuple[bytes, list[OcrWord]]:
    words = ocr_words(TD3)
    image = Image.new("RGB", (640, 420), (235, 240, 250))
    return png_bytes(image), words


def test_text_regions_returns_the_zone_even_when_the_detector_finds_nothing() -> None:
    data, words = zone_image()
    regions = text_regions(data, [SilentDetector()], ocr=FakeOcr(words))
    assert [(r.entity_type, r.box, r.source) for r in regions] == [
        (EntityType.ID_DOCUMENT, union(words), "rules")
    ]


def test_image_masker_covers_the_zone_pixels() -> None:
    from pii_guard.visual.masking import ImageMasker

    empty = json.loads((FIXTURES / "sam_signature.json").read_text(encoding="utf-8"))
    sam = SamClient(
        api_key="k",
        max_retries=0,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=empty)),
    )
    data, words = zone_image()
    masker = ImageMasker(
        sam=sam,
        policies=PolicySet(),
        ocr=FakeOcr(words),
        text_detector=SilentDetector(),
        entity_types=[EntityType.FACE],
    )
    outcome = masker.mask(data)
    masked = [r for r in outcome.regions if r.policy is Policy.MASK]
    assert [r.entity_type for r in masked] == [EntityType.ID_DOCUMENT]
    image = Image.open(io.BytesIO(outcome.image)).convert("RGB")
    zone = union(words)
    assert all(
        image.getpixel((x, y)) == (0, 0, 0)
        for y in range(zone.y1, zone.y2 + 1, 3)
        for x in range(zone.x1, zone.x2 + 1, 3)
    )
    plain = Image.open(io.BytesIO(mask_image(data, []))).convert("RGB")
    assert plain.getpixel((zone.x1, zone.y1)) != (0, 0, 0)


# --- real OCR ----------------------------------------------------------------------------

_MONOSPACE_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Courier.ttc",
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/cour.ttf",
)


def _monospace_font(size: int) -> ImageFont.FreeTypeFont | None:
    for path in _MONOSPACE_FONTS:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return None


@pytest.mark.skipif(not tesseract_available(), reason="pytesseract/tesseract not installed")
def test_tesseract_finds_a_rendered_td3_zone() -> None:
    font = _monospace_font(22)
    if font is None:
        pytest.skip("no monospace font found")
    image = Image.new("RGB", (760, 260), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 30), "PASSPORT  UTOPIA  (FICTIONAL SPECIMEN)", fill="black", font=font)
    drawn: Box | None = None
    for row, line in enumerate(TD3):
        left, top, right, bottom = draw.textbbox((30, 140 + row * 40), line, font=font)
        draw.text((30, 140 + row * 40), line, fill="black", font=font)
        box = Box(int(left), int(top), int(right), int(bottom))
        drawn = box if drawn is None else drawn.union(box)
    assert drawn is not None
    regions = text_regions(png_bytes(image), [SilentDetector()], ocr=TesseractOcr("eng"))
    zones = [r for r in regions if r.entity_type is EntityType.ID_DOCUMENT]
    assert len(zones) == 1
    zone = zones[0].box
    # The zone box sits on the two drawn lines, not on the heading.
    assert zone.y1 > 100
    assert abs(zone.x1 - drawn.x1) <= 15 and abs(zone.x2 - drawn.x2) <= 15
    assert abs(zone.y1 - drawn.y1) <= 15 and abs(zone.y2 - drawn.y2) <= 15
