"""The gateway's Anthropic **Messages API** front end: ``POST /v1/messages`` (LAB-1605).

Claude Code and the Anthropic SDKs speak this API. Same guarantees and order of operations as
``/v1/chat/completions`` (:class:`~pii_guard.gateway.service.Gateway`, ADR 0006) and
``/v1/responses``, on the shared detectors, detection cache, vault and session rules
(``X-PII-Guard-Session``, ``/s/<session>/v1``, known values, outbound re-check):

1. upstream configured? mode, language, session and echo headers valid? body well-formed and
   nothing in it the gateway can't mask (:func:`~pii_guard.gateway.messages_request.
   collect_message_texts`)?
2. detect every text, add the session's known values, drop detections in identifier slots
   that are exactly a declared tool name, mask with one vault session, mask inline images,
   re-check the masked body (:mod:`pii_guard.gateway.outbound`);
3. forward the masked body to ``{upstream base}/messages``, natively (no translation). An
   upstream without a Messages API (404/405 on that path) gets ``400 unsupported_api``
   (LAB-1313's error, :class:`UnsupportedApiError`);
4. restore the answer (:func:`~pii_guard.gateway.messages_restore.restore_message`) or the
   event stream (:class:`~pii_guard.gateway.messages_restore.MessagesSseRestorer`);
5. seed the detection cache with the restored answer text.

``POST /v1/messages/count_tokens`` is masked the same way and answers only the upstream's
``input_tokens``.

Upstream authentication: a configured ``PII_GUARD_UPSTREAM_API_KEY`` goes as ``x-api-key``
(the Anthropic scheme). Without one, the client's own ``x-api-key`` or ``Authorization`` is
passed through (bring your own key). ``anthropic-version`` (default ``2023-06-01``) and
``anthropic-beta`` are passed on when they are plain tokens.

Nothing here logs or raises with request text, values, masked bodies or keys.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncGenerator, Iterable, Mapping
from contextlib import suppress
from typing import Any, cast

import httpx
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from pii_guard.gateway.messages_request import collect_message_texts
from pii_guard.gateway.messages_restore import MessagesSseRestorer, restore_message, stream_error
from pii_guard.gateway.opaque_ids import upstream_ids, without_opaque_ids
from pii_guard.gateway.placeholder_note import add_messages_note
from pii_guard.gateway.request import InvalidChatRequestError
from pii_guard.gateway.responses_restore import iter_sse_events, sse_message
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
    check_upstream_payload,
)
from pii_guard.gateway.stream import stream_sse_events, timed_sse_lines
from pii_guard.gateway.tool_names import model_words, tool_names, without_tool_names
from pii_guard.gateway.trace import CallTrace
from pii_guard.observability import RequestTimer
from pii_guard.types import PiiGuardError
from pii_guard.vault import UnmaskOutputTooLargeError

__all__ = ["ANTHROPIC_VERSION", "MessagesGateway", "UnsupportedApiError", "messages_url"]

logger = logging.getLogger("pii_guard.gateway")

#: Sent when the client names no ``anthropic-version``.
ANTHROPIC_VERSION = "2023-06-01"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_MAX_BETAS = 32
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class UnsupportedApiError(PiiGuardError):
    """The API can't be served (the upstream has no Messages API); nothing was forwarded
    unmasked. A 400, not a 5xx: Claude Code reports a 5xx as a temporary server issue, which
    this is not (LAB-1313); ``x-should-retry: false`` stops SDK retries."""

    code = "unsupported_api"
    status_code = 400

    def __init__(self, message: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.headers = {"x-should-retry": "false", **(headers or {})}


def messages_url(base_url: str, suffix: str = "/messages") -> str:
    """``{base}/messages`` for an upstream base URL (``https://api.anthropic.com/v1``)."""
    base = base_url.rstrip("/")
    for known in ("/chat/completions", "/responses", "/messages"):
        if base.endswith(known):
            base = base[: -len(known)]
    return base + suffix


class _Stats(RequestStats):
    def log(self, outcome: str) -> None:
        logger.info(
            "messages %s mode=%s stream=%s texts=%d cache_hits=%d cache_misses=%d seeded=%d "
            "spans=%s masked=%s detect_ms=%.0f upstream=%s upstream_ms=%.0f unresolved=%d "
            "images=%d outbound=%s",
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
            self.outbound.result if self.outbound is not None else "-",
        )


def _flatten(content: object) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict):
            if isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif block.get("type") == "tool_use":
                parts.append(json.dumps(block.get("input"), ensure_ascii=False))
            elif "content" in block:
                parts.append(_flatten(block["content"]))
    return "\n".join(parts)


