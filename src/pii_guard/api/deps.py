"""Shared dependencies of the ``/v1/*`` routers: the analyzer (detection) and the vault.

Both are built lazily, once per app, and cached on ``app.state``:

- ``app.state.analyzer`` -- anything with ``analyze(text, language) -> list[Span]``. The
  default, :class:`RegistryAnalyzer`, runs the detectors named in
  ``app.state.detector_names`` (default :data:`DEFAULT_DETECTOR_NAMES`) through the registry
  and drops overlaps. A full detection pipeline (resolver, policies) plugs in by setting
  ``app.state.analyzer`` -- the routes only depend on the :class:`Analyzer` protocol.
- ``app.state.vault`` -- a :class:`~pii_guard.vault.Vault` keyed by ``PII_GUARD_TENANT_KEY``.
  Without a key every masking endpoint fails closed with ``vault_not_configured``.

Fail closed (ADR 0006): any detector error, including an unexpected exception or an invalid
span, is raised as :class:`~pii_guard.types.DetectionError`; nothing is ever returned
partially. No error message or log line contains request text or span values.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from fastapi import Request

from pii_guard.registry import create_detector
from pii_guard.types import DetectionError, Detector, PiiGuardError, Span
from pii_guard.vault import Vault

__all__ = [
    "DEFAULT_DETECTOR_NAMES",
    "DEFAULT_MAX_TEXT_CHARS",
    "Analyzer",
    "PayloadTooLargeError",
    "RegistryAnalyzer",
    "get_analyzer",
    "get_language",
    "get_max_text_chars",
    "get_vault",
    "resolve_overlaps",
]

logger = logging.getLogger(__name__)

DEFAULT_DETECTOR_NAMES: tuple[str, ...] = ("rules",)
# Upper bound on the analysed text, in code points. Override with app.state.max_text_chars.
DEFAULT_MAX_TEXT_CHARS = 200_000

_init_lock = threading.Lock()


class PayloadTooLargeError(PiiGuardError):
    """The request body or text is larger than the configured limit."""

    code = "payload_too_large"
    status_code = 413


@runtime_checkable
class Analyzer(Protocol):
    """Detection as the API sees it: non-overlapping spans sorted by ``start``."""

    def analyze(self, text: str, language: str) -> list[Span]: ...


def resolve_overlaps(spans: Sequence[Span]) -> list[Span]:
    """Non-overlapping spans sorted by ``start``.

    Greedy: among overlapping spans the longest wins, then the highest score. A stand-in
    until the detection pipeline's resolver lands.
    """
    ranked = sorted(spans, key=lambda s: (-s.length, -s.score, s.start, s.detector))
    kept: list[Span] = []
    for span in ranked:
        if not any(span.overlaps(other) for other in kept):
            kept.append(span)
    return sorted(kept, key=lambda s: (s.start, s.end))


class RegistryAnalyzer:
    """Runs registry detectors by name and merges their spans with :func:`resolve_overlaps`."""

    def __init__(self, detector_names: Sequence[str] = DEFAULT_DETECTOR_NAMES) -> None:
        if not detector_names:
            raise DetectionError("no detectors configured")
        self.detectors: list[Detector] = [create_detector(name) for name in detector_names]

    def analyze(self, text: str, language: str) -> list[Span]:
        spans: list[Span] = []
        for detector in self.detectors:
            name = getattr(detector, "name", type(detector).__name__)
            try:
                found = detector.detect(text, language=language)
            except DetectionError:
                raise
            except Exception as exc:
                # Never str(exc): it may quote the input.
                raise DetectionError(f"detector {name!r} failed") from exc
            spans.extend(_checked(found, text, name))
        return resolve_overlaps(spans)


def _checked(found: object, text: str, name: str) -> list[Span]:
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


def get_analyzer(request: Request) -> Analyzer:
    """The app's analyzer, built on first use."""
    state = request.app.state
    analyzer = getattr(state, "analyzer", None)
    if analyzer is None:
        with _init_lock:
            analyzer = getattr(state, "analyzer", None)
            if analyzer is None:
                names = getattr(state, "detector_names", None) or DEFAULT_DETECTOR_NAMES
                analyzer = RegistryAnalyzer(names)
                state.analyzer = analyzer
                logger.info("analyzer ready with detectors: %s", list(names))
    return analyzer


def get_vault(request: Request) -> Vault:
    """The app's vault, built on first use. Fails closed if the tenant key is unset."""
    state = request.app.state
    vault = getattr(state, "vault", None)
    if vault is None:
        with _init_lock:
            vault = getattr(state, "vault", None)
            if vault is None:
                try:
                    vault = Vault.from_settings(state.settings)
                except ValueError:
                    # Invalid hex or too short; never echo the key.
                    raise PiiGuardError(
                        "PII_GUARD_TENANT_KEY is invalid: expected at least 16 bytes of hex",
                        code="vault_not_configured",
                    ) from None
                state.vault = vault
    return vault


def get_language(request: Request, language: str | None) -> str:
    """The request's language, or ``Settings.default_language``."""
    return language or request.app.state.settings.default_language


def get_max_text_chars(request: Request) -> int:
    return int(getattr(request.app.state, "max_text_chars", DEFAULT_MAX_TEXT_CHARS))
