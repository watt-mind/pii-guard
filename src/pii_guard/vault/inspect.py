"""Read-only views of a :class:`~pii_guard.vault.Vault` for the vault inspector (LAB-1328).

Nothing here changes the vault: no session is created, purged or touched, so inspecting a
session never extends its sliding TTL. The views hold **personal data** (``original``,
``forms``, known values): they exist for ``GET /v1/vault/sessions*``
(:mod:`pii_guard.api.routes.vault`), which masks them unless the inspector runs in ``full``
mode. Their ``repr()`` never shows a value.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from pii_guard.types import EntityType
from pii_guard.vault.placeholders import normalize_value
from pii_guard.vault.vault import Vault, VaultSession, _Entry

__all__ = [
    "EntryView",
    "KnownView",
    "SessionView",
    "entries_of",
    "live_sessions",
    "ttl_of",
    "view_of",
]

Origin = Literal["detected", "known"]


@dataclass(frozen=True, slots=True)
class SessionView:
    """Counts and timings of one live session. No values."""

    session_id: str
    entries: int
    known_values: int
    entity_counts: dict[str, int]
    idle_seconds: float
    ttl_left_seconds: float
    generation: int


@dataclass(frozen=True, slots=True)
class EntryView:
    """One placeholder and what it stands for. ``original`` and ``forms`` are personal data."""

    placeholder: str
    entity_type: EntityType
    original: str = field(repr=False)
    #: Other written forms of the value matched onto this placeholder (inflected stems,
    #: split surfaces, unconfirmed lemmas), the original excluded.
    forms: tuple[str, ...] = field(repr=False)
    count: int
    origin: Origin
    #: The placeholder of the value this one is a casing or layout variant of.
    variant_of: str | None = None


@dataclass(frozen=True, slots=True)
class KnownView:
    """A pre-loaded known value no placeholder stands for yet. ``value`` is personal data."""

    entity_type: EntityType
    value: str = field(repr=False)


def live_sessions(vault: Vault) -> list[VaultSession]:
    """The sessions that are neither expired nor closed, without purging or touching any."""
    with vault._lock:
        sessions = list(vault._sessions.values())
    return [s for s in sessions if not s.expired]


def ttl_of(vault: Vault) -> float:
    """The vault's sliding session TTL, in seconds."""
    return vault._ttl


def view_of(session: VaultSession) -> SessionView | None:
    """Counts and timings of ``session``, or ``None`` once it has expired."""
    with session._lock:
        if session.expired:
            return None
        now = session._clock()
        ttl_left = max(0.0, session._expires_at - now)
        counts = Counter(e.entity_type.value for e in session._by_placeholder.values())
        return SessionView(
            session_id=session.session_id,
            entries=len(session._by_placeholder),
            known_values=len(session._known),
            entity_counts=dict(sorted(counts.items())),
            idle_seconds=max(0.0, session._ttl - ttl_left),
            ttl_left_seconds=ttl_left,
            generation=session._generation,
        )


def _forms(entry: _Entry) -> tuple[str, ...]:
    found: dict[str, None] = {}
    for form in (*entry.surfaces, *entry.aliases, *entry.seen.values()):
        if form and form != entry.original:
            found[form] = None
    return tuple(found)


def entries_of(session: VaultSession) -> tuple[list[EntryView], list[KnownView]]:
    """Every placeholder of ``session`` (variants after their value) and the known values
    nothing matched yet. Both empty once the session has expired."""
    with session._lock:
        if session.expired:
            return [], []
        known = session._known.values()
        known_keys = {(k.entity_type, normalize_value(k.value)) for k in known}
        views: list[EntryView] = []
        for (entity_type, normalized), entry in session._by_key.items():
            origin: Origin = "known" if (entity_type, normalized) in known_keys else "detected"
            views.append(_view(entry, origin))
            for variant in entry.variants.values():
                views.append(_view(variant, origin, variant_of=entry.placeholder))
        issued = set(session._by_key)
        pending = [
            KnownView(k.entity_type, k.value)
            for k in known
            if (k.entity_type, normalize_value(k.value)) not in issued
        ]
        return views, pending


def _view(entry: _Entry, origin: Origin, variant_of: str | None = None) -> EntryView:
    return EntryView(
        placeholder=entry.placeholder,
        entity_type=entry.entity_type,
        original=entry.original,
        forms=_forms(entry),
        count=entry.count,
        origin=origin,
        variant_of=variant_of,
    )
