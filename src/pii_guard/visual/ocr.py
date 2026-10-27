"""Text in images: OCR word boxes → text detectors → word-box regions.

The OCR engine is pluggable (:class:`OcrEngine`). :class:`TesseractOcr` uses Tesseract through
``pytesseract`` (install the ``ocr`` extra and the ``tesseract`` binary with the language
data you need, e.g. ``hun`` and ``eng``).

The recognised words are joined into one text (single spaces within a line, newlines between
lines), so a text detector sees ``TAJ: 123 456 788`` exactly as on the page, and each detected
span maps back to the words it overlaps. A span that runs over several lines yields one
region per line, so the cover stays tight.

Fail closed (ADR 0006): a missing engine, an OCR failure or a detector failure raises
:class:`~pii_guard.types.DetectionError`.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from PIL import Image

from pii_guard.types import DetectionError, Detector, PiiGuardError
from pii_guard.visual.image import load_image
from pii_guard.visual.mrz import mrz_regions
from pii_guard.visual.regions import Box, Region

__all__ = [
    "OcrEngine",
    "OcrWord",
    "TesseractOcr",
    "join_words",
    "tesseract_available",
    "text_regions",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OcrWord:
    """One recognised word: its text, its box and the line it belongs to.

    ``line`` is any hashable key shared by the words of one text line, in reading order.
    ``repr()`` omits ``text``.
    """

    text: str
    box: Box
    line: tuple[int, ...]

    def __repr__(self) -> str:
        return f"OcrWord(box={self.box!r}, line={self.line!r}, text=<redacted>)"


@runtime_checkable
class OcrEngine(Protocol):
    """Anything that returns the words of an image in reading order."""

    name: str

    def words(self, image: Image.Image) -> list[OcrWord]: ...


def tesseract_available() -> bool:
    """True if both ``pytesseract`` and the ``tesseract`` binary are installed."""
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return shutil.which("tesseract") is not None


class TesseractOcr:
    """Tesseract via ``pytesseract``. ``lang`` is Tesseract's language list (``"hun+eng"``).

    ``min_confidence`` drops words Tesseract itself scores below it (0-100); keep it low,
    since a dropped word is a word that can't be masked.
    """

    name = "tesseract"

    def __init__(
        self, lang: str = "hun+eng", *, config: str = "", min_confidence: float = 0.0
    ) -> None:
        self.lang = lang
        self.config = config
        self.min_confidence = min_confidence

    def words(self, image: Image.Image) -> list[OcrWord]:
        try:
            import pytesseract
        except ImportError as exc:
            raise DetectionError("OCR unavailable: install the 'ocr' extra") from exc
        try:
            data = pytesseract.image_to_data(
                image,
                lang=self.lang,
                config=self.config,
                output_type=pytesseract.Output.DICT,
            )
        except Exception as exc:
            raise DetectionError(f"OCR failed ({type(exc).__name__})") from exc
        words: list[OcrWord] = []
        try:
            for i, text in enumerate(data["text"]):
                text = (text or "").strip()
                if not text or float(data["conf"][i]) < self.min_confidence:
                    continue
                left, top = int(data["left"][i]), int(data["top"][i])
                width, height = int(data["width"][i]), int(data["height"][i])
                if width <= 0 or height <= 0:
                    continue
                line = (
                    int(data["page_num"][i]),
                    int(data["block_num"][i]),
                    int(data["par_num"][i]),
                    int(data["line_num"][i]),
                )
                box = Box(left, top, left + width - 1, top + height - 1)
                words.append(OcrWord(text, box, line))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DetectionError("OCR output has an unexpected format") from exc
        return words


def join_words(words: Sequence[OcrWord]) -> tuple[str, list[tuple[int, int]]]:
    """Join words into one text; return it and each word's ``(start, end)`` offsets."""
    parts: list[str] = []
    offsets: list[tuple[int, int]] = []
    pos = 0
    previous_line: tuple[int, ...] | None = None
    for index, word in enumerate(words):
        if index:
            sep = " " if word.line == previous_line else "\n"
            parts.append(sep)
            pos += 1
        parts.append(word.text)
        offsets.append((pos, pos + len(word.text)))
        pos += len(word.text)
        previous_line = word.line
    return "".join(parts), offsets


def text_regions(
    image: bytes | Image.Image,
    detectors: Sequence[Detector],
    *,
    ocr: OcrEngine,
    language: str = "hu",
) -> list[Region]:
    """OCR ``image``, run every text detector on the recognised text, and return one region
    per detected span per text line (the union of the overlapped word boxes), plus one
    ``ID_DOCUMENT`` region per machine-readable zone found by its layout
    (:func:`~pii_guard.visual.mrz.mrz_regions`).
    """
    if not detectors:
        raise DetectionError("no text detector configured for OCR text")
    if isinstance(image, Image.Image):
        decoded = image
    else:
        try:
            decoded = load_image(bytes(image))
        except ValueError as exc:
            raise DetectionError("image could not be decoded for OCR") from exc
    try:
        words = ocr.words(decoded)
    except PiiGuardError:
        raise
    except Exception as exc:
        raise DetectionError(f"OCR failed ({type(exc).__name__})") from exc
    if not words:
        return []
    text, offsets = join_words(words)

    # Layout-found MRZ zones: one box per zone, whatever the text detectors make of it.
    regions: list[Region] = mrz_regions(words)
    for detector in detectors:
        try:
            spans = detector.detect(text, language)
        except PiiGuardError:
            raise
        except Exception as exc:
            raise DetectionError(f"detector {detector.name!r} failed on OCR text") from exc
        for span in spans:
            by_line: dict[tuple[int, ...], Box] = {}
            for word, (start, end) in zip(words, offsets, strict=True):
                if start < span.end and span.start < end:
                    current = by_line.get(word.line)
                    by_line[word.line] = word.box if current is None else current.union(word.box)
            if not by_line:
                raise DetectionError("detected span does not map to any OCR word")
            regions.extend(
                Region(span.entity_type, box, span.score, span.detector) for box in by_line.values()
            )
    logger.debug("ocr: %d word(s), %d text region(s)", len(words), len(regions))
    return regions
