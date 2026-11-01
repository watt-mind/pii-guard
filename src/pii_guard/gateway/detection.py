"""Per-mode detection for the gateway.

- ``fast`` (the default): :func:`~pii_guard.detect.stack.default_detector_names` --
  ``rules`` + ``ner`` when available, the same stack the REST API runs without
  ``PII_GUARD_DETECTORS``. A configured (``PII_GUARD_NER_MODEL``) but missing NER raises
  ``DetectionError`` at startup.
- ``escalate`` (LAB-1766): the fast pipeline, then only its uncertain spans go to the LLM
  detector as small masked windows (:class:`~pii_guard.detect.escalate.EscalatingDetector`).
  Unavailable without an LLM detector key, like audit.
- ``audit`` (formerly ``strict``): the fast detectors + the LLM detector, resolved by
  :class:`~pii_guard.detect.pipeline.DetectionPipeline`. Without an LLM detector key it is
  *unavailable* (LAB-1290): :meth:`ModeDetector.require_available` refuses every audit request
  with ``503 detection_unavailable`` before any detector runs, so no text (and no image) is sent.

Every detector's output is checked by :class:`~pii_guard.detect.stack.CheckedDetector` (a list of
spans whose offsets match the text, else ``DetectionError``), as in the REST API.

Entity policies (:meth:`pii_guard.policy.PolicySet.from_settings`, shared with the REST API)
are applied *after*
resolution: ``keep`` spans still lose overlaps against masked types but are themselves left in
place, and any ``block`` span raises :class:`~pii_guard.policy.BlockedEntityError`, so the
request is refused and nothing is forwarded.

Every detector is wrapped to record its wall time, for the per-request log line.

In fast mode the gateway detects all of a request's uncached texts in one
:meth:`ModeDetector.detect_many` call, so the NER model runs them in batched forwards
(LAB-1279) instead of one forward per text.
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
from pii_guard.detect.stack import (
    CheckedDetector,
    DetectionUnavailableError,
    build_detectors,
    check_spans,
    unavailable_reason,
)
from pii_guard.gateway.config import GatewayConfig, Mode
from pii_guard.policy import PolicySet
from pii_guard.types import DetectionError, Detector, Span

__all__ = ["ModeDetector", "build_mode_detectors", "detector_timings", "gateway_policies"]

logger = logging.getLogger(__name__)

_timings: contextvars.ContextVar[dict[str, float] | None] = contextvars.ContextVar(
    "pii_guard_gateway_timings", default=None
)


class _CheckedBatch(CheckedDetector):
    """:class:`CheckedDetector` that also passes ``detect_batch`` through, checked per text."""

    def detect_batch(self, texts: Sequence[str], language: str = "hu") -> list[list[Span]]:
        batch = getattr(self.inner, "detect_batch", None)
        if batch is None:
            return [self.detect(text, language) for text in texts]
        try:
            found = batch(list(texts), language)
        except DetectionError:
            raise
        except Exception as exc:
            # Never str(exc): it may quote the input.
            raise DetectionError(f"detector {self.name!r} failed") from exc
        if not isinstance(found, list) or len(found) != len(texts):
            raise DetectionError(f"detector {self.name!r} returned the wrong number of results")
        return [
            check_spans(spans, text, self.name) for spans, text in zip(found, texts, strict=True)
        ]


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
            self._record(started)

    def detect_batch(self, texts: Sequence[str], language: str = "hu") -> list[list[Span]]:
        started = time.perf_counter()
        try:
            batch = getattr(self.inner, "detect_batch", None)
            if batch is None:
                return [self.inner.detect(text, language) for text in texts]
            return batch(texts, language)
        finally:
            self._record(started)

    def _record(self, started: float) -> None:
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
    #: Why this mode can't run as configured (audit without an LLM key), else ``None``.
    unavailable: str | None = None
    #: The gateway sends all of a request's uncached texts as one :meth:`detect_many` job
    #: (LAB-1279). Off for audit mode: its LLM detector is remote and per text, so its texts
    #: still run as parallel jobs.
    batches: bool = False

    def require_available(self) -> None:
        """Raise :class:`DetectionUnavailableError` when the mode is unavailable. The gateway
        calls this first, before detection, image masking or any request."""
        if self.unavailable is not None:
            raise DetectionUnavailableError(self.unavailable)

    def detect(self, text: str, language: str) -> tuple[list[Span], dict[str, float]]:
        """Spans to mask plus per-detector timings (ms). Runs in a worker thread.

        Raises :class:`~pii_guard.policy.BlockedEntityError` if a span has a ``block`` policy,
        :class:`DetectionUnavailableError` if the mode is unavailable.
        """
        spans, timings = self.resolve(text, language)
        return self.policies.apply(spans).masked, timings

    def detect_many(
        self, texts: Sequence[str], language: str
    ) -> tuple[list[list[Span]], dict[str, float]]:
        """:meth:`detect` for several texts in one call (one worker job), with summed timings."""
        found, timings = self.resolve_many(texts, language)
        return [self.policies.apply(spans).masked for spans in found], timings

    def resolve(self, text: str, language: str) -> tuple[list[Span], dict[str, float]]:
        """Like :meth:`detect`, but the spans kept by policy stay in (the gateway reports
        them in its echo, LAB-1180). ``block`` raises as in :meth:`detect`."""
        self.require_available()
        token = _timings.set({})
        try:
            spans = self.detector.detect(text, language)
            timings = dict(_timings.get() or {})
        finally:
            _timings.reset(token)
        spans = check_spans(spans, text, f"{self.mode.value} pipeline")
        self.policies.apply(spans)  # BlockedEntityError for a ``block`` type
        return list(spans), timings

    def resolve_many(
        self, texts: Sequence[str], language: str
    ) -> tuple[list[list[Span]], dict[str, float]]:
        """:meth:`resolve` for several texts in one call (one worker job), with summed timings.

        Uses the pipeline's ``detect_many`` when it has one, so the NER model runs on all
        texts in batched forwards. Fail closed: any error fails every text.
        """
        self.require_available()
        token = _timings.set({})
        try:
            many = getattr(self.detector, "detect_many", None)
            if many is not None:
                found = many(list(texts), language)
            else:
                found = [self.detector.detect(text, language) for text in texts]
            timings = dict(_timings.get() or {})
        finally:
            _timings.reset(token)
        if not isinstance(found, list) or len(found) != len(texts):
            raise DetectionError(f"{self.mode.value} pipeline returned the wrong number of results")
        name = f"{self.mode.value} pipeline"
        resolved = [
            list(check_spans(spans, text, name)) for spans, text in zip(found, texts, strict=True)
        ]
        for spans in resolved:
            self.policies.apply(spans)  # BlockedEntityError for a ``block`` type
        return resolved, timings


def gateway_policies(settings: Settings, config: GatewayConfig) -> PolicySet:
    """:meth:`PolicySet.from_settings`, with ``config.keep_types`` as the deprecated keep list."""
    return PolicySet.from_settings(settings, keep_types=config.keep_types)


def _ner_available() -> bool:
    """Kept for callers of the old name; the decision lives in :mod:`pii_guard.detect.stack`."""
    return stack.ner_available()


def _record_llm_ms(ms: float) -> None:
    timings = _timings.get()
    if timings is not None:
        timings["llm"] = timings.get("llm", 0.0) + ms


def _escalate_detector(
    settings: Settings,
    config: GatewayConfig,
    base: Sequence[Detector],
    llm: Detector,
    policies: PolicySet,
) -> ModeDetector:
    """Escalate mode: the fast pipeline (with raw-span recording for type conflicts) and the
    LLM, built from the gateway's ``escalate_*`` settings."""
    from pii_guard.detect.escalate import EscalatingDetector, RawRecorder

    fast = DetectionPipeline(
        [RawRecorder(_Timed(_CheckedBatch(d))) for d in base], keep_types=policies.keep_types
    )
    escalating = EscalatingDetector(
        fast,
        llm,
        radius=config.escalate_window,
        max_windows=config.escalate_max_windows,
        low_score=config.escalate_low_score,
        timeout=config.escalate_timeout,
        on_failure=config.escalate_on_failure,
        settings=settings,
        on_llm_ms=_record_llm_ms,
    )
    parts = [
        *(d.name for d in base),
        "llm",
        f"model={escalating.model}",
        f"window={config.escalate_window}",
        f"windows={config.escalate_max_windows}",
        f"low={config.escalate_low_score:g}",
        f"on_failure={config.escalate_on_failure}",
        "policies=" + policies.fingerprint(),
    ]
    return ModeDetector(
        Mode.ESCALATE,
        escalating,
        "escalate:" + ";".join(parts),
        policies,
        unavailable_reason(base) or escalating.unavailable_reason,
        batches=True,
    )


