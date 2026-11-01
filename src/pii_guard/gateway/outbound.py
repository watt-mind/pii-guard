"""The outbound re-check: no value the session knows leaves the guard real (LAB-1500).

After masking, and before anything goes upstream, the gateway reads the masked request again
with the request walker it masked it with (:func:`~pii_guard.gateway.request.collect_texts`,
:func:`~pii_guard.gateway.responses_request.collect_response_texts`): every message, tool
definition, tool-call argument, tool result, reasoning text, metadata value and image
transcript and summary, as they will be sent. Each text is searched for the values of the
request's vault session, with the vault's own occurrence patterns
(:meth:`~pii_guard.vault.VaultSession.unmasked`): the values detected in this request and in
earlier ones, and the operator's pre-loaded known values. Placeholders never count.

A value found there fails the request closed (ADR 0006): ``422 outbound_check_failed``, the
entity types and counts only, nothing forwarded, and the response says
``X-PII-Guard-Outbound-Check: blocked``. A request that passes says ``passed``.

What counts (the short-value policy). Every value the session holds is searched for, but an
occurrence blocks only if it can't be a common short token:

- a value the operator pre-loaded (``known``, at least 3 characters by its own rule) always
  blocks: the operator said it is sensitive;
- a value with no letter (a number) needs :data:`MIN_DIGITS` digits, the length from which the
  gateway detects a bare number at all (LAB-1348);
- a value only the NER found needs :data:`MIN_MODEL_CHARS` letters and digits: the NER reads
  some short words as names (``pi``, ``len``, ``89``, LAB-1482);
- any other value (found by the rules or the LLM) needs :data:`MIN_CHARS`, as a known value.

A shorter occurrence is counted (``short``) but does not block. The sweep has already masked
every occurrence of every value in these texts, so a short one left over is one the sweep was
meant to leave (or a token so short that matching it says little); refusing on it would turn
the guard's own noise into refused requests.

Exemptions mirror the masking ones, so the check never refuses what masking rightly kept: an
identifier the upstream issued in this session (LAB-1469) and, in an identifier, a declared tool
name of a word-like type (LAB-1324). A tool name that is also a pre-loaded known value still
blocks, as it fails closed at masking.

**Beyond the walker's slots (LAB-1563).** Re-reading with the same walker cannot see a field
the walker never collected, so :func:`check_outbound` also scans the serialized masked body
(``json.dumps``) as one text, with the same session search, :func:`blocks` thresholds and
exemptions (a kept tool-name value and an issued id — the JSON string enclosing the
occurrence — do not block). Counts merge by taking the larger count per entity type, so a
value both scans see is not counted twice.

**Through JSON escapes (LAB-1755).** A tool output that is not decodable JSON (a prefix, a
trailing note, plain text with ``\\u00f3``) can still carry a value JSON-escaped, which the
upstream model reads as the value. Every text with a backslash is therefore also searched in
its JSON-unescaped views (``\\uXXXX`` including surrogate pairs, ``\\"``, ``\\\\``,
``\\/``, ``\\n`` ...; repeated for nested escaping), with the same thresholds. Unescaping
only reveals text the upstream would read: ordinary backslashes (Windows paths, regexes)
do not create a value that is not there.

Cost: one fold per text (the session's memo serves the texts masking left unchanged) and one
substring search per session value over all of them, plus one serialization and one search
over it; a value is matched text by text only when it can occur at all.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pii_guard.gateway.request import CollectedTexts, TextSlot
from pii_guard.gateway.tool_names import EXEMPT_TYPES
from pii_guard.types import PiiGuardError
from pii_guard.vault import Unmasked, VaultSession, normalize_value

__all__ = [
    "MIN_CHARS",
    "MIN_DIGITS",
    "MIN_MODEL_CHARS",
    "OUTBOUND_CHECK_HEADER",
    "OutboundCheck",
    "OutboundCheckFailedError",
    "blocks",
    "check_outbound",
    "check_slots",
]

OUTBOUND_CHECK_HEADER = "X-PII-Guard-Outbound-Check"

#: Letters and digits a detected value needs to block a request (as a known value's minimum).
MIN_CHARS = 3
#: The same for a value only the NER found.
MIN_MODEL_CHARS = 4
#: Digits a value with no letter needs to block (the gateway's bare-number threshold).
MIN_DIGITS = 6


class OutboundCheckFailedError(PiiGuardError):
    """A value the session knows was still in the masked request. Nothing was sent."""

    code = "outbound_check_failed"
    status_code = 422

    def __init__(self, counts: Mapping[str, int], *, unreadable: bool = False) -> None:
        self.counts = dict(sorted(counts.items()))
        if unreadable:
            message = "the masked request could not be read again, so it was not forwarded"
        else:
            listed = ", ".join(f"{t} ({n})" for t, n in self.counts.items())
            message = (
                "the masked request still contains values this session knows, so it was not "
                f"forwarded: {listed}"
            )
        super().__init__(message)

    @property
    def headers(self) -> dict[str, str]:
        return {OUTBOUND_CHECK_HEADER: "blocked"}


@dataclass
class OutboundCheck:
    """The result of one re-check: counts and time only."""

    texts: int = 0
    #: Occurrences that block, by entity type.
    hits: Counter[str] = field(default_factory=Counter)
    #: Occurrences too short to block (see the module docstring).
    short: int = 0
    ms: float = 0.0

    @property
    def result(self) -> str:
        return "blocked" if self.hits else "passed"

    def event(self) -> dict[str, Any]:
        """The traffic event's ``outbound_check`` field."""
        return {
            "result": self.result,
            "texts": self.texts,
            "hits": dict(sorted(self.hits.items())),
            "short": self.short,
            "ms": round(self.ms, 3),
        }


