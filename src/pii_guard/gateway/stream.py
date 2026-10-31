"""Streaming re-identification of ``chat.completion.chunk`` server-sent events.

Every text field of a delta (``content``, ``refusal``, reasoning), every tool call's
``function.arguments`` and custom ``custom.input``, and the legacy ``function_call.arguments``
gets its own :class:`~pii_guard.vault.StreamUnmasker`, keyed by choice index (and tool-call
index), so a placeholder split across chunks (``[[PERS`` + ``ON_7f3a]]``)
is held back until it is complete. When a choice finishes (``finish_reason``) or the stream
ends, whatever is still held back is flushed into that chunk (or a final synthetic chunk).
Concatenating the emitted deltas gives exactly ``session.unmask()`` of the upstream text.
Arguments (JSON) get JSON-string-escaped values; custom tool input is freeform text and is
restored as is (LAB-1354). In both, a regex-escaped placeholder is restored as a regex literal
and held back while split (LAB-1481). One restore budget covers every field of the response
(LAB-1350).

Upstream ``error`` events are replaced by a generic error: they may quote the masked request.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from contextlib import suppress
from typing import TYPE_CHECKING, Any

import httpx

from pii_guard.gateway.opaque_ids import upstream_ids
from pii_guard.gateway.restore import (
    MESSAGE_TEXT_FIELDS,
    JsonEscapingSession,
    ToolInputSession,
    restore_text,
)
from pii_guard.types import PiiGuardError, Span
from pii_guard.vault import StreamUnmasker, VaultSession

if TYPE_CHECKING:
    from pii_guard.gateway.trace import CallTrace
    from pii_guard.observability import RequestTimer

__all__ = [
    "SseRestorer",
    "iter_sse_data",
    "sse_event",
    "stream_sse_events",
    "timed_lines",
    "timed_sse_lines",
]

DONE = "[DONE]"

#: Caps on what one stream retains (LAB-1566), in every mode: one buffered SSE event, the
#: retained masked content per choice (it only feeds detection-cache seeding, so overflow
#: drops the retained copy instead of failing), and the open unmaskers (per choice/field/
#: tool index). Past the event or unmasker cap the stream ends with the generic error.
MAX_SSE_EVENT_CHARS = 4 * 1024 * 1024
MAX_MASKED_CONTENT_CHARS = 1_000_000
MAX_UNMASKERS = 1024


class StreamTooLargeError(RuntimeError):
    """A stream retention cap was passed; the caller ends the stream with a generic error."""


async def timed_sse_lines(
    response: httpx.Response,
    timer: RequestTimer,
    timeout: float,  # noqa: ASYNC109 - a per-stream deadline, not a call timeout
) -> AsyncIterator[str]:
    """The upstream's lines; time spent waiting on them counts as upstream time.

    The whole stream has a total deadline (LAB-1566), separate from the per-read
    httpx timeout: past it the stream ends with the generic stream error.
    """
    lines = response.aiter_lines().__aiter__()
    deadline = time.perf_counter() + timeout
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


timed_lines = timed_sse_lines


async def stream_sse_events(
    source: AsyncIterator[bytes],
    *,
    response: httpx.Response,
    timer: RequestTimer,
    trace: CallTrace,
    stats: Any,
    restorer: Any,
    session: VaultSession,
    seed_cache: Callable[[Mapping[int, tuple[str, list[Span]]]], None],
    on_error: Callable[[Exception], Iterable[bytes]],
) -> AsyncIterator[bytes]:
    """Hand ``source``'s events to the client; time suspended in ``yield`` is the
    client's (read speed, backpressure), not overhead."""
    outcome = "ok"
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
                for err_chunk in on_error(exc):
                    yield err_chunk
            finally:
                timer.add("client", time.perf_counter() - sending)
    except (GeneratorExit, asyncio.CancelledError):
        # The client went away mid-stream (the server closes or cancels this generator).
        # The answer is partial: record it as such and never seed the cache with it.
        if outcome == "ok":
            outcome = "client_disconnected"
        raise
    finally:
        if hasattr(source, "aclose"):
            await source.aclose()
        await response.aclose()
        _finalize_sse_stream(
            outcome=outcome,
            timer=timer,
            trace=trace,
            stats=stats,
            restorer=restorer,
            session=session,
            seed_cache=seed_cache,
        )


