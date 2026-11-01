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
  is set and the NER dependencies are installed.
- :class:`NerWarmup` -- without ``PII_GUARD_NER_MODEL``, load the resolved NER (download
  included) in a background thread at startup (LAB-1303); requests that need it wait for it,
  bounded, and get ``503 detector_loading`` or ``503 detection_unavailable`` only when it is
  still loading after the wait or failed to load.
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
import sys
import threading
import time
from collections.abc import Iterable, Sequence
from typing import Any, Literal

from pii_guard.config import Settings
from pii_guard.detect import ner_resolve
from pii_guard.registry import create_detector, resolve_detector
from pii_guard.types import DetectionError, Detector, Span

__all__ = [
    "NER_EXTRA_MISSING",
    "CheckedDetector",
    "DetectionUnavailableError",
    "DetectorLoadingError",
    "NerWarmup",
    "build_detector",
    "build_detectors",
    "check_spans",
    "default_detector_names",
    "ner_available",
    "ner_choice",
    "ner_in_stack",
    "rest_detector_names",
    "unavailable_reason",
    "warm_up",
]

logger = logging.getLogger(__name__)

NER_EXTRA_MISSING = "ner configured but torch and transformers are not installed"


class DetectionUnavailableError(DetectionError):
    """A configured detector can't run safely (for example the LLM detector has no key).

    Raised before any detector runs or any request is made. Still a ``DetectionError``, so
    everything that fails closed on detection errors refuses this too.
    """

    code = "detection_unavailable"
    status_code = 503


class DetectorLoadingError(DetectionError):
    """The NER model is still loading after the bounded wait (LAB-1303): retry shortly.

    Nothing ran and nothing was sent. A ``DetectionError``, so callers fail closed on it.
    """

    code = "detector_loading"
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
    """Whether the ``ner`` detector resolves (torch and transformers are installed)."""
    try:
        resolve_detector("ner")
    except DetectionError:
        return False
    return True


def ner_available() -> bool:
    """Whether the ``ner`` detector resolves (delegates to :func:`_ner_available`)."""
    return _ner_available()


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

    ``rules`` plus ``ner`` when torch and transformers are installed (the default install;
    the rules-only base Docker image skips them) and a model resolves (:func:`ner_choice`).
    Raises :class:`DetectionError` when ``PII_GUARD_NER_MODEL`` is set but they are missing.
    """
    from pii_guard.detection_profile import is_local_only, require_detector

    if is_local_only(settings):
        names = settings.detectors or ("rules", "ner")
        for name in names:
            require_detector(settings, name)
        if "ner" in names and not _ner_available():
            raise DetectionError(NER_EXTRA_MISSING)
        return tuple(names)
    if _ner_available():
        choice = ner_choice(settings)
        if choice.usable:
            return ("rules", "ner")
        _warn_no_ner_once(choice.reason)
        return ("rules",)
    if settings.ner_model:
        raise DetectionError(NER_EXTRA_MISSING)
    _warn_no_ner_once(_missing_ner_reason())
    return ("rules",)


def no_torch_build() -> bool:
    """Intel macOS: PyTorch publishes no wheel, so the install skips it (LAB-1743)."""
    import platform

    return sys.platform == "darwin" and platform.machine() == "x86_64"


def _missing_ner_reason() -> str:
    if no_torch_build():
        # The torch dependency is skipped there (pyproject.toml): no wheel exists (LAB-1743).
        return (
            "PyTorch has no Intel macOS build; for rules + NER run the Docker image "
            "(docs/operations.md)"
        )
    return "torch and transformers are not installed"


def rest_detector_names(settings: Settings) -> tuple[str, ...]:
    """The REST API's detectors: an explicit ``PII_GUARD_DETECTORS`` wins over the default."""
    from pii_guard.detection_profile import is_local_only

    if is_local_only(settings):
        return default_detector_names(settings)
    if settings.detectors:
        return tuple(settings.detectors)
    return default_detector_names(settings)


