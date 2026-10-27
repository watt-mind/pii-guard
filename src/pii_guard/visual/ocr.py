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

import contextvars
import logging
import shutil
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from PIL import Image

from pii_guard.types import DetectionError, Detector, PiiGuardError
from pii_guard.visual.captions import (
    SCORE as CAPTION_SCORE,
)
from pii_guard.visual.captions import (
    SOURCE as CAPTION_SOURCE,
)
from pii_guard.visual.captions import (
    CaptionLexicon,
    CaptionValue,
    caption_values,
)
from pii_guard.visual.image import load_image
from pii_guard.visual.mrz import MrzZone, mrz_zones
from pii_guard.visual.regions import Box, Region

__all__ = [
    "OcrEngine",
    "OcrText",
    "OcrTimeoutError",
    "OcrWord",
    "TesseractOcr",
    "TextFinding",
    "check_deadline",
    "deadline",
    "join_words",
    "ocr_text",
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


class OcrTimeoutError(DetectionError):
    """The image work ran past its deadline (:func:`deadline`): fail closed, 503."""


#: Absolute ``time.monotonic()`` by which the current image work must finish (None: no limit).
_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "pii_guard_image_deadline", default=None
)


@contextmanager
def deadline(at: float | None) -> Iterator[None]:
    """Bound the OCR (and the checks of :func:`check_deadline`) in this context by ``at``.

    ``at`` is a ``time.monotonic()`` value. Tesseract gets the remaining time as its
    subprocess timeout, so a slow image is killed rather than left running. Image work runs in
    its own worker thread, so this context is that call's alone.
    """
    token = _DEADLINE.set(at)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def remaining() -> float | None:
    """Seconds left before the current deadline (``None``: no deadline)."""
    at = _DEADLINE.get()
    return None if at is None else at - time.monotonic()


def check_deadline() -> None:
    """Raise :class:`OcrTimeoutError` once the current deadline has passed."""
    left = remaining()
    if left is not None and left <= 0:
        raise OcrTimeoutError("image masking ran past its deadline")


def tesseract_available() -> bool:
    """True if both ``pytesseract`` and the ``tesseract`` binary are installed."""
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return shutil.which("tesseract") is not None


#: Images are enlarged for OCR until their longer side reaches this many pixels.
DEFAULT_UPSCALE_TO = 2000
#: The most an image is enlarged for OCR.
MAX_UPSCALE = 4.0


class TesseractOcr:
    """Tesseract via ``pytesseract``. ``lang`` is Tesseract's language list (``"hun+eng"``).

    ``min_confidence`` drops words Tesseract itself scores below it (0-100); keep it low,
    since a dropped word is a word that can't be masked.

    ``upscale_to``: a smaller image is enlarged (Lanczos, at most :data:`MAX_UPSCALE` times)
    until its longer side has this many pixels before OCR, and the word boxes are mapped
    back. Field captions on ID cards are printed 6-10 px high at card resolution, below what
    Tesseract reads; enlarged, they come back (``Családi név / Surname``), and so do the
    values under them. ``None`` reads the image as it is.
    """

    name = "tesseract"

    def __init__(
        self,
        lang: str = "hun+eng",
        *,
        config: str = "",
        min_confidence: float = 0.0,
        upscale_to: int | None = DEFAULT_UPSCALE_TO,
    ) -> None:
        self.lang = lang
        self.config = config
        self.min_confidence = min_confidence
        self.upscale_to = upscale_to

    def scale_for(self, size: tuple[int, int]) -> float:
        """The factor :meth:`words` enlarges an image of ``size`` by (``1.0``: not at all)."""
        if not self.upscale_to or max(size) <= 0:
            return 1.0
        return max(1.0, min(MAX_UPSCALE, self.upscale_to / max(size)))

    def words(self, image: Image.Image) -> list[OcrWord]:
        try:
            import pytesseract
        except ImportError as exc:
            raise DetectionError("OCR unavailable: install the 'ocr' extra") from exc
        check_deadline()
        scale = self.scale_for(image.size)
        source = image
        if scale > 1.0:
            target = (round(image.width * scale), round(image.height * scale))
            source = image.resize(target, Image.Resampling.LANCZOS)
        check_deadline()
        left = remaining()
        try:
            data = pytesseract.image_to_data(
                source,
                lang=self.lang,
                config=self.config,
                output_type=pytesseract.Output.DICT,
                # pytesseract kills the subprocess when it runs out (0: no limit).
                timeout=max(left, 0.01) if left is not None else 0,
            )
        except RuntimeError as exc:
            if "timeout" in str(exc).lower():
                raise OcrTimeoutError("OCR ran past the image deadline") from None
            raise DetectionError(f"OCR failed ({type(exc).__name__})") from exc
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
                if scale > 1.0:
                    box = _clamp(box.scaled(1 / scale, 1 / scale), image.size)
                words.append(OcrWord(text, box, line))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DetectionError("OCR output has an unexpected format") from exc
        return words


