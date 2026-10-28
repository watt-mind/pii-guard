"""Re-identification of upstream answers (non-streaming) and its building blocks.

- :func:`restore_text` restores placeholders and also returns the **spans** of the restored
  values, so the gateway can pre-seed the detection cache with the assistant answer: the
  client sends it back as history next turn, and it then needs no detection.
- :class:`JsonEscapingSession` restores into a JSON document (tool-call ``arguments``): each
  original value is JSON-string-escaped, so a value with a quote or backslash can't break the
  arguments. It is duck-type compatible with :class:`~pii_guard.vault.StreamUnmasker`.
- :func:`restore_completion` rewrites a ``chat.completion`` body in place.

Unknown placeholders are left as is and counted (``unresolved``). Every restored value is
charged to one :class:`~pii_guard.vault.RestoreBudget` per response, so a response restores at
most ``PII_GUARD_UNMASK_MAX_RESTORED_CHARS`` characters of original values (LAB-1350).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, RestoreBudget, UnmaskResult, VaultSession
from pii_guard.vault.inflection import following_suffix

__all__ = [
    "JsonEscapingSession",
    "RestoreReport",
    "restore_completion",
    "restore_text",
]

#: String fields of an assistant message / delta that may carry placeholders.
MESSAGE_TEXT_FIELDS = ("content", "refusal", "reasoning_content", "reasoning")

RESTORED_DETECTOR = "gateway"


@dataclass(frozen=True)
class _Restored:
    """One placeholder occurrence: ``text[start:end]`` becomes ``value + suffix``.

    ``value`` is ``None`` when the placeholder is unknown (then ``end`` is the placeholder's
    end and ``suffix`` is empty, so the text stays as is).
    """

    start: int
    end: int
    placeholder: str
    entity_type: str
    value: str | None
    suffix: str


def _restorations(session: VaultSession, text: str, budget: RestoreBudget) -> Iterator[_Restored]:
    """Each placeholder in ``text`` restored by the vault, together with its suffix.

    The suffix after a placeholder can change the restored stem (Hungarian
    ``[[PERSON_x]]nak`` -> ``Minta Máriának``), so the vault gets placeholder + suffix:
    the same restore and inflection path :meth:`VaultSession.unmask_with_report` takes for
    a whole text (``/v1/unmask``) and that the streaming unmasker uses.
    """
    cursor = 0
    for match in PLACEHOLDER_RE.finditer(text):
        if match.start() < cursor:  # pragma: no cover - a suffix never holds "[["
            continue
        placeholder = match.group(0)
        suffix = following_suffix(text, match.end())
        result = session.unmask_with_report(placeholder + suffix, budget=budget)
        if result.unresolved:
            cursor = match.end()
            yield _Restored(match.start(), cursor, placeholder, match.group(1), None, "")
            continue
        cursor = match.end() + len(suffix)
        restored = result.text
        if suffix and restored.endswith(suffix):
            restored, kept = restored[: -len(suffix)], suffix
        else:  # pragma: no cover - every matcher keeps the suffix as written
            kept = ""
        yield _Restored(match.start(), cursor, placeholder, match.group(1), restored, kept)


def restore_text(
    session: VaultSession, text: str, budget: RestoreBudget | None = None
) -> tuple[str, list[Span], tuple[str, ...]]:
    """``session.unmask(text)``, plus the spans of restored values and unresolved tokens.

    A span covers the restored value (the stem as inflected), not the suffix after it.
    ``budget``: the response's (default: a fresh one for this text alone).
    """
    if budget is None:
        budget = session.restore_budget()
    parts: list[str] = []
    spans: list[Span] = []
    unresolved: dict[str, None] = {}
    cursor = 0
    length = 0
    for item in _restorations(session, text, budget):
        before = text[cursor : item.start]
        parts.append(before)
        length += len(before)
        cursor = item.end
        if item.value is None:
            unresolved[item.placeholder] = None
            parts.append(item.placeholder)
            length += len(item.placeholder)
            continue
        value = item.value
        parts.append(value + item.suffix)
        if value.strip():
            spans.append(
                Span(
                    length,
                    length + len(value),
                    EntityType(item.entity_type),
                    value,
                    1.0,
                    RESTORED_DETECTOR,
                )
            )
        length += len(value) + len(item.suffix)
    parts.append(text[cursor:])
    return "".join(parts), spans, tuple(unresolved)


class JsonEscapingSession:
    """Restores placeholders as JSON-string-escaped values (for tool-call ``arguments``)."""

    def __init__(self, session: VaultSession, budget: RestoreBudget | None = None) -> None:
        self._session = session
        self._budget = budget

    def restore_budget(self) -> RestoreBudget:
        return self._budget or self._session.restore_budget()

    def unmask_with_report(self, text: str, *, budget: RestoreBudget | None = None) -> UnmaskResult:
        budget = budget or self.restore_budget()
        unresolved: dict[str, None] = {}
        parts: list[str] = []
        cursor = 0
        for item in _restorations(self._session, text, budget):
            parts.append(text[cursor : item.start])
            cursor = item.end
            if item.value is None:
                unresolved[item.placeholder] = None
                parts.append(item.placeholder)
            else:
                parts.append(json.dumps(item.value + item.suffix, ensure_ascii=False)[1:-1])
        parts.append(text[cursor:])
        return UnmaskResult("".join(parts), tuple(unresolved))


@dataclass
class RestoreReport:
    restored_spans: dict[int, tuple[str, list[Span]]] = field(default_factory=dict)
    unresolved: dict[str, None] = field(default_factory=dict)

    def __repr__(self) -> str:
        choices, unresolved = len(self.restored_spans), len(self.unresolved)
        return f"RestoreReport(choices={choices}, unresolved={unresolved})"


def restore_arguments(
    session: VaultSession,
    arguments: str,
    report: RestoreReport,
    budget: RestoreBudget | None = None,
) -> str:
    result = JsonEscapingSession(session, budget).unmask_with_report(arguments)
    report.unresolved.update(dict.fromkeys(result.unresolved))
    return result.text


def restore_completion(session: VaultSession, body: dict[str, Any]) -> RestoreReport:
    """Restore every choice's message in place. ``restored_spans`` maps choice index to the
    restored ``content`` string and its value spans (for the detection cache).

    One :class:`~pii_guard.vault.RestoreBudget` covers the whole body: past it, raises
    :class:`~pii_guard.vault.UnmaskOutputTooLargeError` (fail closed, LAB-1350)."""
    report = RestoreReport()
    budget = session.restore_budget()
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
                restored, spans, unresolved = restore_text(session, value, budget)
                message[name] = restored
                report.unresolved.update(dict.fromkeys(unresolved))
                if name == "content" and isinstance(index, int):
                    report.restored_spans[index] = (restored, spans)
            elif name == "content" and isinstance(value, list):
                for part in value:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        restored, _, unresolved = restore_text(session, part["text"], budget)
                        part["text"] = restored
                        report.unresolved.update(dict.fromkeys(unresolved))
        for call in message.get("tool_calls") or []:
            function = call.get("function") if isinstance(call, dict) else None
            if isinstance(function, dict) and isinstance(function.get("arguments"), str):
                function["arguments"] = restore_arguments(
                    session, function["arguments"], report, budget
                )
        function_call = message.get("function_call")
        if isinstance(function_call, dict) and isinstance(function_call.get("arguments"), str):
            function_call["arguments"] = restore_arguments(
                session, function_call["arguments"], report, budget
            )
    return report
