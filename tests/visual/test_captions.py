"""Caption-adjacent value masking (``visual/captions.py``) on synthetic OCR words.

Every layout is built from fictional words with hand-placed boxes (ADR 0005: no real
documents); one test renders a card with Pillow and reads it with real Tesseract.
"""

from __future__ import annotations

from importlib.resources import files

import pytest
from PIL import Image, ImageDraw, ImageFont
from visual_helpers import FakeOcr, id_card_png, png_bytes

from pii_guard.detect.rules import RuleDetector
from pii_guard.languages import LanguagePack, get_pack, register_pack, unregister_pack
from pii_guard.languages.conformance import check_structure
from pii_guard.types import EntityType
from pii_guard.visual.captions import (
    EXTRA_CAPTIONS,
    SOURCE,
    Caption,
    CaptionLexicon,
    caption_value_regions,
    caption_values,
    default_lexicon,
    parse_captions,
)
from pii_guard.visual.ocr import OcrWord, TesseractOcr, tesseract_available, text_regions
from pii_guard.visual.pipeline import mask_visual
from pii_guard.visual.regions import Box

CHAR = 9  # px per character of a caption-size word in these layouts


def line(text: str, x: int, y: int, h: int, key: int, *, char: int = CHAR) -> list[OcrWord]:
    """One OCR line: the words of ``text`` left to right, one space (``char`` px) apart."""
    words = []
    for token in text.split(" "):
        width = max(1, len(token)) * char
        words.append(OcrWord(token, Box(x, y, x + width - 1, y + h - 1), (key,)))
        x += width + char
    return words


def values(words: list[OcrWord]) -> list[tuple[str, EntityType, str]]:
    return [(v.caption, v.entity_type, v.text) for v in caption_values(words)]


# --- the lexicon ----------------------------------------------------------------------------


def test_parse_captions() -> None:
    text = "# comment\n\nNév\tPERSON\nNem\t-\n"
    assert parse_captions(text, "hu") == (
        Caption("Név", EntityType.PERSON, "hu"),
        Caption("Nem", None, "hu"),
    )


@pytest.mark.parametrize(
    "text",
    ["Név PERSON\n", "Név\tPERSON\textra\n", "Név\tNOT_A_TYPE\n", "--\tPERSON\n", "Név\t\n"],
)
def test_parse_captions_rejects_malformed_lines(text: str) -> None:
    with pytest.raises(ValueError, match="line 1"):
        parse_captions(text, "hu")


@pytest.mark.parametrize("code", ["hu", "en", "de"])
def test_builtin_packs_ship_captions_that_conform(code: str) -> None:
    pack = get_pack(code)
    assert pack is not None and pack.captions is not None
    assert not [f for f in check_structure(pack) if f.check == "structure.captions"]


def test_default_lexicon_has_every_pack_and_the_extras() -> None:
    languages = {c.language for c in default_lexicon().captions}
    assert {"hu", "en", "de"} <= languages
    assert {c.language for c in EXTRA_CAPTIONS} <= languages


def test_conformance_reports_a_broken_captions_file(tmp_path) -> None:
    bad = tmp_path / "captions.tsv"
    bad.write_text("Név\tNO_SUCH_TYPE\n", encoding="utf-8")
    pack = LanguagePack(code="xx", name="Test", captions=bad)  # type: ignore[arg-type]
    findings = [f for f in check_structure(pack) if f.check == "structure.captions"]
    assert findings and findings[0].severity == "error"


@pytest.mark.parametrize(
    ("ocr", "caption"),
    [
        ("Date of birth", "Date of birth"),
        ("Date of bith", "Date of birth"),  # a letter lost in small print
        ("Sumame", "Surname"),  # "rn" read as "m"
        ("Születési idő", "Születési idő"),
        ("Szuletesi ido", "Születési idő"),  # accents lost
        ("Documentno", "Document no"),  # two words read as one
        ("Personal ne", "Personal no"),
        ("Nem", "Nem"),
    ],
)
def test_fuzzy_match(ocr: str, caption: str) -> None:
    from pii_guard.visual.captions import _tokens

    found = default_lexicon().match(_tokens(ocr), 0)
    assert found is not None and found[0].text == caption


@pytest.mark.parametrize("ocr", ["personal", "Nemes", "Namen", "Dates", "Born"])
def test_fuzzy_match_negatives(ocr: str) -> None:
    from pii_guard.visual.captions import _tokens

    lexicon = default_lexicon()
    found = lexicon.match(_tokens(ocr), 0)
    # "personal" is not "Personal no": a whole token may not be dropped.
    assert found is None or found[0].key == "".join(_tokens(ocr))


# --- layouts ------------------------------------------------------------------------------


