"""Re-identification of upstream answers (non-streaming) and its building blocks.

- :func:`restore_text` restores placeholders and also returns the **spans** of the restored
  values, so the gateway can pre-seed the detection cache with the assistant answer: the
  client sends it back as history next turn, and it then needs no detection.
- :class:`JsonEscapingSession` restores into a JSON document (tool-call ``arguments``): each
  original value is JSON-string-escaped, so a value with a quote or backslash can't break the
  arguments. It is duck-type compatible with :class:`~pii_guard.vault.StreamUnmasker`.
- :func:`restore_completion` rewrites a ``chat.completion`` body in place.

Unknown placeholders are left as is and counted (``unresolved``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, UnmaskResult, VaultSession

__all__ = [
    "JsonEscapingSession",
    "RestoreReport",
    "restore_completion",
    "restore_text",
]

#: String fields of an assistant message / delta that may carry placeholders.
MESSAGE_TEXT_FIELDS = ("content", "refusal", "reasoning_content", "reasoning")

RESTORED_DETECTOR = "gateway"


def _lookup(session: VaultSession, placeholder: str) -> str | None:
    result = session.unmask_with_report(placeholder)
    return None if result.unresolved else result.text


def restore_text(session: VaultSession, text: str) -> tuple[str, list[Span], tuple[str, ...]]:
    """``session.unmask(text)``, plus the spans of restored values and unresolved tokens."""
    parts: list[str] = []
    spans: list[Span] = []
    unresolved: dict[str, None] = {}
    cursor = 0
    length = 0
    for match in PLACEHOLDER_RE.finditer(text):
        before = text[cursor : match.start()]
        parts.append(before)
        length += len(before)
        value = _lookup(session, match.group(0))
        if value is None:
            unresolved[match.group(0)] = None
            parts.append(match.group(0))
            length += len(match.group(0))
        else:
            parts.append(value)
            if value.strip():
                spans.append(
                    Span(
                        length,
                        length + len(value),
                        EntityType(match.group(1)),
                        value,
                        1.0,
                        RESTORED_DETECTOR,
                    )
                )
            length += len(value)
        cursor = match.end()
    parts.append(text[cursor:])
    return "".join(parts), spans, tuple(unresolved)


class JsonEscapingSession:
    """Restores placeholders as JSON-string-escaped values (for tool-call ``arguments``)."""

    def __init__(self, session: VaultSession) -> None:
        self._session = session

    def unmask_with_report(self, text: str) -> UnmaskResult:
        unresolved: dict[str, None] = {}

        def replace(match: Any) -> str:
            value = _lookup(self._session, match.group(0))
            if value is None:
                unresolved[match.group(0)] = None
                return match.group(0)
            return json.dumps(value, ensure_ascii=False)[1:-1]

        return UnmaskResult(PLACEHOLDER_RE.sub(replace, text), tuple(unresolved))


@dataclass
class RestoreReport:
    restored_spans: dict[int, tuple[str, list[Span]]] = field(default_factory=dict)
    unresolved: dict[str, None] = field(default_factory=dict)

    def __repr__(self) -> str:
        choices, unresolved = len(self.restored_spans), len(self.unresolved)
        return f"RestoreReport(choices={choices}, unresolved={unresolved})"


def restore_arguments(session: VaultSession, arguments: str, report: RestoreReport) -> str:
    result = JsonEscapingSession(session).unmask_with_report(arguments)
    report.unresolved.update(dict.fromkeys(result.unresolved))
    return result.text


def restore_completion(session: VaultSession, body: dict[str, Any]) -> RestoreReport:
    """Restore every choice's message in place. ``restored_spans`` maps choice index to the
    restored ``content`` string and its value spans (for the detection cache)."""
    report = RestoreReport()
    choices = body.get("choices")
    if not isinstance(choices, list):
        return report
    for position, choice in enumerate(choices):
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            continue
        index = choice.get("index", position)
        message = choice["message"]
        for name in MESSAGE_TEXT_FIELDS:
            value = message.get(name)
            if isinstance(value, str):
                restored, spans, unresolved = restore_text(session, value)
                message[name] = restored
                report.unresolved.update(dict.fromkeys(unresolved))
                if name == "content" and isinstance(index, int):
                    report.restored_spans[index] = (restored, spans)
            elif name == "content" and isinstance(value, list):
                for part in value:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        restored, _, unresolved = restore_text(session, part["text"])
                        part["text"] = restored
                        report.unresolved.update(dict.fromkeys(unresolved))
        for call in message.get("tool_calls") or []:
            function = call.get("function") if isinstance(call, dict) else None
            if isinstance(function, dict) and isinstance(function.get("arguments"), str):
                function["arguments"] = restore_arguments(session, function["arguments"], report)
        function_call = message.get("function_call")
        if isinstance(function_call, dict) and isinstance(function_call.get("arguments"), str):
            function_call["arguments"] = restore_arguments(
                session, function_call["arguments"], report
            )
    return report
