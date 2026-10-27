"""Per-request timing on the monotonic clock (``time.perf_counter``).

A :class:`RequestTimer` starts when the gateway route receives the body and collects:

- **stages** (wall time, ms): ``parse`` (JSON + collecting the texts), ``detect`` (every
  detector over every text, concurrent, plus known values), ``image`` (visual pipeline),
  ``mask`` (vault), ``forward`` (serialising the masked body and opening the upstream
  client), ``upstream_ttfb`` (send until the upstream's response headers),
  ``upstream`` (all time spent waiting on the upstream: headers and body reads), ``unmask``
  (stream restoration, summed over chunks), ``response`` (restoring and building a
  non-streamed answer) and ``client`` (streams: time suspended handing each event to the client,
  i.e. the client's read speed and network backpressure -- neither pii-guard's nor the
  upstream's);
- **detectors** (ms): each detector's own time summed over the texts of the request
  (``rules``, ``ner``, ``llm``, ``known``). They overlap when texts run concurrently, so they
  are reported apart from the stages;
- for streams: the upstream's first data event and the first event sent to the client.

Derived: ``total_ms`` (start until the answer is built or the stream ends), ``overhead_ms =
total - upstream - client`` (what pii-guard added), and for streams ``added_ttft_ms`` = time to
the first event sent to the client minus the upstream's own time to its first data event.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

__all__ = ["STAGES", "RequestTimer"]

#: Stage names in pipeline order; every event has all of them (0 when not run).
STAGES: tuple[str, ...] = (
    "parse",
    "detect",
    "image",
    "mask",
    "forward",
    "upstream_ttfb",
    "upstream",
    "unmask",
    "response",
    "client",
)
#: Stages that are pii-guard's own work (not waiting on the upstream).
OWN_STAGES: tuple[str, ...] = (
    "parse",
    "detect",
    "image",
    "mask",
    "forward",
    "unmask",
    "response",
)


def _ms(seconds: float) -> float:
    return round(seconds * 1000, 3)


class RequestTimer:
    """Monotonic spans of one gateway request. Not thread-safe: one per request."""

    def __init__(self, started: float | None = None) -> None:
        self.started = time.perf_counter() if started is None else started
        self.stages: dict[str, float] = dict.fromkeys(STAGES, 0.0)  # seconds
        self.detectors: dict[str, float] = {}  # ms
        self.ended: float | None = None
        self.upstream_sent: float | None = None
        self.upstream_first_data: float | None = None
        self.first_event: float | None = None

    def __repr__(self) -> str:
        return f"RequestTimer(total_ms={self.total_ms:.1f}, overhead_ms={self.overhead_ms:.1f})"

    def add(self, stage: str, seconds: float) -> None:
        self.stages[stage] = self.stages.get(stage, 0.0) + max(seconds, 0.0)

    @contextmanager
    def span(self, stage: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.add(stage, time.perf_counter() - started)

    def add_detectors(self, timings: dict[str, float]) -> None:
        for name, ms in timings.items():
            self.detectors[name] = self.detectors.get(name, 0.0) + ms

    def mark_first_data(self) -> None:
        if self.upstream_first_data is None:
            self.upstream_first_data = time.perf_counter()

    def mark_first_event(self) -> None:
        if self.first_event is None:
            self.first_event = time.perf_counter()

    def finish(self) -> None:
        if self.ended is None:
            self.ended = time.perf_counter()

    @property
    def total_ms(self) -> float:
        end = self.ended if self.ended is not None else time.perf_counter()
        return _ms(end - self.started)

    @property
    def upstream_ms(self) -> float:
        return _ms(self.stages["upstream"])

    @property
    def client_ms(self) -> float:
        return _ms(self.stages["client"])

    @property
    def overhead_ms(self) -> float:
        """Total minus the time waiting on the upstream and on the client."""
        return round(max(self.total_ms - self.upstream_ms - self.client_ms, 0.0), 3)

    def ttft(self) -> tuple[float | None, float | None, float | None]:
        """``(ttft, upstream ttft, added ttft)`` in ms, or ``None`` when not streamed."""
        if self.first_event is None or self.upstream_first_data is None:
            return None, None, None
        ttft = _ms(self.first_event - self.started)
        sent = self.upstream_sent if self.upstream_sent is not None else self.started
        upstream = _ms(self.upstream_first_data - sent)
        return ttft, upstream, round(max(ttft - upstream, 0.0), 3)

    def breakdown(self) -> dict[str, Any]:
        """The ``timing`` block of a traffic event (all ms)."""
        ttft, upstream_ttft, added = self.ttft()
        return {
            "total_ms": self.total_ms,
            "upstream_ms": self.upstream_ms,
            "overhead_ms": self.overhead_ms,
            "stages_ms": {name: _ms(self.stages.get(name, 0.0)) for name in STAGES},
            "detectors_ms": {k: round(v, 3) for k, v in sorted(self.detectors.items())},
            "ttft_ms": ttft,
            "upstream_ttft_ms": upstream_ttft,
            "added_ttft_ms": added,
        }

    def server_timing(self) -> str:
        """A ``Server-Timing`` header value for what is known now (before any body is sent)."""
        parts = [
            f"{name};dur={_ms(self.stages[name]):.3f}"
            for name in STAGES
            if self.stages.get(name) and name != "upstream"
        ]
        if self.stages.get("upstream"):
            parts.append(f"upstream;dur={self.upstream_ms:.3f}")
        parts.append(f"overhead;dur={self.overhead_ms:.3f}")
        parts.append(f"total;dur={self.total_ms:.3f}")
        return ", ".join(parts)
