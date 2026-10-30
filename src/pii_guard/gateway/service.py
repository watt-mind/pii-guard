"""The gateway: mask a Chat Completions request, forward it, restore the answer.

Order of operations (fail closed at every step, ADR 0006):

1. upstream configured? mode and session headers valid? body well-formed, nothing it can't
   mask (remote image URLs, audio, files)?
2. detect every text (cache first; misses run concurrently, under one per-request timeout),
   then add the session's pre-loaded known values (:mod:`pii_guard.detect.known`), which win
   their conflicts and are masked even for a ``keep`` type (a ``block`` type still refuses),
   and drop the detections in identifier slots that are exactly a tool name the request
   declares (:func:`~pii_guard.gateway.tool_names.without_tool_names`, LAB-1317/LAB-1563);
   an identifier whose
   only rewrites are those names is written back as sent, whatever the session holds
   (:func:`~pii_guard.gateway.tool_names.identifier_keeps_tool_names`, LAB-1324);
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
import threading
import time
import weakref
from collections import Counter, OrderedDict
from collections.abc import AsyncIterator, Callable, Coroutine, Mapping
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from pii_guard.config import Settings
from pii_guard.detect.known import KNOWN_DETECTOR, WIDENED_TYPES, merge_known, widen_request
from pii_guard.gateway.cache import DetectionCache
from pii_guard.gateway.config import DEPRECATED_MODE_ALIASES, GatewayConfig, Mode, parse_mode
from pii_guard.gateway.detection import ModeDetector, build_mode_detectors, detector_timings
from pii_guard.gateway.meter import meter_response, record_payload, record_usage, scan_usage
from pii_guard.gateway.opaque_ids import IssuedIds, upstream_ids, without_opaque_ids
from pii_guard.gateway.outbound import (
    OUTBOUND_CHECK_HEADER,
    OutboundCheck,
    OutboundCheckFailedError,
    check_outbound,
)
from pii_guard.gateway.placeholder_note import NOTE_HEADER, add_chat_note, needs_note
from pii_guard.gateway.request import (
    CollectedTexts,
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
    client_identity,
    resolve_session,
)
from pii_guard.gateway.stream import DONE, SseRestorer, error_event, iter_sse_data, sse_event
from pii_guard.gateway.tool_names import (
    identifier_keeps_tool_names,
    tool_names,
    without_tool_names,
)
from pii_guard.gateway.trace import CallTrace
from pii_guard.observability import Observability, RequestTimer
from pii_guard.policy import Policy
from pii_guard.types import DetectionError, PayloadTooLargeError, PiiGuardError, Span
from pii_guard.vault import (
    PLACEHOLDER_RE,
    UnmaskOutputTooLargeError,
    Vault,
    VaultSession,
    normalize_value,
)
from pii_guard.vault.known import KnownValues
from pii_guard.visual.masking import (
    ImageMasker,
    ImageMaskOutcome,
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

#: The largest masked upstream payload (bytes) the current request was admitted for. Hosted
#: admission charges this bound in advance (hosted/quotas.py); None means no bound (local).
#: The vault leases (session, client identity) the current request holds, set by
#: :meth:`Gateway._with_session_lease` (module-level, LAB-1584: a ContextVar per gateway
#: instance is never collected).
_REQUEST_SESSIONS: ContextVar[list[tuple[VaultSession, str]] | None] = ContextVar(
    "pii_guard_request_sessions", default=None
)

UPSTREAM_PAYLOAD_LIMIT: ContextVar[int | None] = ContextVar(
    "pii_guard_upstream_payload_limit", default=None
)


def check_upstream_payload(payload: bytes, image_bytes: int = 0) -> None:
    """Refuse a masked payload larger than the bound its admission was charged for.

    ``image_bytes`` (the masked images' data URLs the gateway wrote) is left out: hosted
    admission charges each image a fixed provider price instead of its bytes (LAB-1439)."""
    limit = UPSTREAM_PAYLOAD_LIMIT.get()
    if limit is not None and len(payload) - max(0, image_bytes) > limit:
        raise PayloadTooLargeError("the masked request is larger than its admitted size bound")
    # Passed: this payload goes upstream, and settlement estimates its input from it.
    record_payload(len(payload) - max(0, image_bytes))


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
    #: Spans whose masked type a detector forced over a keep-type rule (LAB-1248, LAB-1228):
    #: counts by entity type only, never values.
    forced: Counter[str] = field(default_factory=Counter)
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
    #: Characters of the masked image data URLs written into the body (not rendered).
    image_payload_bytes: int = 0
    session_source: SessionSource | None = None
    #: The placeholder note went upstream with the request (LAB-1471).
    note: bool = False
    #: The outbound re-check of the masked request (LAB-1500); ``None``: not reached.
    outbound: OutboundCheck | None = None

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
        if self.note:
            out[NOTE_HEADER] = "added"
        if self.outbound is not None:
            out[OUTBOUND_CHECK_HEADER] = self.outbound.result
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
            "forced": _counts(self.forced),
            "detect_ms": f"{self.detect_ms:.0f}",
        }
        if self.outbound is not None:
            fields["outbound_check"] = self.outbound.result
        if self.images:
            fields["images"] = self.images
            fields["image_masked"] = _counts(self.image_masked)
            fields["image_ms"] = f"{self.image_ms:.0f}"
        return fields

    def log(self, outcome: str) -> None:
        logger.info(
            "chat.completions %s mode=%s stream=%s texts=%d cache_hits=%d cache_misses=%d "
            "seeded=%d spans=%s masked=%s detect_ms=%.0f detectors=%s upstream=%s "
            "upstream_ms=%.0f unresolved=%d images=%d image_masked=%s image_ms=%.0f "
            "outbound=%s outbound_hits=%s outbound_ms=%.1f",
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
            self.outbound.result if self.outbound is not None else "-",
            _counts(self.outbound.hits) if self.outbound is not None else "-",
            self.outbound.ms if self.outbound is not None else 0.0,
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
                await super(leased, self).__call__(scope, receive, send)  # type: ignore[arg-type]
            finally:
                self._pii_guard_release()

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
        self.cache = cache if cache is not None else DetectionCache(self.config.cache_size)
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
        # Session id -> the requests masking into it now (LAB-1316): a refused request drops
        # the session it created only once no other request holds it and none succeeded.
        self._session_holds: dict[str, _SessionHold] = {}
        self._holds_lock = threading.Lock()
        # Fixed headers added to every upstream call of this gateway (the hosted sponsored
        # route's attribution, LAB-1461); they never override content type or credentials.
        self.upstream_extra_headers: dict[str, str] = {}
        # Ids the upstream issued per session (LAB-1469): sent back as identifiers, they are
        # forwarded without detection (the NER reads some random call ids as phone numbers).
        self.issued_ids = IssuedIds()
        # Session id -> the VaultSession object last seen for it (LAB-1565): a different
        # object under the same id is a new incarnation (dropped/expired/rotated and
        # re-created), so its issued-id exemptions (and, eagerly, its old detection-cache
        # entries) are dropped. Per gateway; the cache itself is keyed by incarnation
        # (LAB-1580), so a cache shared by per-request gateways (hosted/project) starts
        # clean too.
        self._session_incarnations: OrderedDict[str, weakref.ref[VaultSession]] = OrderedDict()

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
        """Bound untrusted hosted upstream bytes before buffering or SSE parsing.

        The transport applies the same policy; this boundary also covers injected
        transports and keeps size enforcement adjacent to every gateway consumer.
        """
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
        meter_response(response)

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

    def _mode(self, headers: Mapping[str, str]) -> Mode:
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
        (:mod:`pii_guard.gateway.sessions`). Recorded on ``stats`` and ``trace``.

        The request holds the session until :meth:`_release_session`, which every caller
        must call once masking finished or failed."""
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
                # New incarnation of this id: start clean (LAB-1565).
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

    async def _with_session_lease(
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
                # The generator's ``finally`` never runs when Starlette never starts it
                # (client gone before ``http.response.start``), so release around the ASGI
                # call too, and on garbage collection for a response nobody calls. Release
                # is idempotent: it pops what is still held.
                response.__class__ = _leased_class(type(response))
                response._pii_guard_release = release  # type: ignore[attr-defined]
                weakref.finalize(response, release)
            else:
                release()
            return response, stats
        except BaseException:
            release()
            raise
        finally:
            _REQUEST_SESSIONS.reset(token)

    def _release_session(self, session: VaultSession, created: bool, *, masked: bool) -> None:
        """End the hold :meth:`_session` took, once masking finished (``masked``) or failed.

        A refused request used to drop the session it created at once, under any concurrent
        request that had already resolved the same client-named id (404 for that one,
        LAB-1316). Now the drop waits for the last holder: the session is dropped only if its
        creator was refused, nobody holds it any more and no request on it finished masking.
        Fail closed: with nobody succeeding, a refused request's values are forgotten; once a
        request succeeded, its placeholders are in use and the session stays.
        """
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

    def _forwarded(
        self,
        body: dict[str, Any],
        session: VaultSession,
        stats: RequestStats,
        add_note: Callable[[dict[str, Any]], None],
    ) -> bytes:
        """The masked body as sent upstream, with the placeholder note if it needs one.

        The note goes in after masking, so it is never scanned; it is a constant, so it can't
        carry a value (LAB-1471).
        """
        text = json.dumps(body, ensure_ascii=False)
        if self.config.placeholder_note and needs_note(text, session):
            add_note(body)
            stats.note = True
            text = json.dumps(body, ensure_ascii=False)
        return text.encode("utf-8")

    def _upstream_url(self) -> str:
        base = self.settings.upstream_base_url
        if not base:
            raise UpstreamNotConfiguredError(
                "PII_GUARD_UPSTREAM_BASE_URL is not set; the gateway has nowhere to forward to"
            )
        base = base.rstrip("/")
        return base if base.endswith("/chat/completions") else base + "/chat/completions"

    def _upstream_headers(self, headers: Mapping[str, str]) -> dict[str, str]:
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
        kept: list[list[Span]] | None = None,
    ) -> list[list[Span]]:
        """The spans to mask, per slot. ``kept``, when given, gets the spans kept by policy,
        per slot (the echo reports them, LAB-1180). The cache holds both."""
        # Audit mode without an LLM key: 503 detection_unavailable before anything is detected,
        # cached, segmented or sent (LAB-1290). Runs first in chat and responses alike.
        detector.require_available()
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
                return await workers.run(detector.resolve, text, language)

            async def run_all(texts: list[str]) -> list[tuple[list[Span], dict[str, float]]]:
                # Fast mode: one job for every uncached text, so the NER model batches them
                # (LAB-1279). Timings are per job; the first output carries them.
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
        decisions = [detector.policies.apply(r or []) for r in results]
        out = [decision.masked for decision in decisions]
        if kept is not None:
            kept[:] = [decision.kept for decision in decisions]
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
        if kept is not None:
            # A kept span that a masked one overlaps (a pre-loaded known value) is masked.
            kept[:] = [
                [k for k in found if not any(m.start < k.end and k.start < m.end for m in spans)]
                for found, spans in zip(kept, out, strict=True)
            ]
        for spans in out:
            stats.spans.update(s.entity_type.value for s in spans)
            stats.forced.update(s.entity_type.value for s in spans if s.forced_by)
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
        for slot, found in zip(slots, spans, strict=True):
            if slot.kind == "identifier" and found:
                slot.write("")
        texts = [slot.text for slot in slots]
        spans = widen_request(texts, spans, session.confirmed_values(WIDENED_TYPES), language)
        results = [
            session.mask_with_report(text, found, language=language)
            for text, found in zip(texts, spans, strict=True)
        ]
        # Second pass: values confirmed in a later text are masked in earlier ones too. Only
        # entries created or changed after a text was masked can find anything new in it; a
        # request that adds no value skips the pass (LAB-1278).
        return [
            session.mask(r.text, [], language=language, remask=True, since=r.generation)
            for r in results
        ]

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
        """Write ``masked`` back. With ``remask``, values first seen in an image are masked in
        the texts too; ``since`` (the session generation before the images) scans only the
        entries the images added (LAB-1278).

        ``names``: the tool names the request declares. An identifier whose only rewrites are
        those names is written as sent, whatever the session holds (LAB-1324); a declared name
        that is also a pre-loaded known value gets no exemption and still fails closed.

        ``issued``: the ids the upstream issued in this session (LAB-1469). An identifier that
        is one of them is written as sent."""
        if remask:
            masked = [
                session.mask(text, [], language=language, remask=True, since=since)
                for text in masked
            ]
        exempt = names
        if names and session.known_values:
            known = {normalize_value(v.value) for v in session.known_values.values()}
            exempt = names - known

        def original(placeholder: str) -> str | None:
            value = session.unmask(placeholder)
            return None if value == placeholder else value

        for slot, text in zip(slots, masked, strict=True):
            if (
                slot.kind == "identifier"
                and text != slot.text
                and (
                    slot.text in issued
                    or identifier_keeps_tool_names(slot.text, text, exempt, original)
                )
            ):
                text = slot.text
            slot.write(text)
            if text != slot.text:
                # Record each placeholder's JSON type for restore (LAB-1361): a number only
                # when a number leaf masked to exactly it; inside a longer text, or as a whole
                # string, it is a string (any ambiguity keeps the string form).
                whole = slot.number is not None and PLACEHOLDER_RE.fullmatch(text)
                for match in PLACEHOLDER_RE.finditer(text):
                    number = (slot.text, slot.number) if whole and slot.number else None
                    session.note_json_leaf(match.group(0), number)

    @staticmethod
    def _recheck(
        body: Mapping[str, Any],
        collect: Callable[[object], CollectedTexts],
        session: VaultSession,
        language: str,
        stats: RequestStats,
        names: frozenset[str],
        issued: frozenset[str],
    ) -> None:
        """The outbound re-check (:mod:`pii_guard.gateway.outbound`, LAB-1500): read the masked
        ``body`` again and refuse it if a value the session knows is still in it."""
        stats.outbound = check_outbound(
            body, collect, session, language, tool_names=names, issued=issued
        )
        if stats.outbound.hits:
            raise OutboundCheckFailedError(stats.outbound.hits)

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
                key = self.cache.key(
                    session.session_id, language, detector.config_id, text, session.incarnation
                )
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
            url = "data:image/png;base64," + base64.b64encode(outcome.image).decode("ascii")
            slot.write(url)
            stats.image_payload_bytes += len(url)
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
        request_id: str | None = None,
    ) -> tuple[Response, RequestStats]:
        """Mask, forward, restore. ``received_at`` (``perf_counter``) starts the timer;
        ``path_session`` is the session id of a ``/s/<session>/v1/...`` URL. ``request_id``
        is the id the route assigned up front (LAB-1179); generated here when absent."""
        timer = RequestTimer(received_at)
        trace = CallTrace(self.observability, timer, body, request_id=request_id)
        try:
            response, stats = await self._with_session_lease(
                self._chat_completions(
                    body,
                    headers,
                    max_text_chars=max_text_chars,
                    timer=timer,
                    trace=trace,
                    path_session=path_session,
                )
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
                kept: list[list[Span]] = []
                spans = await self._detect_all(
                    collected.slots, detector, session, language, stats, kept
                )
                names = tool_names(body)
                spans = without_tool_names(
                    [slot.text for slot in collected.slots],
                    spans,
                    names,
                    [slot.kind for slot in collected.slots],
                )
                issued = self.issued_ids.of(session.session_id)
                spans = without_opaque_ids(collected.slots, spans, issued)
            # Every older entry has scanned every text by the end of _mask: an image's remask
            # needs only the entries this request added (LAB-1278).
            generation = session.generation
            before = _counts_of(session)
            with timer.span("mask"):
                masked = self._mask(collected.slots, spans, session, language)
            _count_masked(stats, before, session)
            if collected.images:
                with timer.span("image"):
                    await self._mask_images(collected.images, detector, language, stats, session)
            before = _counts_of(session)
            with timer.span("mask"):
                remask = bool(collected.images)
                self._write(
                    collected.slots, masked, session, language, remask, generation, names, issued
                )
                collected.finalize()
            _count_masked(stats, before, session)
            with timer.span("mask"):
                self._recheck(body, collect_texts, session, language, stats, names, issued)
            forwarding = time.perf_counter()
            payload = self._forwarded(body, session, stats, add_chat_note)
            check_upstream_payload(payload, stats.image_payload_bytes)
        except BaseException:
            stats.log("blocked")
            self._release_session(session, created, masked=False)
            raise
        self._release_session(session, created, masked=True)
        if trace.payloads:
            trace.masked_request = payload
        # The client's messages as masked: the note is a flag, not a message, so a UI that
        # picks the first system message still finds its own.
        masked_messages = _masked_messages(body)[int(stats.note) :] if echo else None
        kept_spans = (
            _kept_spans(collected.slots, kept, len(body["messages"]) - int(stats.note))
            if echo
            else None
        )
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
            await self.bound_upstream_response(response)
        except httpx.HTTPError as exc:
            timer.add("upstream", time.perf_counter() - started)
            stats.log("upstream_unreachable")
            raise UpstreamError(f"upstream request failed ({type(exc).__name__})") from None
        except UpstreamError:
            # A refused (compressed or oversized) hosted response counts like no response.
            timer.add("upstream", time.perf_counter() - started)
            stats.log("upstream_unreachable")
            raise
        timer.add("upstream_ttfb", time.perf_counter() - started)
        timer.add("upstream", time.perf_counter() - started)

        stats.upstream_status = response.status_code
        out_headers = stats.headers(session.session_id)
        if response.status_code >= 400:
            try:
                raw = await _read_limited(response)
            except httpx.HTTPError as exc:
                stats.log("upstream_unreachable")
                raise UpstreamError(f"upstream response failed ({type(exc).__name__})") from None
            finally:
                await response.aclose()
            stats.upstream_ms = (time.perf_counter() - started) * 1000
            timer.add("upstream", stats.upstream_ms / 1000 - timer.stages["upstream"])
            stats.log("upstream_error")
            return _upstream_error(response.status_code, raw, out_headers), stats

        is_sse = response.headers.get("content-type", "").startswith("text/event-stream")
        if stream and not is_sse:
            # The client requested SSE: never pass through or buffer a whole JSON answer.
            # Closing must not replace the protocol error with transport exception text.
            with suppress(httpx.HTTPError):
                await response.aclose()
            stats.upstream_ms = (time.perf_counter() - started) * 1000
            timer.add("upstream", stats.upstream_ms / 1000 - timer.stages["upstream"])
            stats.log("upstream_did_not_stream")
            raise UpstreamError(
                "upstream did not return an event stream; retry without stream",
                code="upstream_did_not_stream",
            ) from None

        if not stream:
            try:
                raw = await _read_bounded(response, self.config.upstream_max_response_bytes)
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
            self.issued_ids.add(session.session_id, upstream_ids(answer))
            report = restore_completion(session, answer)
            stats.unresolved = len(report.unresolved)
            self._seed_cache(session, language, detector, report.restored_spans, stats)
            out_headers["X-PII-Guard-Unresolved"] = str(stats.unresolved)
            if echo:
                answer["pii_guard"] = {
                    "masked_messages": masked_messages,
                    "kept_spans": kept_spans,
                    "placeholder_note": stats.note,
                    "masked_answer": masked_answer,
                }
            stats.log("ok")
            if trace.full:
                trace.answer = answer
            elif trace.recording and isinstance(answer.get("usage"), dict):
                trace.usage = answer["usage"]
            record_usage(answer.get("usage"))
            result = JSONResponse(answer, headers=out_headers)
            timer.add("response", time.perf_counter() - building)
            timer.finish()
            return result, stats

        restorer = SseRestorer(
            session,
            on_ids=lambda ids: self.issued_ids.add(session.session_id, ids),
            keep_restored_tools=trace.full,
        )
        trace.streaming = True

        async def timed_lines() -> AsyncIterator[str]:
            """The upstream's lines; time spent waiting on them counts as upstream time.

            The whole stream has a total deadline (LAB-1566), separate from the per-read
            httpx timeout: past it the stream ends with the generic stream error.
            """
            lines = response.aiter_lines().__aiter__()
            deadline = time.perf_counter() + self.config.upstream_stream_timeout
            while True:
                waiting = time.perf_counter()
                remaining = deadline - waiting
                if remaining <= 0:
                    raise TimeoutError("upstream stream deadline exceeded")
                try:
                    line = await asyncio.wait_for(lines.__anext__(), remaining)
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
            # A choice past the retention cap has no copy; mark it rather than omit it, so
            # a truncated echo is not mistaken for a short answer (LAB-1581).
            truncated = restorer.masked_truncated()
            choices = [
                {"index": i, "content": None, "truncated": True}
                if i in truncated
                else {"index": i, "content": content[i]}
                for i in sorted({*content, *truncated})
            ]
            return sse_event(
                json.dumps(
                    {"object": "pii_guard.masked_answer", "choices": choices},
                    ensure_ascii=False,
                )
            )

        async def produce() -> AsyncIterator[bytes]:
            """The restored events; every await in here is upstream time or pii-guard's own."""
            nonlocal echoed_answer
            if echo:
                yield sse_event(
                    json.dumps(
                        {
                            "object": "pii_guard.masked_request",
                            "messages": masked_messages,
                            "kept_spans": kept_spans,
                            "placeholder_note": stats.note,
                        },
                        ensure_ascii=False,
                    )
                )
            async for data in iter_sse_data(timed_lines()):
                unmasking = time.perf_counter()
                outs = restorer.process(data)
                timer.add("unmask", time.perf_counter() - unmasking)
                trace.scan_usage(data)
                scan_usage(data)
                for out in outs:
                    timer.mark_first_event()
                    if out == DONE and echo and not echoed_answer:
                        echoed_answer = True
                        yield answer_event()
                    yield sse_event(out)
                    if out == DONE:
                        return
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
                        if isinstance(exc, UnmaskOutputTooLargeError):  # LAB-1350
                            failed = error_event(exc.code, exc.message)
                        else:
                            failed = error_event("stream_failed", "the response stream failed")
                        yield sse_event(failed)
                        yield sse_event(DONE)
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
                    with suppress(PiiGuardError):
                        restored = {}
                        for index, masked in restorer.masked_content().items():
                            text, spans, _ = restore_text(session, masked)
                            restored[index] = (text, spans)
                        self._seed_cache(session, language, detector, restored, stats)
                        if trace.full:
                            trace.stream_restored = {i: t for i, (t, _) in restored.items()}
                            trace.stream_restored_tools = restorer.restored_tool_calls()
                stats.log(outcome)
                if trace.payloads:
                    trace.stream_masked = restorer.masked_content()
                    trace.stream_masked_tools = restorer.masked_tool_calls()
                    trace.stream_chunks = restorer.chunks
                if outcome == "ok":
                    trace.finish()
                elif outcome == "client_disconnected":
                    trace.finish(outcome=outcome, error={"code": outcome})
                else:
                    trace.finish(outcome="stream_error", error={"code": "stream_failed"})

        out_headers["Cache-Control"] = "no-cache"
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


def _kept_spans(
    slots: list[TextSlot], kept: list[list[Span]], messages: int
) -> list[list[dict[str, object]]]:
    """Per client message, the spans kept by policy as type and code-point offsets into the
    message's text, for :data:`ECHO_HEADER` (LAB-1180). Never the values. Only a message
    whose content is one string has offsets to report; any other message gets ``[]``."""
    out: list[list[dict[str, object]]] = [[] for _ in range(messages)]
    for slot, found in zip(slots, kept, strict=True):
        if slot.message is not None and slot.message < messages:
            out[slot.message] = [
                {"type": s.entity_type.value, "start": s.start, "end": s.end}
                for s in sorted(found, key=lambda s: (s.start, s.end))
            ]
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


async def _read_bounded(response: httpx.Response, limit: int) -> bytes:
    """A whole upstream success body, byte-bounded in every mode (LAB-1566).

    Raises :class:`UpstreamError` (sanitised, no body text) once the body passes ``limit``,
    without buffering more than the limit plus one chunk.
    """
    data = bytearray()
    async for chunk in response.aiter_bytes():
        data.extend(chunk)
        if len(data) > limit:
            raise UpstreamError("upstream response is too large")
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
