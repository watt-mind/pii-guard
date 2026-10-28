"""Shared dependencies of the ``/v1/*`` routers: the analyzer, the policies and the vault.

All are cached on ``app.state``; the analyzer and vault are built lazily, once per app:

- ``app.state.analyzer`` -- anything with ``analyze(text, language) -> list[Span]``. The
  default, :class:`RegistryAnalyzer`, runs the detectors named in ``app.state.detector_names``
  (set by ``create_app`` with :func:`~pii_guard.detect.stack.rest_detector_names`: an explicit
  ``PII_GUARD_DETECTORS``, else the gateway fast-mode stack, rules + ner when available) through
  :class:`~pii_guard.detect.pipeline.DetectionPipeline`, the one resolver shared with the
  gateway and the eval. Tests and embedders can set ``app.state.analyzer`` directly -- the
  routes only depend on the :class:`Analyzer` protocol.
- ``app.state.policies`` -- the :class:`~pii_guard.policy.PolicySet` (defaults plus
  ``PII_GUARD_POLICY_OVERRIDES``, via :meth:`~pii_guard.policy.PolicySet.from_settings`, the
  builder the gateway uses too), built by ``create_app``.
- ``app.state.vault`` -- a :class:`~pii_guard.vault.Vault` keyed by ``PII_GUARD_TENANT_KEY``.
  Without a key every masking endpoint fails closed with ``vault_not_configured``.

Fail closed (ADR 0006): any detector error, including an unexpected exception or an invalid
span, is raised as :class:`~pii_guard.types.DetectionError`
(:class:`~pii_guard.detect.stack.CheckedDetector`, shared with the gateway); nothing is ever
returned partially. No error message or log line contains request text or span values.
A detector that can't run safely as configured (``llm`` without a key, LAB-1290) makes the
analyzer refuse with ``503 detection_unavailable`` before any detector runs.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence

from fastapi import Request

from pii_guard.config import DEFAULT_DETECTORS, Settings
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.detect.stack import (
    CheckedDetector,
    DetectionUnavailableError,
    build_detector,
    build_detectors,
    rest_detector_names,
    unavailable_reason,
)
from pii_guard.policy import PolicySet
from pii_guard.types import Analyzer, Detector, PayloadTooLargeError, PiiGuardError, Span
from pii_guard.vault import Vault

__all__ = [
    "DEFAULT_DETECTOR_NAMES",
    "DEFAULT_MAX_TEXT_CHARS",
    "Analyzer",
    "PayloadTooLargeError",
    "RegistryAnalyzer",
    "build_detector",
    "get_analyzer",
    "get_language",
    "get_max_text_chars",
    "get_policies",
    "get_vault",
]

logger = logging.getLogger(__name__)

DEFAULT_DETECTOR_NAMES: tuple[str, ...] = DEFAULT_DETECTORS
# Upper bound on the analysed text, in code points. Override with app.state.max_text_chars.
DEFAULT_MAX_TEXT_CHARS = 200_000

_init_lock = threading.Lock()


class RegistryAnalyzer:
    """Runs registry detectors by name through :class:`DetectionPipeline`.

    ``keep_types`` (from the policies) lose overlaps against masked types in the resolver, so
    a person's name inside a sole trader's company name stays a ``PERSON``.
    """

    def __init__(
        self,
        detector_names: Sequence[str] = DEFAULT_DETECTOR_NAMES,
        *,
        policies: PolicySet | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.detectors: list[Detector] = build_detectors(detector_names, settings)
        self.pipeline = DetectionPipeline(
            [CheckedDetector(d) for d in self.detectors],
            keep_types=(policies or PolicySet()).keep_types,
        )
        #: Why the analyzer refuses (a configured detector can't run safely), else ``None``.
        self.unavailable: str | None = unavailable_reason(self.detectors)
        if self.unavailable is not None:
            logger.warning(
                "analyzer unavailable (requests get 503 detection_unavailable): %s",
                self.unavailable,
            )

    def require_available(self) -> None:
        """Raise :class:`DetectionUnavailableError` if a configured detector can't run."""
        if self.unavailable is not None:
            raise DetectionUnavailableError(self.unavailable)

    def analyze(self, text: str, language: str) -> list[Span]:
        self.require_available()
        return self.pipeline.detect(text, language)


def get_analyzer(request: Request) -> Analyzer:
    """The app's analyzer, built on first use."""
    state = request.app.state
    analyzer = getattr(state, "analyzer", None)
    if analyzer is None:
        with _init_lock:
            analyzer = getattr(state, "analyzer", None)
            if analyzer is None:
                names = getattr(state, "detector_names", None) or rest_detector_names(
                    state.settings
                )
                analyzer = RegistryAnalyzer(
                    names, policies=get_policies(request), settings=state.settings
                )
                state.analyzer = analyzer
                logger.info("analyzer ready with detectors: %s", list(names))
    hosted = getattr(state, "hosted", None)
    if hosted is not None:
        from pii_guard.hosted.runtime import BoundedAnalyzer

        return BoundedAnalyzer(analyzer, hosted.rest_slots)
    return analyzer


def get_policies(request: Request) -> PolicySet:
    """The app's entity policies (``create_app`` sets them from the settings)."""
    state = request.app.state
    policies = getattr(state, "policies", None)
    if policies is None:
        policies = PolicySet.from_settings(state.settings)
        state.policies = policies
    return policies


def get_vault(request: Request) -> Vault:
    """The app's vault, built on first use. Fails closed if the tenant key is unset."""
    runtime = getattr(request.state, "hosted_runtime", None)
    if runtime is not None:
        return runtime.vault
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
