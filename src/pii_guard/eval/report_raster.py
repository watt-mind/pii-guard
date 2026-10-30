"""PNG copies of the generated SVG images, without a browser (LAB-1663).

``pii-guard eval report`` rasterizes each shareable SVG with resvg (the ``resvg-py`` wheel,
pinned in the ``report`` dependency group), with system fonts off and only the Inter files in
``docs/benchmarks/fonts`` loaded, so a PNG depends on the SVG, the fonts and the renderer
version and nothing on the machine.

Every PNG carries a ``tEXt`` chunk naming what it was rendered from (the SVG's SHA-256, the
fonts' SHA-256 and the renderer). ``--check`` regenerates the SVG, compares it byte for byte,
and compares the committed PNG's stamp with the stamp the regenerated SVG would get, so CI
needs no rasterizer and a PNG can never go stale against its SVG unnoticed.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from pii_guard.eval.record import RecordError

__all__ = ["RENDERER", "STAMP_KEY", "Raster", "fonts_digest", "rasterize", "read_stamp"]

#: The rasterizer and its version: a different version may draw different pixels.
RENDERER_PACKAGE = "resvg-py"
RENDERER_VERSION = "0.5.0"
RENDERER = f"{RENDERER_PACKAGE}=={RENDERER_VERSION}"
STAMP_KEY = "pii-guard-source"
_PNG = b"\x89PNG\r\n\x1a\n"


def fonts_digest(fonts_dir: Path) -> str:
    """SHA-256 over the font files' names and bytes, in name order."""
    h = hashlib.sha256()
    files = sorted(fonts_dir.glob("*.ttf"))
    if not files:
        raise RecordError(f"{fonts_dir}: no .ttf fonts to rasterize with")
    for f in files:
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()


@dataclass(frozen=True)
class Raster:
    """A PNG output: drawn from ``svg`` at its own size with the fonts in ``fonts_dir``."""

    svg: str
    fonts_dir: Path

    def stamp(self) -> str:
        svg = hashlib.sha256(self.svg.encode("utf-8")).hexdigest()
        return f"svg={svg} fonts={fonts_digest(self.fonts_dir)} renderer={RENDERER}"

    def is_current(self, path: Path) -> bool:
        try:
            data = path.read_bytes()
        except OSError:
            return False
        return read_stamp(data) == self.stamp()

    def render(self) -> bytes:
        return rasterize(self.svg, self.fonts_dir, self.stamp())


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _chunks(png: bytes) -> list[tuple[bytes, bytes]]:
    if not png.startswith(_PNG):
        raise ValueError("not a PNG")
    out, pos = [], len(_PNG)
    while pos < len(png):
        (length,) = struct.unpack(">I", png[pos : pos + 4])
        kind = png[pos + 4 : pos + 8]
        out.append((kind, png[pos + 8 : pos + 8 + length]))
        pos += 12 + length
    return out


def read_stamp(png: bytes) -> str | None:
    """The ``pii-guard-source`` text of a PNG, or ``None`` (no stamp, or not a PNG)."""
    try:
        chunks = _chunks(png)
    except (ValueError, struct.error):
        return None
    for kind, data in chunks:
        if kind == b"tEXt":
            key, _, value = data.partition(b"\x00")
            if key == STAMP_KEY.encode():
                return value.decode("latin-1")
    return None


def rasterize(svg: str, fonts_dir: Path, stamp: str) -> bytes:
    """``svg`` as PNG at its own size, stamped; needs the ``report`` group's resvg-py."""
    try:
        installed = metadata.version(RENDERER_PACKAGE)
        import resvg_py
    except (metadata.PackageNotFoundError, ImportError) as exc:
        raise RecordError(
            f"PNG images need {RENDERER} (`uv sync --group report`, included in dev): {exc}"
        ) from exc
    if installed != RENDERER_VERSION:
        raise RecordError(f"PNG images are pinned to {RENDERER}; installed: {installed}")
    fonts = [str(p) for p in sorted(fonts_dir.glob("*.ttf"))]
    png = bytes(
        resvg_py.svg_to_bytes(
            svg_string=svg,
            skip_system_fonts=True,
            font_files=fonts,
            font_family="Inter",
            sans_serif_family="Inter",
        )
    )
    chunks = _chunks(png)
    text = _chunk(b"tEXt", STAMP_KEY.encode() + b"\x00" + stamp.encode("latin-1"))
    out = [_PNG]
    for kind, data in chunks:
        out.append(_chunk(kind, data))
        if kind == b"IHDR":
            out.append(text)
    return b"".join(out)
