"""In-memory vault: keyed pseudonyms, the placeholder mapping and re-identification.

The mapping (placeholder -> original value) lives only in this process and expires after a
TTL of inactivity. Nothing in this module logs, reprs or raises with an original value: logs
and errors carry entity types, counts and placeholder ids only (AGENTS.md, ADR 0006).
"""

from __future__ import annotations

import itertools
import logging
import re
import secrets
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pii_guard.types import EntityType, MaskingError, PiiGuardError, Span
from pii_guard.vault.inflection import inflection_for
from pii_guard.vault.placeholders import (
    DEFAULT_ID_LENGTH,
    MAX_ID_LENGTH,
    MIN_ID_LENGTH,
    PLACEHOLDER_RE,
    derive_id,
    format_placeholder,
    normalize_value,
)

if TYPE_CHECKING:
    from pii_guard.config import Settings

__all__ = [
    "DEFAULT_TTL_SECONDS",
    "MIN_TENANT_KEY_BYTES",
    "SessionNotFoundError",
    "UnmaskResult",
    "Vault",
    "VaultSession",
]

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 3600.0
MIN_TENANT_KEY_BYTES = 16


class SessionNotFoundError(PiiGuardError):
    """The vault session is unknown, expired or closed; its mapping is gone."""

    code = "not_found"
    status_code = 404


@dataclass(frozen=True, slots=True)
class UnmaskResult:
    """Re-identified text plus the placeholder-shaped tokens that could not be resolved.

    ``unresolved`` lists unknown placeholders (invented or mangled by the model) once each,
    in order of first appearance; they are left in ``text`` as is. ``repr()`` omits ``text``
    because it holds original values.
    """

    text: str
    unresolved: tuple[str, ...]

    def __repr__(self) -> str:
        return f"UnmaskResult(text=<redacted>, unresolved={list(self.unresolved)!r})"

    __str__ = __repr__


class _Entry:
    """One confirmed value. Never repr'd with its value."""

    __slots__ = ("count", "entity_type", "normalized", "original", "patterns", "placeholder")

    def __init__(
        self, placeholder: str, entity_type: EntityType, original: str, normalized: str
    ) -> None:
        self.placeholder = placeholder
        self.entity_type = entity_type
        self.original = original
        self.normalized = normalized
        self.count = 0
        self.patterns: dict[str, re.Pattern[str]] = {}

    def __repr__(self) -> str:
        return f"_Entry(placeholder={self.placeholder!r}, value=<redacted>, count={self.count})"

    def pattern(self, language: str) -> re.Pattern[str]:
        """Case/whitespace-insensitive pattern for further occurrences of the value."""
        pattern = self.patterns.get(language)
        if pattern is None:
            body = r"\s+".join(re.escape(token) for token in self.original.split())
            left = r"(?<!\w)" if _is_word_char(self.original[0]) else ""
            right = ""
            if _is_word_char(self.original[-1]):
                suffix = inflection_for(language).suffix_pattern(self.original, self.entity_type)
                right = f"(?=(?:{suffix})?(?!\\w))" if suffix else r"(?!\w)"
            pattern = re.compile(left + body + right, re.IGNORECASE)
            self.patterns[language] = pattern
        return pattern


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


