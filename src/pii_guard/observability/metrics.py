"""Prometheus-style latency histograms, rendered as text at ``GET /metrics`` (opt-in).

No client library: a fixed set of buckets (ms) per ``(stage, mode)`` and a request counter per
``(mode, outcome)``. Labels are stage names, modes and outcome codes only -- never ids, model
names from requests, or anything a client controls.
"""

from __future__ import annotations

import threading
from bisect import bisect_left
from collections.abc import Mapping
from typing import Any

__all__ = ["BUCKETS_MS", "LatencyMetrics"]

BUCKETS_MS: tuple[float, ...] = (
    0.5, 1, 2.5, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000,
)  # fmt: skip

_HISTOGRAMS = {
    "overhead": "pii_guard_gateway_overhead_ms",
    "total": "pii_guard_gateway_total_ms",
    "upstream": "pii_guard_gateway_upstream_ms",
    "added_ttft": "pii_guard_gateway_added_ttft_ms",
}


class _Histogram:
    __slots__ = ("buckets", "count", "sum")

    def __init__(self) -> None:
        self.buckets = [0] * (len(BUCKETS_MS) + 1)
        self.count = 0
        self.sum = 0.0

    def observe(self, ms: float) -> None:
        self.buckets[bisect_left(BUCKETS_MS, ms)] += 1
        self.count += 1
        self.sum += ms


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


class LatencyMetrics:
    """Histograms of the timing blocks of traffic events. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._series: dict[tuple[str, str, str], _Histogram] = {}
        self._requests: dict[tuple[str, str], int] = {}

    def _observe(self, name: str, labels: tuple[str, str], ms: float | None) -> None:
        if ms is None:
            return
        key = (name, *labels)
        hist = self._series.get(key)
        if hist is None:
            hist = self._series[key] = _Histogram()
        hist.observe(float(ms))

    def observe(self, mode: str, outcome: str, timing: Mapping[str, Any]) -> None:
        with self._lock:
            self._requests[(mode, outcome)] = self._requests.get((mode, outcome), 0) + 1
            for key in ("overhead", "total", "upstream", "added_ttft"):
                self._observe(_HISTOGRAMS[key], (mode, ""), timing.get(f"{key}_ms"))
            for stage, ms in (timing.get("stages_ms") or {}).items():
                if ms:
                    self._observe("pii_guard_gateway_stage_ms", (mode, stage), ms)

    def render(self) -> str:
        """The Prometheus text exposition format (version 0.0.4)."""
        out = [
            "# HELP pii_guard_gateway_requests_total Gateway requests by mode and outcome.",
            "# TYPE pii_guard_gateway_requests_total counter",
        ]
        with self._lock:
            for (mode, outcome), n in sorted(self._requests.items()):
                out.append(
                    f'pii_guard_gateway_requests_total{{mode="{_label(mode)}",'
                    f'outcome="{_label(outcome)}"}} {n}'
                )
            names = sorted({k[0] for k in self._series})
            for name in names:
                out.append(f"# HELP {name} Gateway latency in milliseconds.")
                out.append(f"# TYPE {name} histogram")
                for (series, mode, stage), hist in sorted(self._series.items()):
                    if series != name:
                        continue
                    labels = f'mode="{_label(mode)}"' + (
                        f',stage="{_label(stage)}"' if stage else ""
                    )
                    running = 0
                    for bound, n in zip((*BUCKETS_MS, None), hist.buckets, strict=True):
                        running += n
                        le = "+Inf" if bound is None else f"{bound:g}"
                        out.append(f'{name}_bucket{{{labels},le="{le}"}} {running}')
                    out.append(f"{name}_sum{{{labels}}} {hist.sum:.3f}")
                    out.append(f"{name}_count{{{labels}}} {hist.count}")
        return "\n".join(out) + "\n"
