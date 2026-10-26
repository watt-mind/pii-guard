"""Streaming re-identification: restore placeholders in an LLM response as it arrives.

A placeholder can be split across chunks (``[[PERS`` + ``ON_7f3a]]``). The unmasker emits
everything that can no longer become part of a placeholder and holds back only a trailing
possible prefix (at most one placeholder long), so the concatenated output is identical to
``session.unmask()`` of the whole text.
"""

from __future__ import annotations

from pii_guard.vault.placeholders import MAX_PLACEHOLDER_LENGTH, is_placeholder_prefix
from pii_guard.vault.vault import VaultSession

__all__ = ["StreamUnmasker"]


class StreamUnmasker:
    """Feed response chunks in order, emit what :meth:`feed` returns, then :meth:`flush`.

    Errors from the session (for example :class:`~pii_guard.vault.SessionNotFoundError`
    once it expires) propagate, so the caller can fail the response (ADR 0006).
    """

    def __init__(self, session: VaultSession) -> None:
        self._session = session
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
        if not text:
            return ""
        result = self._session.unmask_with_report(text)
        self._unresolved.update(dict.fromkeys(result.unresolved))
        return result.text


def _hold_from(buffer: str) -> int:
    """Index of the earliest trailing suffix that may still grow into a placeholder."""
    # A prefix is shorter than a placeholder, so only the tail window can hold one.
    for index in range(max(0, len(buffer) - MAX_PLACEHOLDER_LENGTH), len(buffer)):
        if buffer[index] == "[" and is_placeholder_prefix(buffer[index:]):
            return index
    return len(buffer)
