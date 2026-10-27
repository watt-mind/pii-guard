"""The one percentile definition and the shared formatters (``pii_guard.eval.stats``)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pii_guard.eval.stats import (
    fmt_duration,
    fmt_ms,
    fmt_pct,
    percentile,
    percentiles,
    sha256_file,
)


def test_percentile_empty_is_none() -> None:
    assert percentile([], 0.5) is None
    assert percentiles([]) is None


def test_percentile_single_value() -> None:
    for q in (0.0, 0.5, 0.95, 1.0):
        assert percentile([7.0], q) == 7.0


def test_percentile_two_values_interpolates() -> None:
    assert percentile([10.0, 20.0], 0.0) == 10.0
    assert percentile([10.0, 20.0], 0.5) == 15.0
    assert percentile([10.0, 20.0], 0.95) == pytest.approx(19.5)
    assert percentile([10.0, 20.0], 1.0) == 20.0


def test_percentile_ties() -> None:
    assert percentile([5.0, 5.0, 5.0, 5.0], 0.95) == 5.0
    assert percentile([1.0, 2.0, 2.0, 2.0, 9.0], 0.5) == 2.0


def test_percentile_known_values_match_numpy_linear() -> None:
    # The audit's example: nearest rank gave 30 / 200 here, linear gives 35 / 175.
    v = [10, 20, 30, 40, 100, 200]
    assert percentile(v, 0.5) == pytest.approx(35.0)
    assert percentile(v, 0.95) == pytest.approx(175.0)
    assert percentiles(v) == pytest.approx({"p50": 35.0, "p95": 175.0, "p99": 195.0})
    # Unsorted input; 1..100 is numpy's textbook case.
    assert percentile([200, 10, 100, 30, 20, 40], 0.5) == pytest.approx(35.0)
    assert percentiles([float(x) for x in range(1, 101)]) == pytest.approx(
        {"p50": 50.5, "p95": 95.05, "p99": 99.01}
    )


def test_percentile_rounding_and_bounds() -> None:
    assert percentile([0.0, 1.0], 0.123, 1) == 0.1
    assert percentile([0.0, 1.0], 0.123, 2) == 0.12
    assert percentiles([1.0, 2.0], (50,)) == {"p50": 1.5}
    with pytest.raises(ValueError):
        percentile([1.0], 1.5)


def test_fmt_pct() -> None:
    assert fmt_pct(0.1234) == "12.3"
    assert fmt_pct(0.1234, 0) == "12"
    assert fmt_pct(0.5, sign=True) == "50.0%"
    assert fmt_pct(None) == "—"
    assert fmt_pct(None, none="n/a") == "n/a"


def test_fmt_ms() -> None:
    assert fmt_ms(3.14159) == "3.1"
    assert fmt_ms(3.14159, 2) == "3.14"
    assert fmt_ms(1234.5, whole_from=100) == "1,234"
    assert fmt_ms(99.94, whole_from=100) == "99.9"
    assert fmt_ms(None) == "—"


def test_fmt_duration() -> None:
    assert fmt_duration(2100.0) == "2.1 s"
    assert fmt_duration(45.4) == "45 ms"
    assert fmt_duration(3.21) == "3.2 ms"
    assert fmt_duration(0.413) == "0.41 ms"
    assert fmt_duration(None) == "—"


def test_sha256_file(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    data = b"fictional weights " * 300_000  # more than one 4 MiB chunk
    path.write_bytes(data)
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()
