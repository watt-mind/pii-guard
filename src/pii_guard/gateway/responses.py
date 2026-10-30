"""The gateway's OpenAI **Responses API** front end: ``POST /v1/responses``.

Same guarantees and order of operations as ``/v1/chat/completions``
(:class:`~pii_guard.gateway.service.Gateway`, ADR 0006), on the shared detectors, detection
cache and vault:

1. upstream configured? mode, language, session and echo headers valid? body well-formed and
   nothing in it the gateway can't mask (:func:`~pii_guard.gateway.responses_request.
   collect_response_texts`)?
2. detect every text, add the session's known values, drop detections in identifier slots
   that are exactly one of the tool names the request declares
   (:func:`~pii_guard.gateway.tool_names.without_tool_names`), mask with one vault
   session;
3. forward the masked body to ``{upstream base}/responses``, natively (no translation to Chat
   Completions). An upstream without a Responses API (404/405 on that path) gets a clear 501
   ``responses_unsupported``;
4. restore the answer (:func:`~pii_guard.gateway.responses_restore.restore_response`) or the
   ``response.*`` event stream (:class:`~pii_guard.gateway.responses_restore.
   ResponsesSseRestorer`);
5. seed the detection cache with the restored output text.

``X-PII-Guard-Echo: masked`` is supported on non-streamed calls (``pii-guard connect
muse-code --check`` uses it); with ``stream: true`` it is refused (400).

Nothing here logs or raises with request text, values, masked bodies or keys.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from typing import Any, cast

import httpx
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from pii_guard.gateway.opaque_ids import upstream_ids, without_opaque_ids
from pii_guard.gateway.placeholder_note import add_responses_note
from pii_guard.gateway.request import InvalidChatRequestError
from pii_guard.gateway.responses_request import collect_response_texts
from pii_guard.gateway.responses_restore import (
    DONE,
    ResponsesSseRestorer,
    iter_sse_events,
    restore_response,
    sse_message,
)
from pii_guard.gateway.restore import restore_text
from pii_guard.gateway.service import (
    REQUEST_ID_HEADER,
    Gateway,
    RequestStats,
    UpstreamError,
    _count_masked,
    _counts,
    _counts_of,
    _read_bounded,
    _read_limited,
    _upstream_error,
    check_upstream_payload,
)
from pii_guard.gateway.tool_names import tool_names, without_tool_names
from pii_guard.gateway.trace import CallTrace
from pii_guard.observability import RequestTimer
from pii_guard.types import PayloadTooLargeError, PiiGuardError
from pii_guard.vault import UnmaskOutputTooLargeError

__all__ = [
    "ResponsesGateway",
    "ResponsesUnsupportedError",
    "responses_url",
]

logger = logging.getLogger("pii_guard.gateway")


class ResponsesUnsupportedError(PiiGuardError):
    """The upstream has no Responses API. Nothing was translated or retried."""

    code = "responses_unsupported"
    status_code = 501


def responses_url(base_url: str) -> str:
    """``{base}/responses`` for an upstream base URL (with or without ``/chat/completions``)."""
    base = base_url.rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    return base + "/responses"


class _Stats(RequestStats):
    def log(self, outcome: str) -> None:
        logger.info(
            "responses %s mode=%s stream=%s texts=%d cache_hits=%d cache_misses=%d seeded=%d "
            "spans=%s masked=%s detect_ms=%.0f upstream=%s upstream_ms=%.0f unresolved=%d "
            "images=%d image_masked=%s image_ms=%.0f outbound=%s outbound_hits=%s",
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
            self.upstream_status if self.upstream_status is not None else "-",
            self.upstream_ms,
            self.unresolved,
            self.images,
            _counts(self.image_masked),
            self.image_ms,
            self.outbound.result if self.outbound is not None else "-",
            _counts(self.outbound.hits) if self.outbound is not None else "-",
        )


def _masked_input(body: Mapping[str, Any]) -> list[dict[str, str]]:
    """The forwarded (masked) input, as ``{role or type, content}``, for the echo header."""
    items = body.get("input")
    if isinstance(items, str):
        return [{"role": "user", "content": items}]
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("role") or item.get("type") or "")
        content = item.get("content", item.get("output", item.get("arguments", "")))
        if isinstance(content, list):
            content = "\n".join(
                str(p.get("text", p.get("refusal", ""))) for p in content if isinstance(p, dict)
            )
        out.append({"role": kind, "content": content if isinstance(content, str) else ""})
    return out


def _masked_output(answer: Mapping[str, Any]) -> list[dict[str, object]]:
    """The upstream's output text before restoring, per output index, for the echo header."""
    out: list[dict[str, object]] = []
    for index, item in enumerate(answer.get("output") or []):
        if isinstance(item, dict) and item.get("type") == "message":
            parts = item.get("content") or []
            text = "".join(
                str(p.get("text", "")) for p in parts if isinstance(p, dict) and "text" in p
            )
            out.append({"index": index, "content": text})
    return out


