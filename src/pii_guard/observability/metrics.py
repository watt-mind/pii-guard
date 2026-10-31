"""Prometheus-style metrics, rendered as text at ``GET /metrics`` (opt-in).

No client library: fixed-bucket histograms (ms) and counters for the gateway, detectors,
entities, cache, outbound checks, HTTP routes and live runtime gauges. Labels are stage names,
modes, outcomes, entity types, route templates, status codes and a fixed ``source`` enum only --
never ids, model names from requests, or anything a client controls.

Every count added is a non-negative int capped at :data:`MAX_COUNT_PER_OBSERVATION` and every
duration a finite float clamped to ``[0, MAX_MS]``, so one hostile event (remote telemetry is
self-reported) cannot overflow a series or make the exposition unrenderable (LAB-1731).
"""

from __future__ import annotations

import math
import threading
from bisect import bisect_left
from collections.abc import Mapping
from typing import Any

__all__ = [
    "BUCKETS_MS",
    "MAX_COUNT_PER_OBSERVATION",
    "MAX_MS",
    "NER_STATES",
    "SOURCES",
    "LatencyMetrics",
]

BUCKETS_MS: tuple[float, ...] = (
    0.5, 1, 2.5, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000,
)  # fmt: skip

NER_STATES: tuple[str, ...] = ("off", "loading", "ready", "failed")

# ``local``: traffic this server handled; ``remote``: events a CLI gateway self-reported through
# ``POST /v1/traffic``. Any other value is recorded as ``local``.
SOURCES: tuple[str, ...] = ("local", "remote")

MAX_COUNT_PER_OBSERVATION = 10_000_000
MAX_MS = 3_600_000.0


