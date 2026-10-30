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
  single-quoted, double-quoted or unquoted part, or a ``sed`` ``s`` replacement, is escaped
  for it (LAB-1483, LAB-1564, :mod:`~pii_guard.gateway.shell_context`), so it cannot act as
  shell syntax. Custom tool input gets the same treatment inside quotes only (see
  :class:`ToolInputSession`). Everywhere else a value is byte-exact.
- Both adapters also restore a placeholder whose brackets are ``\\uXXXX``-escaped or
  ``%XX``-encoded (``\\u005b\\u005bEMAIL_x\\u005d\\u005d``, ``%5B%5BEMAIL_x%5D%5D``) to the
  plain value; an unknown one stays as written and counts unresolved (LAB-1564).

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

from pii_guard.gateway.shell_context import (
    BYTE_EXACT,
    ArgumentsContext,
    ShellContext,
    ShellText,
    shell_escape,
)
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, RestoreBudget, UnmaskResult, VaultSession
from pii_guard.vault.inflection import MAX_SUFFIX_LENGTH, following_suffix
from pii_guard.vault.placeholders import MAX_PLACEHOLDER_LENGTH, is_placeholder_prefix

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


def _restorations(
    session: VaultSession,
    text: str,
    budget: RestoreBudget,
    pattern: re.Pattern[str] = PLACEHOLDER_RE,
) -> Iterator[_Restored]:
    """Each placeholder in ``text`` restored by the vault, together with its suffix.

    The suffix after a placeholder can change the restored stem (Hungarian
    ``[[PERSON_x]]nak`` -> ``Minta Máriának``), so the vault gets placeholder + suffix:
    the same restore and inflection path :meth:`VaultSession.unmask_with_report` takes for
    a whole text (``/v1/unmask``) and that the streaming unmasker uses.

    ``pattern`` may also match encoded bracket forms (LAB-1564); the vault always sees the
    canonical ``[[TYPE_id]]`` built from the match's body groups, which for a plain match is
    the match itself.
    """
    cursor = 0
    for match in pattern.finditer(text):
        if match.start() < cursor:  # pragma: no cover - a suffix never holds "[["
            continue
        placeholder = f"[[{match.group(1)}_{match.group(2)}]]"
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

# --- encoded placeholder brackets in tool input (LAB-1564) ----------------------------------
#
# A model may also write a placeholder with its brackets encoded for the layer it is writing:
# ``\u005b\u005bEMAIL_x\u005d\u005d`` in JSON arguments, ``%5B%5BEMAIL_x%5D%5D`` in a URL or
# form field. Each bracket may be written literally or in either encoding. These are not regex
# escapes: they decode to the plain placeholder, so they restore to the plain value (through
# the same shell/JSON escaping as a plain placeholder), and an unknown one is left as written
# and counted unresolved under its canonical form.

_OPEN_TOKENS = ("[", "%5B", "%5b", "\\u005b", "\\u005B")
_CLOSE_TOKENS = ("]", "%5D", "%5d", "\\u005d", "\\u005D")
_ENCODED_RE = re.compile(rf"(?:\[|%5[bB]|\\u005[bB]){{2}}{_BODY}(?:\]|%5[dD]|\\u005[dD]){{2}}")
#: Longest encoded placeholder (every bracket as ``\uXXXX``), plus a suffix that may still grow.
_ENCODED_LONGEST = MAX_PLACEHOLDER_LENGTH + 4 * 5 + MAX_SUFFIX_LENGTH
_OPEN_SUFFIX_RE = re.compile(r"-?\w*")


def _take_token(text: str, pos: int, tokens: tuple[str, ...]) -> int | None:
    """End of the token at ``pos``, ``len(text)`` if only a partial token remains, else None."""
    for token in tokens:
        if text.startswith(token, pos):
            return pos + len(token)
    return len(text) if any(token.startswith(text[pos:]) for token in tokens) else None


def _encoded_prefix(text: str) -> bool:
    """True if ``text`` may still grow into an encoded placeholder (plus a growing suffix)."""
    if len(text) > _ENCODED_LONGEST:
        return False
    match = _ENCODED_RE.match(text)
    if match is not None:
        tail = text[match.end() :]
        return len(tail) <= MAX_SUFFIX_LENGTH and _OPEN_SUFFIX_RE.fullmatch(tail) is not None
    pos = 0
    for _ in range(2):
        taken = _take_token(text, pos, _OPEN_TOKENS)
        if taken is None:
            return False
        pos = taken
        if pos == len(text):
            return True
    body = _BODY_PREFIX_RE.match(text, pos)
    if body is None:
        return pos == len(text)
    pos = body.end()
    for _ in range(2):
        if pos == len(text):
            return True
        taken = _take_token(text, pos, _CLOSE_TOKENS)
        if taken is None:
            return False
        pos = taken
    return pos == len(text)