def _masked_messages(body: Mapping[str, Any]) -> list[dict[str, str]]:
    """The forwarded (masked) system and messages, as ``{role, content}``, for the echo."""
    out = []
    if body.get("system") is not None:
        out.append({"role": "system", "content": _flatten(body["system"])})
    for message in body.get("messages") or []:
        if isinstance(message, dict):
            out.append(
                {"role": str(message.get("role")), "content": _flatten(message.get("content"))}
            )
    return out


def _upstream_error(status: int, raw: bytes, headers: dict[str, str]) -> JSONResponse:
    """The upstream's status in the Anthropic error shape, with only its error ``type`` kept
    (``overloaded_error``, ``rate_limit_error``, ...: SDKs retry on these). The upstream's
    message may quote the (masked) request, so it is never passed on."""
    kind = "api_error"
    try:
        upstream = json.loads(raw).get("error")
    except (ValueError, AttributeError):
        upstream = None
    if isinstance(upstream, dict):
        value = upstream.get("type")
        if isinstance(value, str) and _SAFE_TOKEN_RE.match(value):
            kind = value
    body = {
        "type": "error",
        "error": {
            "type": kind,
            "code": "upstream_error",
            "message": f"upstream returned HTTP {status}",
        },
    }
    return JSONResponse(body, status_code=status, headers=headers)


def _messages_stream_error(exc: Exception) -> Iterable[bytes]:
    error = stream_error()
    if isinstance(exc, UnmaskOutputTooLargeError):  # LAB-1350
        error["error"]["message"] = exc.message
    return (sse_message(json.dumps(error), "error"),)


