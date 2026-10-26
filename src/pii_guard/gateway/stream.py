"""Streaming re-identification of ``chat.completion.chunk`` server-sent events.

Every text field of a delta (``content``, ``refusal``, reasoning) and every tool call's
``function.arguments`` gets its own :class:`~pii_guard.vault.StreamUnmasker`, keyed by choice
index (and tool-call index), so a placeholder split across chunks (``[[PERS`` + ``ON_7f3a]]``)
is held back until it is complete. When a choice finishes (``finish_reason``) or the stream
ends, whatever is still held back is flushed into that chunk (or a final synthetic chunk).
Concatenating the emitted deltas gives exactly ``session.unmask()`` of the upstream text.

Upstream ``error`` events are replaced by a generic error: they may quote the masked request.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from pii_guard.gateway.restore import MESSAGE_TEXT_FIELDS, JsonEscapingSession
from pii_guard.vault import StreamUnmasker, VaultSession

__all__ = ["SseRestorer", "iter_sse_data", "sse_event"]

DONE = "[DONE]"


async def iter_sse_data(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """The ``data`` payload of each server-sent event (multi-line data joined by ``\\n``)."""
    data: list[str] = []
    async for line in lines:
        if line == "":
            if data:
                yield "\n".join(data)
                data = []
            continue
        if line.startswith("data:"):
            value = line[5:]
            data.append(value[1:] if value.startswith(" ") else value)
        # Comments (":"), "event:", "id:" and "retry:" lines are not used by chat completions.
    if data:
        yield "\n".join(data)


def sse_event(data: str) -> bytes:
    return f"data: {data}\n\n".encode()


def error_event(code: str, message: str) -> str:
    return json.dumps({"error": {"code": code, "message": message, "type": code}})


class SseRestorer:
    """Rewrites SSE data payloads; feed them in order with :meth:`process`, then :meth:`finish`."""

    def __init__(self, session: VaultSession) -> None:
        self._session = session
        self._json_session = JsonEscapingSession(session)
        # (choice, field) or (choice, "tool", tool index) -> unmasker
        self._unmaskers: dict[tuple[Any, ...], StreamUnmasker] = {}
        self._retired_unresolved: dict[str, None] = {}
        self._masked_content: dict[int, list[str]] = {}
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
        """Per choice, the upstream (masked) ``content`` seen so far -- for cache seeding."""
        return {index: "".join(parts) for index, parts in self._masked_content.items()}

    def _unmasker(self, key: tuple[Any, ...], json_safe: bool = False) -> StreamUnmasker:
        unmasker = self._unmaskers.get(key)
        if unmasker is None:
            # StreamUnmasker only calls unmask_with_report(); the JSON adapter provides it.
            session: Any = self._json_session if json_safe else self._session
            unmasker = StreamUnmasker(session)
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
                    self._masked_content.setdefault(index, []).append(value)
                delta[name] = self._unmasker((index, name)).feed(value)
        for position_in_delta, call in enumerate(delta.get("tool_calls") or []):
            function = call.get("function") if isinstance(call, dict) else None
            if isinstance(function, dict) and isinstance(function.get("arguments"), str):
                key = (index, "tool", call.get("index", position_in_delta))
                function["arguments"] = self._unmasker(key, json_safe=True).feed(
                    function["arguments"]
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
            if key[1] == "tool":
                calls = delta.setdefault("tool_calls", [])
                target = next(
                    (c for c in calls if isinstance(c, dict) and c.get("index") == key[2]), None
                )
                if target is None:
                    target = {"index": key[2], "function": {"arguments": ""}}
                    calls.append(target)
                function = target.setdefault("function", {})
                function["arguments"] = (function.get("arguments") or "") + rest
            else:
                delta[key[1]] = (delta.get(key[1]) or "") + rest

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
            delta = pending.setdefault(key[0], {})
            if key[1] == "tool":
                delta.setdefault("tool_calls", []).append(
                    {"index": key[2], "function": {"arguments": rest}}
                )
            else:
                delta[key[1]] = rest
        if not pending:
            return []
        chunk = dict(self._template or {"object": "chat.completion.chunk"})
        chunk["choices"] = [
            {"index": index, "delta": delta, "finish_reason": None}
            for index, delta in sorted(pending.items())
        ]
        return [json.dumps(chunk, ensure_ascii=False)]