def _encoded_hold_from(buffer: str) -> int:
    """Index of a trailing possible encoded placeholder (``len(buffer)`` if there is none).

    A ``\\`` right after another ``\\`` is an escaped backslash, not a new ``\\u`` escape:
    holding from the second one alone would lose that pairing and make a split ``\\\\[``
    look like ``\\[``, so a run of backslashes is held from its first one."""
    for index in range(max(0, len(buffer) - _ENCODED_LONGEST), len(buffer)):
        if buffer[index] in "[%\\" and _encoded_prefix(buffer[index:]):
            start = index
            if buffer[index] == "\\":
                while start > 0 and buffer[start - 1] == "\\":
                    start -= 1
            return start
    return len(buffer)


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
    :class:`~pii_guard.vault.StreamUnmasker` (``hold_from`` holds back a split escape).

    Shell boundary (LAB-1564): freeform input may be a patch or program text, not a command,
    so shell escaping is applied only where the shell lexer knows the quoting — a placeholder
    inside a single- or double-quoted string (including a single-quoted ``sed`` script) is
    escaped for that quoting, exactly as in a JSON ``command`` argument, so a restored value
    cannot break out of the quotes or run a substitution. An unquoted placeholder, and
    anything the lexer does not model, stays byte-exact: with no quotes in the text there is
    no evidence it is a shell command at all. The instance reads one input in order, so use
    one per text (or per streamed input)."""

    def __init__(self, session: VaultSession, budget: RestoreBudget | None = None) -> None:
        self._session = session
        self._budget = budget
        self._shell = ShellText()

    def restore_budget(self) -> RestoreBudget:
        return self._budget or self._session.restore_budget()

    def _quoted_context(self) -> ShellContext:
        context = self._shell.context()
        return context if context.single_quoted or context.double_quoted else BYTE_EXACT

    def unmask_with_report(self, text: str, *, budget: RestoreBudget | None = None) -> UnmaskResult:
        budget = budget or self.restore_budget()
        return _restore_escaped(
            self._session,
            text,
            budget,
            _RAW_ESCAPE,
            lambda literal: shell_escape(literal, self._quoted_context(), regex=True),
            lambda part: self._plain(part, budget),
            self._shell.feed,
        )

    @staticmethod
    def hold_from(buffer: str) -> int:
        return min(_RAW_ESCAPE.hold_from(buffer), _encoded_hold_from(buffer))

    def _plain(self, text: str, budget: RestoreBudget) -> UnmaskResult:
        unresolved: dict[str, None] = {}
        parts: list[str] = []
        cursor = 0
        for item in _restorations(self._session, text, budget, _ENCODED_RE):
            self._shell.feed(text[cursor : item.start])
            parts.append(text[cursor : item.start])
            cursor = item.end
            if item.value is None:
                unresolved[item.placeholder] = None
                parts.append(text[item.start : item.end])
            else:
                parts.append(shell_escape(item.value + item.suffix, self._quoted_context()))
            self._shell.feed(text[item.start : item.end])
        self._shell.feed(text[cursor:])
        parts.append(text[cursor:])
        return UnmaskResult("".join(parts), tuple(unresolved))


class JsonEscapingSession:
    """Restores placeholders as JSON-string-escaped values (for tool-call ``arguments``).

    Inside a shell command string of the arguments (a top-level ``command``/``cmd``), a value
    in a single-quoted, double-quoted or unquoted part or a ``sed`` ``s`` replacement is
    escaped for it first (:mod:`~pii_guard.gateway.shell_context`, LAB-1483, LAB-1564). The
    instance reads one arguments text in order, so use one per text (or per streamed
    arguments)."""

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
        hold = min(_JSON_ESCAPE.hold_from(buffer), _encoded_hold_from(buffer))
        return min(hold, _quote_hold_from(buffer))

    def _number(self, text: str, item: _Restored) -> str | None:
        """The JSON literal to write for ``item`` in place of ``"value"``, or ``None``.

        Only a plain placeholder that is a whole JSON string value (its opening quote read
        just now, in this text, and its closing quote right after it) and that the session
        recorded as a masked JSON number of exactly this value (LAB-1361)."""
        if (
            item.value is None
            or item.suffix
            or text[item.start : item.end] != item.placeholder
            or text[item.end : item.end + 1] != '"'
            or text[item.start - 1 : item.start] != '"'
            or not self._context.at_value_start
        ):
            return None
        number = self._session.json_number(item.placeholder)
        if number is None or number[0] != item.value:
            return None
        return number[1]

    def _plain(self, text: str, budget: RestoreBudget) -> UnmaskResult:
        unresolved: dict[str, None] = {}
        parts: list[str] = []
        cursor = 0
        for item in _restorations(self._session, text, budget, _ENCODED_RE):
            self._context.feed(text[cursor : item.start])
            if item.start > cursor and (literal := self._number(text, item)) is not None:
                # ``"[[NATIONAL_ID_HU_TAX_x]]"`` -> ``<NUMBER>``: drop both quotes.
                parts.append(text[cursor : item.start - 1])
                parts.append(literal)
                self._context.feed(text[item.start : item.end + 1])
                cursor = item.end + 1
                continue
            parts.append(text[cursor : item.start])
            cursor = item.end
            if item.value is None:
                unresolved[item.placeholder] = None
                parts.append(text[item.start : item.end])
            else:
                value = shell_escape(item.value + item.suffix, self._context.context())
                parts.append(_json_string(value))
            self._context.feed(text[item.start : item.end])
        self._context.feed(text[cursor:])
        parts.append(text[cursor:])
        return UnmaskResult("".join(parts), tuple(unresolved))


def _quote_hold_from(buffer: str) -> int:
    """Hold back a trailing ``"`` followed by at most a placeholder (or a prefix of one): if it
    turns out to open a whole-value placeholder of a masked number, both quotes are dropped
    (LAB-1361), so the opening quote must not be emitted yet."""
    window = max(0, len(buffer) - MAX_PLACEHOLDER_LENGTH - 2)
    start = buffer.rfind('"', window)
    if start < 0:
        return len(buffer)
    tail = buffer[start + 1 :]
    if not tail:
        opening = buffer.rfind('"', window, start)
        if opening >= 0 and PLACEHOLDER_RE.fullmatch(buffer, opening + 1, start):
            return len(buffer)  # ``"[[TYPE_id]]"`` is complete: release it whole
        return start
    if is_placeholder_prefix(tail) or PLACEHOLDER_RE.fullmatch(tail):
        return start
    return len(buffer)


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
