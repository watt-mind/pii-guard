"""The detector stack shared by the REST API and the gateway (LAB-1270).

One place decides which detectors run for a :class:`~pii_guard.config.Settings` and checks
what they return, so ``/v1/mask`` and gateway fast mode can't drift apart:

- :func:`default_detector_names` -- ``rules``, plus ``ner`` when the ``ner`` detector resolves
  and a model does (:func:`ner_choice`: configured, published, then the public fallback).
  When ``PII_GUARD_NER_MODEL`` is set but NER can't be resolved, it raises
  :class:`~pii_guard.types.DetectionError` (fail closed, ADR 0006) instead of quietly running
  rules only. Without a configured model it falls back to rules and logs one WARNING.
- :func:`rest_detector_names` -- an explicit ``PII_GUARD_DETECTORS``, else the default stack.
- :func:`warm_up` -- load the NER model before serving (LAB-1274), when ``PII_GUARD_NER_MODEL``
  is set and the ``ner`` extra is installed.
- :func:`build_detector` -- a registry detector, configured from the settings (``llm`` gets
  the settings, ``ner`` gets ``ner_model`` / ``ner_revision`` / ``ner_device``).
- :class:`CheckedDetector` / :func:`check_spans` -- detector output must be a list of spans
  whose offsets match the text. Anything else, or an unexpected exception, is a
  ``DetectionError``. Messages never quote request text or span values.
- :class:`DetectionUnavailableError` / :func:`unavailable_reason` -- a detector that can't run
  safely as configured (the LLM detector without a key, LAB-1290) says why in
  ``unavailable_reason``; callers refuse with ``503 detection_unavailable`` before any detector
  runs, so nothing is sent anywhere.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Sequence
from typing import Any

from pii_guard.config import Settings
from pii_guard.detect import ner_resolve
from pii_guard.registry import create_detector, resolve_detector
from pii_guard.types import DetectionError, Detector, Span

__all__ = [
    "NER_EXTRA_MISSING",
    "CheckedDetector",
    "DetectionUnavailableError",
    "build_detector",
    "build_detectors",
    "check_spans",
    "default_detector_names",
    "ner_choice",
    "rest_detector_names",
    "unavailable_reason",
    "warm_up",
]

logger = logging.getLogger(__name__)

NER_EXTRA_MISSING = "ner configured but the 'ner' extra is not installed"


class DetectionUnavailableError(DetectionError):
    """A configured detector can't run safely (for example the LLM detector has no key).

    Raised before any detector runs or any request is made. Still a ``DetectionError``, so
    everything that fails closed on detection errors refuses this too.
    """

    code = "detection_unavailable"
    status_code = 503


def unavailable_reason(detectors: Iterable[object]) -> str | None:
    """The first ``unavailable_reason`` among ``detectors`` (wrappers are looked through)."""
    for detector in detectors:
        seen = 0
        current: object | None = detector
        while current is not None and seen < 8:  # _Timed(CheckedDetector(LlmDetector))
            reason = getattr(current, "unavailable_reason", None)
            if isinstance(reason, str) and reason:
                return reason
            current = getattr(current, "inner", None)
            seen += 1
    return None


_warn_lock = threading.Lock()
_warned_no_ner = False


def _ner_available() -> bool:
    """Whether the ``ner`` detector resolves (the ``ner`` extra is installed)."""
    try:
        resolve_detector("ner")
    except DetectionError:
        return False
    return True


def ner_choice(settings: Settings) -> ner_resolve.NerChoice:
    """Which NER model fast mode would run for ``settings`` (LAB-1192); downloads nothing."""
    return ner_resolve.resolve(
        configured=settings.ner_model,
        revision=settings.ner_revision,
        published=settings.ner_published_model,
        fallback=settings.ner_fallback,
    )


def _warn_no_ner_once(reason: str) -> None:
    global _warned_no_ner
    with _warn_lock:
        if _warned_no_ner:
            return
        _warned_no_ner = True
    logger.warning(
        "ner detector unavailable (%s): running rules only; "
        "set PII_GUARD_NER_MODEL to make a missing NER stop startup instead",
        reason,
    )


def default_detector_names(settings: Settings) -> tuple[str, ...]:
    """The default stack: gateway fast mode, and the REST API without ``PII_GUARD_DETECTORS``.

    ``rules`` plus ``ner`` when the ``ner`` extra is installed and a model resolves
    (:func:`ner_choice`). Raises :class:`DetectionError` when ``PII_GUARD_NER_MODEL`` is set
    but the extra is missing.
    """
    if _ner_available():
        choice = ner_choice(settings)
        if choice.usable:
            return ("rules", "ner")
        _warn_no_ner_once(choice.reason)
        return ("rules",)
    if settings.ner_model:
        raise DetectionError(NER_EXTRA_MISSING)
    _warn_no_ner_once("the 'ner' extra is not installed")
    return ("rules",)


def rest_detector_names(settings: Settings) -> tuple[str, ...]:
    """The REST API's detectors: an explicit ``PII_GUARD_DETECTORS`` wins over the default."""
    if settings.detectors:
        return tuple(settings.detectors)
    return default_detector_names(settings)


