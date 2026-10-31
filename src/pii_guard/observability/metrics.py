"""Prometheus-style metrics, rendered as text at ``GET /metrics`` (opt-in).

No client library: fixed-bucket histograms (ms) and counters for the gateway, detectors,
entities, cache, outbound checks, HTTP routes and live runtime gauges. Labels are stage names,
modes, outcomes, entity types, route templates and status codes only -- never ids, model names
from requests, or anything a client controls.
"""

from __future__ import annotations

import threading
from bisect import bisect_left
from collections.abc import Mapping
from typing import Any

__all__ = ["BUCKETS_MS", "NER_STATES", "LatencyMetrics"]

BUCKETS_MS: tuple[float, ...] = (
    0.5, 1, 2.5, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000,
)  # fmt: skip

NER_STATES: tuple[str, ...] = ("off", "loading", "ready", "failed")

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


def _render_single_label_counter(
    out: list[str],
    name: str,
    help_text: str,
    label_key: str,
    counts: Mapping[str, int],
) -> None:
    if not counts:
        return
    out.append(f"# HELP {name} {help_text}")
    out.append(f"# TYPE {name} counter")
    for key, n in sorted(counts.items()):
        out.append(f'{name}{{{label_key}="{_label(key)}"}} {n}')


class LatencyMetrics:
    """Counters, histograms and live gauges rendered in Prometheus text format. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._series: dict[tuple[str, str, str], _Histogram] = {}
        self._detectors: dict[tuple[str, str], _Histogram] = {}
        self._http_durations: dict[tuple[str, str], _Histogram] = {}
        self._requests: dict[tuple[str, str], int] = {}
        self._http_requests: dict[tuple[str, str, int], int] = {}
        self._entities_detected: dict[str, int] = {}
        self._entities_masked: dict[str, int] = {}
        self._image_regions: dict[tuple[str, str], int] = {}
        self._blocked_entities: dict[tuple[str, str], int] = {}
        self._outbound_checks: dict[str, int] = {}
        self._cache: dict[str, int] = {}
        self._upstream_tokens: dict[str, int] = {}
        self._unresolved_placeholders: int = 0

    def _observe(self, name: str, labels: tuple[str, str], ms: float | None) -> None:
        if ms is None:
            return
        key = (name, *labels)
        hist = self._series.get(key)
        if hist is None:
            hist = self._series[key] = _Histogram()
        hist.observe(float(ms))

    def _observe_detector_locked(self, mode: str, detector: str, ms: float) -> None:
        key = (mode, detector)
        hist = self._detectors.get(key)
        if hist is None:
            hist = self._detectors[key] = _Histogram()
        hist.observe(float(ms))

    def observe(
        self,
        mode: str,
        outcome: str,
        timing: Mapping[str, Any],
        event: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._requests[(mode, outcome)] = self._requests.get((mode, outcome), 0) + 1
            for key in ("overhead", "total", "upstream", "added_ttft"):
                self._observe(_HISTOGRAMS[key], (mode, ""), timing.get(f"{key}_ms"))
            for stage, ms in (timing.get("stages_ms") or {}).items():
                if ms:
                    self._observe("pii_guard_gateway_stage_ms", (mode, stage), ms)
            for detector, ms in (timing.get("detectors_ms") or {}).items():
                if ms:
                    self._observe_detector_locked(mode, str(detector), float(ms))
            if event is not None:
                self._observe_event_locked(outcome, event)

    def _observe_event_locked(self, outcome: str, event: Mapping[str, Any]) -> None:
        entities = event.get("entities")
        if isinstance(entities, Mapping):
            self._add_entities_locked(
                entities.get("detected"),
                entities.get("masked"),
            )
            images = entities.get("images")
            if isinstance(images, Mapping):
                self._add_image_regions_locked(images.get("masked"), images.get("kept"))
        self._observe_outbound_and_blocked_locked(outcome, event)
        self._observe_cache_and_upstream_locked(event)

    def _observe_outbound_and_blocked_locked(self, outcome: str, event: Mapping[str, Any]) -> None:
        outbound = event.get("outbound_check")
        outbound_hits = None
        if isinstance(outbound, Mapping):
            result = outbound.get("result")
            if isinstance(result, str) and result:
                self._outbound_checks[result] = self._outbound_checks.get(result, 0) + 1
            hits = outbound.get("hits")
            if isinstance(hits, Mapping) and hits:
                outbound_hits = hits
                self._add_blocked_locked("outbound", hits)
        if outcome == "blocked" and outbound_hits is None:
            error = event.get("error")
            if isinstance(error, Mapping):
                self._add_blocked_locked("inbound", error.get("entity_types"))

    def _observe_cache_and_upstream_locked(self, event: Mapping[str, Any]) -> None:
        cache = event.get("cache")
        if isinstance(cache, Mapping):
            for field, label in (("hits", "hit"), ("misses", "miss"), ("seeded", "seeded")):
                count = cache.get(field)
                if isinstance(count, int) and count > 0:
                    self._cache[label] = self._cache.get(label, 0) + count
        upstream = event.get("upstream")
        if isinstance(upstream, Mapping):
            unresolved = upstream.get("unresolved_placeholders")
            if isinstance(unresolved, int) and unresolved > 0:
                self._unresolved_placeholders += unresolved
        usage = event.get("usage")
        if isinstance(usage, Mapping):
            tokens_in = usage.get("prompt_tokens")
            if tokens_in is None:
                tokens_in = usage.get("input_tokens")
            tokens_out = usage.get("completion_tokens")
            if tokens_out is None:
                tokens_out = usage.get("output_tokens")
            if isinstance(tokens_in, int) and not isinstance(tokens_in, bool) and tokens_in > 0:
                self._upstream_tokens["input"] = self._upstream_tokens.get("input", 0) + tokens_in
            if isinstance(tokens_out, int) and not isinstance(tokens_out, bool) and tokens_out > 0:
                self._upstream_tokens["output"] = (
                    self._upstream_tokens.get("output", 0) + tokens_out
                )

    def _add_entities_locked(
        self,
        detected: Mapping[str, int] | None,
        masked: Mapping[str, int] | None,
    ) -> None:
        if isinstance(detected, Mapping):
            for entity_type, n in detected.items():
                if isinstance(n, int) and n > 0:
                    self._entities_detected[str(entity_type)] = (
                        self._entities_detected.get(str(entity_type), 0) + n
                    )
        if isinstance(masked, Mapping):
            for entity_type, n in masked.items():
                if isinstance(n, int) and n > 0:
                    self._entities_masked[str(entity_type)] = (
                        self._entities_masked.get(str(entity_type), 0) + n
                    )

    def _add_image_regions_locked(
        self,
        masked: Mapping[str, int] | None,
        kept: Mapping[str, int] | None,
    ) -> None:
        for action, counts in (("masked", masked), ("kept", kept)):
            if isinstance(counts, Mapping):
                for entity_type, n in counts.items():
                    if isinstance(n, int) and n > 0:
                        key = (str(entity_type), action)
                        self._image_regions[key] = self._image_regions.get(key, 0) + n

    def _add_blocked_locked(self, stage: str, counts: Mapping[str, int] | None) -> None:
        if isinstance(counts, Mapping):
            for entity_type, n in counts.items():
                if isinstance(n, int) and n > 0:
                    key = (stage, str(entity_type))
                    self._blocked_entities[key] = self._blocked_entities.get(key, 0) + n

    def observe_entities(
        self,
        *,
        detected: Mapping[str, int] | None = None,
        masked: Mapping[str, int] | None = None,
    ) -> None:
        with self._lock:
            self._add_entities_locked(detected, masked)

    def observe_image_regions(
        self,
        *,
        masked: Mapping[str, int] | None = None,
        kept: Mapping[str, int] | None = None,
    ) -> None:
        with self._lock:
            self._add_image_regions_locked(masked, kept)

    def observe_blocked(self, stage: str, counts: Mapping[str, int]) -> None:
        with self._lock:
            self._add_blocked_locked(stage, counts)

    def observe_unresolved(self, count: int) -> None:
        if count > 0:
            with self._lock:
                self._unresolved_placeholders += count

    def observe_http(self, method: str, path: str, status: int, duration_ms: float) -> None:
        with self._lock:
            req_key = (method, path, int(status))
            self._http_requests[req_key] = self._http_requests.get(req_key, 0) + 1
            dur_key = (method, path)
            hist = self._http_durations.get(dur_key)
            if hist is None:
                hist = self._http_durations[dur_key] = _Histogram()
            hist.observe(max(float(duration_ms), 0.0))

    def _render_counters(self, out: list[str]) -> None:
        _render_single_label_counter(
            out,
            "pii_guard_entities_detected_total",
            "Detected PII spans by entity type.",
            "entity_type",
            self._entities_detected,
        )
        _render_single_label_counter(
            out,
            "pii_guard_entities_masked_total",
            "Masked PII occurrences by entity type.",
            "entity_type",
            self._entities_masked,
        )
        if self._image_regions:
            out.append(
                "# HELP pii_guard_image_regions_total Image PII regions by entity type and action."
            )
            out.append("# TYPE pii_guard_image_regions_total counter")
            for (entity_type, action), n in sorted(self._image_regions.items()):
                out.append(
                    f'pii_guard_image_regions_total{{entity_type="{_label(entity_type)}",'
                    f'action="{_label(action)}"}} {n}'
                )
        if self._blocked_entities:
            out.append(
                "# HELP pii_guard_blocked_entities_total "
                "Blocked entity occurrences by stage and entity type."
            )
            out.append("# TYPE pii_guard_blocked_entities_total counter")
            for (stage, entity_type), n in sorted(self._blocked_entities.items()):
                out.append(
                    f'pii_guard_blocked_entities_total{{stage="{_label(stage)}",'
                    f'entity_type="{_label(entity_type)}"}} {n}'
                )
        _render_single_label_counter(
            out,
            "pii_guard_outbound_checks_total",
            "Outbound re-checks by result.",
            "result",
            self._outbound_checks,
        )
        _render_single_label_counter(
            out,
            "pii_guard_detection_cache_total",
            "Detection cache lookups and seeds.",
            "result",
            self._cache,
        )
        _render_single_label_counter(
            out,
            "pii_guard_upstream_tokens_total",
            "Upstream LLM tokens by direction.",
            "direction",
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
    ) -> str:
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
        return "\n".join(out) + "\n"
