"""The gateway: mask a Chat Completions request, forward it, restore the answer.

Order of operations (fail closed at every step, ADR 0006):

1. upstream configured? mode and session headers valid? body well-formed, nothing it can't
   mask (remote image URLs, audio, files)?
2. detect every text (cache first; misses run concurrently, under one per-request timeout),
   then add the session's pre-loaded known values (:mod:`pii_guard.detect.known`), which win
   their conflicts and are masked even for a ``keep`` type (a ``block`` type still refuses),
   and drop the detections in identifier slots that are exactly a tool name the request
   declares (:func:`~pii_guard.gateway.tool_names.without_tool_names`, LAB-1317/LAB-1563);
3. widen a name detected only in part to a full name known from this request or the session
   (:func:`~pii_guard.detect.known.widen_request`), then mask with the conversation's vault
   session; inline images are masked with the visual pipeline and replaced by a masked PNG
   data URL;
4. forward the masked body; restore the answer (streamed: chunk by chunk);
5. seed the detection cache with the restored answer, which comes back as history next turn.

Nothing in this module logs or raises with request text, values, masked bodies or keys.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import threading
import time
import weakref
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Coroutine, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi.responses import StreamingResponse
from starlette.responses import Response

from pii_guard.config import Settings
from pii_guard.detect.known import KNOWN_DETECTOR, WIDENED_TYPES, merge_known, widen_request
from pii_guard.gateway.cache import DetectionCache
from pii_guard.gateway.chat import (
    ECHO_HEADER,
    LANGUAGE_HEADER,
    MODE_HEADER,
    REQUEST_ID_HEADER,
    RequestStats,
    UpstreamError,
    UpstreamNotConfiguredError,
    _chat_echo_answer_event,
    _chat_stream_error,
    _count_masked,
    _counts,
    _counts_of,
    _flatten,
    _kept_spans,
    _masked_answer,
    _masked_messages,
    _produce_chat_events,
    _read_bounded,
    _read_limited,
    _upstream_error,
    chat_completions,
    check_upstream_payload_with_limit,
    image_annotation,
    run_chat_completions,
    write_masked_slots,
)
from pii_guard.gateway.config import DEPRECATED_MODE_ALIASES, GatewayConfig, Mode, parse_mode
from pii_guard.gateway.detection import ModeDetector, build_mode_detectors, detector_timings
from pii_guard.gateway.opaque_ids import IssuedIds
from pii_guard.gateway.outbound import OutboundCheckFailedError, check_outbound
from pii_guard.gateway.placeholder_note import needs_note
from pii_guard.gateway.request import (
    CollectedTexts,
    ImageSlot,
    InvalidChatRequestError,
    TextSlot,
    dumps_utf8,
)
from pii_guard.gateway.sessions import (
    SESSION_HEADER,
    SESSION_SOURCE_HEADER,
    client_identity,
    resolve_session,
)
from pii_guard.gateway.trace import CallTrace
from pii_guard.observability import Observability, RequestTimer
from pii_guard.policy import Policy
from pii_guard.types import DetectionError, PayloadTooLargeError, PiiGuardError, Span
from pii_guard.vault import Vault, VaultSession
from pii_guard.vault.known import KnownValues
from pii_guard.visual.masking import (
    ImageMasker,
    default_ocr_engine,
    mask_images_bounded,
    require_ocr,
)
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
    "UPSTREAM_PAYLOAD_LIMIT",
    "Gateway",
    "RequestStats",
    "UpstreamError",
    "UpstreamNotConfiguredError",
    "_chat_echo_answer_event",
    "_chat_stream_error",
    "_count_masked",
    "_counts",
    "_counts_of",
    "_flatten",
    "_kept_spans",
    "_masked_answer",
    "_masked_messages",
    "_produce_chat_events",
    "_read_bounded",
    "_read_limited",
    "_upstream_error",
    "check_upstream_payload",
    "image_annotation",
]

logger = logging.getLogger("pii_guard.gateway")

_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})?$")
_UNSET: Any = object()

#: The vault leases (session, client identity) the current request holds, set by
#: :meth:`Gateway.with_session_lease` (module-level, LAB-1584: a ContextVar per gateway
#: instance is never collected).
_REQUEST_SESSIONS: ContextVar[list[tuple[VaultSession, str]] | None] = ContextVar(
    "pii_guard_request_sessions", default=None
)

#: The largest masked upstream payload (bytes) the current request was admitted for. Hosted
#: admission charges this bound in advance (hosted/quotas.py); None means no bound (local).
UPSTREAM_PAYLOAD_LIMIT: ContextVar[int | None] = ContextVar(
    "pii_guard_upstream_payload_limit", default=None
)


def check_upstream_payload(payload: bytes, image_bytes: int = 0) -> None:
    """Refuse a masked payload larger than the bound its admission was charged for."""
    check_upstream_payload_with_limit(payload, image_bytes, UPSTREAM_PAYLOAD_LIMIT)


@dataclass
class _SessionHold:
    """The requests between resolving a session and finishing masking into it (LAB-1316)."""

    in_flight: int = 0
    #: A request on the session finished masking: its placeholders are in use, keep it.
    kept: bool = False
    #: The request that created the session was refused.
    refused_creator: bool = False


_LEASED_CLASSES: dict[type[StreamingResponse], type[StreamingResponse]] = {}


def _leased_class(cls: type[StreamingResponse]) -> type[StreamingResponse]:
    """``cls`` with an ASGI call that always releases the request's vault leases (LAB-1573)."""
    if getattr(cls, "_pii_guard_leased", False):
        return cls
    leased = _LEASED_CLASSES.get(cls)
    if leased is None:

        async def __call__(self: Any, scope: Any, receive: Any, send: Any) -> None:
            try:
                await cls.__call__(self, scope, receive, send)
            finally:
                self.pii_guard_release()

        leased = type(
            f"Leased{cls.__name__}", (cls,), {"__call__": __call__, "_pii_guard_leased": True}
        )
        _LEASED_CLASSES[cls] = leased
    return leased


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
        self.observability = observability
        self.settings = settings
        self.vault = vault
        self.config = config or GatewayConfig()
        self._detectors = dict(detectors) if detectors is not None else None
        self.cache = cache if cache is not None else DetectionCache(self.config.cache_size)
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None
        self._detect_workers: dict[Mode, BoundedWorkers] = {}
        self._image_workers = image_workers
        self._sam = sam
        self._ocr = ocr
        self._session_holds: dict[str, _SessionHold] = {}
        self._holds_lock = threading.Lock()
        self.upstream_extra_headers: dict[str, str] = {}
        self.issued_ids = IssuedIds()
        self._session_incarnations: OrderedDict[str, weakref.ref[VaultSession]] = OrderedDict()

    def __repr__(self) -> str:
        return f"Gateway(mode={self.config.mode.value}, cache={self.cache!r})"

    @property
    def detect_workers(self) -> dict[Mode, BoundedWorkers]:
        """The per-mode bounded worker pools used for detector execution."""
        return self._detect_workers

    @detect_workers.setter
    def detect_workers(self, value: dict[Mode, BoundedWorkers]) -> None:
        self._detect_workers = value

    def bind_shared_state(
        self,
        *,
        detect_workers: dict[Mode, BoundedWorkers],
        session_holds: dict[str, Any],
        holds_lock: Any,
        issued_ids: IssuedIds,
        session_incarnations: OrderedDict[str, Any],
    ) -> None:
        """Bind per-runtime session state and shared detector worker pools to this gateway."""
        self._detect_workers = detect_workers
        self._session_holds = session_holds
        self._holds_lock = holds_lock
        self.issued_ids = issued_ids
        self._session_incarnations = session_incarnations

    # --- the upstream client ------------------------------------------------------------

    def upstream_timeout(self) -> httpx.Timeout:
        """The timeout of one upstream call (set per request on the shared client)."""
        return httpx.Timeout(self.config.upstream_timeout, connect=10.0)

    def upstream_client(self) -> httpx.AsyncClient:
        """The shared upstream client of this gateway, created on first use."""
        loop = asyncio.get_running_loop()
        client = self._client
        if client is None or client.is_closed or self._client_loop is not loop:
            config = self.config
            client = httpx.AsyncClient(
                timeout=self.upstream_timeout(),
                transport=self._transport,
                trust_env=not self.settings.hosted,
                follow_redirects=False,
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
        elif self._transport is not None:
            await self._transport.aclose()

    async def bound_upstream_response(self, response: httpx.Response) -> None:
        """Bound untrusted hosted upstream bytes before buffering or SSE parsing."""
        if not self.settings.hosted:
            return
        from pii_guard.hosted.egress import MAX_RESPONSE_BYTES, BoundedResponseStream

        if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
            await response.aclose()
            raise UpstreamError("Compressed upstream responses are unavailable in hosted mode")
        if response.is_stream_consumed:
            if len(response.content) > MAX_RESPONSE_BYTES:
                await response.aclose()
                raise UpstreamError("Upstream response exceeds hosted size limit")
        else:
            response.stream = BoundedResponseStream(response.stream)

    @property
    def detectors(self) -> dict[Mode, ModeDetector]:
        if self._detectors is None:
            self._detectors = build_mode_detectors(self.settings, self.config)
        from pii_guard.detection_profile import is_local_only, require_detector_instance

        if is_local_only(self.settings):
            for detector in self._detectors.values():
                require_detector_instance(self.settings, detector.detector)
        return self._detectors

    def image_masker(self, detector: ModeDetector) -> ImageMasker:
        """The visual pipeline for one mode: OCR text goes through that mode's detectors."""
        if self._sam is None:
            self._sam = build_segmenter(self.settings)
        if self._ocr is _UNSET:
            self._ocr = default_ocr_engine()
        from pii_guard.detection_profile import require_local_ocr, require_segmenter_instance

        require_segmenter_instance(self.settings, self._sam)
        require_local_ocr(self.settings, self._ocr)
        return ImageMasker(
            sam=self._sam,
            policies=detector.policies,
            ocr=self._ocr,
            text_detector=detector.detector if self._ocr is not None else None,
            text_detector_names=[detector.mode.value],
            max_pixels=self.settings.image_max_pixels,
        )

    # --- request parsing -----------------------------------------------------------------

    def mode(self, headers: Mapping[str, str]) -> Mode:
        raw = headers.get(MODE_HEADER)
        try:
            mode = self.config.mode if raw is None or not raw.strip() else parse_mode(raw)[0]
        except ValueError:
            raise InvalidChatRequestError(
                f"{MODE_HEADER} must be one of: {', '.join(m.value for m in Mode)}"
            ) from None
        if mode is not Mode.FAST:
            from pii_guard.detection_profile import refuse_remote

            refuse_remote(self.settings, "audit detection")
        return mode

    _mode = mode

    @staticmethod
    def mode_alias(headers: Mapping[str, str]) -> str | None:
        """The deprecated mode name in the request header (``strict``), else ``None``."""
        raw = (headers.get(MODE_HEADER) or "").strip().lower()
        return raw if raw in DEPRECATED_MODE_ALIASES else None

    _mode_alias = mode_alias

    def language(self, headers: Mapping[str, str]) -> str:
        raw = headers.get(LANGUAGE_HEADER)
        if raw is None or not raw.strip():
            return self.settings.default_language
        if not _LANGUAGE_RE.match(raw.strip()):
            raise InvalidChatRequestError(f"{LANGUAGE_HEADER} must be a language tag like 'hu'")
        return raw.strip()

    _language = language

    def echo(self, headers: Mapping[str, str]) -> bool:
        raw = headers.get(ECHO_HEADER)
        if raw is None or raw.strip() == "":
            return False
        if raw.strip().lower() != "masked":
            raise InvalidChatRequestError(f"{ECHO_HEADER} must be 'masked'")
        return True

    _echo = echo

    def validate_limits(
        self,
        collected: CollectedTexts,
        max_text_chars: int | None,
        *,
        text_label: str = "a message text",
    ) -> None:
        if max_text_chars is not None and any(
            len(s.text) > max_text_chars for s in collected.slots
        ):
            raise PayloadTooLargeError(f"{text_label} is longer than {max_text_chars} characters")
        if len(collected.images) > self.config.max_images:
            raise PayloadTooLargeError(
                f"a request may carry at most {self.config.max_images} inline images"
            )
        if any(len(img.data) > self.config.max_image_bytes for img in collected.images):
            raise PayloadTooLargeError(
                f"an inline image is larger than {self.config.max_image_bytes} bytes"
            )

    def session(
        self,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        path_session: str | None,
        stats: RequestStats,
        trace: CallTrace,
    ) -> tuple[VaultSession, bool]:
        """The request's vault session: header, URL path, ``prompt_cache_key``, default."""
        identity = client_identity(headers)
        with self._holds_lock:
            session, created, source = self.vault.acquire_session(
                lambda: resolve_session(self.vault, headers, body, path_session),
                identity=identity,
            )
            sessions = _REQUEST_SESSIONS.get()
            if sessions is None:
                self.vault.release_session(session, identity=identity)
                raise RuntimeError("session resolution requires a request lease scope")
            sessions.append((session, identity))
            previous = self._session_incarnations.get(session.session_id)
            if previous is not None and previous() is not session:
                self.cache.drop_session(session.session_id)
                self.issued_ids.drop(session.session_id)
            self._session_incarnations[session.session_id] = weakref.ref(session)
            self._session_incarnations.move_to_end(session.session_id)
            while len(self._session_incarnations) > 16384:
                self._session_incarnations.popitem(last=False)
            hold = self._session_holds.setdefault(session.session_id, _SessionHold())
            hold.in_flight += 1
        stats.session_source = source
        trace.session_id, trace.session_new = session.session_id, created
        trace.session_source = source.value
        return session, created

    _session = session

    async def with_session_lease(
        self, work: Coroutine[Any, Any, tuple[Response, RequestStats]]
    ) -> tuple[Response, RequestStats]:
        """Keep request pins through upstream work and the stream's final cleanup."""
        sessions: list[tuple[VaultSession, str]] = []
        token = _REQUEST_SESSIONS.set(sessions)

        def release() -> None:
            while sessions:
                session, identity = sessions.pop()
                self.vault.release_session(session, identity=identity)

        try:
            response, stats = await work
            if isinstance(response, StreamingResponse):
                source = response.body_iterator

                async def leased_stream() -> AsyncIterator[Any]:
                    try:
                        async for chunk in source:
                            yield chunk
                    finally:
                        try:
                            if hasattr(source, "aclose"):
                                await source.aclose()
                        finally:
                            release()

                response.body_iterator = leased_stream()
                response.__class__ = _leased_class(type(response))
                leased_response: Any = response
                leased_response.pii_guard_release = release
                weakref.finalize(response, release)
            else:
                release()
            return response, stats
        except BaseException:
            release()
            raise
        finally:
            _REQUEST_SESSIONS.reset(token)

    _with_session_lease = with_session_lease

    def release_session(self, session: VaultSession, created: bool, *, masked: bool) -> None:
        """End the hold :meth:`session` took, once masking finished (``masked``) or failed."""
        session_id = session.session_id
        with self._holds_lock:
            hold = self._session_holds[session_id]
            hold.in_flight -= 1
            if masked:
                hold.kept = True
            elif created:
                hold.refused_creator = True
            if hold.in_flight > 0:
                return
            del self._session_holds[session_id]
            if not hold.refused_creator or hold.kept:
                return
            self.vault.drop(session_id)
            self.cache.drop_session(session_id)
            self.issued_ids.drop(session_id)
            self._session_incarnations.pop(session_id, None)

    _release_session = release_session

    def forwarded(
        self,
        body: dict[str, Any],
        session: VaultSession,
        stats: RequestStats,
        add_note: Callable[[dict[str, Any]], None],
    ) -> bytes:
        """The masked body as sent upstream, with the placeholder note if it needs one."""
        text = dumps_utf8(body)
        if self.config.placeholder_note and needs_note(text, session):
            add_note(body)
            stats.note = True
            text = dumps_utf8(body)
        return text.encode("utf-8")

    _forwarded = forwarded

    def upstream_url(self) -> str:
        base = self.settings.upstream_base_url
        if not base:
            raise UpstreamNotConfiguredError(
                "PII_GUARD_UPSTREAM_BASE_URL is not set; the gateway has nowhere to forward to"
            )
        base = base.rstrip("/")
        return base if base.endswith("/chat/completions") else base + "/chat/completions"

    _upstream_url = upstream_url

    def upstream_headers(self, headers: Mapping[str, str]) -> dict[str, str]:
        out = {
            **self.upstream_extra_headers,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.settings.hosted:
            out["Accept-Encoding"] = "identity"
        key = self.settings.upstream_api_key
        if key is not None:
            out["Authorization"] = f"Bearer {key.get_secret_value()}"
        elif headers.get("authorization"):
            out["Authorization"] = headers["authorization"]
        return out

    _upstream_headers = upstream_headers

    async def send_upstream(
        self,
        url: str,
        payload: bytes,
        headers: dict[str, str],
        *,
        timer: RequestTimer,
        stats: RequestStats,
        forwarding_started: float | None = None,
    ) -> tuple[httpx.Response, float]:
        client = self.upstream_client()
        request = client.build_request(
            "POST",
            url,
            content=payload,
            headers=headers,
            timeout=self.upstream_timeout(),
        )
        started = time.perf_counter()
        if forwarding_started is not None:
            timer.add("forward", started - forwarding_started)
        timer.upstream_sent = started
        try:
            response = await client.send(request, stream=True)
            await self.bound_upstream_response(response)
        except httpx.HTTPError as exc:
            timer.add("upstream", time.perf_counter() - started)
            stats.log("upstream_unreachable")
            raise UpstreamError(f"upstream request failed ({type(exc).__name__})") from None
        except UpstreamError:
            timer.add("upstream", time.perf_counter() - started)
            stats.log("upstream_unreachable")
            raise
        timer.add("upstream_ttfb", time.perf_counter() - started)
        timer.add("upstream", time.perf_counter() - started)
        return response, started

    # --- detection and masking -----------------------------------------------------------

    def _partition_cached_slots(
        self,
        slots: list[TextSlot],
        detector: ModeDetector,
        session: VaultSession,
        language: str,
        stats: RequestStats,
    ) -> tuple[list[list[Span] | None], dict[bytes, tuple[str, list[int], Any]]]:
        results: list[list[Span] | None] = [None] * len(slots)
        pending: dict[bytes, tuple[str, list[int], Any]] = {}
        for index, slot in enumerate(slots):
            if not any(ch.isalnum() for ch in slot.text):
                results[index] = []
                continue
            key = self.cache.key(
                session.session_id,
                language,
                detector.config_id,
                slot.text,
                session.incarnation,
            )
            cached = self.cache.get(key, slot.text)
            if cached is not None:
                stats.cache_hits += 1
                results[index] = cached
                continue
            if key[1] in pending:
                pending[key[1]][1].append(index)
                stats.cache_hits += 1
                continue
            stats.cache_misses += 1
            pending[key[1]] = (slot.text, [index], key)
        return results, pending

    async def _run_pending_detections(
        self,
        pending: dict[bytes, tuple[str, list[int], Any]],
        results: list[list[Span] | None],
        detector: ModeDetector,
        language: str,
        stats: RequestStats,
    ) -> None:
        workers = self._detect_workers.get(detector.mode)
        if workers is None:
            workers = BoundedWorkers(
                self.config.concurrency, f"pii-guard-detect-{detector.mode.value}"
            )
            self._detect_workers[detector.mode] = workers

        async def run(text: str) -> tuple[list[Span], dict[str, float]]:
            return await workers.run(detector.resolve, text, language)

        async def run_all(texts: list[str]) -> list[tuple[list[Span], dict[str, float]]]:
            found, timings = await workers.run(detector.resolve_many, texts, language)
            return [(spans, timings if i == 0 else {}) for i, spans in enumerate(found)]

        started = time.perf_counter()
        jobs = list(pending.values())
        texts = [text for text, _, _ in jobs]
        work = run_all(texts) if detector.batches else asyncio.gather(*map(run, texts))
        try:
            outputs = await asyncio.wait_for(work, timeout=self.config.detection_timeout)
        except TimeoutError:
            raise DetectionError(
                f"detection timed out after {self.config.detection_timeout:g}s "
                f"({detector.mode.value} mode)"
            ) from None
        except PiiGuardError:
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

    def _apply_policies_and_known(
        self,
        slots: list[TextSlot],
        results: list[list[Span] | None],
        detector: ModeDetector,
        session: VaultSession,
        language: str,
        stats: RequestStats,
        kept: list[list[Span]] | None,
    ) -> list[list[Span]]:
        decisions = [detector.policies.apply(r or []) for r in results]
        out = [decision.masked for decision in decisions]
        if kept is not None:
            kept[:] = [decision.kept for decision in decisions]
        known = session.known_values
        if known:
            started = time.perf_counter()
            out = [
                self._with_known(slot.text, spans, known, detector, language)
                for slot, spans in zip(slots, out, strict=True)
            ]
            elapsed = (time.perf_counter() - started) * 1000
            stats.detector_ms[KNOWN_DETECTOR] = stats.detector_ms.get(KNOWN_DETECTOR, 0) + elapsed
        if kept is not None:
            kept[:] = [
                [k for k in found if not any(m.start < k.end and k.start < m.end for m in spans)]
                for found, spans in zip(kept, out, strict=True)
            ]
        for spans in out:
            stats.spans.update(s.entity_type.value for s in spans)
            stats.forced.update(s.entity_type.value for s in spans if s.forced_by)
        return out

    async def detect_all(
        self,
        slots: list[TextSlot],
        detector: ModeDetector,
        session: VaultSession,
        language: str,
        stats: RequestStats,
        kept: list[list[Span]] | None = None,
    ) -> list[list[Span]]:
        """The spans to mask, per slot."""
        detector.require_available()
        results, pending = self._partition_cached_slots(slots, detector, session, language, stats)
        if pending:
            await self._run_pending_detections(pending, results, detector, language, stats)
        return self._apply_policies_and_known(
            slots, results, detector, session, language, stats, kept
        )

    _detect_all = detect_all

    @staticmethod
    def _with_known(
        text: str,
        spans: list[Span],
        known: KnownValues,
        detector: ModeDetector,
        language: str,
    ) -> list[Span]:
        merged = merge_known(text, spans, known, language, keep_types=detector.policies.keep_types)
        detector.policies.apply(s for s in merged if s.detector == KNOWN_DETECTOR)
        return merged

    def mask(
        self,
        slots: list[TextSlot],
        spans: list[list[Span]],
        session: VaultSession,
        language: str,
    ) -> list[str]:
        for slot, found in zip(slots, spans, strict=True):
            if slot.kind == "identifier" and found:
                slot.write("")
        texts = [slot.text for slot in slots]
        spans = widen_request(texts, spans, session.confirmed_values(WIDENED_TYPES), language)
        results = [
            session.mask_with_report(text, found, language=language)
            for text, found in zip(texts, spans, strict=True)
        ]
        return [
            session.mask(r.text, [], language=language, remask=True, since=r.generation)
            for r in results
        ]

    _mask = mask

    @staticmethod
    def _write(
        slots: list[TextSlot],
        masked: list[str],
        session: VaultSession,
        language: str,
        remask: bool,
        since: int | None = None,
        names: frozenset[str] = frozenset(),
        issued: frozenset[str] = frozenset(),
    ) -> None:
        write_masked_slots(slots, masked, session, language, remask, since, names, issued)

    def write(
        self,
        slots: list[TextSlot],
        masked: list[str],
        session: VaultSession,
        language: str,
        remask: bool,
        since: int | None = None,
        names: frozenset[str] = frozenset(),
        issued: frozenset[str] = frozenset(),
    ) -> None:
        self._write(slots, masked, session, language, remask, since, names, issued)

    @staticmethod
    def recheck(
        body: Mapping[str, Any],
        collect: Callable[[object], CollectedTexts],
        session: VaultSession,
        language: str,
        stats: RequestStats,
        names: frozenset[str],
        issued: frozenset[str],
    ) -> None:
        """The outbound re-check (:mod:`pii_guard.gateway.outbound`, LAB-1500)."""
        stats.outbound = check_outbound(
            body, collect, session, language, tool_names=names, issued=issued
        )
        if stats.outbound.hits:
            raise OutboundCheckFailedError(stats.outbound.hits)

    _recheck = recheck

    async def mask_images(
        self,
        images: list[ImageSlot],
        detector: ModeDetector,
        language: str,
        stats: RequestStats,
        session: VaultSession,
    ) -> None:
        """Mask every inline image (fail closed) and write masked PNG data URLs back."""
        masker = self.image_masker(detector)
        stats.image_ocr = masker.ocr is not None
        require_ocr(masker.ocr, required=self.settings.image_require_ocr)
        render = self.settings.image_render
        if self._image_workers is None:
            self._image_workers = BoundedWorkers(self.settings.image_concurrency, "pii-guard-image")
        started = time.perf_counter()
        try:
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
            url = "data:image/png;base64," + base64.b64encode(outcome.image).decode("ascii")
            slot.write(url)
            stats.image_payload_bytes += len(url)
            if outcome.summary is not None:
                annotation = session.mask(
                    image_annotation(number, outcome), [], language=language, remask=True
                )
                slot.annotate(annotation)

    _mask_images = mask_images

    # --- the endpoint --------------------------------------------------------------------

    async def chat_completions(
        self,
        body: object,
        headers: Mapping[str, str],
        *,
        max_text_chars: int | None = None,
        received_at: float | None = None,
        path_session: str | None = None,
        request_id: str | None = None,
    ) -> tuple[Response, RequestStats]:
        """Mask, forward, restore a ``/v1/chat/completions`` request."""
        return await chat_completions(
            self,
            body,
            headers,
            max_text_chars=max_text_chars,
            received_at=received_at,
            path_session=path_session,
            request_id=request_id,
        )

    async def run_chat_completions(
        self,
        body: object,
        headers: Mapping[str, str],
        *,
        max_text_chars: int | None,
        timer: RequestTimer,
        trace: CallTrace,
        path_session: str | None = None,
    ) -> tuple[Response, RequestStats]:
        return await run_chat_completions(
            self,
            body,
            headers,
            max_text_chars=max_text_chars,
            timer=timer,
            trace=trace,
            path_session=path_session,
            check_payload=check_upstream_payload,
        )

    _chat_completions = run_chat_completions
