"""The gateway: mask a Chat Completions request, forward it, restore the answer.

Order of operations (fail closed at every step, ADR 0006):

1. upstream configured? mode and session headers valid? body well-formed, nothing it can't
   mask (remote image URLs, audio, files)?
2. detect every text (cache first; misses run concurrently, under one per-request timeout),
   then add the session's pre-loaded known values (:mod:`pii_guard.detect.known`), which win
   their conflicts and are masked even for a ``keep`` type (a ``block`` type still refuses);
3. mask with the conversation's vault session: spans first, then a sweep for every value the
   session already knows (so a value found in one message is masked in all of them); inline
   images are masked with the visual pipeline (SAM 3.1 + OCR text through this mode's
   detectors + policies) and replaced by a masked PNG data URL;
4. forward the masked body; restore the answer (streamed: chunk by chunk);
5. seed the detection cache with the restored answer, which comes back as history next turn.

Nothing in this module logs or raises with request text, values, masked bodies or keys.
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
from pii_guard.api.routes.image_masking import ImageMasker, default_ocr_engine
from pii_guard.config import Settings
from pii_guard.detect.known import KNOWN_DETECTOR, merge_known
from pii_guard.gateway.cache import DetectionCache
from pii_guard.gateway.config import GatewayConfig, Mode
from pii_guard.gateway.detection import ModeDetector, build_mode_detectors, detector_timings
from pii_guard.gateway.request import (
    ImageSlot,
    InvalidChatRequestError,
    TextSlot,
    collect_texts,
)
from pii_guard.gateway.restore import restore_completion, restore_text
from pii_guard.gateway.stream import SseRestorer, error_event, iter_sse_data, sse_event
from pii_guard.policy import Policy
from pii_guard.types import DetectionError, PiiGuardError, Span
from pii_guard.vault import Vault, VaultSession
from pii_guard.vault.known import KnownValues
from pii_guard.visual.ocr import OcrEngine
from pii_guard.visual.sam import SamClient

__all__ = [
    "LANGUAGE_HEADER",
    "MODE_HEADER",
    "SESSION_HEADER",
    "Gateway",
    "UpstreamError",
    "UpstreamNotConfiguredError",
]

logger = logging.getLogger("pii_guard.gateway")

SESSION_HEADER = "X-PII-Guard-Session"
MODE_HEADER = "X-PII-Guard-Mode"
LANGUAGE_HEADER = "X-PII-Guard-Language"

_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
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

    def headers(self, session_id: str) -> dict[str, str]:
        out = {
            SESSION_HEADER: session_id,
            MODE_HEADER: self.mode.value,
            "X-PII-Guard-Cache-Hits": str(self.cache_hits),
            "X-PII-Guard-Cache-Misses": str(self.cache_misses),
            "X-PII-Guard-Masked": str(sum(self.masked.values())),
        }
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
        sam: SamClient | None = None,
        ocr: OcrEngine | None = _UNSET,
    ) -> None:
        """``sam`` / ``ocr`` mask inline images: default a :class:`SamClient` from the
        settings and Tesseract when installed; ``ocr=None`` turns OCR off (SAM only)."""
        self.settings = settings
        self.vault = vault
        self.config = config or GatewayConfig()
        self._detectors = dict(detectors) if detectors is not None else None
        self.cache = cache or DetectionCache(self.config.cache_size)
        self._transport = transport
        self._semaphore: asyncio.Semaphore | None = None
        self._sam = sam
        self._ocr = ocr

    def __repr__(self) -> str:
        return f"Gateway(mode={self.config.mode.value}, cache={self.cache!r})"

    @property
    def detectors(self) -> dict[Mode, ModeDetector]:
        if self._detectors is None:
            self._detectors = build_mode_detectors(self.settings, self.config)
        return self._detectors

    def image_masker(self, detector: ModeDetector) -> ImageMasker:
        """The visual pipeline for one mode: OCR text goes through that mode's detectors."""
        if self._sam is None:
            self._sam = SamClient(settings=self.settings)
        if self._ocr is _UNSET:
            self._ocr = default_ocr_engine()
        return ImageMasker(
            sam=self._sam,
            policies=detector.policies,
            ocr=self._ocr,
            text_detector=detector.detector if self._ocr is not None else None,
            text_detector_names=[detector.mode.value],
        )

    # --- request parsing -----------------------------------------------------------------

    def _mode(self, headers: Mapping[str, str]) -> Mode:
        raw = headers.get(MODE_HEADER)
        if raw is None or not raw.strip():
            return self.config.mode
        try:
            return Mode(raw.strip().lower())
        except ValueError:
            raise InvalidChatRequestError(
                f"{MODE_HEADER} must be one of: {', '.join(m.value for m in Mode)}"
            ) from None

    def _language(self, headers: Mapping[str, str]) -> str:
        raw = headers.get(LANGUAGE_HEADER)
        if raw is None or not raw.strip():
            return self.settings.default_language
        if not _LANGUAGE_RE.match(raw.strip()):
            raise InvalidChatRequestError(f"{LANGUAGE_HEADER} must be a language tag like 'hu'")
        return raw.strip()

    def _session(self, headers: Mapping[str, str]) -> tuple[VaultSession, bool]:
        raw = headers.get(SESSION_HEADER)
        if raw is None or not raw.strip():
            return self.vault.session(), True
        if not _SESSION_RE.match(raw.strip()):
            raise InvalidChatRequestError(f"{SESSION_HEADER} is malformed")
        # Unknown or expired -> SessionNotFoundError (404). Start a new conversation without
        # the header; the mapping is gone, so a silent new session would be a different one.
        return self.vault.session(raw.strip()), False

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
            if self._semaphore is None:
                self._semaphore = asyncio.Semaphore(self.config.concurrency)
            semaphore = self._semaphore

            async def run(text: str) -> tuple[list[Span], dict[str, float]]:
                async with semaphore:
                    return await asyncio.to_thread(detector.detect, text, language)

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
            out = [
                self._with_known(slot.text, spans, known, detector, language)
                for slot, spans in zip(slots, out, strict=True)
            ]
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
        stats: RequestStats,
    ) -> None:
        before = Counter({p: c for p, _, c in session.entities()})
        masked = [
            session.mask(slot.text, found, language=language)
            for slot, found in zip(slots, spans, strict=True)
        ]
        # Second pass: values confirmed in a later text are masked in earlier ones too.
        masked = [session.mask(text, [], language=language, remask=True) for text in masked]
        for slot, text in zip(slots, masked, strict=True):
            slot.write(text)
        for placeholder, entity_type, count in session.entities():
            delta = count - before.get(placeholder, 0)
            if delta > 0:
                stats.masked[entity_type.value] += delta

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
    ) -> None:
        """Mask every inline image (fail closed) and write masked PNG data URLs back."""
        masker = self.image_masker(detector)
        stats.image_ocr = masker.ocr is not None
        started = time.perf_counter()

        def run_all() -> list[bytes]:
            out: list[bytes] = []
            for slot in images:
                outcome = masker.mask(slot.data, language)
                stats.image_masked.update(
                    {t.value: n for t, n in outcome.counts(Policy.MASK).items()}
                )
                stats.image_kept.update(
                    {t.value: n for t, n in outcome.counts(Policy.KEEP).items()}
                )
                out.append(outcome.image)
            return out

        try:
            masked = await asyncio.wait_for(
                asyncio.to_thread(run_all), timeout=self.config.image_timeout
            )
        except TimeoutError:
            raise DetectionError(
                f"image masking timed out after {self.config.image_timeout:g}s"
            ) from None
        except PiiGuardError:
            raise
        except Exception as exc:
            raise DetectionError(f"image masking failed ({type(exc).__name__})") from exc
        finally:
            stats.image_ms = (time.perf_counter() - started) * 1000
        for slot, png in zip(images, masked, strict=True):
            slot.write("data:image/png;base64," + base64.b64encode(png).decode("ascii"))

    # --- the endpoint --------------------------------------------------------------------

    async def chat_completions(
        self, body: object, headers: Mapping[str, str], *, max_text_chars: int | None = None
    ) -> tuple[Response, RequestStats]:
        url = self._upstream_url()
        mode = self._mode(headers)
        language = self._language(headers)
        stats = RequestStats(mode=mode)
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
        session, created = self._session(headers)
        stream = bool(body.get("stream"))
        stats.stream = stream
        stats.texts = len(collected.slots)
        stats.images = len(collected.images)
        try:
            spans = await self._detect_all(collected.slots, detector, session, language, stats)
            if collected.images:
                await self._mask_images(collected.images, detector, language, stats)
            self._mask(collected.slots, spans, session, language, stats)
            collected.finalize()
        except BaseException:
            stats.log("blocked")
            if created:
                self.vault.drop(session.session_id)
                self.cache.drop_session(session.session_id)
            raise

        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.upstream_timeout, connect=10.0),
            transport=self._transport,
        )
        request = client.build_request(
            "POST", url, content=payload, headers=self._upstream_headers(headers)
        )
        started = time.perf_counter()
        try:
            response = await client.send(request, stream=True)
        except httpx.HTTPError as exc:
            await client.aclose()
            stats.log("upstream_unreachable")
            raise UpstreamError(f"upstream request failed ({type(exc).__name__})") from None

        stats.upstream_status = response.status_code
        out_headers = stats.headers(session.session_id)
        if response.status_code >= 400:
            try:
                raw = await _read_limited(response)
            finally:
                await response.aclose()
                await client.aclose()
            stats.upstream_ms = (time.perf_counter() - started) * 1000
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
                await client.aclose()
            stats.upstream_ms = (time.perf_counter() - started) * 1000
            try:
                answer = json.loads(raw)
            except ValueError:
                stats.log("upstream_invalid")
                raise UpstreamError("upstream returned a body that is not JSON") from None
            if not isinstance(answer, dict):
                raise UpstreamError("upstream returned a body that is not a JSON object")
            report = restore_completion(session, answer)
            stats.unresolved = len(report.unresolved)
            self._seed_cache(session, language, detector, report.restored_spans, stats)
            out_headers["X-PII-Guard-Unresolved"] = str(stats.unresolved)
            stats.log("ok")
            return JSONResponse(answer, headers=out_headers), stats

        restorer = SseRestorer(session)

        async def events() -> AsyncIterator[bytes]:
            outcome = "ok"
            try:
                async for data in iter_sse_data(response.aiter_lines()):
                    for out in restorer.process(data):
                        yield sse_event(out)
                for out in restorer.finish():
                    yield sse_event(out)
            except Exception as exc:
                # Fail closed: stop the stream with an error event, no exception text.
                outcome = f"stream_error:{type(exc).__name__}"
                yield sse_event(error_event("stream_failed", "the response stream failed"))
            finally:
                await response.aclose()
                await client.aclose()
                stats.upstream_ms = (time.perf_counter() - started) * 1000
                stats.unresolved = len(restorer.unresolved)
                if outcome == "ok":
                    restored = {}
                    for index, masked in restorer.masked_content().items():
                        text, spans, _ = restore_text(session, masked)
                        restored[index] = (text, spans)
                    self._seed_cache(session, language, detector, restored, stats)
                stats.log(outcome)

        return (
            StreamingResponse(events(), media_type="text/event-stream", headers=out_headers),
            stats,
        )


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
