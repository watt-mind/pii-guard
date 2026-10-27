"""Shared dependencies of the ``/v1/*`` routers: the analyzer, the policies and the vault.

All are cached on ``app.state``; the analyzer and vault are built lazily, once per app:

- ``app.state.analyzer`` -- anything with ``analyze(text, language) -> list[Span]``. The
  default, :class:`RegistryAnalyzer`, runs the detectors named in ``app.state.detector_names``
  (set by ``create_app`` from ``PII_GUARD_DETECTORS``, default ``rules``) through
  :class:`~pii_guard.detect.pipeline.DetectionPipeline`, the one resolver shared with the
  gateway and the eval. Tests and embedders can set ``app.state.analyzer`` directly -- the
  routes only depend on the :class:`Analyzer` protocol.
- ``app.state.policies`` -- the :class:`~pii_guard.policy.PolicySet` (defaults plus
  ``PII_GUARD_POLICY_OVERRIDES``), built by ``create_app``.
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

from pii_guard.config import DEFAULT_DETECTORS, Settings
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.policy import PolicySet
from pii_guard.registry import create_detector
from pii_guard.types import DetectionError, Detector, PiiGuardError, Span
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


class PayloadTooLargeError(PiiGuardError):
    """The request body or text is larger than the configured limit."""

    code = "payload_too_large"
    status_code = 413


@runtime_checkable
class Analyzer(Protocol):
    """Detection as the API sees it: non-overlapping spans sorted by ``start``."""

    def analyze(self, text: str, language: str) -> list[Span]: ...


def build_detector(name: str, settings: Settings | None = None) -> Detector:
    """A registry detector by name. ``llm`` gets the app's settings."""
    if name == "llm":
        return create_detector(name, settings=settings)
    return create_detector(name)


class _Checked:
    """Wraps a detector: unexpected errors and malformed output become ``DetectionError``."""

    def __init__(self, inner: Detector) -> None:
        self.inner = inner
        self.name = getattr(inner, "name", type(inner).__name__)

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        try:
            found = self.inner.detect(text, language=language)
        except DetectionError:
            raise
        except Exception as exc:
            # Never str(exc): it may quote the input.
            raise DetectionError(f"detector {self.name!r} failed") from exc
        return _checked(found, text, self.name)


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
        if not detector_names:
            raise DetectionError("no detectors configured")
        self.detectors: list[Detector] = [build_detector(n, settings) for n in detector_names]
        self.pipeline = DetectionPipeline(
            [_Checked(d) for d in self.detectors],
            keep_types=(policies or PolicySet()).keep_types,
        )

    def analyze(self, text: str, language: str) -> list[Span]:
        return self.pipeline.detect(text, language)


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
                analyzer = RegistryAnalyzer(
                    names, policies=get_policies(request), settings=state.settings
                )
                state.analyzer = analyzer
                logger.info("analyzer ready with detectors: %s", list(names))
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
