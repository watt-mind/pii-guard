"""Streaming re-identification: restore placeholders in an LLM response as it arrives.

A placeholder can be split across chunks (``[[PERS`` + ``ON_7f3a]]``). The unmasker emits
everything that can no longer become part of a placeholder and holds back only a trailing
possible prefix (at most one placeholder long), so the concatenated output is identical to
``session.unmask()`` of the whole text.

How a placeholder is restored can depend on the suffix right after it (Hungarian
``[[PERSON_x]]nak`` -> ``Próba Zsuzsannának``), so a complete placeholder followed only by
word characters is held back too, until a non-word character arrives or the run is too long
to be a suffix (:data:`~pii_guard.vault.inflection.MAX_SUFFIX_LENGTH`).
"""

from __future__ import annotations

import re

from pii_guard.vault.inflection import MAX_SUFFIX_LENGTH
from pii_guard.vault.placeholders import (
    MAX_PLACEHOLDER_LENGTH,
    PLACEHOLDER_RE,
    is_placeholder_prefix,
)
from pii_guard.vault.vault import RestoreBudget, VaultSession

__all__ = ["StreamUnmasker"]


class StreamUnmasker:
    """Feed response chunks in order, emit what :meth:`feed` returns, then :meth:`flush`.

    Errors from the session (for example :class:`~pii_guard.vault.SessionNotFoundError`
    once it expires) propagate, so the caller can fail the response (ADR 0006).

    Every chunk is charged to one :class:`~pii_guard.vault.RestoreBudget`: ``budget`` (share
    one across the unmaskers of one response) or, by default, a fresh one of the session's,
    so a stream restores at most ``PII_GUARD_UNMASK_MAX_RESTORED_CHARS`` characters of
    original values and then raises :class:`~pii_guard.vault.UnmaskOutputTooLargeError`.
    """

    def __init__(self, session: VaultSession, budget: RestoreBudget | None = None) -> None:
        self._session = session
        self._budget = budget if budget is not None else session.restore_budget()
        self._buffer = ""
        self._unresolved: dict[str, None] = {}
        self._finished = False

    def __repr__(self) -> str:
        return f"StreamUnmasker(buffered={len(self._buffer)}, finished={self._finished})"

    __str__ = __repr__

    @property
    def unresolved(self) -> tuple[str, ...]:
        """Unknown placeholder-shaped tokens seen so far, once each, in order of appearance."""
        return tuple(self._unresolved)

    def feed(self, chunk: str) -> str:
        """Text that is safe to emit now; holds back a trailing partial ``[[...``."""
        if self._finished:
            raise RuntimeError("StreamUnmasker.feed() after flush()")
        self._buffer += chunk
        hold = _hold_from(self._buffer)
        ready, self._buffer = self._buffer[:hold], self._buffer[hold:]
        return self._unmask(ready)

    def flush(self) -> str:
        """Whatever is still buffered, at the end of the stream."""
        self._finished = True
        ready, self._buffer = self._buffer, ""
        return self._unmask(ready)

    def _unmask(self, text: str) -> str:
        # Called even with nothing ready, so an expired session fails the stream right away.
        result = self._session.unmask_with_report(text, budget=self._budget)
        self._unresolved.update(dict.fromkeys(result.unresolved))
        return result.text


_OPEN_SUFFIX_RE = re.compile(r"-?\w*")


def _hold_from(buffer: str) -> int:
    """Index of the earliest trailing part whose restoration more input could still change.

    That is a possible placeholder prefix, or a complete placeholder followed by a suffix
    that may still grow (``[[PERSON_x]]na`` before ``k``).
    """
    window = max(0, len(buffer) - MAX_PLACEHOLDER_LENGTH - MAX_SUFFIX_LENGTH - 1)
    last = None
    for match in PLACEHOLDER_RE.finditer(buffer, window):
        last = match
    if (
        last is not None
        and len(buffer) - last.end() <= MAX_SUFFIX_LENGTH
        and _OPEN_SUFFIX_RE.fullmatch(buffer, last.end())
    ):
        return last.start()
    # A prefix is shorter than a placeholder, so only the tail window can hold one.
    for index in range(max(0, len(buffer) - MAX_PLACEHOLDER_LENGTH), len(buffer)):
        if buffer[index] == "[" and is_placeholder_prefix(buffer[index:]):
            return index
    return len(buffer)
