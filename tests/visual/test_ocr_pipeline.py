"""OCR text regions and the end-to-end visual pipeline (fail closed).

CI runs the OCR path with ``FakeOcr`` (the drawn words with exact boxes). The Tesseract test
runs only where ``pytesseract`` and the ``tesseract`` binary are installed.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image
from visual_helpers import (
    FACE_BOX,
    FICTIONAL_NAME,
    FICTIONAL_TAJ,
    FICTIONAL_TAX_ID,
    FakeOcr,
    card_words,
    id_card_png,
)

from pii_guard.detect.rules import RuleDetector
from pii_guard.types import DetectionError, EntityType, MaskingError, Span
from pii_guard.visual import (
    Box,
    OcrWord,
    Region,
    SamClient,
    TesseractOcr,
    analyze_image,
    join_words,
    mask_image,
    mask_visual,
    tesseract_available,
    text_regions,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "visual"
BLACK = (0, 0, 0)


class NameDetector:
    """Stands in for the NER/LLM pass, which the rules detector does not cover: flags the
    fictional name wherever it appears."""

    name = "fake-ner"

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        start = text.find(FICTIONAL_NAME)
        if start < 0:
            return []
        end = start + len(FICTIONAL_NAME)
        return [Span(start, end, EntityType.PERSON, text[start:end], 0.9, self.name)]


class BrokenDetector:
    name = "broken"

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        raise RuntimeError("boom")


def sam_client(face_answer: object | None = None) -> SamClient:
    empty = json.loads((FIXTURES / "sam_signature.json").read_text(encoding="utf-8"))
    face = json.loads((FIXTURES / "sam_face.json").read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["input"][0]["content"][0]["text"]
        if prompt == "face":
            if isinstance(face_answer, httpx.Response):
                return face_answer
            return httpx.Response(200, json=face)
        return httpx.Response(200, json=empty)

    return SamClient(api_key="k", max_retries=0, transport=httpx.MockTransport(handler))


def pixels(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image.convert("RGB")


def covered(image: Image.Image, box: Box) -> bool:
    return all(
        image.getpixel((x, y)) == BLACK
        for y in range(box.y1, box.y2 + 1)
        for x in range(box.x1, box.x2 + 1)
    )


def word_box(*texts: str) -> Box:
    boxes = [w.box for w in card_words() if w.text in texts]
    assert boxes, texts
    result = boxes[0]
    for b in boxes[1:]:
        result = result.union(b)
    return result


# --- OCR → detectors → regions -----------------------------------------------------------


def test_join_words_lines_and_offsets() -> None:
    words = [
        OcrWord("TAJ:", Box(0, 0, 9, 9), (0,)),
        OcrWord("123", Box(12, 0, 20, 9), (0,)),
        OcrWord("Born", Box(0, 20, 9, 29), (1,)),
    ]
    text, offsets = join_words(words)
    assert text == "TAJ: 123\nBorn"
    assert [text[s:e] for s, e in offsets] == ["TAJ:", "123", "Born"]
    assert join_words([]) == ("", [])
    assert "TAJ" not in repr(words[0])


def test_text_regions_with_rules_cover_taj_and_tax_id() -> None:
    regions = text_regions(id_card_png(), [RuleDetector()], ocr=FakeOcr())
    by_type = {r.entity_type: r for r in regions}
    assert set(by_type) == {EntityType.NATIONAL_ID_HU_TAJ, EntityType.NATIONAL_ID_HU_TAX}
    assert by_type[EntityType.NATIONAL_ID_HU_TAJ].box == word_box(*FICTIONAL_TAJ.split())
    assert by_type[EntityType.NATIONAL_ID_HU_TAX].box == word_box(FICTIONAL_TAX_ID)
    assert all(r.source == "rules" for r in regions)


def test_span_over_two_lines_gives_one_region_per_line() -> None:
    words = [
        OcrWord("Teszt", Box(10, 10, 50, 20), (0,)),
        OcrWord("Elek", Box(10, 30, 40, 40), (1,)),
    ]

    class Both:
        name = "both"

        def detect(self, text: str, language: str = "hu") -> list[Span]:
            return [Span(0, len(text), EntityType.PERSON, text, 1.0, self.name)]

    regions = text_regions(id_card_png(), [Both()], ocr=FakeOcr(words))
    assert [r.box for r in regions] == [Box(10, 10, 50, 20), Box(10, 30, 40, 40)]


def test_no_words_no_regions() -> None:
    assert text_regions(id_card_png(), [RuleDetector()], ocr=FakeOcr([])) == []


def test_ocr_and_detector_failures_fail_closed() -> None:
    with pytest.raises(DetectionError, match="OCR failed"):
        text_regions(id_card_png(), [RuleDetector()], ocr=FakeOcr(error=RuntimeError("x")))
    with pytest.raises(DetectionError, match="unavailable"):
        text_regions(
            id_card_png(), [RuleDetector()], ocr=FakeOcr(error=DetectionError("unavailable"))
        )
    with pytest.raises(DetectionError, match="broken"):
        text_regions(id_card_png(), [BrokenDetector()], ocr=FakeOcr())
    with pytest.raises(DetectionError):
        text_regions(id_card_png(), [], ocr=FakeOcr())
    with pytest.raises(DetectionError, match="decoded"):
        text_regions(b"junk", [RuleDetector()], ocr=FakeOcr())


def test_span_that_maps_to_no_word_fails_closed() -> None:
    class OffEnd:
        name = "off-end"

        def detect(self, text: str, language: str = "hu") -> list[Span]:
            # Lies on the newline between two lines: overlaps no word.
            i = text.index("\n")
            return [Span(i, i + 1, EntityType.PERSON, "\n", 1.0, self.name)]

    with pytest.raises(DetectionError, match="OCR word"):
        text_regions(id_card_png(), [OffEnd()], ocr=FakeOcr())


def test_tesseract_missing_raises_detection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def no_pytesseract(name: str, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if name == "pytesseract":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", no_pytesseract)
    assert tesseract_available() is False
    with pytest.raises(DetectionError, match="ocr"):
        TesseractOcr().words(Image.new("RGB", (10, 10)))


# --- pipeline ----------------------------------------------------------------------------


def test_mask_visual_covers_face_and_text_pii() -> None:
    result = mask_visual(
        id_card_png(),
        sam=sam_client(),
        ocr=FakeOcr(),
        detectors=[RuleDetector(), NameDetector()],
        padding=0,
    )
    types = sorted(r.entity_type.value for r in result.regions)
    assert types == ["FACE", "NATIONAL_ID_HU_TAJ", "NATIONAL_ID_HU_TAX", "PERSON"]
    image = pixels(result.image)
    for r in result.regions:
        assert covered(image, r.box), r
    face = next(r for r in result.regions if r.entity_type is EntityType.FACE)
    # The SAM box covers the drawn face's interior.
    assert face.box.x1 <= FACE_BOX.x1 + 3 and face.box.x2 >= FACE_BOX.x2 - 3
    assert "bytes" in repr(result)


def test_analyze_image_sam_only() -> None:
    regions = analyze_image(id_card_png(), sam=sam_client(), entity_types=["FACE"])
    assert [r.entity_type for r in regions] == [EntityType.FACE]


def test_sam_failure_returns_no_image() -> None:
    with pytest.raises(DetectionError):
        mask_visual(
            id_card_png(),
            sam=sam_client(httpx.Response(500)),
            ocr=FakeOcr(),
            detectors=[RuleDetector()],
        )


def test_ocr_failure_returns_no_image() -> None:
    with pytest.raises(DetectionError):
        mask_visual(
            id_card_png(),
            sam=sam_client(),
            ocr=FakeOcr(error=OSError("tesseract crashed")),
            detectors=[RuleDetector()],
        )


def test_unexpected_error_inside_sam_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    client = sam_client()
    monkeypatch.setattr(client, "segment", lambda *a, **k: 1 / 0)
    with pytest.raises(DetectionError, match="ZeroDivisionError"):
        mask_visual(id_card_png(), sam=client)


def test_masking_failure_returns_no_image(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_encode(*args: object, **kwargs: object) -> bytes:
        raise OSError("disk full")

    monkeypatch.setattr("pii_guard.visual.image.encode_image", broken_encode)
    with pytest.raises(MaskingError):
        mask_visual(id_card_png(), sam=sam_client())


def test_misconfiguration_fails_closed() -> None:
    with pytest.raises(DetectionError, match="no visual detector"):
        mask_visual(id_card_png())
    with pytest.raises(DetectionError, match="text detector"):
        mask_visual(id_card_png(), ocr=FakeOcr())
    with pytest.raises(DetectionError, match="decoded"):
        mask_visual(b"junk", sam=sam_client())


def test_region_validation_and_public_dict() -> None:
    r = Region("FACE", Box(1, 2, 3, 4), None, "sam")  # type: ignore[arg-type]
    assert r.entity_type is EntityType.FACE
    assert r.to_public_dict() == {
        "entity_type": "FACE",
        "box": [1, 2, 3, 4],
        "score": None,
        "source": "sam",
    }
    with pytest.raises(ValueError):
        Region("NOPE", Box(0, 0, 1, 1), None, "sam")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Region(EntityType.FACE, Box(0, 0, 1, 1), 1.5, "sam")
    with pytest.raises(ValueError):
        Region(EntityType.FACE, Box(0, 0, 1, 1), None, "")
    for bad in [(-1, 0, 1, 1), (5, 0, 1, 1), (0, 5, 1, 1), (0.5, 0, 1, 1), (True, 0, 1, 1)]:
        with pytest.raises(ValueError):
            Box(*bad)  # type: ignore[arg-type]
    box = Box(10, 10, 19, 19)
    assert (box.width, box.height) == (10, 10)
    assert box.scaled(0.5, 2).to_list() == [5, 20, 9, 39]


# --- real OCR (optional) -----------------------------------------------------------------


@pytest.mark.skipif(not tesseract_available(), reason="pytesseract/tesseract not installed")
def test_tesseract_masks_text_pii_on_the_synthetic_card() -> None:
    ocr = TesseractOcr("hun+eng")
    regions = text_regions(id_card_png(), [RuleDetector()], ocr=ocr)
    types = {r.entity_type for r in regions}
    assert {EntityType.NATIONAL_ID_HU_TAJ, EntityType.NATIONAL_ID_HU_TAX} <= types
    masked = pixels(mask_image(id_card_png(), regions, padding=0))
    for r in regions:
        assert covered(masked, r.box)
    # The OCR boxes sit on the drawn identifiers.
    taj = next(r for r in regions if r.entity_type is EntityType.NATIONAL_ID_HU_TAJ)
    expected = word_box(*FICTIONAL_TAJ.split())
    assert abs(taj.box.x1 - expected.x1) <= 6 and abs(taj.box.x2 - expected.x2) <= 6
