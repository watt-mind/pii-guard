"""Tesseract over pipes: original pixels and recognized text never enter temporary files.

The command consumes a PNG on stdin and emits TSV/OSD on stdout. Keep stderr and
subprocess exceptions private: either can contain OCR text or image-derived diagnostics.
"""

from __future__ import annotations

import contextlib
import io
import shlex
import subprocess
from typing import Any

from PIL import Image


def _run(image: Image.Image, options: list[str], timeout: float) -> str:
    source = io.BytesIO()
    image.save(source, format="PNG")
    try:
        result = subprocess.run(  # noqa: S603 - fixed executable, arguments, no shell
            ["tesseract", "stdin", "stdout", *options],  # noqa: S607 - operator-provisioned PATH
            input=source.getvalue(),
            capture_output=True,
            timeout=timeout if timeout > 0 else None,
            check=False,
        )
    except subprocess.TimeoutExpired:
        # subprocess.run kills and reaps its child before raising.
        raise RuntimeError("Tesseract process timeout") from None
    except OSError:
        raise RuntimeError("Tesseract could not be started") from None
    if result.returncode:
        raise RuntimeError("Tesseract failed") from None
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise RuntimeError("Tesseract returned invalid output") from None


def image_to_data(
    image: Image.Image, *, lang: str, config: str = "", timeout: float = 0
) -> dict[str, list[Any]]:
    """Return the same TSV columns/types as pytesseract's dictionary output."""
    text = _run(image, ["-l", lang, "-c", "tessedit_create_tsv=1", *shlex.split(config)], timeout)
    rows = [row.split("\t") for row in text.strip().split("\n")]
    if len(rows) < 2:
        return {}
    header, *values = rows
    if len(values[-1]) < len(header):
        values[-1].append("")
    result: dict[str, list[Any]] = {name: [] for name in header}
    for i, name in enumerate(header):
        for row in values:
            if len(row) <= i:
                continue
            value: Any = row[i]
            if i != len(header) - 1:
                with contextlib.suppress(ValueError):
                    value = int(float(value))
            result[name].append(value)
    return result


def image_to_osd(image: Image.Image, *, timeout: float = 0) -> dict[str, int]:
    """Read Tesseract's clockwise correction, retaining OSD's existing fallback behavior."""
    text = _run(image, ["-l", "osd", "--psm", "0"], timeout)
    for line in text.splitlines():
        key, sep, value = line.partition(": ")
        if sep and key == "Rotate":
            return {"rotate": int(value)}
    return {}
