"""Synthetic test images (ADR 0005): fictional ID card drawn with Pillow, no real people.

The face is an ellipse with dots for eyes, the signature is a sine-wave scribble, and every
identifier is fictional (the TAJ and tax ID pass their checksums but belong to no one).
``tests/fixtures/visual/sam_*.json`` are live SAM 3.1 responses to :func:`id_card_png`.
If the drawing changes, re-record them (needs ``META_API_KEY``; fictional image only)::

    uv run python tests/visual/visual_helpers.py --record
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from pii_guard.visual.ocr import OcrWord
from pii_guard.visual.regions import Box

WIDTH, HEIGHT = 640, 400
FICTIONAL_NAME = "Teszt Elek"
FICTIONAL_TAJ = "123 456 788"
FICTIONAL_TAX_ID = "8123456786"

#: Where things are drawn (inclusive boxes), for assertions.
FACE_BOX = Box(70, 110, 170, 240)
PHOTO_BOX = Box(30, 80, 210, 320)
SIGNATURE_BOX = Box(248, 270, 582, 330)


TEXT_LINES: tuple[tuple[int, int, str], ...] = (
    (240, 90, f"Name: {FICTIONAL_NAME}"),
    (240, 130, f"TAJ: {FICTIONAL_TAJ}"),
    (240, 170, "Born: 1980-01-01"),
    (240, 210, f"Adoazonosito jel: {FICTIONAL_TAX_ID}"),
)


def render_id_card() -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), (235, 240, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, WIDTH - 1, 50], fill=(30, 60, 120))
    d.text((20, 12), "SAMPLE ID CARD - FICTIONAL", fill="white", font=_font(22))
    # Photo area with a drawn face.
    d.rectangle([30, 80, 210, 320], fill=(200, 210, 225), outline=(80, 80, 80), width=3)
    d.ellipse([70, 110, 170, 240], fill=(240, 200, 170), outline=(120, 80, 60), width=2)
    d.ellipse([95, 150, 110, 162], fill="black")
    d.ellipse([130, 150, 145, 162], fill="black")
    d.arc([100, 185, 140, 215], 20, 160, fill=(150, 40, 40), width=3)
    d.polygon([(120, 165), (114, 185), (126, 185)], fill=(210, 160, 130))
    d.rectangle([60, 240, 180, 320], fill=(60, 80, 140))
    # Fictional text fields.
    for x, y, text in TEXT_LINES:
        d.text((x, y), text, fill="black", font=_font(20))
    # Signature scribble.
    pts = [
        (250 + t * 2.2, 300 + 18 * math.sin(t / 6.0) + 8 * math.sin(t / 2.3)) for t in range(150)
    ]
    d.line(pts, fill=(10, 20, 120), width=3)
    d.text((250, 340), "Signature", fill=(90, 90, 90), font=_font(14))
    return img


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


class FakeOcr:
    """A perfect OCR engine for the synthetic card: the drawn words with their exact boxes.

    Lets the OCR → detector → mask path run in CI without Tesseract.
    """

    name = "fake"

    def __init__(self, words: list[OcrWord] | None = None, error: Exception | None = None):
        self._words = card_words() if words is None else words
        self._error = error
        self.calls = 0

    def words(self, image: Image.Image) -> list[OcrWord]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return list(self._words)


def card_words() -> list[OcrWord]:
    """Every word of :data:`TEXT_LINES` with its drawn bounding box."""
    draw = ImageDraw.Draw(Image.new("RGB", (WIDTH, HEIGHT)))
    font = _font(20)
    words: list[OcrWord] = []
    for line_no, (x, y, text) in enumerate(TEXT_LINES):
        pos = 0
        for word in text.split(" "):
            start = text.index(word, pos)
            pos = start + len(word)
            offset = draw.textlength(text[:start], font=font)
            left, top, right, bottom = draw.textbbox((x + offset, y), word, font=font)
            box = Box(int(left), int(top), math.ceil(right), math.ceil(bottom))
            words.append(OcrWord(word, box, (line_no,)))
    return words


def png_bytes(image: Image.Image, **save_kwargs: object) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG", **save_kwargs)
    return buf.getvalue()


def id_card_png() -> bytes:
    return png_bytes(render_id_card())


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "visual"
#: fixture name -> concept prompt sent to SAM 3.1 with the synthetic ID card.
RECORDED_PROMPTS = {"sam_face": "face", "sam_eye": "eye", "sam_signature": "signature"}


def record_fixtures() -> None:  # pragma: no cover - manual, needs network and a key
    import httpx

    from pii_guard.visual.sam import DEFAULT_BASE_URL, SamClient

    key = os.environ["META_API_KEY"]
    client = SamClient(api_key=key, base_url=DEFAULT_BASE_URL)
    data_url = "data:image/png;base64," + base64.b64encode(id_card_png()).decode()
    for name, prompt in RECORDED_PROMPTS.items():
        response = httpx.post(
            client.url,
            json=client.payload(prompt, data_url),
            headers={"Authorization": f"Bearer {key}"},
            timeout=120,
        )
        response.raise_for_status()
        path = FIXTURES / f"{name}.json"
        path.write_text(json.dumps(response.json(), indent=2) + "\n", encoding="utf-8")
        print(f"recorded {path.name}")


if __name__ == "__main__" and "--record" in sys.argv:  # pragma: no cover
    record_fixtures()
