"""The gateway: mask a Chat Completions request, forward it, restore the answer.

Order of operations (fail closed at every step, ADR 0006):

1. upstream configured? mode and session headers valid? body well-formed, nothing it can't
   mask (remote image URLs, audio, files)?
2. detect every text (cache first; misses run concurrently, under one per-request timeout),
   then add the session's pre-loaded known values (:mod:`pii_guard.detect.known`), which win
   their conflicts and are masked even for a ``keep`` type (a ``block`` type still refuses);
3. widen a name detected only in part to a full name known from this request or the session
   (:func:`~pii_guard.detect.known.widen_request`: ``1,Jane Placeholder`` with only the surname
   detected becomes one span), then
   mask with the conversation's vault session: spans first, then a sweep for every value the
   session already knows (so a value found in one message is masked in all of them); inline
   images are masked with the visual pipeline (SAM 3.1 + OCR text through this mode's
   detectors + policies) and replaced by a masked PNG data URL. With placeholder labels
   (``PII_GUARD_IMAGE_RENDER=labels``, the default) the images' values join the same session
   (fuzzy-matched to the text's values, :mod:`pii_guard.visual.labels`), each covered region
   shows its placeholder, and a text part with the image's masked transcript and document
   summary follows the image; the texts are then swept once more for values first seen in an
   image;
4. forward the masked body; restore the answer (streamed: chunk by chunk);
5. seed the detection cache with the restored answer, which comes back as history next turn.

Nothing in this module logs or raises with request text, values, masked bodies or keys.

Every call is timed per stage (:class:`~pii_guard.observability.RequestTimer`) and, when the
traffic log or the metrics are on, recorded as one event (:mod:`pii_guard.gateway.trace`).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from collections import Counter
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from pii_guard.api.deps import PayloadTooLargeError
from pii_guard.api.routes.image_masking import (
    ImageMasker,
    ImageMaskOutcome,
    default_ocr_engine,
    mask_images_bounded,
    require_ocr,
)
from pii_guard.config import Settings
from pii_guard.detect.known import KNOWN_DETECTOR, WIDENED_TYPES, merge_known, widen_request
from pii_guard.gateway.cache import DetectionCache
from pii_guard.gateway.config import DEPRECATED_MODE_ALIASES, GatewayConfig, Mode, parse_mode
from pii_guard.gateway.detection import ModeDetector, build_mode_detectors, detector_timings
from pii_guard.gateway.request import (
    ImageSlot,
    InvalidChatRequestError,
    TextSlot,
    collect_texts,
)
from pii_guard.gateway.restore import restore_completion, restore_text
from pii_guard.gateway.sessions import (
    SESSION_HEADER,
    SESSION_SOURCE_HEADER,
    SessionSource,
    resolve_session,
)
from pii_guard.gateway.stream import DONE, SseRestorer, error_event, iter_sse_data, sse_event
from pii_guard.gateway.trace import CallTrace
from pii_guard.observability import Observability, RequestTimer
from pii_guard.policy import Policy
from pii_guard.types import DetectionError, PiiGuardError, Span
from pii_guard.vault import Vault, VaultSession
from pii_guard.vault.known import KnownValues
from pii_guard.visual.ocr import OcrEngine
from pii_guard.visual.segment import Segmenter
from pii_guard.visual.segmenters import build_segmenter
from pii_guard.workers import BoundedWorkers

__all__ = [
    "ECHO_HEADER",
    "LANGUAGE_HEADER",
    "MODE_HEADER",
    "REQUEST_ID_HEADER",
    "SESSION_HEADER",
    "SESSION_SOURCE_HEADER",
    "Gateway",
    "UpstreamError",
    "UpstreamNotConfiguredError",
]

logger = logging.getLogger("pii_guard.gateway")

REQUEST_ID_HEADER = "X-PII-Guard-Request-Id"
MODE_HEADER = "X-PII-Guard-Mode"
LANGUAGE_HEADER = "X-PII-Guard-Language"
# Opt-in: "masked" echoes back what the upstream saw (the masked messages) and said (its
# masked answer), for UIs that show the boundary. Masked text only, never the values.
ECHO_HEADER = "X-PII-Guard-Echo"

_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})?$")
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_MAX_ERROR_BODY = 65_536
_UNSET: Any = object()


class UpstreamNotConfiguredError(PiiGuardError):
    code = "upstream_not_configured"
    status_code = 503


class UpstreamError(PiiGuardError):
    """The upstream could not be reached or answered with something unusable."""

    code = "upstream_unavailable"
    status_code = 502


@dataclass
class RequestStats:
    """Counts only. Rendered into response headers and the gateway log line."""

    mode: Mode
    #: The deprecated mode name the request asked for (``strict``), if any.
    mode_alias: str | None = None
    texts: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    seeded: int = 0
    spans: Counter[str] = field(default_factory=Counter)
    masked: Counter[str] = field(default_factory=Counter)
    detect_ms: float = 0.0
    detector_ms: dict[str, float] = field(default_factory=dict)
    upstream_status: int | None = None
    upstream_ms: float = 0.0
    unresolved: int = 0
    stream: bool = False
    images: int = 0
    image_masked: Counter[str] = field(default_factory=Counter)
    image_kept: Counter[str] = field(default_factory=Counter)
    image_ocr: bool | None = None
    image_ms: float = 0.0
    session_source: SessionSource | None = None

    def headers(self, session_id: str) -> dict[str, str]:
        out = {
            SESSION_HEADER: session_id,
            MODE_HEADER: self.mode.value,
            "X-PII-Guard-Cache-Hits": str(self.cache_hits),
            "X-PII-Guard-Cache-Misses": str(self.cache_misses),
            "X-PII-Guard-Masked": str(sum(self.masked.values())),
        }
        if self.session_source is not None:
            out[SESSION_SOURCE_HEADER] = self.session_source.value
        if self.mode_alias:
            out["Deprecation"] = "true"
            out["Warning"] = (
                f'299 pii-guard "{MODE_HEADER}: {self.mode_alias} is deprecated, '
                f'use {self.mode.value}"'
            )
        if self.images:
            out["X-PII-Guard-Images"] = str(self.images)
            out["X-PII-Guard-Image-Regions-Masked"] = str(sum(self.image_masked.values()))
            out["X-PII-Guard-Image-OCR"] = "on" if self.image_ocr else "off"
        return out

    def log_fields(self) -> dict[str, object]:
        fields: dict[str, object] = {
            "mode": self.mode.value,
            "texts": self.texts,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "masked": _counts(self.masked),
            "detect_ms": f"{self.detect_ms:.0f}",
        }
        if self.images:
            fields["images"] = self.images
            fields["image_masked"] = _counts(self.image_masked)
            fields["image_ms"] = f"{self.image_ms:.0f}"
        return fields

    def log(self, outcome: str) -> None:
        logger.info(
            "chat.completions %s mode=%s stream=%s texts=%d cache_hits=%d cache_misses=%d "
            "seeded=%d spans=%s masked=%s detect_ms=%.0f detectors=%s upstream=%s "
            "upstream_ms=%.0f unresolved=%d images=%d image_masked=%s image_ms=%.0f",
            outcome,
            self.mode.value,
            self.stream,
            self.texts,
            self.cache_hits,
            self.cache_misses,
            self.seeded,
            _counts(self.spans),
            _counts(self.masked),
            self.detect_ms,
            ",".join(f"{k}:{v:.0f}" for k, v in sorted(self.detector_ms.items())) or "-",
            self.upstream_status if self.upstream_status is not None else "-",
            self.upstream_ms,
            self.unresolved,
            self.images,
            _counts(self.image_masked),
            self.image_ms,
        )


def _counts(counter: Mapping[str, int]) -> str:
    return ",".join(f"{k}:{v}" for k, v in sorted(counter.items()) if v) or "-"


def _counts_of(session: VaultSession) -> Counter[str]:
    return Counter({p: c for p, _, c in session.entities()})


def _count_masked(stats: RequestStats, before: Counter[str], session: VaultSession) -> None:
    """Add the text occurrences masked since ``before`` to ``stats.masked`` (by type)."""
    for placeholder, entity_type, count in session.entities():
        delta = count - before.get(placeholder, 0)
        if delta > 0:
            stats.masked[entity_type.value] += delta


def image_annotation(number: int, outcome: ImageMaskOutcome) -> str:
    """The text part sent after a labelled image: its summary and masked transcript.

    Placeholders only (the transcript and summary are checked for covered values before they
    get here, :func:`pii_guard.visual.labels.label_image`)."""
    summary = json.dumps(outcome.summary, ensure_ascii=False, sort_keys=True)
    lines = [
        f"[pii-guard: image {number} was masked; each covered region shows the placeholder "
        "of its value, the same placeholders as in the text]",
        f"Document summary: {summary}",
    ]
    if outcome.transcript:
        lines += ["Masked transcript:", outcome.transcript]
    return "\n".join(lines)


class Gateway:
    """One per app. Everything is injectable for tests: detectors, cache, upstream transport."""

    def __init__(
        self,
        *,
        settings: Settings,
        vault: Vault,
        config: GatewayConfig | None = None,
        detectors: Mapping[Mode, ModeDetector] | None = None,
        cache: DetectionCache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sam: Segmenter | None = None,
        ocr: OcrEngine | None = _UNSET,
        observability: Observability | None = None,
        image_workers: BoundedWorkers | None = None,
    ) -> None:
        """``sam`` / ``ocr`` mask inline images: default the segmenter of the settings
        (:func:`~pii_guard.visual.segmenters.build_segmenter`) and Tesseract when installed;
        ``ocr=None`` turns OCR off (segmenter only).
        ``observability`` receives one traffic event per call (none: nothing recorded).
        ``image_workers`` runs image masking (default: a pool of ``image_concurrency``)."""
        self.observability = observability
        self.settings = settings
        self.vault = vault
        self.config = config or GatewayConfig()
        self._detectors = dict(detectors) if detectors is not None else None
        self.cache = cache or DetectionCache(self.config.cache_size)
        self._transport = transport
        # One upstream client per gateway, created on first use (LAB-1176): building one is
        # ~4.5 ms of blocking TLS and proxy setup on the event loop, and only a shared pool
        # keeps connections to the upstream alive between calls.
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None
        # Blocking detector calls run on one bounded pool per mode (LAB-1207): a slot stays
        # taken until the thread finishes, so a hung audit-mode detector can't starve fast.
        self._detect_workers: dict[Mode, BoundedWorkers] = {}
        self._image_workers = image_workers
        self._sam = sam
        self._ocr = ocr

    def __repr__(self) -> str:
        return f"Gateway(mode={self.config.mode.value}, cache={self.cache!r})"

    # --- the upstream client ------------------------------------------------------------

    def upstream_timeout(self) -> httpx.Timeout:
        """The timeout of one upstream call (set per request on the shared client)."""
        return httpx.Timeout(self.config.upstream_timeout, connect=10.0)

    def upstream_client(self) -> httpx.AsyncClient:
        """The shared upstream client of this gateway, created on first use.

        A new one is built when the running event loop changes (pooled connections belong to
        the loop that opened them: test clients may run each request on a new loop; a server
        has one). Callers close the *response*, never this client; :meth:`aclose` closes it on
        app shutdown."""
        loop = asyncio.get_running_loop()
        client = self._client
        if client is None or client.is_closed or self._client_loop is not loop:
            config = self.config
            client = httpx.AsyncClient(
                timeout=self.upstream_timeout(),
                transport=self._transport,
                limits=httpx.Limits(
                    max_connections=config.upstream_max_connections,
                    max_keepalive_connections=config.upstream_max_keepalive,
                    keepalive_expiry=config.upstream_keepalive_expiry,
                ),
            )
            self._client, self._client_loop = client, loop
        return client

    async def aclose(self) -> None:
        """Close the upstream client and its pooled connections (the next call opens a new one)."""
        client, self._client, self._client_loop = self._client, None, None
        if client is not None:
            await client.aclose()

    @property
    def detectors(self) -> dict[Mode, ModeDetector]:
        if self._detectors is None:
            self._detectors = build_mode_detectors(self.settings, self.config)
        return self._detectors

    def image_masker(self, detector: ModeDetector) -> ImageMasker:
        """The visual pipeline for one mode: OCR text goes through that mode's detectors."""
        if self._sam is None:
            self._sam = build_segmenter(self.settings)
        if self._ocr is _UNSET:
            self._ocr = default_ocr_engine()
        return ImageMasker(
            sam=self._sam,
            policies=detector.policies,
            ocr=self._ocr,
            text_detector=detector.detector if self._ocr is not None else None,
            text_detector_names=[detector.mode.value],
            max_pixels=self.settings.image_max_pixels,
        )

    # --- request parsing -----------------------------------------------------------------

    def _mode(self, headers: Mapping[str, str]) -> Mode:
        raw = headers.get(MODE_HEADER)
        if raw is None or not raw.strip():
            return self.config.mode
        try:
            return parse_mode(raw)[0]
        except ValueError:
            raise InvalidChatRequestError(
                f"{MODE_HEADER} must be one of: {', '.join(m.value for m in Mode)}"
            ) from None

    @staticmethod
    def _mode_alias(headers: Mapping[str, str]) -> str | None:
        """The deprecated mode name in the request header (``strict``), else ``None``."""
        raw = (headers.get(MODE_HEADER) or "").strip().lower()
        return raw if raw in DEPRECATED_MODE_ALIASES else None

    def _language(self, headers: Mapping[str, str]) -> str:
        raw = headers.get(LANGUAGE_HEADER)
        if raw is None or not raw.strip():
            return self.settings.default_language
        if not _LANGUAGE_RE.match(raw.strip()):
            raise InvalidChatRequestError(f"{LANGUAGE_HEADER} must be a language tag like 'hu'")
        return raw.strip()

    def _echo(self, headers: Mapping[str, str]) -> bool:
        raw = headers.get(ECHO_HEADER)
        if raw is None or raw.strip() == "":
            return False
        if raw.strip().lower() != "masked":
            raise InvalidChatRequestError(f"{ECHO_HEADER} must be 'masked'")
        return True

    def _session(
        self,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        path_session: str | None,
        stats: RequestStats,
        trace: CallTrace,
    ) -> tuple[VaultSession, bool]:
        """The request's vault session: header, URL path, ``prompt_cache_key``, default
        (:mod:`pii_guard.gateway.sessions`). Recorded on ``stats`` and ``trace``."""
        session, created, source = resolve_session(self.vault, headers, body, path_session)
        stats.session_source = source
        trace.session_id, trace.session_new = session.session_id, created
        trace.session_source = source.value
        return session, created

    def _upstream_url(self) -> str:
        base = self.settings.upstream_base_url
        if not base:
            raise UpstreamNotConfiguredError(
                "PII_GUARD_UPSTREAM_BASE_URL is not set; the gateway has nowhere to forward to"
            )
        base = base.rstrip("/")
        return base if base.endswith("/chat/completions") else base + "/chat/completions"

    def _upstream_headers(self, headers: Mapping[str, str]) -> dict[str, str]:
        out = {"Content-Type": "application/json", "Accept": "application/json"}
        key = self.settings.upstream_api_key
        if key is not None:
            out["Authorization"] = f"Bearer {key.get_secret_value()}"
        elif headers.get("authorization"):
            # No configured key: pass the client's own key through (bring your own key).
            out["Authorization"] = headers["authorization"]
        return out

    # --- detection and masking -----------------------------------------------------------

    async def _detect_all(
        self,
        slots: list[TextSlot],
        detector: ModeDetector,
        session: VaultSession,
        language: str,
        stats: RequestStats,
    ) -> list[list[Span]]:
        # Audit mode without an LLM key: 503 detection_unavailable before anything is detected,
        # cached, segmented or sent (LAB-1290). Runs first in chat and responses alike.
        detector.require_available()
        results: list[list[Span] | None] = [None] * len(slots)
        pending: dict[bytes, tuple[str, list[int], Any]] = {}
        for index, slot in enumerate(slots):
            if not any(ch.isalnum() for ch in slot.text):
                results[index] = []
                continue
            key = self.cache.key(session.session_id, language, detector.config_id, slot.text)
            cached = self.cache.get(key, slot.text)
            if cached is not None:
                stats.cache_hits += 1
                results[index] = cached
                continue
            if key[1] in pending:  # the same text twice in one request: detect once
                pending[key[1]][1].append(index)
                stats.cache_hits += 1
                continue
            stats.cache_misses += 1
            pending[key[1]] = (slot.text, [index], key)

        if pending:
            workers = self._detect_workers.get(detector.mode)
            if workers is None:
                workers = BoundedWorkers(
                    self.config.concurrency, f"pii-guard-detect-{detector.mode.value}"
                )
                self._detect_workers[detector.mode] = workers

            async def run(text: str) -> tuple[list[Span], dict[str, float]]:
                return await workers.run(detector.detect, text, language)

            started = time.perf_counter()
            jobs = list(pending.values())
            try:
                outputs = await asyncio.wait_for(
                    asyncio.gather(*(run(text) for text, _, _ in jobs)),
                    timeout=self.config.detection_timeout,
                )
            except TimeoutError:
                raise DetectionError(
                    f"detection timed out after {self.config.detection_timeout:g}s "
                    f"({detector.mode.value} mode)"
                ) from None
            except PiiGuardError:  # DetectionError, BlockedEntityError: already safe to return
                raise
            except Exception as exc:
                raise DetectionError(f"detection failed ({type(exc).__name__})") from exc
            finally:
                stats.detect_ms = (time.perf_counter() - started) * 1000
            stats.detector_ms = detector_timings(timings for _, timings in outputs)
            for (_, indices, key), (spans, _) in zip(jobs, outputs, strict=True):
                self.cache.put(key, spans)
                for index in indices:
                    results[index] = spans
        out = [r if r is not None else [] for r in results]
        known = session.known_values
        if known:
            # After the cache: values pre-loaded later still apply to cached detections.
            started = time.perf_counter()
            out = [
                self._with_known(slot.text, spans, known, detector, language)
                for slot, spans in zip(slots, out, strict=True)
            ]
            elapsed = (time.perf_counter() - started) * 1000
            stats.detector_ms[KNOWN_DETECTOR] = stats.detector_ms.get(KNOWN_DETECTOR, 0) + elapsed
        for spans in out:
            stats.spans.update(s.entity_type.value for s in spans)
        return out

    @staticmethod
    def _with_known(
        text: str,
        spans: list[Span],
        known: KnownValues,
        detector: ModeDetector,
        language: str,
    ) -> list[Span]:
        merged = merge_known(text, spans, known, language, keep_types=detector.policies.keep_types)
        # BlockedEntityError for a known value of a ``block`` type; ``keep`` ones are masked.
        detector.policies.apply(s for s in merged if s.detector == KNOWN_DETECTOR)
        return merged

    def _mask(
        self,
        slots: list[TextSlot],
        spans: list[list[Span]],
        session: VaultSession,
        language: str,
    ) -> list[str]:
        # A name found whole in one text repairs the same name found in part in another, or
        # one this session already has ("1,Jane Placeholder" with only "Placeholder" detected).
        texts = [slot.text for slot in slots]
        spans = widen_request(texts, spans, session.confirmed_values(WIDENED_TYPES), language)
        masked = [
            session.mask(text, found, language=language)
            for text, found in zip(texts, spans, strict=True)
        ]
        # Second pass: values confirmed in a later text are masked in earlier ones too.
        return [session.mask(text, [], language=language, remask=True) for text in masked]

    @staticmethod
    def _write(
        slots: list[TextSlot],
        masked: list[str],
        session: VaultSession,
        language: str,
        remask: bool,
    ) -> None:
        if remask:  # values first seen in an image are masked in the texts too
            masked = [session.mask(text, [], language=language, remask=True) for text in masked]
        for slot, text in zip(slots, masked, strict=True):
            slot.write(text)

    def _seed_cache(
        self,
        session: VaultSession,
        language: str,
        detector: ModeDetector,
        restored: Mapping[int, tuple[str, list[Span]]],
        stats: RequestStats,
    ) -> None:
        """The client sends the restored answer back as history: pre-detect it.

        Its personal data is exactly the restored placeholders; anything else in it came from
        the upstream itself, which already has it.
        """
        for text, spans in restored.values():
            if text and any(ch.isalnum() for ch in text):
                key = self.cache.key(session.session_id, language, detector.config_id, text)
                self.cache.put(key, spans)
                stats.seeded += 1

    async def _mask_images(
        self,
        images: list[ImageSlot],
        detector: ModeDetector,
        language: str,
        stats: RequestStats,
        session: VaultSession,
    ) -> None:
        """Mask every inline image (fail closed) and write masked PNG data URLs back; with
        placeholder labels, also add each image's transcript and summary after it."""
        masker = self.image_masker(detector)
        stats.image_ocr = masker.ocr is not None
        # No OCR: refuse (503 ocr_unavailable) unless explicitly opted out; nothing is sent.
        require_ocr(masker.ocr, required=self.settings.image_require_ocr)
        render = self.settings.image_render
        if self._image_workers is None:
            self._image_workers = BoundedWorkers(self.settings.image_concurrency, "pii-guard-image")
        started = time.perf_counter()
        try:
            # Bounded pool, per-request deadline (Tesseract killed), values registered in the
            # session only once every image succeeded (LAB-1207).
            outcomes = await mask_images_bounded(
                masker,
                [slot.data for slot in images],
                language,
                workers=self._image_workers,
                timeout=self.config.image_timeout,
                render=render,
                session=session,
            )
        except PiiGuardError:
            raise
        except Exception as exc:
            raise DetectionError(f"image masking failed ({type(exc).__name__})") from exc
        finally:
            stats.image_ms = (time.perf_counter() - started) * 1000
        for outcome in outcomes:
            stats.image_masked.update({t.value: n for t, n in outcome.counts(Policy.MASK).items()})
            stats.image_kept.update({t.value: n for t, n in outcome.counts(Policy.KEEP).items()})
        for number, (slot, outcome) in enumerate(zip(images, outcomes, strict=True), start=1):
            slot.write("data:image/png;base64," + base64.b64encode(outcome.image).decode("ascii"))
            if outcome.summary is not None:
                slot.annotate(image_annotation(number, outcome))

    # --- the endpoint --------------------------------------------------------------------

    async def chat_completions(
        self,
        body: object,
        headers: Mapping[str, str],
        *,
        max_text_chars: int | None = None,
        received_at: float | None = None,
        path_session: str | None = None,
    ) -> tuple[Response, RequestStats]:
        """Mask, forward, restore. ``received_at`` (``perf_counter``) starts the timer;
        ``path_session`` is the session id of a ``/s/<session>/v1/...`` URL."""
        timer = RequestTimer(received_at)
        trace = CallTrace(self.observability, timer, body)
        try:
            response, stats = await self._chat_completions(
                body,
                headers,
                max_text_chars=max_text_chars,
                timer=timer,
                trace=trace,
                path_session=path_session,
            )
        except BaseException as exc:
            trace.fail(exc)
            raise
        response.headers[REQUEST_ID_HEADER] = trace.request_id
        if self.observability is not None and self.observability.server_timing:
            response.headers["Server-Timing"] = timer.server_timing()
        if not trace.streaming:
            trace.finish()
        return response, stats

    async def _chat_completions(
        self,
        body: object,
        headers: Mapping[str, str],
        *,
        max_text_chars: int | None,
        timer: RequestTimer,
        trace: CallTrace,
        path_session: str | None = None,
    ) -> tuple[Response, RequestStats]:
        url = self._upstream_url()
        mode = self._mode(headers)
        language = self._language(headers)
        trace.mode, trace.language = mode.value, language
        echo = self._echo(headers)
        stats = RequestStats(mode=mode, mode_alias=self._mode_alias(headers))
        trace.stats = stats
        collected = collect_texts(body)
        body = cast(dict[str, Any], body)  # collect_texts checked it
        too_long = max_text_chars is not None and any(
            len(s.text) > max_text_chars for s in collected.slots
        )
        if too_long:
            raise PayloadTooLargeError(f"a message text is longer than {max_text_chars} characters")
        if len(collected.images) > self.config.max_images:
            raise PayloadTooLargeError(
                f"a request may carry at most {self.config.max_images} inline images"
            )
        if any(len(img.data) > self.config.max_image_bytes for img in collected.images):
            raise PayloadTooLargeError(
                f"an inline image is larger than {self.config.max_image_bytes} bytes"
            )
        detector = self.detectors[mode]
        session, created = self._session(headers, body, path_session, stats, trace)
        stream = bool(body.get("stream"))
        stats.stream = stream
        stats.texts = len(collected.slots)
        stats.images = len(collected.images)
        timer.add("parse", time.perf_counter() - timer.started)
        try:
            with timer.span("detect"):
                spans = await self._detect_all(collected.slots, detector, session, language, stats)
            before = _counts_of(session)
            with timer.span("mask"):
                masked = self._mask(collected.slots, spans, session, language)
            _count_masked(stats, before, session)
            if collected.images:
                with timer.span("image"):
                    await self._mask_images(collected.images, detector, language, stats, session)
            before = _counts_of(session)
            with timer.span("mask"):
                self._write(collected.slots, masked, session, language, bool(collected.images))
                collected.finalize()
            _count_masked(stats, before, session)
        except BaseException:
            stats.log("blocked")
            if created:
                self.vault.drop(session.session_id)
                self.cache.drop_session(session.session_id)
            raise

        forwarding = time.perf_counter()
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if trace.payloads:
            trace.masked_request = payload
        masked_messages = _masked_messages(body) if echo else None
        client = self.upstream_client()
        request = client.build_request(
            "POST",
            url,
            content=payload,
            headers=self._upstream_headers(headers),
            timeout=self.upstream_timeout(),
        )
        started = time.perf_counter()
        timer.add("forward", started - forwarding)
        timer.upstream_sent = started
        try:
            response = await client.send(request, stream=True)
        except httpx.HTTPError as exc:
            timer.add("upstream", time.perf_counter() - started)
            stats.log("upstream_unreachable")
            raise UpstreamError(f"upstream request failed ({type(exc).__name__})") from None
        timer.add("upstream_ttfb", time.perf_counter() - started)
        timer.add("upstream", time.perf_counter() - started)

        stats.upstream_status = response.status_code
        out_headers = stats.headers(session.session_id)
        if response.status_code >= 400:
            try:
                raw = await _read_limited(response)
            finally:
                await response.aclose()
            stats.upstream_ms = (time.perf_counter() - started) * 1000
            timer.add("upstream", stats.upstream_ms / 1000 - timer.stages["upstream"])
            stats.log("upstream_error")
            return _upstream_error(response.status_code, raw, out_headers), stats

        is_sse = response.headers.get("content-type", "").startswith("text/event-stream")
        if not stream or not is_sse:
            try:
                raw = await response.aread()
            except httpx.HTTPError as exc:
                raise UpstreamError(f"upstream response failed ({type(exc).__name__})") from None
            finally:
                await response.aclose()
            stats.upstream_ms = (time.perf_counter() - started) * 1000
            timer.add("upstream", stats.upstream_ms / 1000 - timer.stages["upstream"])
            if trace.payloads:
                trace.upstream_body = raw
            building = time.perf_counter()
            try:
                answer = json.loads(raw)
            except ValueError:
                stats.log("upstream_invalid")
                raise UpstreamError("upstream returned a body that is not JSON") from None
            if not isinstance(answer, dict):
                raise UpstreamError("upstream returned a body that is not a JSON object")
            masked_answer = _masked_answer(answer) if echo else None
            report = restore_completion(session, answer)
            stats.unresolved = len(report.unresolved)
            self._seed_cache(session, language, detector, report.restored_spans, stats)
            out_headers["X-PII-Guard-Unresolved"] = str(stats.unresolved)
            if echo:
                answer["pii_guard"] = {
                    "masked_messages": masked_messages,
                    "masked_answer": masked_answer,
                }
            stats.log("ok")
            if trace.full:
                trace.answer = answer
            elif trace.recording and isinstance(answer.get("usage"), dict):
                trace.usage = answer["usage"]
            result = JSONResponse(answer, headers=out_headers)
            timer.add("response", time.perf_counter() - building)
            timer.finish()
            return result, stats

        restorer = SseRestorer(session)
        trace.streaming = True

        async def timed_lines() -> AsyncIterator[str]:
            """The upstream's lines; time spent waiting on them counts as upstream time."""
            lines = response.aiter_lines().__aiter__()
            while True:
                waiting = time.perf_counter()
                try:
                    line = await lines.__anext__()
                except StopAsyncIteration:
                    timer.add("upstream", time.perf_counter() - waiting)
                    return
                timer.add("upstream", time.perf_counter() - waiting)
                if line.startswith("data:"):
                    timer.mark_first_data()
                yield line

        echoed_answer = False

        def answer_event() -> bytes:
            content = restorer.masked_content()
            return sse_event(
                json.dumps(
                    {
                        "object": "pii_guard.masked_answer",
                        "choices": [{"index": i, "content": content[i]} for i in sorted(content)],
                    },
                    ensure_ascii=False,
                )
            )

        async def produce() -> AsyncIterator[bytes]:
            """The restored events; every await in here is upstream time or pii-guard's own."""
            nonlocal echoed_answer
            if echo:
                yield sse_event(
                    json.dumps(
                        {"object": "pii_guard.masked_request", "messages": masked_messages},
                        ensure_ascii=False,
                    )
                )
            async for data in iter_sse_data(timed_lines()):
                unmasking = time.perf_counter()
                outs = restorer.process(data)
                timer.add("unmask", time.perf_counter() - unmasking)
                trace.scan_usage(data)
                for out in outs:
                    timer.mark_first_event()
                    if out == DONE and echo and not echoed_answer:
                        echoed_answer = True
                        yield answer_event()
                    yield sse_event(out)
            unmasking = time.perf_counter()
            outs = restorer.finish()
            timer.add("unmask", time.perf_counter() - unmasking)
            for out in outs:
                yield sse_event(out)
            if echo and not echoed_answer:
                echoed_answer = True
                yield answer_event()

        async def events() -> AsyncIterator[bytes]:
            """Hand ``produce()``'s events to the client; time suspended in ``yield`` is the
            client's (read speed, backpressure), not overhead."""
            outcome = "ok"
            source = produce()
            try:
                try:
                    async for chunk in source:
                        sending = time.perf_counter()
                        try:
                            yield chunk
                        finally:
                            timer.add("client", time.perf_counter() - sending)
                except Exception as exc:
                    # Fail closed: stop the stream with an error event, no exception text.
                    outcome = f"stream_error:{type(exc).__name__}"
                    sending = time.perf_counter()
                    try:
                        yield sse_event(error_event("stream_failed", "the response stream failed"))
                    finally:
                        timer.add("client", time.perf_counter() - sending)
            except (GeneratorExit, asyncio.CancelledError):
                # The client went away mid-stream (the server closes or cancels this generator).
                # The answer is partial: record it as such and never seed the cache with it.
                if outcome == "ok":
                    outcome = "client_disconnected"
                raise
            finally:
                await source.aclose()
                await response.aclose()
                stats.upstream_ms = timer.stages["upstream"] * 1000
                stats.unresolved = len(restorer.unresolved)
                if outcome == "ok":
                    restored = {}
                    for index, masked in restorer.masked_content().items():
                        text, spans, _ = restore_text(session, masked)
                        restored[index] = (text, spans)
                    self._seed_cache(session, language, detector, restored, stats)
                    if trace.full:
                        trace.stream_restored = {i: t for i, (t, _) in restored.items()}
                stats.log(outcome)
                if trace.payloads:
                    trace.stream_masked = restorer.masked_content()
                    trace.stream_chunks = restorer.chunks
                if outcome == "ok":
                    trace.finish()
                elif outcome == "client_disconnected":
                    trace.finish(outcome=outcome, error={"code": outcome})
                else:
                    trace.finish(outcome="stream_error", error={"code": "stream_failed"})

        return (
            StreamingResponse(events(), media_type="text/event-stream", headers=out_headers),
            stats,
        )