def test_caption_above_value() -> None:
    words = [
        *line("Családi név / Surname", 320, 117, 8, 0),
        *line("FIKTÍV", 320, 129, 20, 1, char=14),
        *line("Utónév / Given names", 320, 163, 8, 2),
        *line("MÁRIA", 320, 175, 20, 3, char=14),
    ]
    found = caption_values(words)
    assert [(v.caption, v.entity_type, v.text) for v in found] == [
        ("Családi név", EntityType.PERSON, "FIKTÍV"),
        ("Utónév", EntityType.PERSON, "MÁRIA"),
    ]
    value = found[0]
    # The box covers the value word (grown a little), never the caption.
    assert value.box.x1 <= 320 and value.box.y1 <= 129 and value.box.y2 >= 148
    assert value.box.y1 > value.caption_box.y2


def test_two_columns_on_one_caption_line() -> None:
    words = [
        *line("Állampolgárság / Nationality", 380, 222, 10, 0),
        *line("Okmányszám / Document no.", 650, 222, 10, 0),
        *line("UTO", 380, 241, 17, 1, char=12),
        *line("KK7406302", 650, 241, 17, 1, char=12),
    ]
    # Nationality is not personal data: only the document number is masked.
    assert values(words) == [("Okmányszám", EntityType.ID_DOCUMENT, "KK7406302")]


def test_columns_on_separate_ocr_lines() -> None:
    # Tesseract often reads side-by-side captions as separate lines.
    words = [
        *line("Születési idő / Date of birth", 320, 208, 8, 0),
        *line("Nem / Sex", 650, 206, 8, 1),
        *line("1959.01.02.", 320, 223, 16, 2, char=12),
        *line("F", 650, 223, 16, 3, char=12),
    ]
    assert values(words) == [("Születési idő", EntityType.DATE_OF_BIRTH, "1959.01.02.")]


def test_value_on_the_same_line() -> None:
    words = [
        *line("Telefon: +36 30 991 6175", 110, 552, 15, 0),
        *line("Adóazonosító jel: 8452456328", 110, 588, 15, 1),
        *line("PRUMENI / SURNAME SPECIMEN", 22, 84, 10, 2),
    ]
    assert values(words) == [
        ("Telefon", EntityType.PHONE, "+36 30 991 6175"),
        ("Adóazonosító jel", EntityType.NATIONAL_ID_HU_TAX, "8452456328"),
        ("Surname", EntityType.PERSON, "SPECIMEN"),
    ]


def test_value_on_two_lines_is_one_block() -> None:
    words = [
        *line("Lakcím / Address", 300, 263, 9, 0),
        *line("4024 Debrecen,", 300, 281, 16, 1, char=11),
        *line("Próba sor 58.", 300, 299, 16, 2, char=11),
    ]
    [value] = caption_values(words)
    assert value.entity_type is EntityType.ADDRESS
    assert value.text == "4024 Debrecen, Próba sor 58."
    assert value.box.y1 <= 281 and value.box.y2 >= 314


def test_value_stops_at_the_next_caption() -> None:
    # OCR lost the surname: the next caption's value must not be taken for it.
    words = [
        *line("Családi név / Surname", 320, 117, 8, 0),
        *line("Érvényes / Expiry", 320, 163, 8, 1),
        *line("2031.06.30.", 320, 175, 20, 2, char=12),
    ]
    assert values(words) == []


def test_value_split_where_far_apart() -> None:
    words = [
        *line("Date of birth", 50, 160, 8, 0),
        *line("01 APR 1956", 50, 178, 16, 1, char=11),
        *line("Norwich", 400, 178, 16, 1, char=11),
    ]
    assert [v.text for v in caption_values(words)] == ["01 APR 1956", "Norwich"]


def test_caption_inside_running_text_is_not_a_caption() -> None:
    words = [
        *line("Our records show the name Anna Kovacs.", 80, 400, 15, 0),
        *line("Please confirm your address and phone below.", 80, 440, 15, 1),
        *line("Anna Kovacs", 80, 470, 15, 2),
    ]
    assert values(words) == []


def test_caption_with_colon_inside_text_is_a_caption() -> None:
    words = line("Kérjük erősítse meg, E-mail: anna.minta@example.org", 80, 400, 15, 0)
    assert [(v.entity_type, v.text) for v in caption_values(words)] == [
        (EntityType.EMAIL, "anna.minta@example.org")
    ]


def test_non_personal_caption_alone_masks_nothing() -> None:
    words = [*line("Nationality", 50, 100, 8, 0), *line("UTO", 50, 112, 16, 1, char=12)]
    assert values(words) == []


def test_eu_driving_licence_field_numbers() -> None:
    words = [
        *line("1. ROSSI", 156, 52, 11, 0),
        *line("2. MARIA", 156, 74, 11, 1),
        *line("3. 01/01/65 ROMA (RM)", 156, 96, 12, 2),
        *line("4a. 01/03/2014", 156, 119, 12, 3),
        *line("4c. MIT-UCO", 400, 119, 12, 3),
        *line("5. AOA000000A", 156, 164, 11, 4),
    ]
    assert values(words) == [
        ("1.", EntityType.PERSON, "ROSSI"),
        ("2.", EntityType.PERSON, "MARIA"),
        ("3.", EntityType.DATE_OF_BIRTH, "01/01/65 ROMA (RM)"),
        ("5.", EntityType.ID_DOCUMENT, "AOA000000A"),
    ]


