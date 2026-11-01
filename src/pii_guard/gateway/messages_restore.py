"""Re-identification of Anthropic **Messages API** answers, whole and streamed.

- :func:`restore_message` rewrites a ``message`` object in place: every string the upstream
  wrote (``text`` and ``thinking`` blocks, ``stop_sequence``, ...) is restored. A ``tool_use``
  block's ``input`` (a JSON object) is serialised and restored like chat tool-call
  ``arguments`` (:class:`~pii_guard.gateway.restore.JsonEscapingSession`: JSON-string-escaped
  values, shell context for a ``command``, masked numbers back as numbers), then parsed again.
  ``signature`` and ``redacted_thinking.data`` are never touched.
- :class:`MessagesSseRestorer` rewrites the event stream. Each ``content_block_delta`` stream
  (``text_delta.text``, ``thinking_delta.thinking``, ``input_json_delta.partial_json``) gets its
  own :class:`~pii_guard.vault.StreamUnmasker`, keyed by block index, so a placeholder split
  across deltas is held back until it is complete. When the block's ``content_block_stop``
  arrives (or the stream ends), what is still held back is sent as one more delta right before
  it. ``signature_delta`` passes through. Every other event (``message_start``,
  ``content_block_start``, ``message_delta``, ...) is restored like a whole message. Upstream
  ``error`` events are replaced by a generic error: they may quote the masked request.

One :class:`~pii_guard.vault.RestoreBudget` covers a body or a stream (LAB-1350). Unknown
placeholders are left as is and counted (``unresolved``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pii_guard.gateway.opaque_ids import upstream_ids
from pii_guard.gateway.opaque_reasoning import OpaqueStream
from pii_guard.gateway.restore import (
    JsonEscapingSession,
    RestoreReport,
    restore_arguments,
    restore_text,
)
from pii_guard.gateway.stream import (
    MAX_MASKED_CONTENT_CHARS,
    MAX_UNMASKERS,
    StreamTooLargeError,
)
from pii_guard.vault import RestoreBudget, StreamUnmasker, VaultSession

__all__ = ["MessagesSseRestorer", "restore_message", "stream_error"]

#: Provider-signed or encrypted blobs, and image data: forwarded as is.
_OPAQUE = frozenset({"signature", "data"})
#: ``content_block_delta`` delta type -> (its text field, session kind).
_DELTAS = {
    "text_delta": ("text", "text"),
    "thinking_delta": ("thinking", "text"),
    "input_json_delta": ("partial_json", "json"),
}


def stream_error(message: str = "the response stream failed") -> dict[str, Any]:
    """An Anthropic ``error`` event (``api_error``): what the SDKs expect mid-stream."""
    return {"type": "error", "error": {"type": "api_error", "message": message}}


def _restore_input(
    session: VaultSession, value: dict[str, Any], report: RestoreReport, budget: RestoreBudget
) -> dict[str, Any]:
    """A ``tool_use.input`` object, restored as JSON arguments (fail closed if it breaks)."""
    restored = restore_arguments(session, json.dumps(value, ensure_ascii=False), report, budget)
    parsed = json.loads(restored)  # JsonEscapingSession keeps it valid JSON
    if not isinstance(parsed, dict):  # pragma: no cover - restoring never changes the shape
        raise ValueError("restored tool input is not an object")
    return parsed


def _restore_value(
    session: VaultSession,
    value: Any,
    report: RestoreReport,
    budget: RestoreBudget,
    key: str = "",
) -> Any:
    """Restore every string in ``value`` (a ``tool_use`` block's ``input`` as JSON)."""
    if isinstance(value, str):
        if key in _OPAQUE:
            return value
        restored, _, unresolved = restore_text(session, value, budget)
        report.unresolved.update(dict.fromkeys(unresolved))
        return restored
    if isinstance(value, list):
        return [_restore_value(session, item, report, budget) for item in value]
    if isinstance(value, dict):
        tool_use = value.get("type") == "tool_use" and isinstance(value.get("input"), dict)
        out = {}
        for k, v in value.items():
            if tool_use and k == "input":
                out[k] = _restore_input(session, v, report, budget)
            else:
                out[k] = _restore_value(session, v, report, budget, str(k))
        return out
    return value


def restore_message(session: VaultSession, body: dict[str, Any]) -> RestoreReport:
    """Restore a ``message`` object in place. ``restored_spans`` maps index 0 to the joined
    restored ``text`` blocks and their value spans, for the detection cache (the client sends
    the answer back as history).

    Past the response's restore budget, raises
    :class:`~pii_guard.vault.UnmaskOutputTooLargeError` (LAB-1350)."""
    report = RestoreReport()
    text = _message_text(body)
    if text is not None:
        restored, spans, _ = restore_text(session, text)
        report.restored_spans[0] = (restored, spans)
    restored_body = _restore_value(session, body, report, session.restore_budget())
    body.clear()
    body.update(restored_body)
    return report


def _message_text(body: dict[str, Any]) -> str | None:
    parts = [
        b["text"]
        for b in body.get("content") or []
        if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
    ]
    return "".join(parts) if parts else None


class MessagesSseRestorer:
    """Rewrites Messages API events; feed them in order with :meth:`process`, then
    :meth:`finish`. Each returns ``(event name, data)`` pairs to emit."""

    def __init__(
        self,
        session: VaultSession,
        on_ids: Callable[[list[str]], None] | None = None,
        *,
        opaque: OpaqueStream | None = None,
    ) -> None:
        """``on_ids`` receives the ids each event carries, raw (LAB-1469)."""
        self._opaque = opaque
        self._session = session
        self._on_ids = on_ids
        self._budget = session.restore_budget()
        self._unmaskers: dict[int, StreamUnmasker] = {}
        #: The last delta event of each block: the template for a flushed remainder.
        self._last_delta: dict[int, dict[str, Any]] = {}
        self._retired: dict[str, None] = {}
        self._report = RestoreReport()
        self._masked_text: dict[int, list[str]] = {}
        self._masked_len = 0
        self._masked_overflow = False
        self._done = False
        self.chunks = 0
        self.usage: dict[str, Any] = {}

    def __repr__(self) -> str:
        return f"MessagesSseRestorer(chunks={self.chunks}, open={len(self._unmaskers)})"

    @property
    def unresolved(self) -> tuple[str, ...]:
        seen = dict(self._retired)
        seen.update(self._report.unresolved)
        for unmasker in self._unmaskers.values():
            seen.update(dict.fromkeys(unmasker.unresolved))
        return tuple(seen)

    def masked_content(self) -> dict[int, str]:
        """The upstream (masked) answer text seen so far, joined over ``text`` blocks."""
        if not self._masked_text or self._masked_overflow:
            return {}
        return {0: "".join("".join(parts) for _, parts in sorted(self._masked_text.items()))}

    def _unmasker(self, index: int, kind: str) -> StreamUnmasker:
        unmasker = self._unmaskers.get(index)
        if unmasker is None:
            if len(self._unmaskers) >= MAX_UNMASKERS:
                raise StreamTooLargeError("upstream stream has too many open blocks")
            session: Any = (
                JsonEscapingSession(self._session, self._budget)
                if kind == "json"
                else self._session
            )
            unmasker = StreamUnmasker(session, self._budget)
            self._unmaskers[index] = unmasker
        return unmasker

    @staticmethod
    def _emit(data: dict[str, Any]) -> tuple[str | None, str]:
        name = data.get("type")
        return (name if isinstance(name, str) else None), json.dumps(data, ensure_ascii=False)

    def process(self, event: str | None, data: str) -> list[tuple[str | None, str]]:
        if self._done:
            return []
        try:
            parsed = json.loads(data)
        except ValueError:
            return [(event, data)]  # not ours to interpret; holds masked text only
        if not isinstance(parsed, dict):
            return [(event, data)]
        self.chunks += 1
        event_type = parsed.get("type") if isinstance(parsed.get("type"), str) else event
        if event_type == "error":
            return [*self._flush_open(), self._emit(stream_error("upstream stream error"))]
        if self._on_ids is not None:
            self._on_ids(upstream_ids(parsed))
        if self._opaque is not None:
            self._opaque.observe(parsed)
        self._scan_usage(event_type, parsed)
        index = parsed.get("index")
        delta = parsed.get("delta")
        if (
            event_type == "content_block_delta"
            and isinstance(index, int)
            and isinstance(delta, dict)
            and delta.get("type") in _DELTAS
        ):
            return [self._emit(self._delta(index, parsed, delta))]
        out: list[tuple[str | None, str]] = []
        if event_type == "content_block_stop" and isinstance(index, int):
            extra = self._flush(index)
            if extra is not None:
                out.append(self._emit(extra))
        elif event_type == "message_stop":
            out.extend(self._flush_open())
        restored = _restore_value(self._session, parsed, self._report, self._budget)
        out.append(self._emit(restored))
        return out

    def _scan_usage(self, event_type: object, parsed: dict[str, Any]) -> None:
        usage: object = None
        if event_type == "message_start" and isinstance(parsed.get("message"), dict):
            usage = parsed["message"].get("usage")
        elif event_type == "message_delta":
            usage = parsed.get("usage")
        if isinstance(usage, dict):
            self.usage.update(usage)

    def _delta(self, index: int, data: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
        field, kind = _DELTAS[delta["type"]]
        text = delta.get(field)
        if not isinstance(text, str):
            return _restore_value(self._session, data, self._report, self._budget)
        if field == "text" and not self._masked_overflow:
            self._masked_len += len(text)
            if self._masked_len > MAX_MASKED_CONTENT_CHARS:
                self._masked_text.clear()
                self._masked_overflow = True
            else:
                self._masked_text.setdefault(index, []).append(text)
        delta[field] = self._unmasker(index, kind).feed(text)
        self._last_delta[index] = {
            **data,
            "delta": {"type": delta["type"]},
        }
        return data

    def _flush(self, index: int) -> dict[str, Any] | None:
        """The held-back rest of one block's deltas, as a last delta event (or ``None``)."""
        unmasker = self._unmaskers.pop(index, None)
        template = self._last_delta.pop(index, None)
        if unmasker is None:
            return None
        rest = unmasker.flush()
        self._retired.update(dict.fromkeys(unmasker.unresolved))
        if not rest or template is None:
            return None
        delta_type = template["delta"]["type"]
        field, _ = _DELTAS[delta_type]
        return {**template, "delta": {"type": delta_type, field: rest}}

    def _flush_open(self) -> list[tuple[str | None, str]]:
        out = []
        for index in list(self._unmaskers):
            extra = self._flush(index)
            if extra is not None:
                out.append(self._emit(extra))
        return out

    def finish(self) -> list[tuple[str | None, str]]:
        """Delta events for anything still held back when the stream ends early."""
        if self._done:
            return []
        self._done = True
        return self._flush_open()
