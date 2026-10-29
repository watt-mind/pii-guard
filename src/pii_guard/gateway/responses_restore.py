"""Re-identification of OpenAI **Responses API** answers, whole and streamed.

- :func:`restore_response` rewrites a ``response`` object in place: every string the upstream
  wrote (``output`` message text, refusals, reasoning summaries, the request fields it echoes
  back) is restored; ``arguments`` (JSON) are restored with JSON-string-escaped values
  (:class:`~pii_guard.gateway.restore.JsonEscapingSession`); custom tool ``input`` with
  :class:`~pii_guard.gateway.restore.ToolInputSession`. Both also restore a regex-escaped
  placeholder as a regex literal (LAB-1481). ``encrypted_content`` is never touched.
- :class:`ResponsesSseRestorer` rewrites the ``response.*`` server-sent events. Every delta
  stream (``response.output_text.delta``, ``response.refusal.delta``,
  ``response.function_call_arguments.delta``, ``response.reasoning_summary_text.delta``,
  ``response.reasoning_text.delta``, ``response.custom_tool_call_input.delta``) gets its own
  :class:`~pii_guard.vault.StreamUnmasker`, keyed by output index and content/summary index,
  so a placeholder split across deltas is held back until it is complete. When its ``.done``
  event arrives (or the stream ends), what is still held back is sent as one more delta event
  right before it. Every other event (``response.created``, ``response.output_item.done``,
  ``response.content_part.done``, ``response.completed``, ...) carries whole texts and is
  restored like a whole response. The concatenated deltas equal the restored ``.done`` text.

  ``sequence_number`` is renumbered so the extra delta events keep it strictly increasing.
  Upstream ``error`` events (and the message of ``response.failed``) are replaced by a generic
  error: they may quote the masked request.

Unknown placeholders are left as is and counted (``unresolved``).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from pii_guard.gateway.opaque_ids import upstream_ids
from pii_guard.gateway.restore import (
    JsonEscapingSession,
    RestoreReport,
    ToolInputSession,
    restore_arguments,
    restore_text,
    restore_tool_input,
)
from pii_guard.vault import RestoreBudget, StreamUnmasker, VaultSession

__all__ = [
    "DONE",
    "ResponsesSseRestorer",
    "iter_sse_events",
    "restore_response",
    "sse_message",
]

DONE = "[DONE]"
#: Provider-encrypted blobs: forwarded as is.
_OPAQUE = frozenset({"encrypted_content"})
#: JSON documents (tool-call arguments): restored with JSON-escaped values.
_JSON_FIELDS = frozenset({"arguments"})
#: Freeform tool input (custom tool calls): regex-escaped placeholders restored too.
_TOOL_FIELDS = frozenset({"input"})

#: delta event -> (stream name, index fields, session kind: text, json or tool). The ``.done``
#: event of the same stream has the same prefix.
_DELTAS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "response.output_text.delta": ("text", ("output_index", "content_index"), "text"),
    "response.refusal.delta": ("refusal", ("output_index", "content_index"), "text"),
    "response.reasoning_summary_text.delta": (
        "summary",
        ("output_index", "summary_index"),
        "text",
    ),
    "response.reasoning_text.delta": ("reasoning", ("output_index", "content_index"), "text"),
    "response.function_call_arguments.delta": ("arguments", ("output_index",), "json"),
    "response.custom_tool_call_input.delta": ("input", ("output_index",), "tool"),
}
_DONES = {name[: -len(".delta")] + ".done": name for name in _DELTAS}


def _restore_value(
    session: VaultSession,
    value: Any,
    report: RestoreReport,
    budget: RestoreBudget,
    key: str = "",
) -> Any:
    if isinstance(value, str):
        if key in _OPAQUE:
            return value
        if key in _JSON_FIELDS:
            return restore_arguments(session, value, report, budget)
        if key in _TOOL_FIELDS:
            return restore_tool_input(session, value, report, budget)
        restored, _, unresolved = restore_text(session, value, budget)
        report.unresolved.update(dict.fromkeys(unresolved))
        return restored
    if isinstance(value, list):
        return [_restore_value(session, item, report, budget, key) for item in value]
    if isinstance(value, dict):
        # Keys are the upstream's own field names; values are restored.
        return {k: _restore_value(session, v, report, budget, str(k)) for k, v in value.items()}
    return value


def restore_response(session: VaultSession, body: dict[str, Any]) -> RestoreReport:
    """Restore a ``response`` object in place. ``restored_spans`` maps each ``output`` index
    holding a message to its restored text (joined ``output_text`` parts) and value spans, for
    the detection cache (the client sends it back as history).

    One :class:`~pii_guard.vault.RestoreBudget` covers the body (the cache copy has its own):
    past it, raises :class:`~pii_guard.vault.UnmaskOutputTooLargeError` (LAB-1350)."""
    report = RestoreReport()
    for index, item in enumerate(body.get("output") or []):
        text = _message_text(item)
        if text is not None:
            restored, spans, _ = restore_text(session, text)
            report.restored_spans[index] = (restored, spans)
    restored_body = _restore_value(session, body, report, session.restore_budget())
    body.clear()
    body.update(restored_body)
    return report


def _message_text(item: object) -> str | None:
    """The ``output_text`` of a message item, joined (a single part: exactly its text)."""
    if not isinstance(item, dict) or item.get("type") != "message":
        return None
    parts = [
        p["text"]
        for p in item.get("content") or []
        if isinstance(p, dict) and p.get("type") == "output_text" and isinstance(p.get("text"), str)
    ]
    return "".join(parts) if parts else None


# --- server-sent events ------------------------------------------------------------------


async def iter_sse_events(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str | None, str]]:
    """``(event name, data)`` of each server-sent event (multi-line data joined by ``\\n``)."""
    event: str | None = None
    data: list[str] = []
    async for line in lines:
        if line == "":
            if data:
                yield event, "\n".join(data)
            event, data = None, []
            continue
        if line.startswith("data:"):
            value = line[5:]
            data.append(value[1:] if value.startswith(" ") else value)
        elif line.startswith("event:"):
            event = line[6:].strip() or None
        # Comments (":"), "id:" and "retry:" lines are not used by the Responses API.
    if data:
        yield event, "\n".join(data)


def sse_message(data: str, event: str | None = None) -> bytes:
    head = f"event: {event}\n" if event else ""
    return f"{head}data: {data}\n\n".encode()


def _error(code: str, message: str) -> dict[str, Any]:
    return {"type": "error", "code": code, "message": message, "param": None}


class ResponsesSseRestorer:
    """Rewrites ``response.*`` events; feed them in order with :meth:`process`, then
    :meth:`finish`. Each returns ``(event name, data)`` pairs to emit."""

    def __init__(
        self, session: VaultSession, on_ids: Callable[[list[str]], None] | None = None
    ) -> None:
        """``on_ids`` receives the ids each event carries, raw (LAB-1469)."""
        self._session = session
        self._on_ids = on_ids
        # One budget for every event of the stream (LAB-1350).
        self._budget = session.restore_budget()
        self._tool_session = ToolInputSession(session, self._budget)
        self._unmaskers: dict[tuple[Any, ...], StreamUnmasker] = {}
        #: The last delta event of each stream: the template for a flushed remainder.
        self._last_delta: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._retired: dict[str, None] = {}
        self._report = RestoreReport()
        self._masked_text: dict[int, list[str]] = {}
        self._sequence: int | None = None
        self._done = False
        self.chunks = 0

    def __repr__(self) -> str:
        return f"ResponsesSseRestorer(chunks={self.chunks}, open={len(self._unmaskers)})"

    @property
    def unresolved(self) -> tuple[str, ...]:
        seen = dict(self._retired)
        seen.update(self._report.unresolved)
        for unmasker in self._unmaskers.values():
            seen.update(dict.fromkeys(unmasker.unresolved))
        return tuple(seen)

    def masked_content(self) -> dict[int, str]:
        """Per output index, the upstream (masked) ``output_text`` seen so far."""
        return {index: "".join(parts) for index, parts in self._masked_text.items()}

    def _unmasker(self, key: tuple[Any, ...], kind: str) -> StreamUnmasker:
        unmasker = self._unmaskers.get(key)
        if unmasker is None:
            # A JSON adapter tracks where it is in the arguments, so one per stream (LAB-1483).
            session: Any = {
                "json": JsonEscapingSession(self._session, self._budget),
                "tool": self._tool_session,
            }.get(kind, self._session)
            unmasker = StreamUnmasker(session, self._budget)
            self._unmaskers[key] = unmasker
        return unmasker

    def _emit(self, data: dict[str, Any]) -> tuple[str | None, str]:
        sequence = data.get("sequence_number")
        if isinstance(sequence, int) and not isinstance(sequence, bool):
            if self._sequence is None:
                self._sequence = sequence
            data["sequence_number"] = self._sequence
            self._sequence += 1
        name = data.get("type")
        return (name if isinstance(name, str) else None), json.dumps(data, ensure_ascii=False)

    @staticmethod
    def _key(event_type: str, data: dict[str, Any]) -> tuple[Any, ...]:
        stream, fields, _ = _DELTAS[event_type]
        return (stream, *(data.get(f) for f in fields))

    def process(self, event: str | None, data: str) -> list[tuple[str | None, str]]:
        if data.strip() == DONE:
            return [*self.finish(), (None, DONE)]
        try:
            parsed = json.loads(data)
        except ValueError:
            return [(event, data)]  # not ours to interpret; holds masked text only
        if not isinstance(parsed, dict):
            return [(event, data)]
        self.chunks += 1
        event_type = parsed.get("type") if isinstance(parsed.get("type"), str) else event
        if event_type == "error" or (event_type is None and "error" in parsed):
            return [self._emit(_error("upstream_error", "upstream stream error"))]
        if self._on_ids is not None:
            self._on_ids(upstream_ids(parsed))
        if event_type in _DELTAS:
            return [self._emit(self._delta(event_type, parsed))]
        out: list[tuple[str | None, str]] = []
        if event_type in _DONES:
            extra = self._flush(self._key(_DONES[event_type], parsed))
            if extra is not None:
                out.append(self._emit(extra))
        restored = _restore_value(self._session, parsed, self._report, self._budget)
        if event_type == "response.failed":
            response = restored.get("response")
            if isinstance(response, dict) and isinstance(response.get("error"), dict):
                response["error"] = {"code": "upstream_error", "message": "upstream failed"}
        out.append(self._emit(restored))
        return out

    def _delta(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        delta = data.get("delta")
        if not isinstance(delta, str):
            return data
        key = self._key(event_type, data)
        _, _, kind = _DELTAS[event_type]
        if event_type == "response.output_text.delta":
            index = data.get("output_index")
            if isinstance(index, int):
                self._masked_text.setdefault(index, []).append(delta)
        data["delta"] = self._unmasker(key, kind).feed(delta)
        self._last_delta[key] = {k: v for k, v in data.items() if k not in ("delta", "logprobs")}
        return data

    def _flush(self, key: tuple[Any, ...]) -> dict[str, Any] | None:
        """The held-back rest of one delta stream, as a last delta event (or ``None``)."""
        unmasker = self._unmaskers.pop(key, None)
        template = self._last_delta.pop(key, None)
        if unmasker is None:
            return None
        rest = unmasker.flush()
        self._retired.update(dict.fromkeys(unmasker.unresolved))
        if not rest or template is None:
            return None
        return {**template, "delta": rest}

    def finish(self) -> list[tuple[str | None, str]]:
        """Delta events for anything still held back when the stream ends early."""
        if self._done:
            return []
        self._done = True
        out = []
        for key in list(self._unmaskers):
            extra = self._flush(key)
            if extra is not None:
                out.append(self._emit(extra))
        return out