class ResponsesGateway:
    """``/v1/responses`` on top of the app's :class:`Gateway` (its detectors, cache, vault)."""

    def __init__(self, gateway: Gateway) -> None:
        self.gateway = gateway

    def __repr__(self) -> str:
        return f"ResponsesGateway({self.gateway!r})"

    def _upstream_url(self) -> str:
        self.gateway._upstream_url()  # UpstreamNotConfiguredError without a base URL
        return responses_url(cast(str, self.gateway.settings.upstream_base_url))

    async def responses(
        self,
        body: object,
        headers: Mapping[str, str],
        *,
        max_text_chars: int | None = None,
        received_at: float | None = None,
        path_session: str | None = None,
    ) -> tuple[Response, RequestStats]:
        timer = RequestTimer(received_at)
        trace = CallTrace(self.gateway.observability, timer, body)
        try:
            response, stats = await self.gateway._with_session_lease(
                self._responses(
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
        observability = self.gateway.observability
        if observability is not None and observability.server_timing:
            response.headers["Server-Timing"] = timer.server_timing()
        if not trace.streaming:
            trace.finish()
        return response, stats

    async def _responses(
        self,
        body: object,
        headers: Mapping[str, str],
        *,
        max_text_chars: int | None,
        timer: RequestTimer,
        trace: CallTrace,
        path_session: str | None = None,
    ) -> tuple[Response, RequestStats]:
        gw = self.gateway
        url = self._upstream_url()
        mode = gw._mode(headers)
        language = gw._language(headers)
        trace.mode, trace.language = mode.value, language
        echo = gw._echo(headers)
        stats = _Stats(mode=mode)
        trace.stats = stats
        collected = collect_response_texts(body)
        body = cast(dict[str, Any], body)
        stream = bool(body.get("stream"))
        if echo and stream:
            raise InvalidChatRequestError(
                "X-PII-Guard-Echo is supported on non-streamed /v1/responses calls only"
            )
        if max_text_chars is not None and any(
            len(s.text) > max_text_chars for s in collected.slots
        ):
            raise PayloadTooLargeError(f"a text is longer than {max_text_chars} characters")
        if len(collected.images) > gw.config.max_images:
            raise PayloadTooLargeError(
                f"a request may carry at most {gw.config.max_images} inline images"
            )
        if any(len(img.data) > gw.config.max_image_bytes for img in collected.images):
            raise PayloadTooLargeError(
                f"an inline image is larger than {gw.config.max_image_bytes} bytes"
            )
        detector = gw.detectors[mode]
        session, created = gw._session(headers, body, path_session, stats, trace)
        stats.stream = stream
        stats.texts = len(collected.slots)
        stats.images = len(collected.images)
        timer.add("parse", time.perf_counter() - timer.started)
        try:
            with timer.span("detect"):
                spans = await gw._detect_all(collected.slots, detector, session, language, stats)
                names = tool_names(body)
                spans = without_tool_names(
                    [slot.text for slot in collected.slots],
                    spans,
                    names,
                    [slot.kind for slot in collected.slots],
                )
                issued = gw.issued_ids.of(session.session_id)
                spans = without_opaque_ids(collected.slots, spans, issued)
            # Inline images go through the chat path (LAB-1285): mask the texts, then the
            # images, then remask the texts with the values the images added (LAB-1278).
            generation = session.generation
            before = _counts_of(session)
            with timer.span("mask"):
                masked = gw._mask(collected.slots, spans, session, language)
            _count_masked(stats, before, session)
            if collected.images:
                with timer.span("image"):
                    await gw._mask_images(collected.images, detector, language, stats, session)
            before = _counts_of(session)
            with timer.span("mask"):
                remask = bool(collected.images)
                gw._write(
                    collected.slots, masked, session, language, remask, generation, names, issued
                )
                collected.finalize()
            _count_masked(stats, before, session)
            with timer.span("mask"):
                gw._recheck(body, collect_response_texts, session, language, stats, names, issued)
        except BaseException:
            stats.log("blocked")
            gw._release_session(session, created, masked=False)
            raise
        gw._release_session(session, created, masked=True)

        forwarding = time.perf_counter()
        payload = gw._forwarded(body, session, stats, add_responses_note)
        try:
            check_upstream_payload(payload, stats.image_payload_bytes)
        except PayloadTooLargeError:
            stats.log("blocked")
            raise
        if trace.payloads:
            trace.masked_request = payload
        masked_input = _masked_input(body) if echo else None
        client = gw.upstream_client()  # shared with /v1/chat/completions (LAB-1176)
        upstream_headers = gw._upstream_headers(headers)
        if stream:
            upstream_headers["Accept"] = "text/event-stream"
        request = client.build_request(
            "POST", url, content=payload, headers=upstream_headers, timeout=gw.upstream_timeout()
        )
        started = time.perf_counter()
        timer.add("forward", started - forwarding)
        timer.upstream_sent = started
        try:
            response = await client.send(request, stream=True)
            await gw.bound_upstream_response(response)
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
            if response.status_code in (404, 405):
                stats.log("responses_unsupported")
                raise ResponsesUnsupportedError(
                    f"the upstream has no Responses API (POST .../responses answered HTTP "
                    f"{response.status_code}); use /v1/chat/completions with this upstream"
                )
            stats.log("upstream_error")
            return _upstream_error(response.status_code, raw, out_headers), stats

        is_sse = response.headers.get("content-type", "").startswith("text/event-stream")
        if not stream or not is_sse:
            return await self._whole(
                response,
                started,
                timer,
                trace,
                stats,
                session,
                language,
                detector,
                out_headers,
                echo,
                masked_input,
            )
        return self._streamed(
            response, timer, trace, stats, session, language, detector, out_headers
        )

    async def _whole(
        self,
        response: httpx.Response,
        started: float,
        timer: RequestTimer,
        trace: CallTrace,
        stats: RequestStats,
        session: Any,
        language: str,
        detector: Any,
        out_headers: dict[str, str],
        echo: bool,
        masked_input: list[dict[str, str]] | None,
    ) -> tuple[Response, RequestStats]:
        try:
            raw = await _read_bounded(response, self.gateway.config.upstream_max_response_bytes)
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
        masked_output = _masked_output(answer) if echo else None
        self.gateway.issued_ids.add(session.session_id, upstream_ids(answer))
        report = restore_response(session, answer)
        stats.unresolved = len(report.unresolved)
        self.gateway._seed_cache(session, language, detector, report.restored_spans, stats)
        out_headers["X-PII-Guard-Unresolved"] = str(stats.unresolved)
        if echo:
            answer["pii_guard"] = {"masked_input": masked_input, "masked_output": masked_output}
        stats.log("ok")
        if trace.full:
            trace.answer = answer
        elif trace.recording and isinstance(answer.get("usage"), dict):
            trace.usage = answer["usage"]
        result = JSONResponse(answer, headers=out_headers)
        timer.add("response", time.perf_counter() - building)
        timer.finish()
        return result, stats

    def _streamed(
        self,
        response: httpx.Response,
        timer: RequestTimer,
        trace: CallTrace,
        stats: RequestStats,
        session: Any,
        language: str,
        detector: Any,
        out_headers: dict[str, str],
    ) -> tuple[Response, RequestStats]:
        issued = self.gateway.issued_ids
        restorer = ResponsesSseRestorer(
            session, on_ids=lambda ids: issued.add(session.session_id, ids)
        )
        trace.streaming = True

        async def timed_lines() -> AsyncIterator[str]:
            # Whole-stream deadline (LAB-1566), like the chat stream's timed lines.
            lines = response.aiter_lines().__aiter__()
            deadline = time.perf_counter() + self.gateway.config.upstream_stream_timeout
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

        async def produce() -> AsyncGenerator[bytes, None]:
            async for event, data in iter_sse_events(timed_lines()):
                unmasking = time.perf_counter()
                outs = restorer.process(event, data)
                timer.add("unmask", time.perf_counter() - unmasking)
                _scan_usage(trace, data)
                for name, out in outs:
                    timer.mark_first_event()
                    yield sse_message(out, name)
            for name, out in restorer.finish():
                yield sse_message(out, name)

        async def events() -> AsyncIterator[bytes]:
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
                    outcome = f"stream_error:{type(exc).__name__}"
                    error = {
                        "type": "error",
                        "code": "stream_failed",
                        "message": "the response stream failed",
                        "param": None,
                    }
                    if isinstance(exc, UnmaskOutputTooLargeError):  # LAB-1350
                        error.update(code=exc.code, message=exc.message)
                    yield sse_message(json.dumps(error), "error")
            except (GeneratorExit, asyncio.CancelledError):
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
                    self.gateway._seed_cache(session, language, detector, restored, stats)
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


def _scan_usage(trace: CallTrace, data: str) -> None:
    """``usage`` arrives inside ``response.completed`` (``{"response": {"usage": ...}}``)."""
    if not trace.recording or '"usage"' not in data or data.strip() == DONE:
        return
    try:
        parsed = json.loads(data)
    except ValueError:
        return
    response = parsed.get("response") if isinstance(parsed, dict) else None
    usage = response.get("usage") if isinstance(response, dict) else None
    if isinstance(usage, dict):
        trace.usage = usage
