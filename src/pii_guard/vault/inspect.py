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
from pii_guard.vault.entry import _Entry
from pii_guard.vault.placeholders import normalize_value
from pii_guard.vault.session import VaultSession
from pii_guard.vault.vault import Vault

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
    occurrences: int
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
    #: The detector of the first span that created the entry (LAB-1332); ``None`` when
    #: unknown or recorded before this field existed.
    detector: str | None = None
    #: Vault-clock seconds of the first and latest masked occurrence (LAB-1332); ``None``
    #: until the entry's first occurrence is assembled.
    first_seen: float | None = None
    last_seen: float | None = None


@dataclass(frozen=True, slots=True)
class KnownView:
    """A pre-loaded known value no placeholder stands for yet. ``value`` is personal data."""

    entity_type: EntityType
    value: str = field(repr=False)


def live_sessions(vault: Vault) -> list[VaultSession]:
    """The sessions that are neither expired nor closed, without purging or touching any."""
    return vault.live_sessions()


def ttl_of(vault: Vault) -> float:
    """The vault's sliding session TTL, in seconds."""
    return vault.ttl_seconds


def view_of(session: VaultSession) -> SessionView | None:
    """Counts and timings of ``session``, or ``None`` once it has expired."""
    summary = session.peek_summary()
    if summary is None:
        return None
    entries, known_values, idle_seconds, ttl_left, generation = summary
    counts = Counter(e.entity_type.value for e in entries)
    return SessionView(
        session_id=session.session_id,
        entries=len(entries),
        occurrences=sum(e.count for e in entries),
        known_values=known_values,
        entity_counts=dict(sorted(counts.items())),
        idle_seconds=idle_seconds,
        ttl_left_seconds=ttl_left,
        generation=generation,
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
    snapshot = session.peek_entries()
    if snapshot is None:
        return [], []
    by_key, known = snapshot
    known_keys = {(k.entity_type, normalize_value(k.value)) for k in known}
    views: list[EntryView] = []
    for (entity_type, normalized), entry in by_key:
        origin: Origin = "known" if (entity_type, normalized) in known_keys else "detected"
        views.append(_view(entry, origin))
        for variant in entry.variants.values():
            views.append(_view(variant, origin, variant_of=entry.placeholder))
    issued = {key for key, _ in by_key}
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
        detector=entry.detector,
        first_seen=entry.first_seen,
        last_seen=entry.last_seen,
    )
