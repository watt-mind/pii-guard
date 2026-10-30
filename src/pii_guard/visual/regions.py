"""Typed image regions: what the visual pipeline finds and what ``mask_image`` covers.

Also the one overlap measure every visual component uses: :func:`intersection` and
:func:`iou` of two :class:`Box` es (inclusive pixel corners), and :func:`iou_xyxy` for raw
detector boxes in continuous ``(x1, y1, x2, y2)`` coordinates (a :class:`Box` is the
continuous box ``(x1, y1, x2 + 1, y2 + 1)``, so the two agree).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from pii_guard.types import EntityType

__all__ = ["Box", "Region", "SamMask", "intersection", "iou", "iou_xyxy"]


@dataclass(frozen=True, slots=True)
class Box:
    """An axis-aligned pixel box with **inclusive** corners: ``(x1, y1)`` to ``(x2, y2)``.

    Coordinates refer to the image after EXIF orientation is applied (see
    :func:`pii_guard.visual.image.load_image`), which is the image every component sees.
    """

    x1: int
    y1: int
    x2: int
    y2: int

    def __post_init__(self) -> None:
        for name in ("x1", "y1", "x2", "y2"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"box coordinate {name} must be an int")
        if self.x1 < 0 or self.y1 < 0 or self.x2 < self.x1 or self.y2 < self.y1:
            raise ValueError(f"invalid box ({self.x1}, {self.y1}, {self.x2}, {self.y2})")

    @property
    def width(self) -> int:
        return self.x2 - self.x1 + 1

    @property
    def height(self) -> int:
        return self.y2 - self.y1 + 1

    def union(self, other: Box) -> Box:
        return Box(
            min(self.x1, other.x1),
            min(self.y1, other.y1),
            max(self.x2, other.x2),
            max(self.y2, other.y2),
        )

    def scaled(self, sx: float, sy: float) -> Box:
        """The box in an image scaled by ``(sx, sy)``, rounded outwards (never shrinks)."""
        return Box(
            max(0, math.floor(self.x1 * sx)),
            max(0, math.floor(self.y1 * sy)),
            max(0, math.ceil((self.x2 + 1) * sx) - 1),
            max(0, math.ceil((self.y2 + 1) * sy) - 1),
        )

    def to_list(self) -> list[int]:
        return [self.x1, self.y1, self.x2, self.y2]


@dataclass(frozen=True, slots=True)
class SamMask:
    """The per-object mask SAM 3.1 returns on the Meta Model API, kept as received.

    The API sends ``<|mask;x=..;y=..;data=H,W,~<payload>|>`` after each box: ``H``/``W`` are
    the mask grid size (it matches the box size), ``payload`` is a base-85 string whose first
    four bytes are the big-endian length of an entropy-coded bitstream. Meta's official parser,
    ``meta_sam_parser``, checks the payload decodes; the mask is still carried opaquely, as
    masking always fills the whole box, a superset of the mask (safer, never smaller).
    """

    x: int
    y: int
    height: int
    width: int
    data: str
    encoding: str = "meta-sam-b85"

    def __repr__(self) -> str:
        return (
            f"SamMask(x={self.x}, y={self.y}, height={self.height}, width={self.width}, "
            f"encoding={self.encoding!r}, data=<{len(self.data)} chars>)"
        )


@dataclass(frozen=True, slots=True)
class Region:
    """A detected piece of personal data in an image.

    - ``entity_type``: a visual type (``FACE``, ``SIGNATURE``, ...) for SAM regions, or a text
      type (``NATIONAL_ID_HU_TAJ``, ...) for OCR text found by a text detector.
    - ``box``: the pixel area to cover.
    - ``score``: confidence in ``[0, 1]``, or ``None`` when the source gives none (SAM 3.1 on
      the Meta Model API returns no scores).
    - ``source``: ``"sam"`` or the name of the text detector (``"rules"``).
    - ``mask``: SAM's own mask for the object, if any (informational; see :class:`SamMask`).

    A region never carries the text it covers, so it is safe to log.
    """

    entity_type: EntityType
    box: Box
    score: float | None
    source: str
    mask: SamMask | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.entity_type, EntityType):
            try:
                object.__setattr__(self, "entity_type", EntityType(self.entity_type))
            except ValueError:
                raise ValueError(f"unknown entity_type {self.entity_type!r}") from None
        if self.score is not None and not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score must be in [0, 1], got {self.score}")
        if not self.source:
            raise ValueError("region source must not be empty")

    def to_public_dict(self) -> dict[str, object]:
        """JSON form, as an ``/v1/analyze`` response would carry it."""
        return {
            "entity_type": self.entity_type.value,
            "box": self.box.to_list(),
            "score": self.score,
            "source": self.source,
        }


def intersection(a: Box, b: Box) -> int:
    """The number of pixels ``a`` and ``b`` share (``0`` when they don't overlap)."""
    ix = min(a.x2, b.x2) - max(a.x1, b.x1) + 1
    iy = min(a.y2, b.y2) - max(a.y1, b.y1) + 1
    return ix * iy if ix > 0 and iy > 0 else 0


def iou(a: Box, b: Box) -> float:
    """Intersection over union of two boxes, in ``[0, 1]``."""
    return iou_xyxy((a.x1, a.y1, a.x2 + 1, a.y2 + 1), (b.x1, b.y1, b.x2 + 1, b.y2 + 1))


def iou_xyxy(a: Sequence[float], b: Sequence[float]) -> float:
    """Intersection over union of two continuous ``(x1, y1, x2, y2, ...)`` boxes (extra items,
    such as a detector's score, are ignored); ``0.0`` for empty boxes."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0
