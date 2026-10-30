"""In-memory vault: keyed pseudonyms, the placeholder mapping and re-identification.

The mapping (placeholder -> original value) lives only in this process and expires after a
TTL of inactivity. Nothing in this module logs, reprs or raises with an original value: logs
and errors carry entity types, counts and placeholder ids only (AGENTS.md, ADR 0006).

Compiled patterns (the ``re`` module cache, at most 512 entries process-wide) may briefly
outlive a dropped session: the vault and the detectors build patterns from folded values,
and CPython keeps them until LRU eviction or a restart. This is accepted residual risk
(LAB-1364): the cache is bounded and memory-only, in the same trust boundary as the
running vault, and it never reaches logs, traces or error messages. Wiring ``re.purge()``
into the delete path would force every live session to recompile its patterns, so it is
deliberately not done.

Doubled case suffixes are out of scope (LAB-1142): a case ending stacked on a case ending
is not Hungarian (``Hajnának`` + ``nak``), so the vault does not split the surface to its
lemma first. Both occurrences share one placeholder keyed on the labelled value's lemma
and the extra suffix is not restored on unmask; nothing leaks, the text just does not
round-trip. Real stacked suffixes (``-é``/``-ék``/``-éi`` plus a case ending, LAB-1337)
round-trip normally.
"""

from __future__ import annotations

import copy
import hashlib
import heapq
import hmac
import logging
import secrets
import threading
import time
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

from pii_guard.types import MaskingError, VaultNotConfiguredError
from pii_guard.vault.entry import (
    _CASE_AMBIGUOUS,
    _MIN_ALIAS_LETTERS,
    CASE_SENSITIVE_TYPES,
    IDENTIFIER_TYPES,
    MODEL_DETECTORS,
    NEUTRAL_DETECTORS,
    _absent,
    _body,
    _compile,
    _Entry,
    _exact,
    _folded_index,
    _forms,
    _initial,
    _is_mark,
    _is_word_char,
    _layout,
    _letters,
    _literal_forms,
    _Needles,
    _needles,
    _occurrence,
    _occurs_alone,
    _Plan,
    _recased,
    _relaid,
    _restored,
    _validated,
    _value_key,
    _value_shape,
)
from pii_guard.vault.placeholders import (
    DEFAULT_ID_LENGTH,
    MAX_ID_LENGTH,
    MIN_ID_LENGTH,
    derive_id,
)
from pii_guard.vault.session import (
    _COMMITTED_STATE,
    _RESET_CACHES,
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_RESTORED_CHARS,
    Authorize,
    MaskResult,
    PlaceholderInInputError,
    RestoreBudget,
    SessionEntryLimitError,
    SessionNotFoundError,
    Unmasked,
    UnmaskOutputTooLargeError,
    UnmaskResult,
    VaultSession,
    _authorized,
    _Masked,
)

if TYPE_CHECKING:
    from pii_guard.config import Settings

__all__ = [
    "CASE_SENSITIVE_TYPES",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MAX_LEASES_PER_IDENTITY",
    "DEFAULT_MAX_RESTORED_CHARS",
    "DEFAULT_MAX_SESSIONS",
    "DEFAULT_TTL_SECONDS",
    "IDENTIFIER_TYPES",
    "MIN_TENANT_KEY_BYTES",
    "MODEL_DETECTORS",
    "NEUTRAL_DETECTORS",
    "_CASE_AMBIGUOUS",
    "_COMMITTED_STATE",
    "_MIN_ALIAS_LETTERS",
    "_RESET_CACHES",
    "Authorize",
    "MaskResult",
    "PlaceholderInInputError",
    "RestoreBudget",
    "SessionEntryLimitError",
    "SessionNotFoundError",
    "UnmaskOutputTooLargeError",
    "UnmaskResult",
    "Unmasked",
    "Vault",
    "VaultCapacityError",
    "VaultSession",
    "_Entry",
    "_Masked",
    "_Needles",
    "_Plan",
    "_absent",
    "_authorized",
    "_body",
    "_compile",
    "_exact",
    "_folded_index",
    "_forms",
    "_initial",
    "_is_mark",
    "_is_word_char",
    "_layout",
    "_letters",
    "_literal_forms",
    "_needles",
    "_occurrence",
    "_occurs_alone",
    "_recased",
    "_relaid",
    "_restored",
    "_validated",
    "_value_key",
    "_value_shape",
    "copy",
    "derive_id",
]

logger = logging.getLogger(__name__)

_SessionMetadata = TypeVar("_SessionMetadata")

