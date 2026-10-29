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

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from pii_guard.gateway.opaque_ids import upstream_ids
from pii_guard.gateway.restore import MESSAGE_TEXT_FIELDS, JsonEscapingSession, ToolInputSession
from pii_guard.vault import StreamUnmasker, VaultSession

__all__ = ["SseRestorer", "iter_sse_data", "sse_event"]

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
    return f"data: {data}\n\n".encode()


def error_event(code: str, message: str) -> str:
    return json.dumps({"error": {"code": code, "message": message, "type": code}})


class SseRestorer:
    """Rewrites SSE data payloads; feed them in order with :meth:`process`, then :meth:`finish`."""

    def __init__(
        self, session: VaultSession, on_ids: Callable[[list[str]], None] | None = None
    ) -> None:
        """``on_ids`` receives the ids each chunk carries, raw (LAB-1469)."""
        self._session = session
        self._on_ids = on_ids
        # One budget for the whole response: every choice, field and tool call (LAB-1350).
        self._budget = session.restore_budget()
        self._tool_session = ToolInputSession(session, self._budget)
        # (choice, field) or (choice, "tool", tool index) -> unmasker
        self._unmaskers: dict[tuple[Any, ...], StreamUnmasker] = {}
        self._retired_unresolved: dict[str, None] = {}
        self._masked_content: dict[int, list[str]] = {}
        self._masked_overflow: set[int] = set()  # choices past the retention cap (LAB-1566)
        self._masked_len: dict[int, int] = {}
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

    def _unmasker(self, key: tuple[Any, ...], kind: str = "text") -> StreamUnmasker:
        unmasker = self._unmaskers.get(key)
        if unmasker is None and len(self._unmaskers) >= MAX_UNMASKERS:
            raise StreamTooLargeError("upstream stream has too many open fields")
        if unmasker is None:
            # StreamUnmasker calls unmask_with_report() (and hold_from()); the adapters have them.
            # A JSON adapter tracks where it is in the arguments, so one per stream (LAB-1483).
            session: Any = {
                "json": JsonEscapingSession(self._session, self._budget),
                "tool": self._tool_session,
            }.get(kind, self._session)
            unmasker = StreamUnmasker(session, self._budget)
            self._unmaskers[key] = unmasker
        return unmasker

    def process(self, data: str) -> list[str]:
        """The payloads to emit for one upstream payload."""
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
        if "error" in chunk:
            return [error_event("upstream_error", "upstream stream error")]
        if self._on_ids is not None:
            self._on_ids(upstream_ids(chunk))
        choices = chunk.get("choices")
        if isinstance(choices, list):
            for position, choice in enumerate(choices):
                if isinstance(choice, dict):
                    self._process_choice(choice, position)
            if self._template is None and choices:
                self._template = {
                    k: chunk[k] for k in ("id", "object", "created", "model") if k in chunk
                }
        self.chunks += 1
        return [json.dumps(chunk, ensure_ascii=False)]

    def _process_choice(self, choice: dict[str, Any], position: int) -> None:
        index = choice.get("index", position)
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            delta = {}
            if choice.get("finish_reason"):
                choice["delta"] = delta
        for name in MESSAGE_TEXT_FIELDS:
            value = delta.get(name)
            if isinstance(value, str):
                if name == "content" and isinstance(index, int):
                    self._retain_masked(index, value)
                delta[name] = self._unmasker((index, name)).feed(value)
        for position_in_delta, call in enumerate(delta.get("tool_calls") or []):
            if not isinstance(call, dict):
                continue
            tool_index = call.get("index", position_in_delta)
            function = call.get("function")
            if isinstance(function, dict) and isinstance(function.get("arguments"), str):
                function["arguments"] = self._unmasker((index, "tool", tool_index), "json").feed(
                    function["arguments"]
                )
            custom = call.get("custom")
            if isinstance(custom, dict) and isinstance(custom.get("input"), str):
                custom["input"] = self._unmasker((index, "custom", tool_index), "tool").feed(
                    custom["input"]
                )
        # The legacy (pre-tools) single function call: ``delta.function_call.arguments``.
        function_call = delta.get("function_call")
        if isinstance(function_call, dict) and isinstance(function_call.get("arguments"), str):
            function_call["arguments"] = self._unmasker((index, "function_call"), "json").feed(
                function_call["arguments"]
            )
        if choice.get("finish_reason") and isinstance(index, int):
            self._flush_choice(index, delta)

    def _flush_choice(self, index: int, delta: dict[str, Any]) -> None:
        for key in [k for k in self._unmaskers if k[0] == index]:
            unmasker = self._unmaskers.pop(key)
            rest = unmasker.flush()
            self._retired_unresolved.update(dict.fromkeys(unmasker.unresolved))
            if not rest:
                continue
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
            _append_rest(pending.setdefault(key[0], {}), key, rest)
        if not pending:
            return []
        chunk = dict(self._template or {"object": "chat.completion.chunk"})
        chunk["choices"] = [
            {"index": index, "delta": delta, "finish_reason": None}
            for index, delta in sorted(pending.items())
        ]
        return [json.dumps(chunk, ensure_ascii=False)]


#: Unmasker key kind -> (tool-call field, its text field). Text fields sit on the delta itself.
_TOOL_FIELDS = {"tool": ("function", "arguments"), "custom": ("custom", "input")}


def _append_rest(delta: dict[str, Any], key: tuple[Any, ...], rest: str) -> None:
    """Append a flushed remainder to the field of ``delta`` its unmasker ``key`` restores."""
    kind = key[1]
    if kind in _TOOL_FIELDS:
        container, name = _TOOL_FIELDS[kind]
        calls = delta.setdefault("tool_calls", [])
        target = next((c for c in calls if isinstance(c, dict) and c.get("index") == key[2]), None)
        if target is None:
            target = {"index": key[2]}
            calls.append(target)
        holder = target.setdefault(container, {})
    elif kind == "function_call":
        holder, name = delta.setdefault("function_call", {}), "arguments"
    else:
        holder, name = delta, kind
    holder[name] = (holder.get(name) or "") + rest
