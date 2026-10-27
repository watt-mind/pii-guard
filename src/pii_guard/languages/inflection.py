"""The inflection interface a language pack implements (used by the vault and the LLM detector).

An :class:`InflectionMatcher` says which suffixes may follow a confirmed value, so the vault
masks ``Teszt Eleknek`` as ``[[PERSON_7f3a]]nek``. Optional methods (``variant_stems``,
``splits``, ``restore``) cover languages whose stems change before a suffix; see
:mod:`pii_guard.vault.inflection` for how they are used, and the Hungarian pack for a full
implementation. This module has no dependencies on the components, so a pack can import it
without import cycles; :mod:`pii_guard.vault.inflection` re-exports everything here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pii_guard.types import EntityType

__all__ = ["ExactMatcher", "InflectionMatcher", "Split"]


@dataclass(frozen=True, slots=True)
class Split:
    """One way to read a surface form as ``stem + suffix`` of a lemma. Never logged.

    ``stem + suffix`` is the surface form; ``lemma`` is the dictionary form as written
    (``Próba Zsuzsannának`` -> lemma ``Próba Zsuzsanna``, stem ``Próba Zsuzsanná``, suffix
    ``nak``). ``strong`` splits are unambiguous enough to apply on their own; the vault applies
    a weak one only when the lemma is confirmed (it occurs on its own, another span or an
    earlier request has it).
    """

    lemma: str
    stem: str
    suffix: str
    strong: bool = False

    def __repr__(self) -> str:
        return f"Split(suffix_length={len(self.suffix)}, strong={self.strong})"

    __str__ = __repr__


@runtime_checkable
class InflectionMatcher(Protocol):
    """Says what may directly follow an occurrence of a confirmed value."""

    def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
        """A regex fragment, without capturing groups, matching an allowed suffix.

        The empty string means "no suffix": the value must end at a word boundary. The
        vault compiles the fragment case-insensitively and requires a word boundary after it.
        """
        ...


class ExactMatcher:
    """No inflection: the value must stand on its own between word boundaries."""

    def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
        return ""
