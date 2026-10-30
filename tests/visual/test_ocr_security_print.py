"""Security-printed documents (LAB-1183): a poor reading of a colour-printed page is read again
with the coloured background suppressed, and the better reading wins.

CI has no Tesseract, so a fake ``pytesseract`` stands in: it reads the fictional TAJ number
confidently from a page whose background is white, and junk from one with a tinted (pastel
guilloche-like) background, the way Tesseract misreads values on security print.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from PIL import Image, ImageDraw
from visual_helpers import FICTIONAL_TAJ

from pii_guard.visual.ocr import TesseractOcr, suppress_background

PASTEL = (190, 235, 200)  # a light green guilloche tint
INK = (20, 20, 20)


class FakeTesseract:
    class Output:
        DICT = "dict"

    def __init__(self) -> None:
        self.configs: list[str] = []
        self.modes: list[str] = []
        #: Read junk whatever the image (the suppressed page reads no better).
        self.always_junk = False

    def image_to_data(self, image: Image.Image, **kwargs: Any) -> dict[str, list[Any]]:
        self.configs.append(kwargs.get("config", ""))
        self.modes.append(image.mode)
        grey = image.convert("L")
        # The page's background: its top-left corner.
        clean = grey.getpixel((2, 2)) >= 230 and not self.always_junk
        texts = ["TAJ:", *FICTIONAL_TAJ.split()] if clean else ["~#", "1Z3", "4S6", "7B8"]
        conf = 95.0 if clean else 20.0
        scale = image.width / 600
        data: dict[str, list[Any]] = {
            k: []
            for k in (
                *("text", "conf", "left", "top", "width", "height"),
                *("page_num", "block_num", "par_num", "line_num"),
            )
        }
        for i, text in enumerate(texts):
            row = (text, conf, round((100 + 70 * i) * scale), round(100 * scale))
            row += (round(60 * scale), round(20 * scale), 1, 1, 1, 1)
            for key, value in zip(data, row, strict=True):
                data[key].append(value)
        return data


@pytest.fixture
def fake_tesseract(monkeypatch: pytest.MonkeyPatch) -> FakeTesseract:
    fake = FakeTesseract()
    module = types.ModuleType("pytesseract")
    module.Output = FakeTesseract.Output  # type: ignore[attr-defined]
    module.image_to_data = fake.image_to_data  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pytesseract", module)
    return fake


def page(background: tuple[int, int, int] | str = PASTEL) -> Image.Image:
    image = Image.new("RGB", (600, 300), background)
    ImageDraw.Draw(image).rectangle([100, 100, 400, 119], fill=INK)
    return image


def ocr(**kwargs: Any) -> TesseractOcr:
    return TesseractOcr(upscale_to=None, orient=False, deskew=False, small_text=False, **kwargs)


def test_suppress_background_keeps_dark_ink_and_whitens_a_pastel_tint() -> None:
    out = suppress_background(page())
    assert out.mode == "L"
    assert out.size == (600, 300)
    assert out.getpixel((10, 10)) >= 235  # the tint, near white
    assert out.getpixel((200, 110)) <= 20  # the ink, still dark


def test_a_security_printed_page_is_read_again_with_its_background_suppressed(
    fake_tesseract: FakeTesseract,
) -> None:
    words = ocr().words(page())
    assert [w.text for w in words] == ["TAJ:", *FICTIONAL_TAJ.split()]
    assert len(fake_tesseract.configs) == 2
    assert fake_tesseract.modes[1] == "L"
    # Values sit apart from their captions on a card: the second pass reads sparse text.
    assert "--psm 11" in fake_tesseract.configs[1]
    # Boxes are in input pixels.
    assert words[0].box.x1 == 100 and words[0].box.y1 == 100


def test_a_clean_page_is_read_once(fake_tesseract: FakeTesseract) -> None:
    words = ocr().words(page("white"))
    assert words[0].text == "TAJ:"
    assert len(fake_tesseract.configs) == 1


def test_a_grey_page_read_poorly_is_not_read_again(fake_tesseract: FakeTesseract) -> None:
    ocr().words(page((200, 200, 200)))
    assert len(fake_tesseract.configs) == 1  # no colour to suppress


def test_the_first_reading_wins_when_the_suppressed_one_is_no_better(
    fake_tesseract: FakeTesseract,
) -> None:
    fake_tesseract.always_junk = True
    words = ocr().words(page())
    assert len(fake_tesseract.configs) == 2
    assert [w.text for w in words] == ["~#", "1Z3", "4S6", "7B8"]
    assert fake_tesseract.modes[0] == "RGB"


def test_the_second_pass_can_be_turned_off(fake_tesseract: FakeTesseract) -> None:
    ocr(suppress=False).words(page())
    assert len(fake_tesseract.configs) == 1


def test_the_second_pass_is_scaled_like_the_first(fake_tesseract: FakeTesseract) -> None:
    engine = TesseractOcr(upscale_to=1200, orient=False, deskew=False, small_text=False)
    words = engine.words(page())
    assert words[0].text == "TAJ:"
    assert words[0].box.x1 == 100 and words[0].box.y1 == 100
