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
import itertools
import logging
import math
import shutil
import statistics
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

from PIL import Image, ImageChops, ImageOps

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
    "OcrPage",
    "OcrText",
    "OcrTimeoutError",
    "OcrWord",
    "PageFrame",
    "TesseractOcr",
    "TextFinding",
    "check_deadline",
    "deadline",
    "estimate_skew",
    "join_words",
    "ocr_text",
    "suppress_background",
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
#: The most an image (or a tile of small text, :data:`MIN_TEXT_HEIGHT`) is enlarged for OCR.
MAX_UPSCALE = 4.0
#: A text line under this many pixels high, as Tesseract read it, is read again on its own,
#: enlarged to :data:`TARGET_TEXT_HEIGHT`. 11 px screenshot text comes back 8 px high and
#: misread (``123 456 788`` as ``123 458788``); enlarged four times it reads right.
MIN_TEXT_HEIGHT = 12
#: The line height a small-text tile is enlarged to.
TARGET_TEXT_HEIGHT = 40
#: At most this many small-text tiles are read again (more: one tile around all of them).
MAX_TILES = 12
#: The most pixels all the enlarged small-text tiles of one image may have together.
MAX_TILE_PIXELS = 24_000_000
#: A reading whose share of confidently read characters is below this is poor: the image is
#: read again upside down (a quarter turn either way when its words stand upright).
#: Measured on the fictional set (LAB-1210): upright documents read 0.72-1.0, rotated ones
#: 0.03-0.28.
POOR_READING = 0.35
#: A page read below :data:`GOOD_READING` whose pixels are at least this share tinted (a
#: coloured security print: guilloche, rainbow print) is read again with the background
#: suppressed (:func:`suppress_background`). The 65 official specimens are 6-91 % tinted, a
#: screenshot or a scan of black print on white about 0 %.
TINTED_PAGE = 0.05
#: A pixel whose channels differ by more than this counts as tinted.
TINT = 24
#: Tesseract's page segmentation for the suppressed reading: sparse text. Values on an ID card
#: are scattered blocks between captions, not paragraphs (LAB-1183).
SPARSE_TEXT = "--psm 11"
#: A reading at least this confident is taken as upright without trying another orientation.
#: Between :data:`POOR_READING` and this, Tesseract's orientation detection (OSD) decides
#: whether an upside-down reading is worth a pass: the fictional card upside down reads 0.37,
#: while half of the official specimens read below 0.53 upright.
GOOD_READING = 0.7
#: Tesseract's own confidence (0-100) for a character to count as confidently read.
CONFIDENT = 60.0
#: The skew search: up to this many degrees either way.
MAX_SKEW = 20.0
#: A skew estimate smaller than this many degrees is left alone (Tesseract copes with it).
MIN_SKEW = 1.0