def build_mode_detectors(
    settings: Settings,
    config: GatewayConfig,
    *,
    base: Sequence[Detector] | None = None,
    llm_detector: Detector | None = None,
    escalate_llm: Detector | None = None,
) -> dict[Mode, ModeDetector]:
    """The fast, escalate and audit detectors.

    ``base`` defaults to :func:`~pii_guard.detect.stack.default_detector_names` (``rules`` +
    ``ner`` when available, built from the settings); ``llm_detector`` defaults to
    :class:`~pii_guard.detect.llm.LlmDetector` from the settings. ``escalate_llm`` is escalate
    mode's LLM detector: by default ``llm_detector`` when one is passed, else an
    :class:`~pii_guard.detect.llm.LlmDetector` with ``escalate_timeout`` and no empty-answer
    challenge (its found spans are masked, so the rules have nothing left to point at). All
    are injectable for tests. The local-only profile builds fast mode only.
    """
    if base is None:
        base = build_detectors(stack.default_detector_names(settings), settings)
    from pii_guard.detection_profile import is_local_only, require_detector_instance

    if is_local_only(settings):
        for detector in base:
            require_detector_instance(settings, detector)
        policies = gateway_policies(settings, config)
        pipeline = DetectionPipeline(
            [_Timed(_CheckedBatch(d)) for d in base], keep_types=policies.keep_types
        )
        return {
            Mode.FAST: ModeDetector(
                Mode.FAST,
                pipeline,
                "local-only:"
                + ",".join(d.name for d in base)
                + ";policies="
                + policies.fingerprint(),
                policies,
                unavailable_reason(base),
                batches=True,
            )
        }
    injected_llm = llm_detector is not None
    if llm_detector is None:
        from pii_guard.detect.llm import LlmDetector

        llm_detector = LlmDetector(settings=settings, reasoning_effort=config.llm_reasoning_effort)
    if escalate_llm is None:
        if injected_llm:
            escalate_llm = llm_detector
        else:
            from pii_guard.detect.llm import LlmDetector

            escalate_llm = LlmDetector(
                settings=settings,
                reasoning_effort=config.llm_reasoning_effort,
                timeout=config.escalate_timeout,
                challenge_empty=False,
            )
    policies = gateway_policies(settings, config)

    def build(mode: Mode, detectors: Iterable[Detector]) -> ModeDetector:
        detectors = list(detectors)
        pipeline = DetectionPipeline(
            [_Timed(_CheckedBatch(d)) for d in detectors], keep_types=policies.keep_types
        )
        llm_model = getattr(llm_detector, "model", "")
        parts = [d.name for d in detectors]
        if mode is Mode.AUDIT:
            parts.append(f"model={llm_model}")
        parts.append("policies=" + policies.fingerprint())
        return ModeDetector(
            mode,
            pipeline,
            f"{mode.value}:" + ";".join(parts),
            policies,
            unavailable_reason(detectors),
            batches=mode is Mode.FAST,
        )

    detectors = {
        Mode.FAST: build(Mode.FAST, base),
        Mode.ESCALATE: _escalate_detector(settings, config, base, escalate_llm, policies),
        Mode.AUDIT: build(Mode.AUDIT, [*base, llm_detector]),
    }
    logger.info(
        "gateway detectors: fast=%s audit=%s",
        [d.name for d in base],
        [*(d.name for d in base), llm_detector.name],
    )
    for mode_detector in detectors.values():
        if mode_detector.unavailable is not None:
            logger.warning(
                "gateway %s mode unavailable (requests get 503 detection_unavailable): %s",
                mode_detector.mode.value,
                mode_detector.unavailable,
            )
    return detectors


def detector_timings(per_text: Iterable[dict[str, float]]) -> dict[str, float]:
    """Sum per-detector wall times across a request's uncached texts."""
    totals: dict[str, float] = {}
    for timings in per_text:
        for name, ms in timings.items():
            totals[name] = totals.get(name, 0.0) + ms
    return totals
