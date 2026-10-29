"""Re-identification of upstream answers (non-streaming) and its building blocks.

- :func:`restore_text` restores placeholders and also returns the **spans** of the restored
  values, so the gateway can pre-seed the detection cache with the assistant answer: the
  client sends it back as history next turn, and it then needs no detection.
- :class:`JsonEscapingSession` restores into a JSON document (tool-call ``arguments``): each
  original value is JSON-string-escaped, so a value with a quote or backslash can't break the
  arguments. It is duck-type compatible with :class:`~pii_guard.vault.StreamUnmasker`.
- :func:`restore_completion` rewrites a ``chat.completion`` body in place: message texts,
  tool-call ``function.arguments`` and the legacy ``function_call.arguments`` (JSON-escaped),
  and custom tool ``custom.input`` (freeform text, restored as is; LAB-1354).
- :class:`ToolInputSession` restores custom tool input. It and :class:`JsonEscapingSession`
  also restore a **regex-escaped** placeholder (``\\[\\[EMAIL_x\\]\\]``, which a model
  writes in a ``sed``/``perl``/``python`` pattern) to the value as a regex literal
  (:func:`regex_literal`), so the command still matches the file (LAB-1481). In JSON arguments
  the escape is JSON-encoded too (``\\\\[\\\\[``). Only tool-call fields get this; message
  text keeps an escaped placeholder as written.
- In a shell command in JSON arguments (a top-level ``command``/``cmd``), a value restored in a
  single-quoted string or a ``sed`` ``s`` replacement is escaped for it (LAB-1483,
  :mod:`~pii_guard.gateway.shell_context`). Everywhere else a value is byte-exact.

Unknown placeholders are left as is and counted (``unresolved``). Every restored value is
charged to one :class:`~pii_guard.vault.RestoreBudget` per response, so a response restores at
most ``PII_GUARD_UNMASK_MAX_RESTORED_CHARS`` characters of original values (LAB-1350).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from pii_guard.gateway.shell_context import ArgumentsContext, shell_escape
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, RestoreBudget, UnmaskResult, VaultSession
from pii_guard.vault.inflection import following_suffix
from pii_guard.vault.placeholders import MAX_PLACEHOLDER_LENGTH

__all__ = [
    "JsonEscapingSession",
    "RestoreReport",
    "ToolInputSession",
    "regex_literal",
    "restore_completion",
    "restore_text",
    "restore_tool_input",
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


# --- regex-escaped placeholders in tool input (LAB-1481) -----------------------------------

#: Escaped with a backslash: literal in every regex flavour (BRE, ERE, PCRE, Python, JS).
_BACKSLASHED = frozenset("\\.*[]^$/")
#: Bracketed instead: ``\+``, ``\?``, ``\(``, ``\{``, ``\|`` are *operators* in GNU sed's BRE,
#: and Perl interpolates ``@name`` in a pattern, while ``[+]`` and ``[@]`` are literals everywhere.
_BRACKETED = frozenset("+?(){}|@")

#: Placeholder body, as in :data:`~pii_guard.vault.PLACEHOLDER_RE`.
_BODY = r"([A-Z][A-Z0-9_]*)_([0-9a-f]{4,})"
#: A possible body still growing (loose, like the vault's prefix check): only for holding back.
_BODY_PREFIX_RE = re.compile(r"[A-Z][A-Z0-9_a-f]*")


def regex_literal(value: str) -> str:
    """``value`` as a regex matching exactly it, in BRE, ERE, Perl, PCRE, Python and JS alike."""
    return "".join(
        "\\" + char if char in _BACKSLASHED else f"[{char}]" if char in _BRACKETED else char
        for char in value
    )


class _EscapeForm:
    """One escape depth: ``\\[\\[TYPE_id\\]\\]`` written with ``escape`` before each bracket.

    The opening brackets must both be escaped; a closing one may be escaped or not (an
    unescaped ``]`` is a literal in a regex too). An escape right after another backslash is
    not one (``\\\\[`` is an escaped backslash and a bracket), so it is not matched.
    """

    def __init__(self, escape: str) -> None:
        e = re.escape(escape)
        self.escape = escape
        self.pattern = re.compile(rf"(?<!\\){e}\[{e}\[{_BODY}(?:(?:{e})?\]){{2}}")
        self.opening = f"{escape}[{escape}["
        closes = (f"{escape}]", "]")
        self.closings = tuple(a + b for a in closes for b in closes)
        self.longest = MAX_PLACEHOLDER_LENGTH + 4 * len(escape)

    def is_prefix(self, text: str) -> bool:
        """True if ``text`` is an incomplete escaped placeholder that more input could complete."""
        if len(text) >= self.longest:
            return False
        if len(text) <= len(self.opening):
            return self.opening.startswith(text)
        if not text.startswith(self.opening):
            return False
        body = _BODY_PREFIX_RE.match(text, len(self.opening))
        if body is None:
            return False
        tail = text[body.end() :]
        return any(len(tail) < len(c) and c.startswith(tail) for c in self.closings)

    def hold_from(self, buffer: str) -> int:
        """Index of a trailing possible escaped placeholder (``len(buffer)`` if there is none)."""
        for index in range(max(0, len(buffer) - self.longest), len(buffer)):
            if (
                buffer[index] == "\\"
                and (index == 0 or buffer[index - 1] != "\\")
                and self.is_prefix(buffer[index:])
            ):
                return index
        return len(buffer)


#: In freeform tool input (a shell command): ``\\[\\[``.
_RAW_ESCAPE = _EscapeForm("\\")
#: In JSON arguments, the same escape JSON-encoded: ``\\\\[\\\\[`` (decodes to ``\\[\\[``).
_JSON_ESCAPE = _EscapeForm("\\\\")


def _restore_escaped(
    session: VaultSession,
    text: str,
    budget: RestoreBudget,
    form: _EscapeForm,
    encode: Callable[[str], str],
    rest: Callable[[str], UnmaskResult],
    observe: Callable[[str], None] | None = None,
) -> UnmaskResult:
    """Escaped placeholders in ``text`` restored to ``encode(regex_literal(value))``; the text
    between them goes through ``rest`` (the plain restore). Unknown ones stay as written.
    ``observe`` sees each escaped placeholder as written, after it is encoded (the text around
    it goes through ``rest``), so a context tracker reads the whole text in order."""
    unresolved: dict[str, None] = {}
    parts: list[str] = []
    cursor = 0
    for match in form.pattern.finditer(text):
        plain = rest(text[cursor : match.start()])
        parts.append(plain.text)
        unresolved.update(dict.fromkeys(plain.unresolved))
        cursor = match.end()
        placeholder = f"[[{match.group(1)}_{match.group(2)}]]"
        result = session.unmask_with_report(placeholder, budget=budget)
        if result.unresolved:
            unresolved[placeholder] = None
            parts.append(match.group(0))
        else:
            parts.append(encode(regex_literal(result.text)))
        if observe is not None:
            observe(match.group(0))
    plain = rest(text[cursor:])
    parts.append(plain.text)
    unresolved.update(dict.fromkeys(plain.unresolved))
    return UnmaskResult("".join(parts), tuple(unresolved))


def _json_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)[1:-1]


class ToolInputSession:
    """Restores freeform tool input (custom tool ``input``): plain placeholders as the session
    does, and regex-escaped ones as regex literals. Duck-type compatible with
    :class:`~pii_guard.vault.StreamUnmasker` (``hold_from`` holds back a split escape)."""

    def __init__(self, session: VaultSession, budget: RestoreBudget | None = None) -> None:
        self._session = session
        self._budget = budget

    def restore_budget(self) -> RestoreBudget:
        return self._budget or self._session.restore_budget()

    def unmask_with_report(self, text: str, *, budget: RestoreBudget | None = None) -> UnmaskResult:
        budget = budget or self.restore_budget()
        return _restore_escaped(
            self._session,
            text,
            budget,
            _RAW_ESCAPE,
            lambda literal: literal,
            lambda part: self._session.unmask_with_report(part, budget=budget),
        )

    @staticmethod
    def hold_from(buffer: str) -> int:
        return _RAW_ESCAPE.hold_from(buffer)


class JsonEscapingSession:
    """Restores placeholders as JSON-string-escaped values (for tool-call ``arguments``).

    Inside a shell command string of the arguments (a top-level ``command``/``cmd``), a value
    in a single-quoted string or a ``sed`` ``s`` replacement is escaped for it first
    (:mod:`~pii_guard.gateway.shell_context`, LAB-1483). The instance reads one arguments text
    in order, so use one per text (or per streamed arguments)."""

    def __init__(self, session: VaultSession, budget: RestoreBudget | None = None) -> None:
        self._session = session
        self._budget = budget
        self._context = ArgumentsContext()

    def restore_budget(self) -> RestoreBudget:
        return self._budget or self._session.restore_budget()

    def unmask_with_report(self, text: str, *, budget: RestoreBudget | None = None) -> UnmaskResult:
        budget = budget or self.restore_budget()
        return _restore_escaped(
            self._session,
            text,
            budget,
            _JSON_ESCAPE,
            lambda literal: _json_string(
                shell_escape(literal, self._context.context(), regex=True)
            ),
            lambda part: self._plain(part, budget),
            self._context.feed,
        )

    @staticmethod
    def hold_from(buffer: str) -> int:
        return _JSON_ESCAPE.hold_from(buffer)

    def _plain(self, text: str, budget: RestoreBudget) -> UnmaskResult:
        unresolved: dict[str, None] = {}
        parts: list[str] = []
        cursor = 0
        for item in _restorations(self._session, text, budget):
            self._context.feed(text[cursor : item.start])
            parts.append(text[cursor : item.start])
            cursor = item.end
            if item.value is None:
                unresolved[item.placeholder] = None
                parts.append(item.placeholder)
            else:
                value = shell_escape(item.value + item.suffix, self._context.context())
                parts.append(_json_string(value))
            self._context.feed(text[item.start : item.end])
        self._context.feed(text[cursor:])
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


def restore_tool_input(
    session: VaultSession,
    text: str,
    report: RestoreReport,
    budget: RestoreBudget | None = None,
) -> str:
    """Freeform tool input (custom tool ``input``), with regex-escaped placeholders too."""
    result = ToolInputSession(session, budget).unmask_with_report(text)
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
            if not isinstance(call, dict):
                continue
            function = call.get("function")
            if isinstance(function, dict) and isinstance(function.get("arguments"), str):
                function["arguments"] = restore_arguments(
                    session, function["arguments"], report, budget
                )
            custom = call.get("custom")
            if isinstance(custom, dict) and isinstance(custom.get("input"), str):
                # Custom tool input is freeform text, not JSON: restored without JSON escaping.
                custom["input"] = restore_tool_input(session, custom["input"], report, budget)
        function_call = message.get("function_call")
        if isinstance(function_call, dict) and isinstance(function_call.get("arguments"), str):
            function_call["arguments"] = restore_arguments(
                session, function_call["arguments"], report, budget
            )
    return report