DEFAULT_TTL_SECONDS = 3600.0
#: Most live sessions a vault holds; a new one beyond it evicts the least recently used.
DEFAULT_MAX_SESSIONS = 10_000
#: Most requests one gateway client identity may hold sessions for at once (LAB-1584): without
#: it, one client with ~``max_sessions`` in-flight streams pins every slot and the rest get
#: ``503 vault_capacity_exhausted``.
DEFAULT_MAX_LEASES_PER_IDENTITY = 1_000
MIN_TENANT_KEY_BYTES = 16


class VaultCapacityError(MaskingError):
    """Every capacity slot is pinned by an active request, or the caller's identity is at its
    lease cap (existing sessions included); retry after one finishes."""

    code = "vault_capacity_exhausted"
    status_code = 503


class Vault:
    """Per-tenant store of :class:`VaultSession` mappings, held in memory with a TTL.

    ``tenant_key`` keys every placeholder id (at least 16 bytes; ``openssl rand -hex 32``
    decoded). ``ttl_seconds`` is sliding: each use of a session extends it. ``id_length`` is
    the initial hex length of placeholder ids (collisions extend it).
    ``case_sensitive_placeholders`` gives each casing class of a value its own placeholder
    (see :meth:`VaultSession.mask`). ``clock`` is injectable for tests.

    ``max_sessions`` caps the live sessions (every ``/v1/mask`` without a ``session_id``
    creates one): creating one more **evicts the least recently used** session (the one
    whose sliding TTL ends first) among unleased sessions. It is closed like an expired
    one, so its later use is ``404 session_not_found``. When every session is leased,
    creation fails with ``503 vault_capacity_exhausted`` without evicting an active session.

    ``max_entries`` caps a **get-or-create** session (:meth:`session_or_create`: the gateway's
    path, ``prompt_cache_key`` and default sessions, which can live as long as a client keeps
    using them). Once a session holds that many placeholders, the next lookup of its id starts
    a new, empty **generation** under a new derived id (logged once per rotation); the full
    generation is no longer handed out and expires with its TTL. A conversation that crosses
    a rotation is re-masked from its re-sent history under the new generation; only a
    placeholder it kept from before the rotation (and no longer sends the value of) stays
    unrestored. Explicit sessions (:meth:`session`) cannot rotate (the client addresses them
    by id), so the same ``max_entries`` is enforced at mask time instead: a full explicit
    session fails closed and its client starts a new one (LAB-1565).

    ``max_restored_chars`` caps the characters of original values one unmask call (or one
    :meth:`VaultSession.restore_budget`, a gateway response) restores: see
    :class:`RestoreBudget` (LAB-1350).

    ``max_leases_per_identity`` caps the leases (:meth:`acquire_session`: in-flight gateway
    requests, streams included) one client identity holds at once, so one client can't pin
    every session slot: over it, that identity gets ``503 vault_capacity_exhausted`` while
    others still acquire (LAB-1584).
    """

    def __init__(
        self,
        tenant_key: bytes,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        id_length: int = DEFAULT_ID_LENGTH,
        clock: Callable[[], float] = time.monotonic,
        case_sensitive_placeholders: bool = False,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_restored_chars: int = DEFAULT_MAX_RESTORED_CHARS,
        max_leases_per_identity: int = DEFAULT_MAX_LEASES_PER_IDENTITY,
    ) -> None:
        if not isinstance(tenant_key, bytes | bytearray):
            raise TypeError("tenant_key must be bytes")
        if len(tenant_key) < MIN_TENANT_KEY_BYTES:
            raise ValueError(f"tenant_key must be at least {MIN_TENANT_KEY_BYTES} bytes")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if not MIN_ID_LENGTH <= id_length <= MAX_ID_LENGTH:
            raise ValueError(f"id_length must be in [{MIN_ID_LENGTH}, {MAX_ID_LENGTH}]")
        if max_sessions < 1:
            raise ValueError("max_sessions must be at least 1")
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        if max_restored_chars < 1:
            raise ValueError("max_restored_chars must be at least 1")
        if max_leases_per_identity < 1:
            raise ValueError("max_leases_per_identity must be at least 1")
        self._max_leases_per_identity = max_leases_per_identity
        self._max_restored = max_restored_chars
        self._max_sessions = max_sessions
        self._max_entries = max_entries
        # base id -> current generation, only for ids that rotated at least once.
        self._generations: dict[str, int] = {}
        self._tenant_key = bytes(tenant_key)
        self._ttl = ttl_seconds
        self._id_length = id_length
        self._clock = clock
        self._case_sensitive = case_sensitive_placeholders
        self._lock = threading.RLock()
        self._leases: Counter[VaultSession] = Counter()
        self._identity_leases: Counter[str] = Counter()
        self._sessions: dict[str, VaultSession] = {}
        self._earliest_expiry = float("inf")

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> Vault:
        """A vault keyed by ``PII_GUARD_TENANT_KEY``. Fails closed if the key is unset.

        ``PII_GUARD_VAULT_CASE_SENSITIVE_PLACEHOLDERS`` sets ``case_sensitive_placeholders``
        ``PII_GUARD_VAULT_MAX_SESSIONS`` sets ``max_sessions``, ``PII_GUARD_VAULT_MAX_ENTRIES``
        sets ``max_entries``, ``PII_GUARD_UNMASK_MAX_RESTORED_CHARS`` sets
        ``max_restored_chars`` and ``PII_GUARD_VAULT_MAX_LEASES_PER_IDENTITY`` sets
        ``max_leases_per_identity``, unless ``kwargs`` does.
        """
        key = settings.tenant_key_bytes()
        if key is None:
            raise VaultNotConfiguredError("PII_GUARD_TENANT_KEY is not set")
        kwargs.setdefault("case_sensitive_placeholders", settings.vault_case_sensitive_placeholders)
        kwargs.setdefault("max_sessions", settings.vault_max_sessions)
        kwargs.setdefault("max_entries", settings.vault_max_entries)
        kwargs.setdefault("max_restored_chars", settings.unmask_max_restored_chars)
        kwargs.setdefault("max_leases_per_identity", settings.vault_max_leases_per_identity)
        return cls(key, **kwargs)

    def __repr__(self) -> str:
        return f"Vault(sessions={len(self._sessions)}, ttl_seconds={self._ttl})"

    __str__ = __repr__

    def __len__(self) -> int:
        """Number of live sessions."""
        with self._lock:
            self._purge_locked(force=True)
            return len(self._sessions)

    @property
    def ttl_seconds(self) -> float:
        """The vault's sliding session TTL, in seconds."""
        return self._ttl

    def live_sessions(self) -> list[VaultSession]:
        """The sessions that are neither expired nor closed, without purging or touching any."""
        with self._lock:
            sessions = list(self._sessions.values())
        return [s for s in sessions if not s.expired]

    def session_count(self) -> int:
        """Current number of stored sessions without purging."""
        return len(self._sessions)

    def session(
        self, session_id: str | None = None, *, authorize: Authorize | None = None
    ) -> VaultSession:
        """``None`` -> a new session with a fresh random id; an existing id -> that session.

        Raises :class:`SessionNotFoundError` for an unknown, expired or closed id.
        ``authorize`` (the gateway's identity binding) runs on the session before its TTL is
        extended: a caller it refuses leaves the session's expiry as it was (LAB-1584).
        """
        with self._lock:
            self._purge_locked()
            if session_id is None:
                created = self._create_locked(f"s_{secrets.token_hex(16)}")
                created.touch_explicit(self._max_entries)  # explicit: capped, not rotated
                return created
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError("vault session not found or expired")
            # Addressed explicitly now: capped from here on, not rotated.
            session.touch_explicit(self._max_entries, authorize=authorize)
            return session

    def session_or_create(
        self, session_id: str, *, authorize: Authorize | None = None
    ) -> tuple[VaultSession, bool]:
        """The live session for ``session_id``, created when there is none: ``(session, new)``.

        For ids the caller chose or derived (:meth:`derive_session_id`), never 404. The
        returned session's id differs from ``session_id`` once that id rotated to a later
        generation (``max_entries``); send the returned id back to address it directly.
        ``authorize`` runs as in :meth:`session`, before any TTL extension, on the live
        session found (a refused caller can't rotate it either) and on the one returned.
        """
        if not session_id:
            raise ValueError("session_id must not be empty")
        with self._lock:
            self._purge_locked()
            generation = self._generations.get(session_id, 0)
            current = self._generation_id(session_id, generation)
            session = self._sessions.get(current)
            if session is not None and not session.expired:
                if session.touch(authorize=authorize, below_entries=self._max_entries):
                    return session, False
                generation += 1
                current = self._generation_id(session_id, generation)
                logger.info(
                    "vault: a session reached %d placeholders; starting generation %d",
                    self._max_entries,
                    generation,
                )
                existing = self._sessions.get(current)
                if existing is not None and not existing.expired:  # pragma: no cover - race
                    existing.touch(authorize=authorize)
                    return existing, False
            session = self._create_locked(current)
            if generation:
                self._generations[session_id] = generation
            _authorized(session, authorize)
            return session, True

    def acquire_session(
        self,
        resolve: Callable[[], tuple[VaultSession, bool, _SessionMetadata]],
        *,
        identity: str | None = None,
    ) -> tuple[VaultSession, bool, _SessionMetadata]:
        """Resolve and pin a session atomically against LRU eviction.

        ``resolve`` must use this vault's session lookup methods. Each successful acquire
        requires one :meth:`release_session` (with the same ``identity``), including on
        failure or cancellation. Pins protect against capacity eviction only; explicit
        deletion and TTL still apply. An ``identity`` already holding
        ``max_leases_per_identity`` leases is refused with :class:`VaultCapacityError`
        before ``resolve`` runs, so nothing is created for it (LAB-1584).
        """
        with self._lock:
            if identity is not None and (
                self._identity_leases[identity] >= self._max_leases_per_identity
            ):
                raise VaultCapacityError("too many active requests for this client")
            result = resolve()
            session = result[0]
            if self._sessions.get(session.session_id) is not session:
                raise SessionNotFoundError("vault session not found or expired")
            session.touch()
            self._leases[session] += 1
            if identity is not None:
                self._identity_leases[identity] += 1
            return result

    def release_session(self, session: VaultSession, *, identity: str | None = None) -> None:
        """Release one pin, even if TTL or explicit deletion already removed the session."""
        with self._lock:
            if self._leases[session] <= 0:
                raise ValueError("session has no lease")
            if identity is not None and self._identity_leases[identity] <= 0:
                raise ValueError("identity has no lease")
            self._leases[session] -= 1
            if not self._leases[session]:
                del self._leases[session]
            if identity is not None:
                self._identity_leases[identity] -= 1
                if not self._identity_leases[identity]:
                    del self._identity_leases[identity]

    def derive_session_id(self, material: str) -> str:
        """A stable session id for ``material``, keyed with the tenant key: ``d_`` + 32 hex.

        The same material gives the same id in this deployment and different ids under
        another tenant key; the id reveals nothing about the material.
        """
        digest = hmac.new(
            self._tenant_key, b"pii-guard-session\x00" + material.encode("utf-8"), hashlib.sha256
        )
        return "d_" + digest.hexdigest()[:32]

    def _generation_id(self, base: str, generation: int) -> str:
        if generation == 0:
            return base
        return self.derive_session_id(f"generation:{generation}:{base}")

    def _create_locked(self, session_id: str) -> VaultSession:
        self._evict_locked(self._max_sessions - 1)
        session = VaultSession(
            session_id,
            self._tenant_key,
            ttl_seconds=self._ttl,
            id_length=self._id_length,
            clock=self._clock,
            case_sensitive_placeholders=self._case_sensitive,
            max_restored_chars=self._max_restored,
        )
        self._sessions[session_id] = session
        if session.expires_at < self._earliest_expiry:
            self._earliest_expiry = session.expires_at
        return session

    def drop(self, session_id: str) -> None:
        """Close and forget a session now (no error if it is already gone).

        Compiled patterns built from its values may stay in the process-wide ``re`` cache
        until eviction: accepted residual risk, see the module docstring (LAB-1364).
        """
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.close()

    def purge_expired(self) -> int:
        """Drop every expired session; returns how many were dropped.

        Like :meth:`drop`, this leaves compiled patterns in the process-wide ``re`` cache
        until eviction (LAB-1364).
        """
        with self._lock:
            return self._purge_locked(force=True)

    def _evict_locked(self, keep: int) -> None:
        """Close the least recently used sessions until at most ``keep`` are left."""
        excess = len(self._sessions) - keep
        if excess <= 0:
            return
        oldest = heapq.nsmallest(
            excess,
            (
                (sid, session)
                for sid, session in self._sessions.items()
                if not self._leases[session]
            ),
            key=lambda item: item[1].expires_at,
        )
        if len(oldest) < excess:
            raise VaultCapacityError("vault session capacity is occupied by active requests")
        for sid, session in oldest:
            del self._sessions[sid]
            session.close()
        logger.info("vault: evicted %d least recently used session(s)", len(oldest))

    def _purge_locked(self, *, force: bool = False) -> int:
        if (
            not force
            and not self._generations
            and (not self._sessions or self._clock() < self._earliest_expiry)
        ):
            return 0
        stale = [sid for sid, session in self._sessions.items() if session.expired]
        for sid in stale:
            self._sessions.pop(sid).close()
        if self._generations:  # a rotated id whose current generation is gone starts over
            gone = [
                base
                for base, generation in self._generations.items()
                if self._generation_id(base, generation) not in self._sessions
            ]
            for base in gone:
                del self._generations[base]
        self._earliest_expiry = min(
            (s.expires_at for s in self._sessions.values()), default=float("inf")
        )
        return len(stale)