_ESCAPE_RE = re.compile(
    r"\\u([dD][89abAB][0-9a-fA-F]{2})\\u([dD][c-fC-F][0-9a-fA-F]{2})"
    r"|\\u([0-9a-fA-F]{4})|\\([\"\\/bfnrt])"
)
_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
#: Nested escaping levels searched (a JSON text in a JSON string in a tool output ...).
MAX_UNESCAPE_LAYERS = 5


def _unescape_once(match: re.Match[str]) -> str:
    high, low, code, simple = match.groups()
    if high is not None:
        return chr(0x10000 + ((int(high, 16) - 0xD800) << 10) + (int(low, 16) - 0xDC00))
    if code is not None:
        point = int(code, 16)
        # A lone surrogate is kept escaped: it is no readable character.
        return match.group(0) if 0xD800 <= point <= 0xDFFF else chr(point)
    return _SIMPLE_ESCAPES[simple]


def unescaped_views(text: str) -> list[str]:
    """``text`` with its JSON escapes decoded, once per nesting level (none: no escapes)."""
    views: list[str] = []
    while "\\" in text and len(views) < MAX_UNESCAPE_LAYERS:
        view = _ESCAPE_RE.sub(_unescape_once, text)
        if view == text:
            break
        views.append(view)
        text = view
    return views


def blocks(occurrence: Unmasked) -> bool:
    """Whether an occurrence left in the request refuses it: the short-value policy."""
    if occurrence.known:
        return True
    if occurrence.digits_only:
        return occurrence.chars >= MIN_DIGITS
    return occurrence.chars >= (MIN_MODEL_CHARS if occurrence.model_only else MIN_CHARS)


def check_slots(
    slots: list[TextSlot],
    session: VaultSession,
    language: str,
    *,
    tool_names: frozenset[str] = frozenset(),
    issued: frozenset[str] = frozenset(),
) -> OutboundCheck:
    """Re-check the texts of ``slots`` (as they will be sent) against ``session``."""
    started = time.perf_counter()
    check = OutboundCheck(texts=len(slots))
    if tool_names and session.known_values:
        known = {normalize_value(v.value) for v in session.known_values.values()}
        tool_names = tool_names - known
    texts = [slot.text for slot in slots]
    # The JSON-unescaped views of a text are checked as the text itself (LAB-1755).
    owners = list(range(len(slots)))
    for index, slot in enumerate(slots):
        if slot.kind != "identifier" and "\\" in slot.text:
            views = unescaped_views(slot.text)
            texts += views
            owners += [index] * len(views)
    for occurrence in session.unmasked(texts, language):
        slot = slots[owners[occurrence.index]]
        if occurrence.index >= len(slots):
            if blocks(occurrence):
                check.hits[occurrence.entity_type.value] += 1
            # A short occurrence in a view is the text's own, counted there already.
            continue
        if slot.kind == "identifier" and not occurrence.known:
            if slot.text in issued:
                continue
            written = slot.text[occurrence.start : occurrence.end]
            if occurrence.entity_type in EXEMPT_TYPES and normalize_value(written) in tool_names:
                continue
        if blocks(occurrence):
            check.hits[occurrence.entity_type.value] += 1
        else:
            check.short += 1
    check.ms = (time.perf_counter() - started) * 1000
    return check


