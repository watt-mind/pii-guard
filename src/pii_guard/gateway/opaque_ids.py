"""Opaque ids in identifier fields: forwarded as sent, not refused (LAB-1469).

Coding agents send ids back in every request: Chat Completions ``tool_calls[].id`` and
``tool_call_id``, Responses ``function_call`` ``call_id`` and item ``id``. The gateway checks
those fields like any identifier (personal data in one fails closed, because an id can't carry
a placeholder). Measured live (docs/integrations/harness-matrix-2026-10-28.md), the NER encoder
reads random ids as a ``PHONE``: 37 of 300 upstream call ids (``call_<32 hex>``) and 59 of 200
client message ids (Codex's ``msg_<uuid>``), so pi and Muse Code were refused after a few tool
calls and Codex on its first request. It also reads JavaScript's ``Number.MAX_SAFE_INTEGER``
(``9007199254740991``, the bound zod writes into OpenCode's tool schemas as ``maximum``) as a
``BANK_ACCOUNT``, which refused every OpenCode request. Two rules, both narrow:

1. **Upstream-issued ids.** An id the upstream wrote can't tell it anything it doesn't have:
   it minted it from masked text. The gateway remembers the ids each upstream answer carried
   (raw, before restore) per vault session; an identifier slot whose whole text is one of them
   gets no detection. The store is in memory and bounded: after a restart, or once evicted, the
   id is checked again (fail closed).
2. **Hex, UUID and number tokens.** An identifier that is exactly an optional short prefix plus
   a UUID or a run of 16+ hex digits (``msg_01a184b6-8156-7cc2-b584-a0fb83dedf84``), or a JSON
   number (a schema bound such as ``-9007199254740991``), has no room for a name or an address.
   Hits from the model-based detectors (NER) are dropped there; the rules (phone formats,
   checksummed ids), the LLM detector and known values still apply.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pii_guard.gateway.request import TextSlot
    from pii_guard.types import Span

__all__ = ["ID_KEYS", "IssuedIds", "is_opaque_token", "upstream_ids", "without_opaque_ids"]

#: The keys whose string values in an upstream answer are ids the client may send back.
ID_KEYS = frozenset({"id", "call_id"})
#: Longer strings aren't ids; ids with whitespace or a placeholder aren't opaque tokens.
MAX_ID_CHARS = 256
#: An optional short prefix, then a UUID or 16+ hex digits; or a JSON number.
_OPAQUE_TOKEN_RE = re.compile(
    r"(?:[A-Za-z]{1,24}[_-])?"
    r"(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|[0-9a-fA-F]{16,128})"
    r"|-?[0-9]{1,40}(?:\.[0-9]{1,40})?(?:[eE][+-]?[0-9]{1,4})?"
)
#: Detectors whose hits in an opaque token are dropped: learned models, which read digit runs as
#: phone numbers. Rules (checksums, formats) and the LLM detector keep theirs.
MODEL_DETECTORS = frozenset({"ner", "ner_gliner"})
#: Sessions remembered, and ids per session (least recently used out first).
MAX_SESSIONS = 4096
MAX_IDS_PER_SESSION = 4096


def _is_token(value: str) -> bool:
    return (
        0 < len(value) <= MAX_ID_CHARS
        and "[[" not in value
        and not any(ch.isspace() for ch in value)
    )


def upstream_ids(payload: Any) -> list[str]:
    """Every ``id`` / ``call_id`` string in an upstream answer, chunk or event."""
    out: list[str] = []
    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ID_KEYS and isinstance(item, str):
                    if _is_token(item):
                        out.append(item)
                elif isinstance(item, (dict, list)):
                    stack.append(item)
        elif isinstance(value, list):
            stack.extend(v for v in value if isinstance(v, (dict, list)))
    return out


class IssuedIds:
    """Session id -> the ids the upstream issued in it. Thread-safe and bounded."""

    def __init__(
        self, max_sessions: int = MAX_SESSIONS, max_ids: int = MAX_IDS_PER_SESSION
    ) -> None:
        self._max_sessions = max_sessions
        self._max_ids = max_ids
        self._sessions: OrderedDict[str, OrderedDict[str, None]] = OrderedDict()
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"IssuedIds(sessions={len(self._sessions)})"

    def add(self, session_id: str, ids: Iterable[str]) -> None:
        ids = [i for i in ids if _is_token(i)]
        if not ids:
            return
        with self._lock:
            known = self._sessions.get(session_id)
            if known is None:
                known = self._sessions[session_id] = OrderedDict()
                while len(self._sessions) > self._max_sessions:
                    self._sessions.popitem(last=False)
            else:
                self._sessions.move_to_end(session_id)
            for value in ids:
                known[value] = None
                known.move_to_end(value)
            while len(known) > self._max_ids:
                known.popitem(last=False)

    def of(self, session_id: str) -> frozenset[str]:
        with self._lock:
            known = self._sessions.get(session_id)
            return frozenset(known) if known else frozenset()

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


def is_opaque_token(text: str) -> bool:
    """``text`` is a prefixed UUID or hex run, or a JSON number (rule 2 above)."""
    return _OPAQUE_TOKEN_RE.fullmatch(text) is not None


def without_opaque_ids(
    slots: Sequence[TextSlot], spans: list[list[Span]], issued: frozenset[str]
) -> list[list[Span]]:
    """``spans`` without the hits in identifier slots that are opaque ids (both rules)."""
    out = []
    for slot, found in zip(slots, spans, strict=True):
        if slot.kind == "identifier" and found:
            if slot.text in issued:
                found = []
            elif is_opaque_token(slot.text):
                found = [s for s in found if s.detector not in MODEL_DETECTORS]
        out.append(found)
    return out