class VaultSession:
    """The placeholder mapping of one conversation. Obtain one from :meth:`Vault.session`.

    Thread-safe. Once the session expires or is closed, every method raises
    :class:`SessionNotFoundError`; the gateway must then fail the request (ADR 0006).
    """

    def __init__(
        self,
        session_id: str,
        tenant_key: bytes,
        *,
        ttl_seconds: float,
        id_length: int,
        clock: Callable[[], float],
    ) -> None:
        self.session_id = session_id
        self._tenant_key = tenant_key
        self._ttl = ttl_seconds
        self._id_length = id_length
        self._clock = clock
        self._lock = threading.RLock()
        self._by_key: dict[tuple[EntityType, str], _Entry] = {}
        self._by_placeholder: dict[str, _Entry] = {}
        self._closed = False
        self._expires_at = clock() + ttl_seconds

    def __repr__(self) -> str:
        return (
            f"VaultSession(session_id={self.session_id[:6]!r}…, "
            f"placeholders={len(self._by_placeholder)}, closed={self._closed})"
        )

    __str__ = __repr__

    # --- lifecycle -----------------------------------------------------------------------

    @property
    def expired(self) -> bool:
        return self._closed or self._clock() >= self._expires_at

    def close(self) -> None:
        """Forget the mapping now. Later calls raise :class:`SessionNotFoundError`."""
        with self._lock:
            self._closed = True
            self._by_key.clear()
            self._by_placeholder.clear()

    def _check_alive(self) -> None:
        """Raise if expired; otherwise extend the TTL (sliding expiry)."""
        if self.expired:
            self.close()
            raise SessionNotFoundError("vault session not found or expired")
        self._expires_at = self._clock() + self._ttl

    # --- masking -------------------------------------------------------------------------

    def mask(self, text: str, spans: Sequence[Span], *, language: str = "hu") -> str:
        """Replace each span, and every other occurrence of a confirmed value, by its placeholder.

        Confirmed values are those in ``spans`` plus every value this session masked before.
        Further occurrences match case- and whitespace-insensitively and, for ``language``,
        with inflectional suffixes kept outside the placeholder (``[[PERSON_7f3a]]nek``).

        Raises :class:`MaskingError` for invalid, out-of-range or overlapping spans, and
        :class:`SessionNotFoundError` once the session has expired. Nothing is recorded when
        it raises.
        """
        with self._lock:
            self._check_alive()
            ordered = _validated(text, spans)
            taken = bytearray(len(text))
            replacements: list[tuple[int, int, _Entry]] = []
            for span in ordered:
                entry = self._entry_for(span.entity_type, span.text)
                replacements.append((span.start, span.end, entry))
                taken[span.start : span.end] = b"\x01" * span.length
            # Longest values first, so "Teszt Elek" wins over a separately confirmed "Elek".
            entries = sorted(self._by_key.values(), key=lambda e: len(e.normalized), reverse=True)
            for entry in entries:
                for match in entry.pattern(language).finditer(text):
                    start, end = match.span()
                    if any(taken[start:end]):
                        continue
                    replacements.append((start, end, entry))
                    taken[start:end] = b"\x01" * (end - start)
            replacements.sort(key=lambda r: r[0])
            parts: list[str] = []
            cursor = 0
            per_type: Counter[str] = Counter()
            for start, end, entry in replacements:
                parts.append(text[cursor:start])
                parts.append(entry.placeholder)
                entry.count += 1
                per_type[entry.entity_type.value] += 1
                cursor = end
            parts.append(text[cursor:])
            logger.debug(
                "masked %d occurrences (%d from spans): %s",
                len(replacements),
                len(ordered),
                dict(per_type),
            )
            return "".join(parts)

    def _entry_for(self, entity_type: EntityType, value: str) -> _Entry:
        normalized = normalize_value(value)
        key = (entity_type, normalized)
        entry = self._by_key.get(key)
        if entry is not None:
            return entry
        length = self._id_length
        while True:
            placeholder_id = derive_id(
                self._tenant_key, self.session_id, entity_type, normalized, length
            )
            placeholder = format_placeholder(entity_type, placeholder_id)
            if placeholder not in self._by_placeholder:
                break
            # Collision with a different value: extend the id (ADR 0007).
            if length >= MAX_ID_LENGTH:  # pragma: no cover - a full SHA-256 collision
                raise MaskingError(f"could not derive a unique {entity_type.value} placeholder")
            length = min(length + 2, MAX_ID_LENGTH)
        entry = _Entry(placeholder, entity_type, value, normalized)
        self._by_key[key] = entry
        self._by_placeholder[placeholder] = entry
        return entry

    # --- re-identification ---------------------------------------------------------------

    def unmask(self, text: str) -> str:
        """Replace known placeholders with their original values; unknown ones stay as is."""
        return self.unmask_with_report(text).text

    def unmask_with_report(self, text: str) -> UnmaskResult:
        """Like :meth:`unmask`, also listing placeholder-shaped tokens that weren't resolved."""
        with self._lock:
            self._check_alive()
            unresolved: dict[str, None] = {}
            restored = 0

            def replace(match: re.Match[str]) -> str:
                nonlocal restored
                entry = self._by_placeholder.get(match.group(0))
                if entry is None:
                    unresolved[match.group(0)] = None
                    return match.group(0)
                restored += 1
                return entry.original

            result = PLACEHOLDER_RE.sub(replace, text)
            if unresolved:
                logger.warning(
                    "unmask left %d unresolved placeholders: %s", len(unresolved), list(unresolved)
                )
            logger.debug("unmasked %d placeholders", restored)
            return UnmaskResult(result, tuple(unresolved))

    def entities(self) -> list[tuple[str, EntityType, int]]:
        """``(placeholder, entity_type, count)`` for every placeholder this session issued."""
        with self._lock:
            self._check_alive()
            return [(e.placeholder, e.entity_type, e.count) for e in self._by_placeholder.values()]


