"""Ids the upstream issued, per vault session (LAB-1469).

A coding agent sends the model's own ids back in the next request: Chat Completions
``tool_calls[].id`` and ``tool_call_id``, Responses ``function_call`` ``call_id`` and item
``id``. The gateway checks those fields like any identifier (personal data in one fails
closed, because an id can't carry a placeholder). The upstream mints them as random tokens
(``call_01a1849936ef77df938b17792f84e7f8``), and the NER encoder reads about one in eight of
them as a ``PHONE``, so a long agent session was refused sooner or later.

An id the upstream issued can't tell the upstream anything it doesn't have: it wrote it, from
masked text. So the gateway remembers the ids each upstream answer carried (raw, before
restore) for that answer's vault session, and an identifier slot whose whole text is one of
them is forwarded as sent, without detection. Any other identifier is still checked. The store
is in memory and bounded: after a restart, or once evicted, an id is checked again (fail
closed, never open).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pii_guard.gateway.request import TextSlot
    from pii_guard.types import Span

__all__ = ["ID_KEYS", "IssuedIds", "upstream_ids", "without_issued_ids"]

#: The keys whose string values in an upstream answer are ids the client may send back.
ID_KEYS = frozenset({"id", "call_id"})
#: Longer strings aren't ids; ids with whitespace or a placeholder aren't opaque tokens.
MAX_ID_CHARS = 256
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


def without_issued_ids(
    slots: Sequence[TextSlot], spans: list[list[Span]], issued: frozenset[str]
) -> list[list[Span]]:
    """``spans`` with nothing found in an identifier slot that is an upstream-issued id."""
    if not issued:
        return spans
    return [
        [] if slot.kind == "identifier" and slot.text in issued else found
        for slot, found in zip(slots, spans, strict=True)
    ]
