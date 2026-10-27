"""Line protocol shared by the image baseline workers (stdlib only, no pii-guard imports).

An image worker runs in its own virtual environment (see ``../envs``), like the text
workers (``_protocol.py``), because the tools pin heavy, conflicting dependencies (OpenCV,
torch, Ultralytics, spaCy models).

1. The worker loads its tool, runs one warm-up call on a blank image and writes
   ``{"ready": true, "info": {...}}`` (tool versions, models, configuration and the region
   kinds it can mask: ``"supports": ["text", "face", "signature", ...]``).
2. For each request line ``{"id": n, "image": "<base64 PNG>", "language": str}`` it writes
   ``{"id": n, "regions": [{"box": [x1, y1, x2, y2], "label": str, "kind": "text" | "visual",
   "group": str | null, "score": float | null}, ...], "ms": float}`` or, on failure,
   ``{"id": n, "error": "<exception class name>"}``. Boxes are inclusive pixel corners in the
   image that was sent. ``group`` ties the word boxes of one detected entity together (the
   client merges them per text line, as pii-guard does with its own spans); ``ms`` is the
   tool's own time for the image, without the pipe. Replies never carry recognised text.
3. End of input ends the worker.

The protocol uses the original stdout file descriptor only; anything a library prints is
redirected to stderr, which the client discards unless ``PII_GUARD_BASELINE_DEBUG`` is set.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from typing import Any

#: ``handle(image, language) -> regions`` (``image`` is a PIL image in RGB).
ImageHandler = Callable[[Any, str], list[dict[str, Any]]]


def quiet_logging() -> None:
    """Tools log detections with their raw values; keep only errors."""
    logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
    for name in ("presidio-analyzer", "presidio-image-redactor", "ultralytics", "transformers"):
        logging.getLogger(name).setLevel(logging.ERROR)


def protocol_stdout() -> Any:
    """A private handle on stdout, after pointing fd 1 at stderr for library chatter."""
    out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return out


def decode(data: str) -> Any:
    from PIL import Image

    image = Image.open(io.BytesIO(base64.b64decode(data)))
    image.load()
    return image.convert("RGB")


def clamp_box(box: Any, width: int, height: int) -> list[int] | None:
    """``[x0, y0, x1, y1]`` (exclusive or inclusive ends) as inclusive corners in the image."""
    x0, y0, x1, y1 = (round(float(v)) for v in box)
    x0, y0 = max(0, min(width - 1, x0)), max(0, min(height - 1, y0))
    x1, y1 = max(0, min(width - 1, x1)), max(0, min(height - 1, y1))
    if x1 < x0 or y1 < y0:
        return None
    return [x0, y0, x1, y1]


def serve(out: Any, info: dict[str, Any], handle: ImageHandler) -> int:
    from PIL import Image

    handle(Image.new("RGB", (320, 200), "white"), "en")
    out.write(json.dumps({"ready": True, "info": info}) + "\n")
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        try:
            image = decode(request["image"])
            started = time.perf_counter()
            regions = handle(image, request["language"])
            reply: dict[str, Any] = {
                "id": request["id"],
                "regions": regions,
                "ms": (time.perf_counter() - started) * 1000,
            }
        except Exception as exc:  # report the type only: messages may contain the text
            reply = {"id": request["id"], "error": type(exc).__name__}
        out.write(json.dumps(reply) + "\n")
    return 0