def build_detector(name: str, settings: Settings | None = None) -> Detector:
    """A registry detector by name, configured from ``settings`` where it takes any."""
    kwargs: dict[str, Any] = {}
    if settings is not None:
        from pii_guard.detection_profile import is_local_only, require_detector

        require_detector(settings, name)
        if name == "ner" and is_local_only(settings):
            kwargs["local_files_only"] = True
            kwargs["backend_kind"] = "transformers"
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

    Runs only when ``PII_GUARD_NER_MODEL`` is set and torch/transformers are installed; returns
    whether it loaded. The REST API's and the gateway's NER detectors share the loaded model
    (:mod:`pii_guard.detect.ner`). A model that can't be loaded raises
    :class:`DetectionError` (fail closed: startup stops).
    """
    from pii_guard.detection_profile import is_local_only

    if is_local_only(settings) and "ner" not in default_detector_names(settings):
        return False
    if not settings.ner_model or not _ner_available():
        return False
    _load_ner(settings)
    return True


def _load_ner(settings: Settings) -> None:
    """Build the ``ner`` detector and load its model (process-wide, shared: ``detect.ner``)."""
    detector = build_detector("ner", settings)
    load = getattr(detector, "load", None)
    if callable(load):
        load()


def ner_in_stack(settings: Settings) -> bool:
    """Whether the REST API's or the gateway's detectors include ``ner`` for ``settings``."""
    try:
        names = {*rest_detector_names(settings), *default_detector_names(settings)}
    except DetectionError:
        return False
    return "ner" in names


NerState = Literal["off", "loading", "ready", "failed"]


class NerWarmup:
    """Loads the NER model in a background thread so the server answers while it loads.

    ``state`` is ``off`` (no NER in the stack, or not started), ``loading``, ``ready`` or
    ``failed`` (``error`` says why: the exception type only, ADR 0006). Requests that need a
    detector call :meth:`wait` / :meth:`wait_async` first: they wait for the load, up to a
    timeout, instead of loading the model themselves (on the event loop, for the gateway) or
    racing it. A failed load is not retried: restart the server.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state: NerState = "off"
        self.error: str | None = None
        #: Wall time of the load, once it finished (ready or failed).
        self.seconds: float | None = None
        self._done = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def pending(self) -> bool:
        """Requests must wait (``loading``) or be refused (``failed``)."""
        return self.state in ("loading", "failed")

    def mark_ready(self) -> None:
        """The model was loaded some other way (``PII_GUARD_NER_MODEL``: :func:`warm_up`)."""
        with self._lock:
            self.state = "ready"
            self._done.set()

    def start(self) -> bool:
        """Start the background load if ``ner`` is in the stack; returns whether it started."""
        with self._lock:
            if self.state != "off" or not ner_in_stack(self.settings):
                return False
            self.state = "loading"
            self._thread = threading.Thread(
                target=self._run, name="pii-guard-ner-warmup", daemon=True
            )
            self._thread.start()
        return True

    def _run(self) -> None:
        started = time.monotonic()
        try:
            _load_ner(self.settings)
        except DetectionError as exc:
            self._finish("failed", exc.message, started)
        except Exception as exc:  # never str(exc): it may quote a path or the input
            self._finish("failed", f"ner model could not be loaded ({type(exc).__name__})", started)
        else:
            self._finish("ready", None, started)

    def _finish(self, state: NerState, error: str | None, started: float) -> None:
        with self._lock:
            self.state, self.error = state, error
            self.seconds = time.monotonic() - started
            self._done.set()
        if error is None:
            logger.info("ner model ready after %.1fs (background warm-up)", self.seconds)
        else:
            logger.error("ner warm-up failed (requests get 503 detection_unavailable): %s", error)

    def check(self, waited: float | None = None) -> None:
        """Raise unless requests may run now (``off`` or ``ready``)."""
        if self.state == "failed":
            raise DetectionUnavailableError(f"ner model unavailable: {self.error}")
        if self.state == "loading":
            after = f" after waiting {waited:g}s" if waited is not None else ""
            raise DetectorLoadingError(f"the ner model is still loading{after}; retry shortly")

    def wait(self, timeout: float) -> None:
        """Block until the load finished, up to ``timeout`` seconds, then :meth:`check`."""
        if self.state == "loading":
            self._done.wait(timeout)
        self.check(timeout)

    async def wait_async(self, timeout: float, poll: float = 0.05) -> None:
        """:meth:`wait` without blocking the event loop (or holding a worker thread)."""
        import anyio  # the API's event loop library; not needed by the rest of the stack

        if self.state == "loading":
            with anyio.move_on_after(timeout):
                while not self._done.is_set():  # noqa: ASYNC110
                    await anyio.sleep(poll)
        self.check(timeout)


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