def _validated(text: str, spans: Sequence[Span]) -> list[Span]:
    """Spans sorted by start; raises :class:`MaskingError` (no values in the message)."""
    for index, span in enumerate(spans):
        if not isinstance(span, Span):
            raise MaskingError(f"span {index} is not a Span")
        label = f"span {index} ({span.entity_type.value})"
        if span.end > len(text):
            raise MaskingError(f"{label} is out of range [{span.start}, {span.end})")
        if text[span.start : span.end] != span.text:
            raise MaskingError(f"{label} does not match the text at [{span.start}, {span.end})")
        if span.entity_type.is_visual:
            raise MaskingError(f"{label} is a visual entity type, not a text span")
        if not normalize_value(span.text):
            raise MaskingError(f"{label} is blank")
    ordered = sorted(spans, key=lambda s: (s.start, s.end))
    for previous, current in itertools.pairwise(ordered):
        if previous.overlaps(current):
            raise MaskingError(
                f"overlapping spans {previous.entity_type.value} [{previous.start}, "
                f"{previous.end}) and {current.entity_type.value} [{current.start}, "
                f"{current.end})"
            )
    return ordered


class Vault:
    """Per-tenant store of :class:`VaultSession` mappings, held in memory with a TTL.

    ``tenant_key`` keys every placeholder id (at least 16 bytes; ``openssl rand -hex 32``
    decoded). ``ttl_seconds`` is sliding: each use of a session extends it. ``id_length`` is
    the initial hex length of placeholder ids (collisions extend it). ``clock`` is injectable
    for tests.
    """

    def __init__(
        self,
        tenant_key: bytes,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        id_length: int = DEFAULT_ID_LENGTH,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(tenant_key, bytes | bytearray):
            raise TypeError("tenant_key must be bytes")
        if len(tenant_key) < MIN_TENANT_KEY_BYTES:
            raise ValueError(f"tenant_key must be at least {MIN_TENANT_KEY_BYTES} bytes")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if not MIN_ID_LENGTH <= id_length <= MAX_ID_LENGTH:
            raise ValueError(f"id_length must be in [{MIN_ID_LENGTH}, {MAX_ID_LENGTH}]")
        self._tenant_key = bytes(tenant_key)
        self._ttl = ttl_seconds
        self._id_length = id_length
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, VaultSession] = {}

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> Vault:
        """A vault keyed by ``PII_GUARD_TENANT_KEY``. Fails closed if the key is unset."""
        key = settings.tenant_key_bytes()
        if key is None:
            raise MaskingError("PII_GUARD_TENANT_KEY is not set", code="vault_not_configured")
        return cls(key, **kwargs)

    def __repr__(self) -> str:
        return f"Vault(sessions={len(self._sessions)}, ttl_seconds={self._ttl})"

    __str__ = __repr__

    def __len__(self) -> int:
        """Number of live sessions."""
        with self._lock:
            self._purge_locked()
            return len(self._sessions)

    def session(self, session_id: str | None = None) -> VaultSession:
        """``None`` -> a new session with a fresh random id; an existing id -> that session.

        Raises :class:`SessionNotFoundError` for an unknown, expired or closed id.
        """
        with self._lock:
            self._purge_locked()
            if session_id is None:
                session_id = f"s_{secrets.token_hex(16)}"
                session = VaultSession(
                    session_id,
                    self._tenant_key,
                    ttl_seconds=self._ttl,
                    id_length=self._id_length,
                    clock=self._clock,
                )
                self._sessions[session_id] = session
                return session
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError("vault session not found or expired")
            session._check_alive()
            return session

    def drop(self, session_id: str) -> None:
        """Close and forget a session now (no error if it is already gone)."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.close()

    def purge_expired(self) -> int:
        """Drop every expired session; returns how many were dropped."""
        with self._lock:
            return self._purge_locked()

    def _purge_locked(self) -> int:
        stale = [sid for sid, session in self._sessions.items() if session.expired]
        for sid in stale:
            self._sessions.pop(sid).close()
        return len(stale)