def test_a_numbered_list_is_not_a_licence() -> None:
    words = [*line("1. Kérjük töltse ki", 80, 400, 15, 0), *line("Anna", 80, 430, 15, 1)]
    assert values(words) == []


def test_custom_lexicon_and_empty_input() -> None:
    lexicon = CaptionLexicon([Caption("Codice", EntityType.ID_DOCUMENT, "it")])
    words = [*line("Codice", 50, 100, 8, 0), *line("ABC123", 50, 112, 16, 1, char=12)]
    assert [(v.caption, v.text) for v in caption_values(words, lexicon)] == [("Codice", "ABC123")]
    assert caption_values([], lexicon) == []
    assert caption_values(words, CaptionLexicon([])) == []


def test_regions_and_repr_carry_no_text() -> None:
    words = [*line("Name", 50, 100, 8, 0), *line("Teszt Elek", 50, 112, 16, 1, char=12)]
    [value] = caption_values(words)
    assert "Teszt" not in repr(value) and "redacted" in repr(value)
    [region] = caption_value_regions(words)
    assert region.source == SOURCE and region.entity_type is EntityType.PERSON
    assert region.box == value.box


# --- integration ------------------------------------------------------------------------------


def test_text_regions_adds_caption_values() -> None:
    # The synthetic card prints "Name: Teszt Elek"; no text detector finds the name.
    regions = text_regions(id_card_png(), [RuleDetector()], ocr=FakeOcr())
    by_source = {(r.source, r.entity_type) for r in regions}
    assert (SOURCE, EntityType.PERSON) in by_source
    off = text_regions(id_card_png(), [RuleDetector()], ocr=FakeOcr(), captions=False)
    assert all(r.source != SOURCE for r in off)
    custom = text_regions(
        id_card_png(),
        [RuleDetector()],
        ocr=FakeOcr(),
        captions=CaptionLexicon([Caption("Born", EntityType.DATE_OF_BIRTH, "en")]),
    )
    assert {r.entity_type for r in custom if r.source == SOURCE} == {EntityType.DATE_OF_BIRTH}


def test_mask_visual_covers_the_caption_value() -> None:
    result = mask_visual(id_card_png(), ocr=FakeOcr(), detectors=[RuleDetector()], padding=0)
    [name] = [r for r in result.regions if r.source == SOURCE and r.entity_type.value == "PERSON"]
    from io import BytesIO

    image = Image.open(BytesIO(result.image)).convert("RGB")
    cx, cy = (name.box.x1 + name.box.x2) // 2, (name.box.y1 + name.box.y2) // 2
    assert image.getpixel((cx, cy)) == (0, 0, 0)


def test_a_registered_pack_brings_its_captions(tmp_path) -> None:
    resource = tmp_path / "captions.tsv"
    resource.write_text("Kodu\tID_DOCUMENT\n", encoding="utf-8")
    pack = LanguagePack(
        code="et",
        name="Estonian",
        prompt=files("pii_guard.languages.en").joinpath("prompt.md"),
        captions=resource,  # type: ignore[arg-type]
    )
    register_pack(pack)
    try:
        assert any(c.text == "Kodu" for c in default_lexicon().captions)
    finally:
        unregister_pack("et")
    assert not any(c.text == "Kodu" for c in default_lexicon().captions)


def _render_card() -> Image.Image:
    """A fictional card with 9 px captions above 20 px values, as on real ID cards."""
    img = Image.new("RGB", (640, 400), (240, 244, 250))
    draw = ImageDraw.Draw(img)
    small, big = ImageFont.load_default(size=11), ImageFont.load_default(size=22)
    rows = [
        ("Családi név / Surname", "FIKTÍV"),
        ("Utónév / Given names", "MÁRIA"),
        ("Születési idő / Date of birth", "1959.01.02."),
    ]
    for i, (caption, value) in enumerate(rows):
        y = 60 + i * 70
        draw.text((220, y), caption, fill=(80, 80, 90), font=small)
        draw.text((220, y + 16), value, fill="black", font=big)
    return img


@pytest.mark.skipif(not tesseract_available(), reason="tesseract not installed")
def test_real_tesseract_reads_small_captions_and_masks_values() -> None:
    data = png_bytes(_render_card())
    regions = text_regions(data, [RuleDetector()], ocr=TesseractOcr(lang="eng"))
    types = sorted(r.entity_type.value for r in regions if r.source == SOURCE)
    assert types == ["DATE_OF_BIRTH", "PERSON", "PERSON"]
