"""Per-mode detection for the gateway.

- ``fast`` (the default): :func:`~pii_guard.detect.stack.default_detector_names` --
  ``rules`` + ``ner`` when available, the same stack the REST API runs without
  ``PII_GUARD_DETECTORS``. A configured (``PII_GUARD_NER_MODEL``) but missing NER raises
  ``DetectionError`` at startup.
- ``audit`` (formerly ``strict``): the fast detectors + the LLM detector, resolved by
  :class:`~pii_guard.detect.pipeline.DetectionPipeline`.

Every detector's output is checked by :class:`~pii_guard.detect.stack.CheckedDetector` (a list of
spans whose offsets match the text, else ``DetectionError``), as in the REST API.

Entity policies (:meth:`pii_guard.policy.PolicySet.from_settings`, shared with the REST API)
are applied *after*
resolution: ``keep`` spans still lose overlaps against masked types but are themselves left in
place, and any ``block`` span raises :class:`~pii_guard.policy.BlockedEntityError`, so the
request is refused and nothing is forwarded.

Every detector is wrapped to record its wall time, for the per-request log line.
"""

from __future__ import annotations

import contextvars
import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pii_guard.config import Settings
from pii_guard.detect import stack
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.detect.stack import CheckedDetector, build_detectors, check_spans
from pii_guard.gateway.config import GatewayConfig, Mode
from pii_guard.policy import PolicySet
from pii_guard.types import Detector, Span

__all__ = ["ModeDetector", "build_mode_detectors", "detector_timings", "gateway_policies"]

logger = logging.getLogger(__name__)

_timings: contextvars.ContextVar[dict[str, float] | None] = contextvars.ContextVar(
    "pii_guard_gateway_timings", default=None
)


class _Timed:
    """A detector wrapper that adds its wall time (ms) to the current timing dict."""

    def __init__(self, inner: Detector) -> None:
        self.inner = inner
        self.name = inner.name

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        started = time.perf_counter()
        try:
            return self.inner.detect(text, language)
        finally:
            timings = _timings.get()
            if timings is not None:
                elapsed = (time.perf_counter() - started) * 1000
                timings[self.name] = timings.get(self.name, 0.0) + elapsed


@dataclass(frozen=True)
class ModeDetector:
    """One mode's detector, with a stable id for the detection cache key."""

    mode: Mode
    detector: Detector
    config_id: str
    policies: PolicySet

    def detect(self, text: str, language: str) -> tuple[list[Span], dict[str, float]]:
        """Spans to mask plus per-detector timings (ms). Runs in a worker thread.

        Raises :class:`~pii_guard.policy.BlockedEntityError` if a span has a ``block`` policy.
        """
        token = _timings.set({})
        try:
            spans = self.detector.detect(text, language)
            timings = dict(_timings.get() or {})
        finally:
            _timings.reset(token)
        spans = check_spans(spans, text, f"{self.mode.value} pipeline")
        return self.policies.apply(spans).masked, timings


def gateway_policies(settings: Settings, config: GatewayConfig) -> PolicySet:
    """:meth:`PolicySet.from_settings`, with ``config.keep_types`` as the deprecated keep list."""
    return PolicySet.from_settings(settings, keep_types=config.keep_types)


def _ner_available() -> bool:
    """Kept for callers of the old name; the decision lives in :mod:`pii_guard.detect.stack`."""
    return stack._ner_available()


def build_mode_detectors(
    settings: Settings,
    config: GatewayConfig,
    *,
    base: Sequence[Detector] | None = None,
    llm_detector: Detector | None = None,
) -> dict[Mode, ModeDetector]:
    """The fast and audit detectors.

    ``base`` defaults to :func:`~pii_guard.detect.stack.default_detector_names` (``rules`` +
    ``ner`` when available, built from the settings); ``llm_detector`` defaults to
    :class:`~pii_guard.detect.llm.LlmDetector` from the settings. Both are injectable for tests.
    """
    if base is None:
        base = build_detectors(stack.default_detector_names(settings), settings)
    if llm_detector is None:
        from pii_guard.detect.llm import LlmDetector

        llm_detector = LlmDetector(settings=settings, reasoning_effort=config.llm_reasoning_effort)
    policies = gateway_policies(settings, config)

    def build(mode: Mode, detectors: Iterable[Detector]) -> ModeDetector:
        detectors = list(detectors)
        pipeline = DetectionPipeline(
            [_Timed(CheckedDetector(d)) for d in detectors], keep_types=policies.keep_types
        )
        llm_model = getattr(llm_detector, "model", "")
        parts = [d.name for d in detectors]
        if mode is Mode.AUDIT:
            parts.append(f"model={llm_model}")
        parts.append("policies=" + policies.fingerprint())
        return ModeDetector(mode, pipeline, f"{mode.value}:" + ";".join(parts), policies)

    detectors = {
        Mode.FAST: build(Mode.FAST, base),
        Mode.AUDIT: build(Mode.AUDIT, [*base, llm_detector]),
    }
    logger.info(
        "gateway detectors: fast=%s audit=%s",
        [d.name for d in base],
        [*(d.name for d in base), llm_detector.name],
    )
    return detectors


def detector_timings(results: Iterable[dict[str, float]]) -> dict[str, float]:
    total: dict[str, float] = {}
    for timings in results:
        for name, ms in timings.items():
            total[name] = total.get(name, 0.0) + ms
    return total