@dataclass(frozen=True, slots=True)
class PageFrame:
    """Where OCR read an image: the input turned ``angle`` degrees counter-clockwise about its
    centre on a canvas grown to hold all of it (Pillow's ``rotate(angle, expand=True)``),
    ``size`` pixels. ``angle == 0``: the input itself. Quarter turns put a sideways or
    upside-down document upright, the rest of the angle straightens a skewed one."""

    angle: float
    source_size: tuple[int, int]
    size: tuple[int, int]

    @classmethod
    def of(cls, source_size: tuple[int, int], angle: float) -> PageFrame:
        angle = angle % 360.0
        if angle == 0:
            return cls(0.0, source_size, source_size)
        w, h = source_size
        c, s = abs(math.cos(math.radians(angle))), abs(math.sin(math.radians(angle)))
        if angle in (90.0, 270.0):
            return cls(angle, source_size, (h, w))
        if angle == 180.0:
            return cls(angle, source_size, source_size)
        # Pillow's expand: the rotated corners' bounding box, rounded the same way.
        size = (math.ceil(w * c + h * s - 1e-9), math.ceil(w * s + h * c - 1e-9))
        return cls(angle, source_size, size)

    @property
    def identity(self) -> bool:
        return self.angle == 0.0

    def render(self, image: Image.Image) -> Image.Image:
        """``image`` (of :attr:`source_size`) in this frame."""
        if self.identity:
            return image
        if self.angle in (90.0, 180.0, 270.0):
            turn = {
                90.0: Image.Transpose.ROTATE_90,
                180.0: Image.Transpose.ROTATE_180,
                270.0: Image.Transpose.ROTATE_270,
            }[self.angle]
            return image.transpose(turn)
        out = image.rotate(
            self.angle, Image.Resampling.BICUBIC, expand=True, fillcolor=_background(image)
        )
        if out.size != self.size:  # never expected; keep the frame's geometry authoritative
            out = out.crop((0, 0, *self.size))
        return out

    def to_source(self, box: Box) -> Box:
        """``box`` (in this frame) in the input: the bounding box of its turned corners, so
        it covers at least what the box covers here (slightly more for a skewed page)."""
        if self.identity:
            return box
        sw, sh = self.source_size
        fw, fh = self.size
        rad = math.radians(self.angle)
        cos, sin = math.cos(rad), math.sin(rad)
        xs: list[float] = []
        ys: list[float] = []
        for x, y in (
            (box.x1, box.y1),
            (box.x2 + 1, box.y1),
            (box.x1, box.y2 + 1),
            (box.x2 + 1, box.y2 + 1),
        ):
            dx, dy = x - fw / 2, y - fh / 2
            # Frame -> source: undo a counter-clockwise turn on y-down pixel axes.
            xs.append(cos * dx - sin * dy + sw / 2)
            ys.append(sin * dx + cos * dy + sh / 2)
        x1 = max(0, math.floor(min(xs) + 1e-6))
        y1 = max(0, math.floor(min(ys) + 1e-6))
        x2 = min(sw - 1, math.ceil(max(xs) - 1e-6) - 1)
        y2 = min(sh - 1, math.ceil(max(ys) - 1e-6) - 1)
        return Box(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))


@dataclass(frozen=True, slots=True)
class OcrPage:
    """What an orientation-aware engine read: the words in :attr:`frame` coordinates (the
    image put upright and straight), which is where captions and machine-readable zones are
    found, and the frame that maps their boxes back to the input."""

    words: list[OcrWord]
    frame: PageFrame

    def __repr__(self) -> str:
        return f"OcrPage(words={len(self.words)}, frame={self.frame!r})"

    def source_words(self) -> list[OcrWord]:
        """The words with their boxes in the input image."""
        if self.frame.identity:
            return list(self.words)
        return [OcrWord(w.text, self.frame.to_source(w.box), w.line) for w in self.words]


@dataclass(frozen=True, slots=True)
class _Reading:
    """One Tesseract pass: words in frame coordinates, and how well it read."""

    frame: PageFrame
    words: list[OcrWord]
    confidences: list[float]

    @property
    def confident_chars(self) -> int:
        return sum(
            len(w.text)
            for w, conf in zip(self.words, self.confidences, strict=True)
            if conf >= CONFIDENT and len(w.text) >= 2 and any(ch.isalnum() for ch in w.text)
        )

    @property
    def share(self) -> float:
        """Confidently read characters per character read (``0.0``: nothing read)."""
        total = sum(len(w.text) for w in self.words if len(w.text) >= 3)
        return min(1.0, self.confident_chars / total) if total else 0.0

    @property
    def upright_words(self) -> float:
        """The share of words (3+ characters) whose box stands taller than wide: text that
        runs up or down the page, which Tesseract reads in place without turning it."""
        long = [w for w in self.words if len(w.text) >= 3]
        return sum(w.box.height > w.box.width for w in long) / len(long) if long else 0.0

    @property
    def sideways(self) -> bool:
        return self.upright_words > 0.5

    @property
    def rank(self) -> float:
        """Confidently read characters, halved for a sideways reading: captions and
        machine-readable zones are found on a page lying flat, so a flat reading wins a near
        tie."""
        return self.confident_chars * (0.5 if self.sideways else 1.0)


