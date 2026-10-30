"""Small copies of the masked images a call sent upstream, for the Live traffic tab (LAB-1188).

:func:`scrub` replaces every inline image in a traffic event with a summary, so the event
cannot show what the model received. :func:`masked_thumbnails` keeps a downscaled WebP of each
image in the *masked* request instead: the gateway has already blacked out its regions, so the
thumbnail holds nothing the upstream did not see. Originals are never thumbnailed.

Bounded on purpose, because events sit in the in-memory ring buffer:

- longest side at most :data:`MAX_SIDE` px;
- each thumbnail's data URL at most :data:`MAX_THUMBNAIL_CHARS` characters (a smaller copy is
  tried first; an image that still does not fit is left out, with a note);
- at most :data:`MAX_THUMBNAILS` per event, so one event adds at most
  ``MAX_THUMBNAILS * MAX_THUMBNAIL_CHARS`` characters (64 KiB).

A thumbnail is matched to its image by ``index``: the image's position among the
``image_url`` parts of ``messages`` (in order, remote URLs included), which is how the UI
counts them.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
from collections.abc import Iterator, Mapping
from typing import Any

__all__ = ["MAX_SIDE", "MAX_THUMBNAILS", "MAX_THUMBNAIL_CHARS", "masked_thumbnails"]

#: Longest side of a thumbnail, in pixels.
MAX_SIDE = 320
#: Longest thumbnail data URL kept, in characters (base64 WebP).
MAX_THUMBNAIL_CHARS = 16 * 1024
#: Most thumbnails kept per event; further images get none.
MAX_THUMBNAILS = 4
#: Sides tried in turn until the encoded thumbnail fits :data:`MAX_THUMBNAIL_CHARS`.
_SIDES = (MAX_SIDE, 240, 160)
_QUALITY = 60
_PREFIX = "data:image/"


def _image_urls(body: Any) -> Iterator[tuple[int, Any]]:
    """``(index, url)`` for every ``image_url`` part of ``messages``, in order."""
    if not isinstance(body, Mapping) or not isinstance(body.get("messages"), list):
        return
    index = 0
    for message in body["messages"]:
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, Mapping) or part.get("type") != "image_url":
                continue
            image_url = part.get("image_url")
            yield index, image_url.get("url") if isinstance(image_url, Mapping) else image_url
            index += 1


def _decode(url: str) -> bytes | None:
    head, sep, payload = url.partition(",")
    if not sep or not head.endswith(";base64"):
        return None
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return None


def _thumbnail(raw: bytes) -> dict[str, Any]:
    """The thumbnail fields, or ``{"omitted": "invalid" | "too_large"}``."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(raw)) as opened:
            opened.load()
            image = opened.convert("RGBA" if "A" in opened.getbands() else "RGB")
    except Exception:  # not an image Pillow reads: no thumbnail, never a failed call
        return {"omitted": "invalid"}
    for side in _SIDES:
        copy = image.copy()
        copy.thumbnail((side, side))
        buf = io.BytesIO()
        copy.save(buf, format="WEBP", quality=_QUALITY, method=4)
        url = "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        if len(url) <= MAX_THUMBNAIL_CHARS:
            return {"width": copy.width, "height": copy.height, "data": url}
    return {"omitted": "too_large"}


def masked_thumbnails(masked_request: bytes | None) -> list[dict[str, Any]]:
    """Bounded WebP thumbnails of the inline images in the masked request body.

    Each entry is ``{"index", "width", "height", "data"}`` or, when the image could not be
    made small enough (``too_large``), could not be read (``invalid``) or the per-event cap
    was reached (``limit``), ``{"index", "omitted"}``."""
    if not masked_request or _PREFIX.encode() not in masked_request:
        return []
    try:
        body = json.loads(masked_request)
    except ValueError:
        return []
    out: list[dict[str, Any]] = []
    kept = 0
    for index, url in _image_urls(body):
        if not isinstance(url, str) or not url.startswith(_PREFIX):
            continue
        if kept >= MAX_THUMBNAILS:
            out.append({"index": index, "omitted": "limit"})
            continue
        raw = _decode(url)
        thumb = _thumbnail(raw) if raw is not None else {"omitted": "invalid"}
        out.append({"index": index, **thumb})
        kept += "data" in thumb
    return out