def _clamp(box: Box, size: tuple[int, int]) -> Box:
    width, height = size
    x2, y2 = min(box.x2, width - 1), min(box.y2, height - 1)
    return Box(min(box.x1, x2), min(box.y1, y2), x2, y2)


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


@dataclass(frozen=True, slots=True)
class TextFinding:
    """One masking region found in OCR text, with the text it covers (kept in memory only).

    ``origin`` is ``"detector"`` (a text detector's span), ``"caption"`` (the value next to a
    field caption; ``caption`` says which) or ``"mrz"`` (a machine-readable zone found by its
    layout; ``text`` is its lines, newline-joined) or ``"vault"`` (a value of the vault
    session found on the image, :meth:`~pii_guard.visual.labels.VaultMatcher.find`).
    ``repr()`` omits ``text``.
    """

    region: Region
    text: str
    origin: str
    caption: str | None = None

    def __repr__(self) -> str:
        return (
            f"TextFinding(region={self.region!r}, origin={self.origin!r}, "
            f"caption={self.caption!r}, text=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class OcrText:
    """Everything one OCR pass found: the words, the masking findings (in the order
    :func:`text_regions` returns their regions), the MRZ zones, and the values of the
    non-personal captions (``Expiry``), which the document summary reads and nothing masks."""

    words: list[OcrWord]
    findings: list[TextFinding]
    zones: list[MrzZone]
    fields: list[CaptionValue]

    def __repr__(self) -> str:
        return (
            f"OcrText(words={len(self.words)}, findings={len(self.findings)}, "
            f"zones={len(self.zones)}, fields={len(self.fields)})"
        )


def text_regions(
    image: bytes | Image.Image,
    detectors: Sequence[Detector],
    *,
    ocr: OcrEngine,
    language: str = "hu",
    captions: bool | CaptionLexicon = True,
) -> list[Region]:
    """OCR ``image``, run every text detector on the recognised text, and return one region
    per detected span per text line (the union of the overlapped word boxes), plus:

    - one ``ID_DOCUMENT`` region per machine-readable zone found by its layout
      (:func:`~pii_guard.visual.mrz.mrz_regions`);
    - one region per value printed next to a known field caption (``Név``, ``Date of
      birth``; :func:`~pii_guard.visual.captions.caption_value_regions`), unless
      ``captions`` is ``False``. A :class:`~pii_guard.visual.captions.CaptionLexicon` replaces
      the language packs' captions.

    :func:`ocr_text` returns the same regions with the text they cover.
    """
    found = ocr_text(image, detectors, ocr=ocr, language=language, captions=captions)
    return [finding.region for finding in found.findings]


def ocr_text(
    image: bytes | Image.Image,
    detectors: Sequence[Detector],
    *,
    ocr: OcrEngine,
    language: str = "hu",
    captions: bool | CaptionLexicon = True,
) -> OcrText:
    """Like :func:`text_regions`, keeping the words and the text of every finding."""
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
        return OcrText([], [], [], [])
    text, offsets = join_words(words)

    # Layout-found MRZ zones: one box per zone, whatever the text detectors make of it.
    zones = mrz_zones(words)
    findings: list[TextFinding] = [
        TextFinding(zone.region, "\n".join(zone.lines), "mrz") for zone in zones
    ]
    # Values next to known field captions, whatever the text detectors make of them.
    fields: list[CaptionValue] = []
    if captions is not False:
        lexicon = captions if isinstance(captions, CaptionLexicon) else None
        for value in caption_values(words, lexicon, include_non_personal=True):
            if value.entity_type is None:
                fields.append(value)
                continue
            region = Region(value.entity_type, value.box, CAPTION_SCORE, CAPTION_SOURCE)
            findings.append(TextFinding(region, value.text, "caption", value.caption))
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
            findings.extend(
                TextFinding(
                    Region(span.entity_type, box, span.score, span.detector), span.text, "detector"
                )
                for box in by_line.values()
            )
    logger.debug("ocr: %d word(s), %d text region(s)", len(words), len(findings))
    return OcrText(words, findings, zones, fields)