def _flatten(content: object) -> str:
    """A message's text content; non-text parts (masked images) as a short marker."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                out.append(str(part.get("text", "")))
            elif isinstance(part, dict):
                out.append(f"[{part.get('type', 'part')}]")
        return "\n".join(out)
    return ""


def _masked_messages(body: Mapping[str, Any]) -> list[dict[str, str]]:
    """The forwarded (masked) messages, role and text only, for :data:`ECHO_HEADER`."""
    out = []
    for message in body.get("messages") or []:
        if isinstance(message, dict):
            out.append(
                {"role": str(message.get("role", "")), "content": _flatten(message.get("content"))}
            )
    return out


def _masked_answer(answer: Mapping[str, Any]) -> list[dict[str, object]]:
    """The upstream's answer before restoring, per choice, for :data:`ECHO_HEADER`."""
    out: list[dict[str, object]] = []
    for position, choice in enumerate(answer.get("choices") or []):
        if isinstance(choice, dict):
            message = choice.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            out.append(
                {
                    "index": choice.get("index", position),
                    "content": content if isinstance(content, str) else "",
                }
            )
    return out


async def _read_limited(response: httpx.Response) -> bytes:
    data = bytearray()
    async for chunk in response.aiter_bytes():
        data.extend(chunk)
        if len(data) > _MAX_ERROR_BODY:
            break
    return bytes(data)


def _upstream_error(status: int, raw: bytes, headers: dict[str, str]) -> JSONResponse:
    """The upstream's status, with only its error ``type``/``code`` tokens kept.

    The upstream's message may quote the (masked) request, so it is never passed on.
    """
    error: dict[str, object] = {
        "code": "upstream_error",
        "message": f"upstream returned HTTP {status}",
        "type": "upstream_error",
    }
    try:
        upstream = json.loads(raw).get("error")
    except (ValueError, AttributeError):
        upstream = None
    if isinstance(upstream, dict):
        for name in ("type", "code"):
            value = upstream.get(name)
            if isinstance(value, str) and _SAFE_TOKEN_RE.match(value):
                error[f"upstream_{name}"] = value
    return JSONResponse({"error": error}, status_code=status, headers=headers)
