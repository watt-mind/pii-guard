"""Shared statistics and formatting helpers for the eval and bench harnesses.

One percentile definition for every published latency (see :func:`percentile`), one way to
print a rate or a duration, and one file digest. Pure standard library: no numpy.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from pathlib import Path

__all__ = ["NONE", "fmt_duration", "fmt_ms", "fmt_pct", "percentile", "percentiles", "sha256_file"]

#: What a table prints for a value that was not measured.
NONE = "—"


def percentile(values: Iterable[float], q: float, ndigits: int | None = None) -> float | None:
    """The ``q``-quantile (``0 <= q <= 1``) of ``values``; ``None`` when there are none.

    Linear interpolation between the closest ranks, numpy's default (``method="linear"``,
    Hyndman and Fan type 7): sort the values, take the fractional position ``(n - 1) * q``
    and interpolate between the two values either side of it. p50 is the median; p0 and p100
    are the minimum and maximum. ``[10, 20, 30, 40, 100, 200]`` gives p50 35.0 and p95 175.0.

    ``ndigits`` rounds the result (``round(v, ndigits)``); ``None`` leaves it as computed.
    """
    if not 0 <= q <= 1:
        raise ValueError(f"q must be in [0, 1], got {q!r}")
    ordered = sorted(values)
    if not ordered:
        return None
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    value = ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)
    return value if ndigits is None else round(value, ndigits)


def percentiles(
    values: Sequence[float], qs: Sequence[int] = (50, 95, 99)
) -> dict[str, float] | None:
    """``{"p50": ..., "p95": ..., "p99": ...}`` per :func:`percentile`; ``None`` when empty.

    ``qs`` are whole percent (``95`` is the 0.95 quantile). Values are not rounded.
    """
    out: dict[str, float] = {}
    for p in qs:
        v = percentile(values, p / 100)
        if v is None:
            return None
        out[f"p{p}"] = v
    return out


def fmt_pct(value: float | None, digits: int = 1, none: str = NONE, *, sign: bool = False) -> str:
    """A rate in ``[0, 1]`` as a percentage: ``0.1234`` -> ``"12.3"``, ``"12.3%"`` with ``sign``."""
    if value is None:
        return none
    return f"{float(value) * 100:.{digits}f}{'%' if sign else ''}"


def fmt_ms(
    value: float | None, digits: int = 1, none: str = NONE, *, whole_from: float | None = None
) -> str:
    """Milliseconds as a bare number: ``digits`` decimals, or a grouped whole number
    (``1,234``) from ``whole_from`` up when it is set."""
    if value is None:
        return none
    v = float(value)
    if whole_from is not None and v >= whole_from:
        return f"{v:,.0f}"
    return f"{v:.{digits}f}"


def fmt_duration(value: float | None, none: str = NONE) -> str:
    """Milliseconds with a unit and a precision that fits the size: ``2.1 s``, ``45 ms``,
    ``3.2 ms``, ``0.41 ms``."""
    if value is None:
        return none
    v = float(value)
    if v >= 1000:
        return f"{v / 1000:.1f} s"
    if v >= 10:
        return f"{v:.0f} ms"
    if v >= 1:
        return f"{v:.1f} ms"
    return f"{v:.2f} ms"


def sha256_file(path: str | Path) -> str:
    """Hex SHA-256 of a file, read in 4 MiB chunks so model weights don't sit in memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1 << 22):
            digest.update(chunk)
    return digest.hexdigest()
