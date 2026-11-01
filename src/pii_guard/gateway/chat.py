"""Chat Completions handler and shared request/response helpers for the gateway.

Extracted from :mod:`pii_guard.gateway.service` so each gateway module stays focused and
under 1,000 lines while :class:`~pii_guard.gateway.service.Gateway` and
:mod:`pii_guard.gateway.service` preserve all existing methods and re-exports.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import httpx
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from pii_guard.gateway.config import Mode
from pii_guard.gateway.detection import ModeDetector
from pii_guard.gateway.meter import client_chunk, record_payload, record_usage, scan_usage
from pii_guard.gateway.opaque_ids import upstream_ids, without_opaque_ids
from pii_guard.gateway.opaque_reasoning import OpaqueStream, observe, validate
from pii_guard.gateway.outbound import OUTBOUND_CHECK_HEADER, OutboundCheck
from pii_guard.gateway.placeholder_note import NOTE_HEADER, add_chat_note
from pii_guard.gateway.request import CollectedTexts, TextSlot, collect_texts
from pii_guard.gateway.restore import restore_completion
from pii_guard.gateway.sessions import SESSION_HEADER, SESSION_SOURCE_HEADER, SessionSource
from pii_guard.gateway.stream import (
    DONE,
    SseRestorer,
    error_event,
    iter_sse_data,
    sse_event,
    stream_sse_events,
    timed_sse_lines,
)
from pii_guard.gateway.tool_names import (
    identifier_keeps_tool_names,
    tool_names,
    without_tool_names,
)
from pii_guard.gateway.trace import CallTrace
from pii_guard.observability import RequestTimer
from pii_guard.types import PayloadTooLargeError, PiiGuardError, Span
from pii_guard.vault import (
    PLACEHOLDER_RE,
    UnmaskOutputTooLargeError,
    VaultSession,
    normalize_value,
)
from pii_guard.visual.masking import ImageMaskOutcome

if TYPE_CHECKING:
    from contextvars import ContextVar

    from pii_guard.gateway.service import Gateway

__all__ = [
    "ECHO_HEADER",
    "LANGUAGE_HEADER",
    "MODE_HEADER",
    "REQUEST_ID_HEADER",
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
    "chat_completions",
    "check_upstream_payload_with_limit",
    "image_annotation",
    "run_chat_completions",
    "write_masked_slots",
]

logger = logging.getLogger("pii_guard.gateway")

REQUEST_ID_HEADER = "X-PII-Guard-Request-Id"
MODE_HEADER = "X-PII-Guard-Mode"
LANGUAGE_HEADER = "X-PII-Guard-Language"
# Opt-in: "masked" echoes back what the upstream saw (the masked messages) and said (its
# masked answer), for UIs that show the boundary. Masked text only, never the values.
ECHO_HEADER = "X-PII-Guard-Echo"

_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_MAX_ERROR_BODY = 65_536


def check_upstream_payload_with_limit(
    payload: bytes, image_bytes: int, limit_var: ContextVar[int | None]
) -> None:
    """Refuse a masked payload larger than the bound its admission was charged for."""
    limit = limit_var.get()
    if limit is not None and len(payload) - max(0, image_bytes) > limit:
        raise PayloadTooLargeError("the masked request is larger than its admitted size bound")
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


def write_masked_slots(
    slots: list[TextSlot],
    masked: list[str],
    session: VaultSession,
    language: str,
    remask: bool,
    since: int | None = None,
    names: frozenset[str] = frozenset(),
    issued: frozenset[str] = frozenset(),
) -> None:
    """Write ``masked`` back to ``slots``, honoring tool-name and issued-id exemptions."""
    if remask:
        masked = [
            session.mask(text, [], language=language, remask=True, since=since) for text in masked
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
            whole = slot.number is not None and PLACEHOLDER_RE.fullmatch(text)
            for match in PLACEHOLDER_RE.finditer(text):
                number = (slot.text, slot.number) if whole and slot.number else None
                session.note_json_leaf(match.group(0), number)


async def chat_completions(
    gateway: Gateway,
    body: object,
    headers: Mapping[str, str],
    *,
    max_text_chars: int | None = None,
    received_at: float | None = None,
    path_session: str | None = None,
    request_id: str | None = None,
) -> tuple[Response, RequestStats]:
    """Mask, forward, restore a ``/v1/chat/completions`` request."""
    timer = RequestTimer(received_at)
    trace = CallTrace(gateway.observability, timer, body, request_id=request_id)
    try:
        response, stats = await gateway.with_session_lease(
            gateway.run_chat_completions(
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
    if gateway.observability is not None and gateway.observability.server_timing:
        response.headers["Server-Timing"] = timer.server_timing()
    if not trace.streaming:
        trace.finish()
    return response, stats


async def mask_chat_request(
    gateway: Gateway,
    body: dict[str, Any],
    collected: CollectedTexts,
    headers: Mapping[str, str],
    *,
    detector: ModeDetector,
    language: str,
    path_session: str | None,
    timer: RequestTimer,
    trace: CallTrace,
    stats: RequestStats,
    check_payload: Callable[[bytes, int], None],
) -> tuple[VaultSession, bytes, list[list[Span]], float]:
    session, created = gateway.session(headers, body, path_session, stats, trace)
    stats.texts = len(collected.slots)
    stats.images = len(collected.images)
    timer.add("parse", time.perf_counter() - timer.started)
    kept: list[list[Span]] = []
    try:
        validate(session, "chat", collected)
        with timer.span("detect"):
            spans = await gateway.detect_all(
                collected.slots, detector, session, language, stats, kept
            )
            names = tool_names(body)
            spans = without_tool_names(
                [slot.text for slot in collected.slots],
                spans,
                names,
                [slot.kind for slot in collected.slots],
            )
            issued = gateway.issued_ids.of(session.session_id)
            spans = without_opaque_ids(collected.slots, spans, issued)
        generation = session.generation
        before = _counts_of(session)
        with timer.span("mask"):
            masked = gateway.mask(collected.slots, spans, session, language)
        _count_masked(stats, before, session)
        if collected.images:
            with timer.span("image"):
                await gateway.mask_images(collected.images, detector, language, stats, session)
        before = _counts_of(session)
        with timer.span("mask"):
            remask = bool(collected.images)
            gateway.write(
                collected.slots, masked, session, language, remask, generation, names, issued
            )
            collected.finalize()
        _count_masked(stats, before, session)
        with timer.span("mask"):
            gateway.recheck(body, collect_texts, session, language, stats, names, issued)
        forwarding = time.perf_counter()
        payload = gateway.forwarded(body, session, stats, add_chat_note)
        check_payload(payload, stats.image_payload_bytes)
    except BaseException:
        stats.log("blocked")
        gateway.release_session(session, created, masked=False)
        raise
    gateway.release_session(session, created, masked=True)
    return session, payload, kept, forwarding


async def check_chat_upstream(
    response: httpx.Response,
    *,
    started: float,
    stream: bool,
    timer: RequestTimer,
    stats: RequestStats,
    out_headers: dict[str, str],
) -> JSONResponse | None:
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
        return _upstream_error(response.status_code, raw, out_headers)

    is_sse = response.headers.get("content-type", "").startswith("text/event-stream")
    if stream and not is_sse:
        with suppress(httpx.HTTPError):
            await response.aclose()
        stats.upstream_ms = (time.perf_counter() - started) * 1000
        timer.add("upstream", stats.upstream_ms / 1000 - timer.stages["upstream"])
        stats.log("upstream_did_not_stream")
        raise UpstreamError(
            "upstream did not return an event stream; retry without stream",
            code="upstream_did_not_stream",
        ) from None
    return None


async def complete_chat_json(
    gateway: Gateway,
    response: httpx.Response,
    *,
    started: float,
    timer: RequestTimer,
    trace: CallTrace,
    stats: RequestStats,
    session: VaultSession,
    language: str,
    detector: ModeDetector,
    out_headers: dict[str, str],
    echo_data: dict[str, Any] | None,
) -> tuple[Response, RequestStats]:
    try:
        raw = await _read_bounded(response, gateway.config.upstream_max_response_bytes)
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
    masked_answer = _masked_answer(answer) if echo_data is not None else None
    gateway.issued_ids.add(session.session_id, upstream_ids(answer))
    observe(session, "chat", answer)
    report = restore_completion(session, answer)
    stats.unresolved = len(report.unresolved)
    gateway.seed_cache(session, language, detector, report.restored_spans, stats)
    out_headers["X-PII-Guard-Unresolved"] = str(stats.unresolved)
    if echo_data is not None:
        answer["pii_guard"] = {**echo_data, "masked_answer": masked_answer}
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


def complete_chat_stream(
    gateway: Gateway,
    response: httpx.Response,
    *,
    timer: RequestTimer,
    trace: CallTrace,
    stats: RequestStats,
    session: VaultSession,
    language: str,
    detector: ModeDetector,
    out_headers: dict[str, str],
    echo_data: dict[str, Any] | None,
) -> tuple[Response, RequestStats]:
    restorer = SseRestorer(
        session,
        opaque=OpaqueStream(session, "chat"),
        on_ids=lambda ids: gateway.issued_ids.add(session.session_id, ids),
        keep_restored_tools=trace.full,
    )
    trace.streaming = True
    lines = timed_sse_lines(response, timer, gateway.config.upstream_stream_timeout)
    source = _produce_chat_events(lines, restorer, timer, trace, echo_data)
    events = stream_sse_events(
        source,
        response=response,
        timer=timer,
        trace=trace,
        stats=stats,
        restorer=restorer,
        session=session,
        seed_cache=lambda restored: gateway.seed_cache(
            session, language, detector, restored, stats
        ),
        on_error=_chat_stream_error,
    )
    out_headers["Cache-Control"] = "no-cache"
    return (
        StreamingResponse(events, media_type="text/event-stream", headers=out_headers),
        stats,
    )


async def run_chat_completions(
    gateway: Gateway,
    body: object,
    headers: Mapping[str, str],
    *,
    max_text_chars: int | None,
    timer: RequestTimer,
    trace: CallTrace,
    path_session: str | None,
    check_payload: Callable[[bytes, int], None],
) -> tuple[Response, RequestStats]:
    url = gateway.upstream_url()
    mode = gateway.mode(headers)
    language = gateway.language(headers)
    trace.mode, trace.language = mode.value, language
    echo = gateway.echo(headers)
    stats = RequestStats(mode=mode, mode_alias=gateway.mode_alias(headers))
    trace.stats = stats
    collected = collect_texts(body)
    body = cast(dict[str, Any], body)
    gateway.validate_limits(collected, max_text_chars)
    detector = gateway.detectors[mode]
    stream = bool(body.get("stream"))
    stats.stream = stream
    session, payload, kept, forwarding = await mask_chat_request(
        gateway,
        body,
        collected,
        headers,
        detector=detector,
        language=language,
        path_session=path_session,
        timer=timer,
        trace=trace,
        stats=stats,
        check_payload=check_payload,
    )
    if trace.payloads:
        trace.masked_request = payload
    echo_data = (
        {
            "masked_messages": _masked_messages(body)[int(stats.note) :],
            "kept_spans": _kept_spans(
                collected.slots, kept, len(body["messages"]) - int(stats.note)
            ),
            "placeholder_note": stats.note,
        }
        if echo
        else None
    )
    response, started = await gateway.send_upstream(
        url,
        payload,
        gateway.upstream_headers(headers),
        timer=timer,
        stats=stats,
        forwarding_started=forwarding,
    )
    stats.upstream_status = response.status_code
    out_headers = stats.headers(session.session_id)
    err_response = await check_chat_upstream(
        response,
        started=started,
        stream=stream,
        timer=timer,
        stats=stats,
        out_headers=out_headers,
    )
    if err_response is not None:
        return err_response, stats
    if not stream:
        return await complete_chat_json(
            gateway,
            response,
            started=started,
            timer=timer,
            trace=trace,
            stats=stats,
            session=session,
            language=language,
            detector=detector,
            out_headers=out_headers,
            echo_data=echo_data,
        )
    return complete_chat_stream(
        gateway,
        response,
        timer=timer,
        trace=trace,
        stats=stats,
        session=session,
        language=language,
        detector=detector,
        out_headers=out_headers,
        echo_data=echo_data,
    )


def _chat_echo_answer_event(restorer: SseRestorer) -> bytes:
    content = restorer.masked_content()
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


def _chat_stream_error(exc: Exception) -> Iterable[bytes]:
    if isinstance(exc, UnmaskOutputTooLargeError):  # LAB-1350
        failed = error_event(exc.code, exc.message)
    else:
        failed = error_event("stream_failed", "the response stream failed")
    return (sse_event(failed), sse_event(DONE))


async def _produce_chat_events(
    lines: AsyncIterator[str],
    restorer: SseRestorer,
    timer: RequestTimer,
    trace: CallTrace,
    echo_data: dict[str, Any] | None,
) -> AsyncIterator[bytes]:
    """The restored events; every await in here is upstream time or pii-guard's own."""
    echoed_answer = False
    if echo_data is not None:
        yield sse_event(
            json.dumps(
                {
                    "object": "pii_guard.masked_request",
                    "messages": echo_data["masked_messages"],
                    "kept_spans": echo_data["kept_spans"],
                    "placeholder_note": echo_data["placeholder_note"],
                },
                ensure_ascii=False,
            )
        )
    async for data in iter_sse_data(lines):
        trace.scan_usage(data)
        scan_usage(data)
        shown = client_chunk(data)
        if shown is None:
            continue
        unmasking = time.perf_counter()
        outs = restorer.process(shown)
        timer.add("unmask", time.perf_counter() - unmasking)
        for out in outs:
            timer.mark_first_event()
            if out == DONE and echo_data is not None and not echoed_answer:
                echoed_answer = True
                yield _chat_echo_answer_event(restorer)
            yield sse_event(out)
            if out == DONE:
                return
    unmasking = time.perf_counter()
    outs = restorer.finish()
    timer.add("unmask", time.perf_counter() - unmasking)
    for out in outs:
        yield sse_event(out)
    if echo_data is not None and not echoed_answer:
        yield _chat_echo_answer_event(restorer)


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
    """Per client message, the spans kept by policy as type and code-point offsets."""
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
    """A whole upstream success body, byte-bounded in every mode (LAB-1566)."""
    data = bytearray()
    async for chunk in response.aiter_bytes():
        data.extend(chunk)
        if len(data) > limit:
            raise UpstreamError("upstream response is too large")
    return bytes(data)


def _upstream_error(status: int, raw: bytes, headers: dict[str, str]) -> JSONResponse:
    """The upstream's status, with only its error ``type``/``code`` tokens kept."""
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
