"""Page geometry, skew estimation, and security-print background suppression for OCR."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageOps

from pii_guard.visual.regions import Box

__all__ = [
    "MAX_SKEW",
    "MIN_SKEW",
    "TINT",
    "TINTED_PAGE",
    "PageFrame",
    "_background",
    "_centre_in",
    "_clamp",
    "_merge_boxes",
    "_tinted_share",
    "estimate_skew",
    "suppress_background",
]

#: A page read below ``GOOD_READING`` whose pixels are at least this share tinted (a
#: coloured security print: guilloche, rainbow print) is read again with the background
#: suppressed (:func:`suppress_background`). The 65 official specimens are 6-91 % tinted, a
#: screenshot or a scan of black print on white about 0 %.
TINTED_PAGE = 0.05
#: A pixel whose channels differ by more than this counts as tinted.
TINT = 24
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


def _background(image: Image.Image) -> float | tuple[int, ...]:
    """The colour to fill the corners of a turned image with: its top-left pixel's (a page's
    margin), so the fill adds no edges for the reader to find."""
    pixel = image.getpixel((0, 0))
    return pixel if pixel is not None else 255


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