def _finalize_sse_stream(
    *,
    outcome: str,
    timer: RequestTimer,
    trace: CallTrace,
    stats: Any,
    restorer: Any,
    session: VaultSession,
    seed_cache: Callable[[Mapping[int, tuple[str, list[Span]]]], None],
) -> None:
    stats.upstream_ms = timer.stages["upstream"] * 1000
    stats.unresolved = len(restorer.unresolved)
    if trace.recording and getattr(restorer, "usage", None):
        trace.usage = restorer.usage
    if outcome == "ok":
        _seed_restored_stream(session, restorer, trace, seed_cache)
    stats.log(outcome)
    if trace.payloads:
        trace.stream_masked = restorer.masked_content()
        if hasattr(restorer, "masked_tool_calls"):
            trace.stream_masked_tools = restorer.masked_tool_calls()
        trace.stream_chunks = restorer.chunks
    if outcome == "ok":
        trace.finish()
    elif outcome == "client_disconnected":
        trace.finish(outcome=outcome, error={"code": outcome})
    else:
        trace.finish(outcome="stream_error", error={"code": "stream_failed"})


def _seed_restored_stream(
    session: VaultSession,
    restorer: Any,
    trace: CallTrace,
    seed_cache: Callable[[Mapping[int, tuple[str, list[Span]]]], None],
) -> None:
    with suppress(PiiGuardError):
        restored = {}
        for index, masked in restorer.masked_content().items():
            text, spans, _ = restore_text(session, masked)
            restored[index] = (text, spans)
        seed_cache(restored)
        if trace.full:
            trace.stream_restored = {i: t for i, (t, _) in restored.items()}
            if hasattr(restorer, "restored_tool_calls"):
                trace.stream_restored_tools = restorer.restored_tool_calls()


