"""Image loading, re-encoding and masking.

Every component works on the same normalized image: decoded with Pillow, EXIF orientation
applied, converted to RGB. Region coordinates refer to that image.

Output images are rebuilt from raw pixels into a fresh image, so nothing from the input file
survives except the pixels themselves: no EXIF, XMP, ICC profile, comments, thumbnails or
extra frames.
"""

from __future__ import annotations

import io
from collections.abc import Iterable

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from pii_guard.types import MaskingError
from pii_guard.visual.regions import Region

__all__ = [
    "DEFAULT_FILL",
    "MAX_PIXELS",
    "encode_image",
    "load_image",
    "mask_image",
]

DEFAULT_FILL: tuple[int, int, int] = (0, 0, 0)
#: Refuse images above this many pixels (decompression-bomb guard), ~40 megapixels.
MAX_PIXELS = 40_000_000

_FORMATS = {"PNG": "PNG", "JPEG": "JPEG", "JPG": "JPEG", "WEBP": "WEBP"}


def load_image(data: bytes) -> Image.Image:
    """Decode ``data`` into an RGB image with EXIF orientation applied.

    Raises :class:`ValueError` (never echoing the bytes) if it is not a readable image.
    """
    if not isinstance(data, bytes | bytearray) or not data:
        raise ValueError("image must be non-empty bytes")
    try:
        with Image.open(io.BytesIO(data)) as raw:
            if raw.width * raw.height > MAX_PIXELS:
                raise ValueError("image is too large")
            raw.load()
            oriented = ImageOps.exif_transpose(raw)
            return _fresh_rgb(oriented)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("unreadable image") from exc


def _fresh_rgb(image: Image.Image) -> Image.Image:
    """A brand-new RGB image holding only ``image``'s pixels (no ``info``, no metadata)."""
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        # Flatten transparency onto white so hidden pixels under alpha=0 are not kept.
        rgba = image.convert("RGBA")
        base = Image.new("RGB", rgba.size, (255, 255, 255))
        base.paste(rgba, mask=rgba.getchannel("A"))
        rgb = base
    else:
        rgb = image.convert("RGB")
    return Image.frombytes("RGB", rgb.size, rgb.tobytes())


def encode_image(image: Image.Image, image_format: str = "PNG") -> bytes:
    """Encode ``image`` from its pixels only, without any metadata."""
    fmt = _FORMATS.get(image_format.upper())
    if fmt is None:
        raise ValueError(f"unsupported output format {image_format!r}")
    clean = _fresh_rgb(image)
    buf = io.BytesIO()
    if fmt == "JPEG":
        clean.save(buf, format=fmt, quality=90, exif=b"", icc_profile=None)
    else:
        clean.save(buf, format=fmt)
    return buf.getvalue()


def mask_image(
    image_bytes: bytes,
    regions: Iterable[Region],
    *,
    fill: tuple[int, int, int] = DEFAULT_FILL,
    padding: int = 2,
    image_format: str = "PNG",
) -> bytes:
    """Cover every region's box with a solid ``fill`` and return the re-encoded image.

    - Solid fill, not blur: covered pixels carry no information about the original.
    - Each box is grown by ``padding`` pixels on every side (clipped to the image).
    - The result is rebuilt from pixels (EXIF and all other metadata are gone), even when
      ``regions`` is empty, so the original bytes are never returned.

    Raises :class:`~pii_guard.types.MaskingError` if the image can't be decoded or encoded,
    or a region is invalid. It never returns the unmasked input.
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
        for region in regions:
            if not isinstance(region, Region):
                raise TypeError("regions must be Region instances")
            box = region.box
            x1, y1 = max(0, box.x1 - padding), max(0, box.y1 - padding)
            x2, y2 = min(width - 1, box.x2 + padding), min(height - 1, box.y2 + padding)
            if x1 > x2 or y1 > y2:
                continue  # entirely outside the image: nothing to cover
            draw.rectangle((x1, y1, x2, y2), fill=fill)
        return encode_image(image, image_format)
    except Exception as exc:
        raise MaskingError("image masking failed") from exc