def check_outbound(
    body: Mapping[str, Any],
    collect: Callable[[object], CollectedTexts],
    session: VaultSession,
    language: str,
    *,
    tool_names: frozenset[str] = frozenset(),
    issued: frozenset[str] = frozenset(),
) -> OutboundCheck:
    """Re-read the masked ``body`` with ``collect`` and re-check every text in it, then scan
    the serialized body independently of the walker's slots (LAB-1563).

    The walker only reads here: nothing is written back. A masked body it can no longer read
    (or serialize) is refused like a hit (fail closed)."""
    started = time.perf_counter()
    try:
        slots = collect(body).slots
    except PiiGuardError:
        raise OutboundCheckFailedError({}, unreadable=True) from None
    check = check_slots(slots, session, language, tool_names=tool_names, issued=issued)
    _check_serialized(body, session, language, check, tool_names=tool_names, issued=issued)
    check.ms = (time.perf_counter() - started) * 1000
    return check


def _check_serialized(
    body: Mapping[str, Any],
    session: VaultSession,
    language: str,
    check: OutboundCheck,
    *,
    tool_names: frozenset[str],
    issued: frozenset[str],
) -> None:
    """Search the serialized masked ``body`` for session values, wherever they sit.

    This is the walker's blind-spot net: keys, structural values, raw numbers and any field
    no slot covers. Exemptions mirror :func:`check_slots` without slot context: a declared
    tool name of a word-like type (the tool-name identifiers masking keeps) and an upstream
    issued id (the occurrence itself, or the JSON string enclosing it) do not block; a
    pre-loaded known value always does. Merged into ``check`` by the larger count.
    """
    try:
        serialized = json.dumps(body, ensure_ascii=False)
    except (TypeError, ValueError):
        raise OutboundCheckFailedError({}, unreadable=True) from None
    if tool_names and session.known_values:
        known = {normalize_value(v.value) for v in session.known_values.values()}
        tool_names = tool_names - known
    hits: Counter[str] = Counter()
    short = 0
    for occurrence in session.unmasked([serialized], language):
        if not occurrence.known:
            surface = serialized[occurrence.start : occurrence.end]
            if occurrence.entity_type in EXEMPT_TYPES and (normalize_value(surface) in tool_names):
                continue
            if surface in issued or (
                _enclosing_json_string(serialized, occurrence.start, occurrence.end) in issued
            ):
                continue
        if blocks(occurrence):
            hits[occurrence.entity_type.value] += 1
        else:
            short += 1
    for entity_type, count in hits.items():
        check.hits[entity_type] = max(check.hits[entity_type], count)
    check.short = max(check.short, short)


def _unescaped_quote(serialized: str, pos: int) -> bool:
    if serialized[pos] != '"':
        return False
    backslashes = 0
    cursor = pos - 1
    while cursor >= 0 and serialized[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 0


def _enclosing_json_string(serialized: str, start: int, end: int) -> str:
    """The raw content of the JSON string enclosing ``serialized[start:end]`` (``""``: none
    found nearby). Bounded: the quotes are searched within 1024 characters each way."""
    opening = -1
    for i in range(start - 1, max(start - 1025, -1), -1):
        if _unescaped_quote(serialized, i):
            opening = i
            break
    if opening < 0:
        return ""
    for j in range(end, min(end + 1024, len(serialized))):
        if _unescaped_quote(serialized, j):
            return serialized[opening + 1 : j]
    return ""
