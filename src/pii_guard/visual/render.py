"""Placeholder-labelled masking: each covered region carries the placeholder that replaced it.

An opaque box hides a value and says nothing; the upstream model sees a black rectangle and
can't connect the card to anything else in the conversation. Here a covered region is filled
with a neutral box (:data:`LABEL_FILL`, with a border) and the session placeholder is printed
in it (``[[PERSON_a1b2c3]]``; ``PHOTO · [[PERSON_a1b2c3]]`` on a portrait), so the model can
read which value was there, and the same person has the same placeholder in the image, the
transcript and the text of the conversation.

Coverage is exactly that of :func:`~pii_guard.visual.image.mask_image`: the same boxes grown
by the same padding, every pixel overwritten (fill, border or label ink, never an original
pixel), so visual recall does not depend on the mode. Only the label differs.

A value box on a card is often narrower than its placeholder (``FIKTÍV`` vs
``[[PERSON_a1b2c3]]``). So that the label stays legible, a box is first **extended to the
right** until the label fits at a readable size (:data:`LEGIBLE_FONT_SIZE`, or the box height
if smaller), but only into free space: never past the image edge, another covered box or an
``obstacle`` (the OCR words left visible), keeping a small gap. Extending only ever covers
more. The boxes actually covered are returned, so the response reports them.

A cover inside another cover with the same label (the face inside its ID photo, both
``PHOTO · [[PERSON_a1b2c3]]``) is drawn without its own label, mirroring the landing's
``labelCovers``: the fill and the border still cover every pixel, but the placeholder
reads once instead of twice. Covers with the same label that mostly overlap on one row (two
detectors' reads of one date, a few pixels apart) are drawn as their union box with the
label once (LAB-1672). Coverage never shrinks below the padded detected boxes; a
suppressed duplicate is not extended for its label, so a pixel only an old label extension
covered can be left free.

The label's font size is then fitted to the box: the largest size from the box height down
to :data:`MIN_FONT_SIZE` at which it fits; if the bracketed placeholder is too wide even then,
the brackets are dropped (``PERSON_a1b2c3``), then the label is split over two lines
(``PERSON`` / ``a1b2c3``); a box too small for any of them is filled without a label (its
placeholder is still in the transcript).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from PIL import ImageDraw, ImageFont

from pii_guard.types import MaskingError
from pii_guard.visual.image import encode_image, load_image
from pii_guard.visual.regions import Box, same_value

__all__ = [
    "LABEL_FILL",
    "LABEL_INK",
    "LEGIBLE_FONT_SIZE",
    "MIN_FONT_SIZE",
    "LabelBox",
    "fit_label",
    "render_labels",
]

#: The box fill: a light neutral grey, distinct from paper white and from ink.
LABEL_FILL: tuple[int, int, int] = (226, 228, 232)
#: Border and text colour.
LABEL_INK: tuple[int, int, int] = (32, 36, 44)
#: Smallest font size (px) a label is drawn at.
MIN_FONT_SIZE = 8
#: Font size a box is extended (to the right, into free space) to print its label at.
LEGIBLE_FONT_SIZE = 13
#: Gap kept between an extended box and the next obstacle, in pixels.
OBSTACLE_GAP = 3
#: Largest font size, whatever the box height.
MAX_FONT_SIZE = 48
#: Inner margin between the border and the label, as a share of the font size.
MARGIN = 0.25


@dataclass(frozen=True, slots=True)
class LabelBox:
    """One area to cover and the label to print in it (``None``: cover only)."""

    box: Box
    label: str | None


@lru_cache(maxsize=64)
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _measure(draw: ImageDraw.ImageDraw, text: str, size: int) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=_font(size))
    return right - left, bottom - top


def _variants(label: str) -> list[list[str]]:
    """The label as written, without brackets, then on two lines."""
    out = [[label]]
    bare = label
    if "[[" in label:
        bare = label.replace("[[", "").replace("]]", "")
        out.append([bare])
    head, sep, tail = bare.rpartition("_")
    if sep and head and tail:
        out.append([head, tail])
    elif " · " in bare:
        first, _, rest = bare.partition(" · ")
        out.append([first, rest])
    return out


def fit_label(
    draw: ImageDraw.ImageDraw, label: str, width: int, height: int
) -> tuple[list[str], int] | None:
    """The lines and font size to print ``label`` in a ``width`` x ``height`` box, or ``None``."""
    for lines in _variants(label):
        top = min(MAX_FONT_SIZE, int(height / (len(lines) * (1 + MARGIN))))
        for size in range(top, MIN_FONT_SIZE - 1, -1):
            margin = max(1, round(size * MARGIN))
            sizes = [_measure(draw, line, size) for line in lines]
            text_w = max(w for w, _ in sizes)
            text_h = sum(h for _, h in sizes) + margin * (len(lines) - 1)
            if text_w + 2 * margin <= width and text_h + 2 * margin <= height:
                return lines, size
    return None


@dataclass(frozen=True, slots=True)
class LabelledImage:
    """The re-encoded image and the box each input :class:`LabelBox` actually covers
    (grown by the padding and any extension, clipped; ``None`` if it was outside)."""

    image: bytes
    boxes: list[Box | None]

    def __repr__(self) -> str:
        return f"LabelledImage(image=<{len(self.image)} bytes>, boxes={len(self.boxes)})"


def _inside(inner: tuple[int, int, int, int], outer: tuple[int, int, int, int]) -> bool:
    """Whether the ``inner`` cover lies within the ``outer`` one (edges may touch)."""
    return (
        inner[0] >= outer[0]
        and inner[1] >= outer[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _duplicate_labels(
    items: list[LabelBox], rects: list[tuple[int, int, int, int] | None]
) -> set[int]:
    """Indexes whose label another cover of the same value already prints (LAB-1488, LAB-1672).

    Covers with the same label that are :func:`~pii_guard.visual.regions.same_value` (one
    inside the other, or mostly overlapping on one row) print it once:

    - **nested** (the face inside its ID photo, both ``PHOTO · [[PERSON_…]]``): like the
      landing's ``labelCovers``, the outer cover prints the label and the inner one is drawn
      (fill and border) without it;
    - **overlapping** (a caption read and an NER read of one date, a few pixels apart): every
      cover of the group is widened in ``rects`` to the group's union box, which holds every
      padded detected box, so coverage never shrinks below them; the first prints the label.

    Only labels are skipped: every cover is still filled.
    """
    out: set[int] = set()
    group_of = list(range(len(items)))

    def root(i: int) -> int:
        while group_of[i] != i:
            group_of[i] = group_of[group_of[i]]
            i = group_of[i]
        return i

    for i, (item, rect) in enumerate(zip(items, rects, strict=True)):
        if rect is None or not item.label:
            continue
        for j in range(i):
            other = rects[j]
            if other is None or items[j].label != item.label:
                continue
            if same_value(Box(*rect), Box(*other)):
                group_of[root(i)] = root(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        if rects[i] is not None and items[i].label:
            groups.setdefault(root(i), []).append(i)
    for members in groups.values():
        if len(members) < 2:
            continue
        member_rects = [r for i in members if (r := rects[i]) is not None]
        union = (
            min(r[0] for r in member_rects),
            min(r[1] for r in member_rects),
            max(r[2] for r in member_rects),
            max(r[3] for r in member_rects),
        )
        outer = [i for i in members if rects[i] == union]
        if not outer:
            for i in members:
                rects[i] = union
            outer = members
        out.update(i for i in members if i != outer[0])
    return out


def _extend(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    label: str,
    others: list[tuple[int, int, int, int]],
    width: int,
) -> tuple[int, int, int, int]:
    """``rect`` widened to the right so ``label`` fits at a legible size, into free space."""
    x1, y1, x2, y2 = rect
    h = y2 - y1 + 1
    size = max(MIN_FONT_SIZE, min(LEGIBLE_FONT_SIZE, int(h / (1 + MARGIN))))
    margin = max(1, round(size * MARGIN))
    needed = _measure(draw, label, size)[0] + 2 * margin
    if needed <= x2 - x1 + 1:
        return rect
    limit = width - 1
    for ox1, oy1, ox2, oy2 in others:
        if oy2 < y1 or oy1 > y2 or ox2 <= x2:
            continue  # not beside the box on its right
        if ox1 <= x2:
            return rect  # already touching: no free space
        limit = min(limit, ox1 - OBSTACLE_GAP)
    return (x1, y1, max(x2, min(limit, x1 + needed - 1)), y2)


def render_labels(
    image_bytes: bytes,
    boxes: Iterable[LabelBox],
    *,
    padding: int = 2,
    image_format: str = "PNG",
    fill: tuple[int, int, int] = LABEL_FILL,
    ink: tuple[int, int, int] = LABEL_INK,
    obstacles: Iterable[Box] = (),
) -> LabelledImage:
    """Cover every box (grown by ``padding``, extended for its label, clipped to the image)
    and print its label.

    All boxes are filled first, then the labels are drawn, so an overlapping box never hides
    a label already drawn and no original pixel survives under any box. Like
    :func:`~pii_guard.visual.image.mask_image` the result is rebuilt from pixels (no
    metadata) and a failure raises :class:`~pii_guard.types.MaskingError`, never returning
    the input.
    """
    if padding < 0:
        raise MaskingError("padding must be >= 0")
    try:
        image = load_image(bytes(image_bytes))
    except ValueError as exc:
        raise MaskingError("image could not be decoded for masking") from exc
    try:
        draw = ImageDraw.Draw(image)
        width, height = image.size
        items = list(boxes)
        rects: list[tuple[int, int, int, int] | None] = []
        for item in items:
            if not isinstance(item, LabelBox):
                raise TypeError("boxes must be LabelBox instances")
            box = item.box
            x1, y1 = max(0, box.x1 - padding), max(0, box.y1 - padding)
            x2, y2 = min(width - 1, box.x2 + padding), min(height - 1, box.y2 + padding)
            rects.append((x1, y1, x2, y2) if x1 <= x2 and y1 <= y2 else None)
        blocked = [(b.x1, b.y1, b.x2, b.y2) for b in obstacles]
        suppressed = _duplicate_labels(items, rects)
        for index, (item, rect) in enumerate(zip(items, rects, strict=True)):
            if rect is None or not item.label or index in suppressed:
                continue
            others = blocked + [r for j, r in enumerate(rects) if r is not None and j != index]
            rects[index] = _extend(draw, rect, item.label, others, width)
        for rect in rects:
            if rect is not None:
                draw.rectangle(rect, fill=fill)
        for index, (item, rect) in enumerate(zip(items, rects, strict=True)):
            if rect is None:
                continue
            x1, y1, x2, y2 = rect
            label = None if index in suppressed else item.label
            w, h = x2 - x1 + 1, y2 - y1 + 1
            if w >= 4 and h >= 4:
                draw.rectangle(rect, outline=ink, width=1)
            if not label:
                continue
            fitted = fit_label(draw, label, w, h)
            if fitted is None:
                continue
            lines, size = fitted
            font = _font(size)
            margin = max(1, round(size * MARGIN))
            sizes = [_measure(draw, line, size) for line in lines]
            total = sum(lh for _, lh in sizes) + margin * (len(lines) - 1)
            y = y1 + (h - total) // 2
            for line, (lw, lh) in zip(lines, sizes, strict=True):
                left, top, _, _ = draw.textbbox((0, 0), line, font=font)
                draw.text((x1 + (w - lw) // 2 - left, y - top), line, fill=ink, font=font)
                y += lh + margin
        covered = [Box(*rect) if rect is not None else None for rect in rects]
        return LabelledImage(encode_image(image, image_format), covered)
    except Exception as exc:
        raise MaskingError("image masking failed") from exc
