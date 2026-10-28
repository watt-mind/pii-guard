"""A virtual clock for the gateway's timing tests (LAB-1275).

The gateway times itself with ``time.perf_counter``. A test that makes a fake upstream (or
client) ``asyncio.sleep`` for 80 ms and then asserts the gateway's own overhead stayed under
80 ms measures the CI runner's scheduler as much as the gateway: it failed at 162-249 ms on
loaded machines. :class:`VirtualClock` is the real clock plus an offset that only the test
moves, so a fake upstream's "delay" is a jump of that offset: instant, exact, and immune to
load. The gateway's own work still takes real time on top, which is what the overhead
assertions bound -- against a delay (seconds, virtual) far above any scheduling noise, so a
gateway that mis-counts the delay as its own overhead fails by seconds, not milliseconds.
"""

from __future__ import annotations

import time

import pytest


class VirtualClock:
    """``time.perf_counter`` plus a test-controlled offset."""

    def __init__(self) -> None:
        self._real = time.perf_counter
        self.offset = 0.0

    def __call__(self) -> float:
        return self._real() + self.offset

    def skip(self, seconds: float) -> None:
        """Move time forward as if ``seconds`` had passed, without waiting."""
        self.offset += seconds


def install(monkeypatch: pytest.MonkeyPatch) -> VirtualClock:
    """Replace ``time.perf_counter`` for the test; undone by ``monkeypatch``."""
    clock = VirtualClock()
    monkeypatch.setattr(time, "perf_counter", clock)
    return clock