def build_detector(name: str, settings: Settings | None = None) -> Detector:
    """A registry detector by name, configured from ``settings`` where it takes any."""
    kwargs: dict[str, Any] = {}
    if name == "llm":
        kwargs["settings"] = settings
    elif name == "ner" and settings is not None:
        # Only what is set: NerDetector keeps its own env fallback for direct use.
        for key, value in (
            ("model", settings.ner_model),
            ("revision", settings.ner_revision),
            ("device", settings.ner_device),
            ("published", settings.ner_published_model),
            ("fallback", settings.ner_fallback),
        ):
            if value:
                kwargs[key] = value
    return create_detector(name, **kwargs)


def build_detectors(names: Sequence[str], settings: Settings | None = None) -> list[Detector]:
    if not names:
        raise DetectionError("no detectors configured")
    return [build_detector(name, settings) for name in names]


def warm_up(settings: Settings) -> bool:
    """Load the configured NER model now, so the first requests don't race to load it.

    Runs only when ``PII_GUARD_NER_MODEL`` is set and the ``ner`` extra is installed; returns
    whether it loaded. The REST API's and the gateway's NER detectors share the loaded model
    (:mod:`pii_guard.detect.ner`). A model that can't be loaded raises
    :class:`DetectionError` (fail closed: startup stops).
    """
    if not settings.ner_model or not _ner_available():
        return False
    detector = build_detector("ner", settings)
    load = getattr(detector, "load", None)
    if callable(load):
        load()
    return True


def check_spans(found: object, text: str, name: str) -> list[Span]:
    """Reject anything that is not a list of valid spans of ``text`` (fail closed)."""
    if not isinstance(found, list):
        raise DetectionError(f"detector {name!r} returned {type(found).__name__}, not a list")
    for index, span in enumerate(found):
        if not isinstance(span, Span):
            raise DetectionError(f"detector {name!r} returned a non-span at index {index}")
        if span.end > len(text) or text[span.start : span.end] != span.text:
            raise DetectionError(
                f"detector {name!r} returned a {span.entity_type.value} span that does not "
                f"match the text at [{span.start}, {span.end})"
            )
    return found


class CheckedDetector:
    """Wraps a detector: unexpected errors and malformed output become ``DetectionError``."""

    def __init__(self, inner: Detector) -> None:
        self.inner = inner
        self.name: str = getattr(inner, "name", type(inner).__name__)

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        try:
            found = self.inner.detect(text, language=language)
        except DetectionError:
            raise
        except Exception as exc:
            # Never str(exc): it may quote the input.
            raise DetectionError(f"detector {self.name!r} failed") from exc
        return check_spans(found, text, self.name)