def _count(value: object) -> int:
    """A count to add: a positive int (never bool) capped per observation, else 0."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return min(value, MAX_COUNT_PER_OBSERVATION)
    return 0


def _ms(value: object) -> float | None:
    """A duration to observe: a finite number (never bool) clamped to [0, MAX_MS], else None."""
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    try:
        fval = float(value)
    except OverflowError:  # an int too large for a float
        return MAX_MS if value > 0 else 0.0
    if not math.isfinite(fval):
        return None
    return min(max(fval, 0.0), MAX_MS)


def _source(value: str) -> str:
    return value if value in SOURCES else "local"


_HISTOGRAMS = {
    "overhead": "pii_guard_gateway_overhead_ms",
    "total": "pii_guard_gateway_total_ms",
    "upstream": "pii_guard_gateway_upstream_ms",
    "added_ttft": "pii_guard_gateway_added_ttft_ms",
}

_HISTOGRAM_HELP = {
    "pii_guard_gateway_overhead_ms": "Gateway latency in milliseconds.",
    "pii_guard_gateway_total_ms": "Gateway latency in milliseconds.",
    "pii_guard_gateway_upstream_ms": "Gateway latency in milliseconds.",
    "pii_guard_gateway_added_ttft_ms": "Gateway latency in milliseconds.",
    "pii_guard_gateway_stage_ms": "Gateway latency in milliseconds.",
    "pii_guard_detector_duration_ms": "Detector execution time in milliseconds.",
    "pii_guard_http_request_duration_ms": "HTTP request duration in milliseconds.",
}


class _Histogram:
    __slots__ = ("buckets", "count", "sum")

    def __init__(self) -> None:
        self.buckets = [0] * (len(BUCKETS_MS) + 1)
        self.count = 0
        self.sum = 0.0

    def observe(self, ms: float) -> None:
        # Callers pass values already clamped by ``_ms``; clamp again as a last line.
        ms = min(max(ms, 0.0), MAX_MS) if math.isfinite(ms) else MAX_MS
        self.buckets[bisect_left(BUCKETS_MS, ms)] += 1
        self.count += 1
        self.sum += ms


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _render_histogram(out: list[str], name: str, label_str: str, hist: _Histogram) -> None:
    prefix = f"{label_str}," if label_str else ""
    running = 0
    for bound, n in zip((*BUCKETS_MS, None), hist.buckets, strict=True):
        running += n
        le = "+Inf" if bound is None else f"{bound:g}"
        out.append(f'{name}_bucket{{{prefix}le="{le}"}} {running}')
    out.append(f"{name}_sum{{{label_str}}} {hist.sum:.3f}")
    out.append(f"{name}_count{{{label_str}}} {hist.count}")


def _render_counter(
    out: list[str],
    name: str,
    help_text: str,
    label_keys: tuple[str, ...],
    counts: Mapping[Any, int],  # keys: tuples of label values, in label_keys order
) -> None:
    if not counts:
        return
    out.append(f"# HELP {name} {help_text}")
    out.append(f"# TYPE {name} counter")
    for key, n in sorted(counts.items()):
        labels = ",".join(f'{k}="{_label(v)}"' for k, v in zip(label_keys, key, strict=True))
        out.append(f"{name}{{{labels}}} {n}")


def _render_gauges(
    out: list[str],
    *,
    active_sessions: int | None,
    ner_state: str | None,
    hosted_stats: Mapping[str, int] | None,
) -> None:
    if active_sessions is not None:
        out.append("# HELP pii_guard_vault_active_sessions Live vault sessions in memory.")
        out.append("# TYPE pii_guard_vault_active_sessions gauge")
        out.append(f"pii_guard_vault_active_sessions {max(int(active_sessions), 0)}")
    if ner_state is not None:
        out.append(
            "# HELP pii_guard_ner_state NER warmup state (1 for current state, 0 otherwise)."
        )
        out.append("# TYPE pii_guard_ner_state gauge")
        for state in NER_STATES:
            val = 1 if state == ner_state else 0
            out.append(f'pii_guard_ner_state{{state="{_label(state)}"}} {val}')
    if hosted_stats is not None:
        owners = max(int(hosted_stats.get("owner_runtimes", 0)), 0)
        guests = max(int(hosted_stats.get("guest_runtimes", 0)), 0)
        streams = max(int(hosted_stats.get("active_streams", 0)), 0)
        sponsored = 1 if hosted_stats.get("sponsored_available", 0) else 0
        out.extend(
            (
                "# HELP pii_guard_hosted_active_runtimes "
                "Active hosted tenant runtimes in memory by kind.",
                "# TYPE pii_guard_hosted_active_runtimes gauge",
                f'pii_guard_hosted_active_runtimes{{kind="owner"}} {owners}',
                f'pii_guard_hosted_active_runtimes{{kind="guest"}} {guests}',
                "# HELP pii_guard_hosted_active_streams Active hosted SSE traffic streams.",
                "# TYPE pii_guard_hosted_active_streams gauge",
                f"pii_guard_hosted_active_streams {streams}",
                "# HELP pii_guard_hosted_sponsored_available "
                "Whether hosted sponsored inference is available (1 or 0).",
                "# TYPE pii_guard_hosted_sponsored_available gauge",
                f"pii_guard_hosted_sponsored_available {sponsored}",
            )
        )


class LatencyMetrics:
    """Counters, histograms and live gauges rendered in Prometheus text format. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._series: dict[tuple[str, str, str], _Histogram] = {}
        self._detectors: dict[tuple[str, str], _Histogram] = {}
        self._http_durations: dict[tuple[str, str], _Histogram] = {}
        # Keys end with the ``source`` label (``local`` or ``remote``).
        self._requests: dict[tuple[str, str, str], int] = {}
        self._entities_detected: dict[tuple[str, str], int] = {}
        self._entities_masked: dict[tuple[str, str], int] = {}
        self._image_regions: dict[tuple[str, str, str], int] = {}
        self._blocked_entities: dict[tuple[str, str, str], int] = {}
        self._upstream_tokens: dict[tuple[str, str], int] = {}
        self._http_requests: dict[tuple[str, str, int], int] = {}
        self._outbound_checks: dict[tuple[str], int] = {}
        self._cache: dict[tuple[str], int] = {}
        self._unresolved_placeholders: int = 0

    @staticmethod
    def _bump(table: dict[Any, int], key: Any, value: object) -> None:
        n = _count(value)
        if n:
            table[key] = table.get(key, 0) + n

    def _observe(self, name: str, labels: tuple[str, str], value: object) -> None:
        ms = _ms(value)
        if ms is None:
            return
        key = (name, *labels)
        hist = self._series.get(key)
        if hist is None:
            hist = self._series[key] = _Histogram()
        hist.observe(ms)

    def _observe_detector_locked(self, mode: str, detector: str, value: object) -> None:
        ms = _ms(value)
        if ms is None:
            return
        key = (mode, detector)
        hist = self._detectors.get(key)
        if hist is None:
            hist = self._detectors[key] = _Histogram()
        hist.observe(ms)

    def observe(
        self,
        mode: str,
        outcome: str,
        timing: Mapping[str, Any],
        event: Mapping[str, Any] | None = None,
        *,
        source: str = "local",
    ) -> None:
        src = _source(source)
        with self._lock:
            key = (mode, outcome, src)
            self._requests[key] = self._requests.get(key, 0) + 1
            for name in ("overhead", "total", "upstream", "added_ttft"):
                self._observe(_HISTOGRAMS[name], (mode, ""), timing.get(f"{name}_ms"))
            stages = timing.get("stages_ms")
            if isinstance(stages, Mapping):
                for stage, ms in stages.items():
                    if ms:
                        self._observe("pii_guard_gateway_stage_ms", (mode, str(stage)), ms)
            detectors = timing.get("detectors_ms")
            if isinstance(detectors, Mapping):
                for detector, ms in detectors.items():
                    if ms:
                        self._observe_detector_locked(mode, str(detector), ms)
            if event is not None:
                self._observe_event_locked(outcome, event, src)

    def _observe_event_locked(self, outcome: str, event: Mapping[str, Any], source: str) -> None:
        entities = event.get("entities")
        if isinstance(entities, Mapping):
            self._add_entities_locked(entities.get("detected"), entities.get("masked"), source)
            images = entities.get("images")
            if isinstance(images, Mapping):
                self._add_image_regions_locked(images.get("masked"), images.get("kept"), source)
        self._observe_outbound_and_blocked_locked(outcome, event, source)
        self._observe_cache_and_upstream_locked(event, source)

    def _observe_outbound_and_blocked_locked(
        self, outcome: str, event: Mapping[str, Any], source: str
    ) -> None:
        outbound = event.get("outbound_check")
        outbound_hits = None
        if isinstance(outbound, Mapping):
            result = outbound.get("result")
            if isinstance(result, str) and result:
                self._bump(self._outbound_checks, (result,), 1)
            hits = outbound.get("hits")
            if isinstance(hits, Mapping) and hits:
                outbound_hits = hits
                self._add_blocked_locked("outbound", hits, source)
        if outcome == "blocked" and outbound_hits is None:
            error = event.get("error")
            if isinstance(error, Mapping):
                self._add_blocked_locked("inbound", error.get("entity_types"), source)

    def _observe_cache_and_upstream_locked(self, event: Mapping[str, Any], source: str) -> None:
        cache = event.get("cache")
        if isinstance(cache, Mapping):
            for field, label in (("hits", "hit"), ("misses", "miss"), ("seeded", "seeded")):
                self._bump(self._cache, (label,), cache.get(field))
        upstream = event.get("upstream")
        if isinstance(upstream, Mapping):
            self._unresolved_placeholders += _count(upstream.get("unresolved_placeholders"))
        usage = event.get("usage")
        if isinstance(usage, Mapping):
            tokens_in = usage.get("prompt_tokens")
            if tokens_in is None:
                tokens_in = usage.get("input_tokens")
            tokens_out = usage.get("completion_tokens")
            if tokens_out is None:
                tokens_out = usage.get("output_tokens")
            self._bump(self._upstream_tokens, ("input", source), tokens_in)
            self._bump(self._upstream_tokens, ("output", source), tokens_out)

    def _add_entities_locked(
        self,
        detected: Mapping[str, int] | None,
        masked: Mapping[str, int] | None,
        source: str,
    ) -> None:
        for table, counts in ((self._entities_detected, detected), (self._entities_masked, masked)):
            if isinstance(counts, Mapping):
                for entity_type, n in counts.items():
                    self._bump(table, (str(entity_type), source), n)

    def _add_image_regions_locked(
        self,
        masked: Mapping[str, int] | None,
        kept: Mapping[str, int] | None,
        source: str,
    ) -> None:
        for action, counts in (("masked", masked), ("kept", kept)):
            if isinstance(counts, Mapping):
                for entity_type, n in counts.items():
                    self._bump(self._image_regions, (str(entity_type), action, source), n)

    def _add_blocked_locked(
        self, stage: str, counts: Mapping[str, int] | None, source: str
    ) -> None:
        if isinstance(counts, Mapping):
            for entity_type, n in counts.items():
                self._bump(self._blocked_entities, (stage, str(entity_type), source), n)

    def observe_entities(
        self,
        *,
        detected: Mapping[str, int] | None = None,
        masked: Mapping[str, int] | None = None,
    ) -> None:
        with self._lock:
            self._add_entities_locked(detected, masked, "local")

    def observe_image_regions(
        self,
        *,
        masked: Mapping[str, int] | None = None,
        kept: Mapping[str, int] | None = None,
    ) -> None:
        with self._lock:
            self._add_image_regions_locked(masked, kept, "local")

    def observe_blocked(self, stage: str, counts: Mapping[str, int]) -> None:
        with self._lock:
            self._add_blocked_locked(stage, counts, "local")

    def observe_unresolved(self, count: int) -> None:
        n = _count(count)
        if n:
            with self._lock:
                self._unresolved_placeholders += n

    def observe_http(self, method: str, path: str, status: int, duration_ms: float) -> None:
        ms = _ms(duration_ms)
        with self._lock:
            req_key = (method, path, int(status))
            self._http_requests[req_key] = self._http_requests.get(req_key, 0) + 1
            if ms is None:
                return
            dur_key = (method, path)
            hist = self._http_durations.get(dur_key)
            if hist is None:
                hist = self._http_durations[dur_key] = _Histogram()
            hist.observe(ms)

    def _render_counters(self, out: list[str]) -> None:
        _render_counter(
            out,
            "pii_guard_entities_detected_total",
            "Detected PII spans by entity type and source.",
            ("entity_type", "source"),
            self._entities_detected,
        )
        _render_counter(
            out,
            "pii_guard_entities_masked_total",
            "Masked PII occurrences by entity type and source.",
            ("entity_type", "source"),
            self._entities_masked,
        )
        _render_counter(
            out,
            "pii_guard_image_regions_total",
            "Image PII regions by entity type, action and source.",
            ("entity_type", "action", "source"),
            self._image_regions,
        )
        _render_counter(
            out,
            "pii_guard_blocked_entities_total",
            "Blocked entity occurrences by stage, entity type and source.",
            ("stage", "entity_type", "source"),
            self._blocked_entities,
        )
        _render_counter(
            out,
            "pii_guard_outbound_checks_total",
            "Outbound re-checks by result.",
            ("result",),
            self._outbound_checks,
        )
        _render_counter(
            out,
            "pii_guard_detection_cache_total",
            "Detection cache lookups and seeds.",
            ("result",),
            self._cache,
        )
        _render_counter(
            out,
            "pii_guard_upstream_tokens_total",
            "Upstream LLM tokens by direction and source.",
            ("direction", "source"),
            self._upstream_tokens,
        )
        if self._unresolved_placeholders:
            out.append(
                "# HELP pii_guard_unresolved_placeholders_total "
                "Unresolved placeholder tokens seen during restoration."
            )
            out.append("# TYPE pii_guard_unresolved_placeholders_total counter")
            out.append(f"pii_guard_unresolved_placeholders_total {self._unresolved_placeholders}")
        if self._http_requests:
            out.append(
                "# HELP pii_guard_http_requests_total HTTP requests by method, route and status."
            )
            out.append("# TYPE pii_guard_http_requests_total counter")
            for (method, path, status), n in sorted(self._http_requests.items()):
                out.append(
                    f'pii_guard_http_requests_total{{method="{_label(method)}",'
                    f'path="{_label(path)}",status="{status}"}} {n}'
                )

    def render(
        self,
        *,
        active_sessions: int | None = None,
        ner_state: str | None = None,
        hosted_stats: Mapping[str, int] | None = None,
    ) -> str:
        """The Prometheus text exposition format (version 0.0.4)."""
        out = [
            "# HELP pii_guard_gateway_requests_total Gateway requests by mode, outcome and source.",
            "# TYPE pii_guard_gateway_requests_total counter",
        ]
        with self._lock:
            for (mode, outcome, source), n in sorted(self._requests.items()):
                out.append(
                    f'pii_guard_gateway_requests_total{{mode="{_label(mode)}",'
                    f'outcome="{_label(outcome)}",source="{source}"}} {n}'
                )
            names = sorted({k[0] for k in self._series})
            for name in names:
                out.append(f"# HELP {name} {_HISTOGRAM_HELP[name]}")
                out.append(f"# TYPE {name} histogram")
                for (series, mode, stage), hist in sorted(self._series.items()):
                    if series != name:
                        continue
                    labels = f'mode="{_label(mode)}"' + (
                        f',stage="{_label(stage)}"' if stage else ""
                    )
                    _render_histogram(out, name, labels, hist)
            if self._detectors:
                name = "pii_guard_detector_duration_ms"
                out.append(f"# HELP {name} {_HISTOGRAM_HELP[name]}")
                out.append(f"# TYPE {name} histogram")
                for (mode, detector), hist in sorted(self._detectors.items()):
                    labels = f'mode="{_label(mode)}",detector="{_label(detector)}"'
                    _render_histogram(out, name, labels, hist)
            self._render_counters(out)
            if self._http_durations:
                name = "pii_guard_http_request_duration_ms"
                out.append(f"# HELP {name} {_HISTOGRAM_HELP[name]}")
                out.append(f"# TYPE {name} histogram")
                for (method, path), hist in sorted(self._http_durations.items()):
                    labels = f'method="{_label(method)}",path="{_label(path)}"'
                    _render_histogram(out, name, labels, hist)
        _render_gauges(
            out,
            active_sessions=active_sessions,
            ner_state=ner_state,
            hosted_stats=hosted_stats,
        )
        return "\n".join(out) + "\n"