class MessagesGateway:
    """``/v1/messages`` on top of the app's :class:`Gateway` (its detectors, cache, vault)."""

    def __init__(self, gateway: Gateway) -> None:
        self.gateway = gateway

    def __repr__(self) -> str:
        return f"MessagesGateway({self.gateway!r})"

    def _upstream_url(self, suffix: str) -> str:
        self.gateway.upstream_url()  # UpstreamNotConfiguredError without a base URL
        return messages_url(cast(str, self.gateway.settings.upstream_base_url), suffix)

    def _upstream_headers(self, headers: Mapping[str, str]) -> dict[str, str]:
        out = self.gateway.upstream_headers(headers)
        key = self.gateway.settings.upstream_api_key
        if key is not None:
            out.pop("Authorization", None)
            out["x-api-key"] = key.get_secret_value()
        elif headers.get("x-api-key"):
            out["x-api-key"] = headers["x-api-key"]
        version = (headers.get("anthropic-version") or "").strip()
        out["anthropic-version"] = version if _TOKEN_RE.match(version) else ANTHROPIC_VERSION
        betas = [b.strip() for b in (headers.get("anthropic-beta") or "").split(",")]
        betas = [b for b in betas if _TOKEN_RE.match(b)][:_MAX_BETAS]
        if betas:
            out["anthropic-beta"] = ",".join(betas)
        return out

    async def messages(
        self,
        body: object,
        headers: Mapping[str, str],
        *,
        max_text_chars: int | None = None,
        received_at: float | None = None,
        path_session: str | None = None,
        request_id: str | None = None,
        count_tokens: bool = False,
    ) -> tuple[Response, RequestStats]:
        timer = RequestTimer(received_at)
        trace = CallTrace(self.gateway.observability, timer, body, request_id=request_id)
        try:
            response, stats = await self.gateway.with_session_lease(
                self._messages(
                    body,
                    headers,
                    max_text_chars=max_text_chars,
                    timer=timer,
                    trace=trace,
                    path_session=path_session,
                    count_tokens=count_tokens,
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

    async def _mask(
        self,
        body: object,
        headers: Mapping[str, str],
        *,
        max_text_chars: int | None,
        timer: RequestTimer,
        trace: CallTrace,
        path_session: str | None,
        stats: RequestStats,
    ) -> tuple[Any, str, Any, bytes]:
        """Steps 1-2: mask body in place and return ``(session, language, detector, payload)``."""
        gw = self.gateway
        mode = stats.mode
        language = gw.language(headers)
        trace.mode, trace.language = mode.value, language
        collected = collect_message_texts(body)
        body = cast(dict[str, Any], body)
        gw.validate_limits(collected, max_text_chars, text_label="a text")
        detector = gw.detectors[mode]
        session, created = gw.session(headers, body, path_session, stats, trace)
        stats.texts = len(collected.slots)
        stats.images = len(collected.images)
        timer.add("parse", time.perf_counter() - timer.started)
        try:
            with timer.span("detect"):
                spans = await gw.detect_all(collected.slots, detector, session, language, stats)
                # The model id's words count as declared names too (Claude Code, LAB-1605).
                names = tool_names(body) | model_words(body)
                spans = without_tool_names(
                    [slot.text for slot in collected.slots],
                    spans,
                    names,
                    [slot.kind for slot in collected.slots],
                )
                issued = gw.issued_ids.of(session.session_id)
                spans = without_opaque_ids(collected.slots, spans, issued)
            generation = session.generation
            before = _counts_of(session)
            with timer.span("mask"):
                masked = gw.mask(collected.slots, spans, session, language)
            _count_masked(stats, before, session)
            if collected.images:
                with timer.span("image"):
                    await gw.mask_images(collected.images, detector, language, stats, session)
            before = _counts_of(session)
            with timer.span("mask"):
                remask = bool(collected.images)
                gw.write(
                    collected.slots, masked, session, language, remask, generation, names, issued
                )
                collected.finalize()
            _count_masked(stats, before, session)
            with timer.span("mask"):
                gw.recheck(body, collect_message_texts, session, language, stats, names, issued)
            forwarding = time.perf_counter()
            payload = gw.forwarded(body, session, stats, add_messages_note)
            check_upstream_payload(payload, stats.image_payload_bytes)
            timer.add("forward", time.perf_counter() - forwarding)
        except BaseException:
            stats.log("blocked")
            gw.release_session(session, created, masked=False)
            raise
        gw.release_session(session, created, masked=True)
        return session, language, detector, payload

    async def _check_upstream(
        self,
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
            if response.status_code in (404, 405):
                stats.log("unsupported_api")
                raise UnsupportedApiError(
                    "the upstream has no Anthropic Messages API (POST .../messages answered "
                    f"HTTP {response.status_code}); point PII_GUARD_UPSTREAM_BASE_URL at an "
                    "Anthropic-compatible upstream, or use an OpenAI-compatible client with "
                    "/v1/chat/completions (see the Connect page in the PII Guard console)"
                )
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

    async def _messages(
        self,
        body: object,
        headers: Mapping[str, str],
        *,
        max_text_chars: int | None,
        timer: RequestTimer,
        trace: CallTrace,
        path_session: str | None,
        count_tokens: bool,
    ) -> tuple[Response, RequestStats]:
        gw = self.gateway
        url = self._upstream_url("/messages/count_tokens" if count_tokens else "/messages")
        mode = gw.mode(headers)
        echo = gw.echo(headers)
        stats = _Stats(mode=mode, mode_alias=gw.mode_alias(headers))
        trace.stats = stats
        stream = isinstance(body, dict) and body.get("stream") is True and not count_tokens
        if echo and (stream or count_tokens):
            raise InvalidChatRequestError(
                "X-PII-Guard-Echo is supported on non-streamed /v1/messages calls only"
            )
        stats.stream = stream
        session, language, detector, payload = await self._mask(
            body,
            headers,
            max_text_chars=max_text_chars,
            timer=timer,
            trace=trace,
            path_session=path_session,
            stats=stats,
        )
        body = cast(dict[str, Any], body)
        if trace.payloads:
            trace.masked_request = payload
        masked_input = _masked_messages(body) if echo else None
        upstream_headers = self._upstream_headers(headers)
        if stream:
            upstream_headers["Accept"] = "text/event-stream"
        response, started = await gw.send_upstream(
            url, payload, upstream_headers, timer=timer, stats=stats
        )
        stats.upstream_status = response.status_code
        out_headers = stats.headers(session.session_id)
        err_response = await self._check_upstream(
            response,
            started=started,
            stream=stream,
            timer=timer,
            stats=stats,
            out_headers=out_headers,
        )
        if err_response is not None:
            return err_response, stats
        if count_tokens:
            return await self._count(response, started, timer, stats, out_headers)
        if not stream:
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
                masked_input,
            )
        return self._streamed(
            response, timer, trace, stats, session, language, detector, out_headers
        )

    async def _json(
        self, response: httpx.Response, started: float, timer: RequestTimer, stats: RequestStats
    ) -> tuple[bytes, dict[str, Any]]:
        try:
            raw = await _read_bounded(response, self.gateway.config.upstream_max_response_bytes)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"upstream response failed ({type(exc).__name__})") from None
        finally:
            await response.aclose()
        stats.upstream_ms = (time.perf_counter() - started) * 1000
        timer.add("upstream", stats.upstream_ms / 1000 - timer.stages["upstream"])
        try:
            answer = json.loads(raw)
        except ValueError:
            stats.log("upstream_invalid")
            raise UpstreamError("upstream returned a body that is not JSON") from None
        if not isinstance(answer, dict):
            raise UpstreamError("upstream returned a body that is not a JSON object")
        return raw, answer

    async def _count(
        self,
        response: httpx.Response,
        started: float,
        timer: RequestTimer,
        stats: RequestStats,
        out_headers: dict[str, str],
    ) -> tuple[Response, RequestStats]:
        _, answer = await self._json(response, started, timer, stats)
        tokens = answer.get("input_tokens")
        if isinstance(tokens, bool) or not isinstance(tokens, int):
            raise UpstreamError("upstream token count has no input_tokens")
        stats.log("ok")
        timer.finish()
        return JSONResponse({"input_tokens": tokens}, headers=out_headers), stats

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
        masked_input: list[dict[str, str]] | None,
    ) -> tuple[Response, RequestStats]:
        raw, answer = await self._json(response, started, timer, stats)
        if trace.payloads:
            trace.upstream_body = raw
        building = time.perf_counter()
        masked_output = _flatten(answer.get("content")) if masked_input is not None else None
        self.gateway.issued_ids.add(session.session_id, upstream_ids(answer))
        try:
            report = restore_message(session, answer)
        except ValueError:  # a tool_use input that no longer parses: never half-restored
            stats.log("upstream_invalid")
            raise UpstreamError("upstream tool input could not be restored") from None
        stats.unresolved = len(report.unresolved)
        self.gateway.seed_cache(session, language, detector, report.restored_spans, stats)
        out_headers["X-PII-Guard-Unresolved"] = str(stats.unresolved)
        if masked_input is not None:
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
        restorer = MessagesSseRestorer(
            session, on_ids=lambda ids: issued.add(session.session_id, ids)
        )
        trace.streaming = True
        timeout = self.gateway.config.upstream_stream_timeout

        async def produce() -> AsyncGenerator[bytes, None]:
            async for event, data in iter_sse_events(timed_sse_lines(response, timer, timeout)):
                unmasking = time.perf_counter()
                outs = restorer.process(event, data)
                timer.add("unmask", time.perf_counter() - unmasking)
                for name, out in outs:
                    timer.mark_first_event()
                    yield sse_message(out, name)
            for name, out in restorer.finish():
                yield sse_message(out, name)

        events = stream_sse_events(
            produce(),
            response=response,
            timer=timer,
            trace=trace,
            stats=stats,
            restorer=restorer,
            session=session,
            seed_cache=lambda restored: self.gateway.seed_cache(
                session, language, detector, restored, stats
            ),
            on_error=_messages_stream_error,
        )
        out_headers["Cache-Control"] = "no-cache"
        return (
            StreamingResponse(events, media_type="text/event-stream", headers=out_headers),
            stats,
        )