async def iter_sse_data(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """The ``data`` payload of each server-sent event (multi-line data joined by ``\\n``)."""
    data: list[str] = []
    buffered = 0
    async for line in lines:
        if line == "":
            if data:
                yield "\n".join(data)
                data = []
                buffered = 0
            continue
        if line.startswith("data:"):
            value = line[5:]
            value = value[1:] if value.startswith(" ") else value
            buffered += len(value) + 1
            if buffered > MAX_SSE_EVENT_CHARS:
                raise StreamTooLargeError("upstream SSE event is too large")
            data.append(value)
        # Comments (":"), "event:", "id:" and "retry:" lines are not used by chat completions.
    if data:
        yield "\n".join(data)


def sse_event(data: str) -> bytes:
    return ("".join(f"data: {line}\n" for line in data.split("\n")) + "\n").encode()


def error_event(code: str, message: str) -> str:
    return json.dumps({"error": {"code": code, "message": message, "type": code}})


class SseRestorer:
    """Rewrites SSE data payloads; feed them in order with :meth:`process`, then :meth:`finish`."""

    def __init__(
        self,
        session: VaultSession,
        on_ids: Callable[[list[str]], None] | None = None,
        *,
        keep_restored_tools: bool = False,
    ) -> None:
        """``on_ids`` receives the ids each chunk carries, raw (LAB-1469).

        ``keep_restored_tools`` also retains the restored tool-call arguments (traffic log
        level ``full``); the masked ones are always retained, under the same cap (LAB-1189).
        """
        self._session = session
        self._on_ids = on_ids
        # One budget for the whole response: every choice, field and tool call (LAB-1350).
        self._budget = session.restore_budget()
        # (choice, field) or (choice, "tool", tool index) -> unmasker
        self._unmaskers: dict[tuple[Any, ...], StreamUnmasker] = {}
        self._retired_unresolved: dict[str, None] = {}
        self._masked_content: dict[int, list[str]] = {}
        self._masked_overflow: set[int] = set()  # choices past the retention cap (LAB-1566)
        self._masked_len: dict[int, int] = {}
        # Per choice, per tool index: the tool call as the upstream streamed it (masked) and
        # as the client received it (restored), for the traffic log (LAB-1189).
        self._keep_restored_tools = keep_restored_tools
        self._tools: dict[int, dict[Any, dict[str, Any]]] = {}
        self._tools_restored: dict[int, dict[Any, list[str]]] = {}
        self._tools_len: dict[int, int] = {}
        self._tools_overflow: set[int] = set()
        self._template: dict[str, Any] | None = None
        self._done = False
        self.chunks = 0

    def __repr__(self) -> str:
        return f"SseRestorer(chunks={self.chunks}, open={len(self._unmaskers)})"

    @property
    def unresolved(self) -> tuple[str, ...]:
        seen: dict[str, None] = dict(self._retired_unresolved)
        for unmasker in self._unmaskers.values():
            seen.update(dict.fromkeys(unmasker.unresolved))
        return tuple(seen)

    def masked_content(self) -> dict[int, str]:
        """Per choice, the upstream (masked) ``content`` seen so far -- for cache seeding.

        A choice that passed the retention cap is absent: seeding is an optimisation, and a
        partial copy would only seed a text the client never sends back (LAB-1566).
        """
        return {index: "".join(parts) for index, parts in self._masked_content.items()}

    def masked_truncated(self) -> frozenset[int]:
        """The choices whose masked copy passed the retention cap and was dropped (LAB-1581).

        The ``masked_answer`` echo marks them truncated, so a dropped copy is distinguishable
        from a short or empty answer.
        """
        return frozenset(self._masked_overflow)

    def _retain_masked(self, index: int, value: str) -> None:
        if index in self._masked_overflow:
            return
        parts = self._masked_content.setdefault(index, [])
        if self._masked_len.get(index, 0) + len(value) > MAX_MASKED_CONTENT_CHARS:
            del self._masked_content[index]
            self._masked_len.pop(index, None)
            self._masked_overflow.add(index)
            return
        parts.append(value)
        self._masked_len[index] = self._masked_len.get(index, 0) + len(value)

    def masked_tool_calls(self) -> dict[int, list[dict[str, Any]]]:
        """Per choice, the streamed tool calls as the upstream sent them (masked), in the
        non-streamed ``message.tool_calls`` shape. A choice past the cap is absent."""
        return {
            index: [_tool_call(i, call, call["function"]["arguments"]) for i, call in calls.items()]
            for index, calls in self._tools.items()
        }

    def restored_tool_calls(self) -> dict[int, list[dict[str, Any]]]:
        """Per choice, the streamed tool calls as the client received them (restored); empty
        unless ``keep_restored_tools``."""
        return {
            index: [
                _tool_call(i, call, "".join(self._tools_restored[index][i]))
                for i, call in calls.items()
            ]
            for index, calls in self._tools.items()
            if index in self._tools_restored
        }

    def _retain_tool(
        self, index: int, tool_index: Any, call: dict[str, Any], masked: str, restored: str
    ) -> None:
        if index in self._tools_overflow:
            return
        size = len(masked) + (len(restored) if self._keep_restored_tools else 0)
        if self._tools_len.get(index, 0) + size > MAX_MASKED_CONTENT_CHARS:
            self._tools.pop(index, None)
            self._tools_restored.pop(index, None)
            self._tools_len.pop(index, None)
            self._tools_overflow.add(index)
            return
        self._tools_len[index] = self._tools_len.get(index, 0) + size
        held = self._tools.setdefault(index, {}).setdefault(
            tool_index, {"function": {"arguments": ""}}
        )
        for name in ("id", "type"):
            if isinstance(call.get(name), str):
                held[name] = call[name]
        function = call.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            held["function"]["name"] = function["name"]
        held["function"]["arguments"] += masked
        if self._keep_restored_tools:
            self._tools_restored.setdefault(index, {}).setdefault(tool_index, []).append(restored)

    def _retain_rest(self, key: tuple[Any, ...], rest: str) -> None:
        """A flushed remainder of a tool call's arguments joins its restored copy."""
        if key[1] != "tool" or not self._keep_restored_tools:
            return
        parts = self._tools_restored.get(key[0], {}).get(key[2])
        if parts is not None:
            parts.append(rest)

    def _unmasker(self, key: tuple[Any, ...], kind: str = "text") -> StreamUnmasker:
        unmasker = self._unmaskers.get(key)
        if unmasker is None and len(self._unmaskers) >= MAX_UNMASKERS:
            raise StreamTooLargeError("upstream stream has too many open fields")
        if unmasker is None:
            session: Any = {
                "json": JsonEscapingSession(self._session, self._budget),
                "tool": ToolInputSession(self._session, self._budget),
            }.get(kind, self._session)
            unmasker = StreamUnmasker(session, self._budget)
            self._unmaskers[key] = unmasker
        return unmasker

    def _process_choices(self, chunk: dict[str, Any]) -> None:
        choices = chunk.get("choices")
        if not isinstance(choices, list):
            return
        for position, choice in enumerate(choices):
            if isinstance(choice, dict):
                self._process_choice(choice, position)
        if self._template is None and choices:
            self._template = {
                k: chunk[k] for k in ("id", "object", "created", "model") if k in chunk
            }

    def process(self, data: str) -> list[str]:
        """The payloads to emit for one upstream payload."""
        if self._done:
            return []
        if data.strip() == DONE:
            out = self.finish()
            self._done = True
            return [*out, DONE]
        try:
            chunk = json.loads(data)
        except ValueError:
            return [data]  # not ours to interpret; holds masked text only
        if not isinstance(chunk, dict):
            return [data]
        if chunk.get("error"):  # ``error: null`` is a normal chunk, not a failure (LAB-1564)
            return [
                *self.finish(),
                error_event("upstream_error", "upstream stream error"),
                DONE,
            ]
        if self._on_ids is not None:
            self._on_ids(upstream_ids(chunk))
        self._process_choices(chunk)
        self.chunks += 1
        return [json.dumps(chunk, ensure_ascii=False)]

    def _process_content_parts(self, index: int, name: str, parts: list[Any]) -> None:
        for part in parts:
            if (
                not isinstance(part, dict)
                or part.get("type") != "text"
                or not isinstance(part.get("text"), str)
            ):
                raise ValueError("unsupported upstream content part")
            text = part["text"]
            self._retain_masked(index, text)
            part["text"] = self._unmasker((index, name)).feed(text)

    def _process_delta_text_fields(self, index: int, delta: dict[str, Any]) -> None:
        for name in MESSAGE_TEXT_FIELDS:
            value = delta.get(name)
            if name == "content" and isinstance(value, list):
                self._process_content_parts(index, name, value)
            elif isinstance(value, str):
                if name == "content":
                    self._retain_masked(index, value)
                delta[name] = self._unmasker((index, name)).feed(value)

    def _process_delta_tool_calls(self, index: int, delta: dict[str, Any]) -> None:
        for position_in_delta, call in enumerate(delta.get("tool_calls") or []):
            if not isinstance(call, dict):
                continue
            tool_index = call.get("index", position_in_delta)
            function = call.get("function")
            if isinstance(function, dict):
                masked = function.get("arguments")
                restored = ""
                if isinstance(masked, str):
                    restored = self._unmasker((index, "tool", tool_index), "json").feed(masked)
                    function["arguments"] = restored
                self._retain_tool(
                    index, tool_index, call, masked if isinstance(masked, str) else "", restored
                )
            custom = call.get("custom")
            if isinstance(custom, dict) and isinstance(custom.get("input"), str):
                custom["input"] = self._unmasker((index, "custom", tool_index), "tool").feed(
                    custom["input"]
                )

    def _process_choice(self, choice: dict[str, Any], position: int) -> None:
        index = choice.get("index")
        if type(index) is not int:
            index = position
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            delta = {}
            if choice.get("finish_reason"):
                choice["delta"] = delta
        self._process_delta_text_fields(index, delta)
        self._process_delta_tool_calls(index, delta)
        # The legacy (pre-tools) single function call: ``delta.function_call.arguments``.
        function_call = delta.get("function_call")
        if isinstance(function_call, dict) and isinstance(function_call.get("arguments"), str):
            function_call["arguments"] = self._unmasker((index, "function_call"), "json").feed(
                function_call["arguments"]
            )
        if choice.get("finish_reason"):
            self._flush_choice(index, delta)

    def _flush_choice(self, index: int, delta: dict[str, Any]) -> None:
        for key in [k for k in self._unmaskers if k[0] == index]:
            unmasker = self._unmaskers.pop(key)
            rest = unmasker.flush()
            self._retired_unresolved.update(dict.fromkeys(unmasker.unresolved))
            if not rest:
                continue
            self._retain_rest(key, rest)
            _append_rest(delta, key, rest)

    def finish(self) -> list[str]:
        """Payloads for anything still held back when the stream ends without a finish."""
        if self._done:
            return []
        self._done = True
        pending: dict[int, dict[str, Any]] = {}
        for key, unmasker in self._unmaskers.items():
            rest = unmasker.flush()
            if not rest or not isinstance(key[0], int):
                continue
            self._retain_rest(key, rest)
            _append_rest(pending.setdefault(key[0], {}), key, rest)
        if not pending:
            return []
        chunk = dict(self._template or {"object": "chat.completion.chunk"})
        chunk["choices"] = [
            {"index": index, "delta": delta, "finish_reason": None}
            for index, delta in sorted(pending.items())
        ]
        return [json.dumps(chunk, ensure_ascii=False)]


def _tool_call(tool_index: Any, held: dict[str, Any], arguments: str) -> dict[str, Any]:
    """One retained tool call in the ``message.tool_calls`` shape, with ``arguments``."""
    return {"index": tool_index, **held, "function": {**held["function"], "arguments": arguments}}


#: Unmasker key kind -> (tool-call field, its text field). Text fields sit on the delta itself.
_TOOL_FIELDS = {"tool": ("function", "arguments"), "custom": ("custom", "input")}


def _append_rest(delta: dict[str, Any], key: tuple[Any, ...], rest: str) -> None:
    """Append a flushed remainder to the field of ``delta`` its unmasker ``key`` restores."""
    kind = key[1]
    if kind in _TOOL_FIELDS:
        container, name = _TOOL_FIELDS[kind]
        calls = delta.setdefault("tool_calls", [])
        target = next(
            (
                c
                for position, c in enumerate(calls)
                if isinstance(c, dict) and c.get("index", position) == key[2]
            ),
            None,
        )
        if target is None:
            target = {"index": key[2]}
            calls.append(target)
        holder = target.setdefault(container, {})
    elif kind == "function_call":
        holder, name = delta.setdefault("function_call", {}), "arguments"
    else:
        holder, name = delta, kind
    if name == "content" and isinstance(holder.get(name), list):
        parts = holder[name]
        if parts:
            parts[-1]["text"] += rest
        else:
            parts.append({"type": "text", "text": rest})
    else:
        holder[name] = (holder.get(name) or "") + rest