class TesseractOcr:
    """Tesseract via ``pytesseract``. ``lang`` is Tesseract's language list (``"hun+eng"``).

    ``min_confidence`` drops words Tesseract itself scores below it (0-100); keep it low,
    since a dropped word is a word that can't be masked.

    ``upscale_to``: a smaller image is enlarged (Lanczos, at most :data:`MAX_UPSCALE` times)
    until its longer side has this many pixels before OCR, and the word boxes are mapped
    back. Field captions on ID cards are printed 6-10 px high at card resolution, below what
    Tesseract reads; enlarged, they come back (``Családi név / Surname``), and so do the
    values under them. ``None`` reads the image as it is.

    ``orient`` (LAB-1210): a page whose words stand upright (text running up or down) is read
    again a quarter turn either way; a page read poorly, upside down; one read middlingly, in
    the orientation Tesseract's OSD suggests. The best reading wins, so a wrong guess costs a
    pass, never the upright reading.
    ``deskew``: a page skewed by :data:`MIN_SKEW`-:data:`MAX_SKEW` degrees (estimated from its
    row profile) is straightened before reading. Both read in a :class:`PageFrame` and map the
    boxes back (:meth:`read`). Upright, straight pages cost nothing extra.

    ``suppress`` (LAB-1183): a colour-printed page read poorly (security print: guilloche,
    rainbow print, holograms under 2-4 px strokes) is read once more, in the frame the best
    reading was made in, with the background suppressed (:func:`suppress_background`) and as
    sparse text (:data:`SPARSE_TEXT`). The reading with more confidently read characters
    wins, so coloured ink the suppression whitens never loses the first reading.

    ``small_text``: a line read under :data:`MIN_TEXT_HEIGHT` pixels high is read again on a
    tile enlarged to :data:`TARGET_TEXT_HEIGHT` (a 2560 px screenshot is not enlarged as a
    whole, so its 11 px text would otherwise be misread).
    """

    name = "tesseract"

    def __init__(
        self,
        lang: str = "hun+eng",
        *,
        config: str = "",
        min_confidence: float = 0.0,
        upscale_to: int | None = DEFAULT_UPSCALE_TO,
        orient: bool = True,
        deskew: bool = True,
        small_text: bool = True,
        suppress: bool = True,
    ) -> None:
        self.lang = lang
        self.config = config
        self.min_confidence = min_confidence
        self.upscale_to = upscale_to
        self.orient = orient
        self.deskew = deskew
        self.small_text = small_text
        self.suppress = suppress

    def scale_for(self, size: tuple[int, int]) -> float:
        """The factor :meth:`words` enlarges an image of ``size`` by (``1.0``: not at all)."""
        if not self.upscale_to or max(size) <= 0:
            return 1.0
        return max(1.0, min(MAX_UPSCALE, self.upscale_to / max(size)))

    def words(self, image: Image.Image) -> list[OcrWord]:
        """The words of ``image``, their boxes in ``image`` (see :meth:`read`)."""
        return self.read(image).source_words()

    def read(self, image: Image.Image) -> OcrPage:
        """Read ``image`` upright and straight: the words in the frame they were read in."""
        try:
            import pytesseract  # noqa: F401
        except ImportError as exc:
            raise DetectionError("OCR unavailable: install the 'ocr' extra") from exc
        check_deadline()
        scale = self.scale_for(image.size)
        best = self._straight(image, 0.0, scale)
        if self.orient and (best.sideways or best.share < GOOD_READING):
            for turn in self._turns(image, best, scale):
                candidate = self._straight(image, turn, scale)
                if candidate.rank > best.rank:
                    best = candidate
                if not best.sideways and best.share >= GOOD_READING:
                    break
        if self.suppress and best.share < GOOD_READING:
            best = self._suppressed(image, best, scale)
        words = best.words
        if self.small_text:
            words = self._small_text(image, best, scale)
        if not best.frame.identity:
            logger.debug("ocr: read in a frame turned %.1f degrees", best.frame.angle)
        return OcrPage(words, best.frame)

    def _turns(self, image: Image.Image, reading: _Reading, scale: float) -> list[float]:
        """The quarter turns worth reading ``image`` in, given its upright ``reading``.

        Words standing up: a quarter turn either way. A poor reading: upside down. A middling
        one (a busy real document reads like that upright): whatever Tesseract's orientation
        detection suggests, or upside down when it can't tell.
        """
        if reading.sideways:
            return [90.0, 270.0]
        if reading.share < POOR_READING:
            return [180.0]
        hint = self._osd_turn(image, scale)
        if hint is None:
            return [180.0]
        return [hint] if hint else []

    def _osd_turn(self, image: Image.Image, scale: float) -> float | None:
        """The quarter turn (counter-clockwise) Tesseract's orientation detection puts
        ``image`` upright with, or ``None`` when it can't tell (too little text, no ``osd``
        language data)."""
        import pytesseract

        check_deadline()
        source = image
        factor = min(scale, 2.0)
        if factor > 1.0:
            target = (round(image.width * factor), round(image.height * factor))
            source = image.resize(target, Image.Resampling.LANCZOS)
        left = remaining()
        try:
            data = pytesseract.image_to_osd(
                source,
                output_type=pytesseract.Output.DICT,
                timeout=max(left, 0.01) if left is not None else 0,
            )
            rotate = int(data["rotate"]) % 360
        except RuntimeError as exc:
            if "timeout" in str(exc).lower():
                raise OcrTimeoutError("OCR ran past the image deadline") from None
            return None
        except Exception:
            return None
        if rotate not in (0, 90, 180, 270):
            return None
        # OSD gives the clockwise turn that rights the page; frames turn counter-clockwise.
        return float((360 - rotate) % 360)

    def _straight(self, image: Image.Image, turn: float, scale: float) -> _Reading:
        """Read ``image`` turned ``turn`` degrees and, if it is skewed, straightened."""
        reading = self._read(image, PageFrame.of(image.size, turn), scale)
        if not self.deskew:
            return reading
        skew = estimate_skew(reading.frame.render(image) if turn else image)
        if not skew:
            return reading
        check_deadline()
        straightened = self._read(image, PageFrame.of(image.size, turn + skew), scale)
        return straightened if straightened.rank >= reading.rank else reading

    def _suppressed(self, image: Image.Image, reading: _Reading, scale: float) -> _Reading:
        """``reading``, or a reading of the same frame with the coloured background
        suppressed, whichever read more confidently. A page with no tint is left alone."""
        framed = reading.frame.render(image)
        if _tinted_share(framed) < TINTED_PAGE:
            return reading
        check_deadline()
        config = f"{self.config} {SPARSE_TEXT}".strip()
        words, confidences = self._tesseract(
            suppress_background(framed), scale, (0, 0), (), config=config
        )
        candidate = _Reading(reading.frame, words, confidences)
        return candidate if candidate.rank > reading.rank else reading

    def _read(self, image: Image.Image, frame: PageFrame, scale: float) -> _Reading:
        """One Tesseract pass over ``image`` in ``frame``, enlarged ``scale`` times."""
        framed = frame.render(image)
        words, confidences = self._tesseract(framed, scale, (0, 0), ())
        return _Reading(frame, words, confidences)

    def _tesseract(
        self,
        source: Image.Image,
        scale: float,
        offset: tuple[int, int],
        line_prefix: tuple[int, ...],
        *,
        config: str | None = None,
    ) -> tuple[list[OcrWord], list[float]]:
        """Tesseract on ``source`` enlarged ``scale`` times; boxes at ``source`` resolution
        plus ``offset``, line keys prefixed with ``line_prefix``. ``config`` replaces the
        engine's own Tesseract options."""
        import pytesseract

        check_deadline()
        size = source.size
        if scale > 1.0:
            target = (round(source.width * scale), round(source.height * scale))
            source = source.resize(target, Image.Resampling.LANCZOS)
        check_deadline()
        left = remaining()
        try:
            data = pytesseract.image_to_data(
                source,
                lang=self.lang,
                config=self.config if config is None else config,
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
        confidences: list[float] = []
        dx, dy = offset
        try:
            for i, text in enumerate(data["text"]):
                text = (text or "").strip()
                conf = float(data["conf"][i])
                if not text or conf < self.min_confidence:
                    continue
                x, y = int(data["left"][i]), int(data["top"][i])
                width, height = int(data["width"][i]), int(data["height"][i])
                if width <= 0 or height <= 0:
                    continue
                line = (
                    *line_prefix,
                    int(data["page_num"][i]),
                    int(data["block_num"][i]),
                    int(data["par_num"][i]),
                    int(data["line_num"][i]),
                )
                box = Box(x, y, x + width - 1, y + height - 1)
                if scale > 1.0:
                    box = _clamp(box.scaled(1 / scale, 1 / scale), size)
                if offset != (0, 0):
                    box = Box(box.x1 + dx, box.y1 + dy, box.x2 + dx, box.y2 + dy)
                words.append(OcrWord(text, box, line))
                confidences.append(conf)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DetectionError("OCR output has an unexpected format") from exc
        return words, confidences

    def _small_text(self, image: Image.Image, reading: _Reading, scale: float) -> list[OcrWord]:
        """``reading``'s words, with every line read under :data:`MIN_TEXT_HEIGHT` pixels
        (at OCR resolution) read again on an enlarged tile, where that reads better."""
        lines: dict[tuple[int, ...], list[Box]] = {}
        for word in reading.words:
            lines.setdefault(word.line, []).append(word.box)
        # A line's text height is its words' median height: one misread word can stand
        # three times taller than the rest.
        small: list[tuple[Box, int]] = []
        for boxes in lines.values():
            height = round(statistics.median(b.height for b in boxes))
            if height * scale < MIN_TEXT_HEIGHT:
                union = boxes[0]
                for b in boxes[1:]:
                    union = union.union(b)
                small.append((union, max(height, 1)))
        if not small:
            return reading.words
        fw, fh = reading.frame.size
        tiles = _merge_boxes(
            [
                Box(
                    max(0, b.x1 - 2 * h),
                    max(0, b.y1 - h),
                    min(fw - 1, b.x2 + 2 * h),
                    min(fh - 1, b.y2 + h),
                )
                for b, h in small
            ]
        )
        if len(tiles) > MAX_TILES:
            everything = tiles[0]
            for tile in tiles[1:]:
                everything = everything.union(tile)
            tiles = [everything]
        height = min(h for _, h in small)
        factor = min(MAX_UPSCALE, TARGET_TEXT_HEIGHT / max(height, 1))
        area = sum(t.width * t.height for t in tiles)
        factor = min(factor, math.sqrt(MAX_TILE_PIXELS / max(area, 1)))
        if factor <= scale * 1.25:
            return reading.words
        framed = reading.frame.render(image)
        words = list(reading.words)
        confidences = list(reading.confidences)
        for index, tile in enumerate(tiles):
            crop = framed.crop((tile.x1, tile.y1, tile.x2 + 1, tile.y2 + 1))
            found, found_conf = self._tesseract(crop, factor, (tile.x1, tile.y1), (-1, index))
            inside = [i for i, w in enumerate(words) if _centre_in(w.box, tile)]
            old = _Reading(
                reading.frame, [words[i] for i in inside], [confidences[i] for i in inside]
            )
            new = _Reading(reading.frame, found, found_conf)
            if not found or new.confident_chars <= old.confident_chars:
                continue
            at = inside[0] if inside else len(words)
            keep = set(inside)
            merged: list[tuple[OcrWord, float]] = []
            for k, item in enumerate(zip(words, confidences, strict=True)):
                if k == at:
                    merged.extend(zip(found, found_conf, strict=True))
                if k not in keep:
                    merged.append(item)
            if at == len(words):
                merged.extend(zip(found, found_conf, strict=True))
            words = [w for w, _ in merged]
            confidences = [c for _, c in merged]
        return words


def suppress_background(image: Image.Image) -> Image.Image:
    """``image`` in greyscale, each pixel its brightest channel (HSV value).

    Security print is light and coloured (a pastel guilloche, rainbow print), the values on it
    dark: the brightest channel turns a pastel tint near white and leaves dark ink dark, where
    plain greyscale keeps the tint mid-grey around the strokes. On the official specimens it
    cut the values Tesseract read no word of from 109 of 274 to 57 (LAB-1183). Saturated
    coloured ink (pure red) whitens too, which is why its reading only replaces a worse one.
    """
    rgb = image.convert("RGB")
    red, green, blue = rgb.split()
    return ImageChops.lighter(ImageChops.lighter(red, green), blue)


def _tinted_share(image: Image.Image) -> float:
    """The share of ``image``'s pixels whose channels differ by more than :data:`TINT`
    (measured on a copy at most 256 px on its longer side)."""
    if image.mode in ("1", "L", "LA", "I", "F", "I;16"):
        return 0.0
    small = image.convert("RGB")
    small.thumbnail((256, 256))
    red, green, blue = small.split()
    high = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    low = ImageChops.darker(ImageChops.darker(red, green), blue)
    spread = ImageChops.subtract(high, low).point(lambda v: 255 if v > TINT else 0)
    histogram = spread.histogram()
    return histogram[255] / max(1, small.width * small.height)


def _background(image: Image.Image) -> tuple[int, ...] | int:
    """The colour to fill the corners of a turned image with: its top-left pixel's (a page's
    margin), so the fill adds no edges for the reader to find."""
    pixel = image.getpixel((0, 0))
    return pixel if pixel is not None else 255  # type: ignore[return-value]


def estimate_skew(image: Image.Image, max_angle: float = MAX_SKEW) -> float:
    """The angle (degrees, counter-clockwise, as Pillow's ``rotate``) that straightens the text
    lines of ``image``, or ``0.0`` when it is already straight within :data:`MIN_SKEW`.

    Projection profile: dark pixels are summed per row of the image turned by each candidate
    angle; text lines lying flat give the sharpest profile. Pure Pillow, on a copy at most
    600 px across (about 30 evaluations, tens of milliseconds).
    """
    gray = image.convert("L")
    longest = max(gray.size)
    if longest > 600:
        ratio = 600 / longest
        gray = gray.resize(
            (max(1, round(gray.width * ratio)), max(1, round(gray.height * ratio))),
            Image.Resampling.BILINEAR,
        )
    gray = ImageOps.autocontrast(gray)
    ink = gray.point(lambda v: 255 if v < 128 else 0)
    if not ink.getbbox():
        return 0.0

    def sharpness(angle: float) -> float:
        turned = ink.rotate(angle, Image.Resampling.BILINEAR, expand=False, fillcolor=0)
        profile = turned.resize((1, turned.height), Image.Resampling.BOX).tobytes()
        return float(sum((b - a) ** 2 for a, b in itertools.pairwise(profile)))

    scores: dict[float, float] = {}

    def best_near(centre: float, step: float, reach: float) -> float:
        count = round(reach / step)
        for i in range(-count, count + 1):
            angle = round(centre + i * step, 2)
            if abs(angle) <= max_angle and angle not in scores:
                scores[angle] = sharpness(angle)
        near = [a for a in scores if abs(a - centre) <= reach + 1e-9]
        return max(near, key=lambda a: (scores[a], -abs(a)))

    angle = best_near(0.0, 2.0, max_angle)
    angle = best_near(angle, 0.5, 1.5)
    angle = best_near(angle, 0.1, 0.4)
    if abs(angle) < MIN_SKEW or scores[angle] < scores[0.0] * 1.05:
        return 0.0
    return round(angle, 1)


def _merge_boxes(boxes: list[Box]) -> list[Box]:
    """Overlapping boxes merged until none overlap, top to bottom."""
    merged = sorted(boxes, key=lambda b: (b.y1, b.x1))
    changed = True
    while changed:
        changed = False
        out: list[Box] = []
        for box in merged:
            for i, other in enumerate(out):
                if (
                    box.x1 <= other.x2
                    and other.x1 <= box.x2
                    and box.y1 <= other.y2
                    and other.y1 <= box.y2
                ):
                    out[i] = other.union(box)
                    changed = True
                    break
            else:
                out.append(box)
        merged = out
    return sorted(merged, key=lambda b: (b.y1, b.x1))


def _centre_in(box: Box, tile: Box) -> bool:
    cx, cy = (box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2
    return tile.x1 <= cx <= tile.x2 and tile.y1 <= cy <= tile.y2


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
        read = getattr(ocr, "read", None)
        page = read(decoded) if callable(read) else OcrPage(ocr.words(decoded), _NO_FRAME)
    except PiiGuardError:
        raise
    except Exception as exc:
        raise DetectionError(f"OCR failed ({type(exc).__name__})") from exc
    if not isinstance(page, OcrPage):
        raise DetectionError("OCR engine returned an unexpected page")
    words = page.words
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
    found = OcrText(words, findings, zones, fields)
    return found if page.frame.identity else _to_source(found, page.frame)


#: The frame of an engine that reads images as they are (``OcrEngine.words`` only).
_NO_FRAME = PageFrame(0.0, (0, 0), (0, 0))


def _to_source(found: OcrText, frame: PageFrame) -> OcrText:
    """``found`` (read in ``frame``) with every box mapped back to the input image. Captions
    and zones were found in the frame, where the page lies upright and straight."""

    def word(w: OcrWord) -> OcrWord:
        return OcrWord(w.text, frame.to_source(w.box), w.line)

    def region(r: Region) -> Region:
        return replace(r, box=frame.to_source(r.box))

    return OcrText(
        [word(w) for w in found.words],
        [replace(f, region=region(f.region)) for f in found.findings],
        [replace(z, region=region(z.region)) for z in found.zones],
        [
            replace(
                v,
                box=frame.to_source(v.box),
                caption_box=frame.to_source(v.caption_box),
                words=tuple(word(w) for w in v.words),
            )
            for v in found.fields
        ],
    )
