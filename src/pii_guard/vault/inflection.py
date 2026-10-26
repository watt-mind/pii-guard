"""Language hooks for finding inflected occurrences of a confirmed value.

Once a value is confirmed (a detector found it), the vault masks every occurrence of it,
not only the detected span. In an agglutinative language such as Hungarian the value is
often followed by a case suffix (``Teszt Eleknek``, ``Kovácsnál``), so a plain word-boundary
match would miss it. An :class:`InflectionMatcher` says which suffixes may follow a value;
the vault replaces only the value itself and keeps the suffix, so
``Teszt Eleknek`` becomes ``[[PERSON_7f3a]]nek`` and re-identification is exact.

Forms that change the value itself (``Anna`` -> ``Annának``, ``Kovács`` -> ``Kováccsal``)
are not matched by the simple Hungarian matcher here.

English adds only the possessive (``Smith's`` -> ``[[PERSON_7f3a]]'s``, ``James'``); see
:class:`EnglishPossessiveMatcher`. Matchers are part of a language pack (ADR 0008) and are
looked up by primary language, so ``en-GB`` uses the ``en`` matcher.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from pii_guard.types import EntityType

__all__ = [
    "EnglishPossessiveMatcher",
    "ExactMatcher",
    "HungarianSuffixMatcher",
    "InflectionMatcher",
    "inflection_for",
    "register_inflection",
]


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


# Case endings that attach to the unchanged stem (vowel-harmony variants listed together).
_HU_SUFFIXES: tuple[str, ...] = (
    "nak", "nek",                      # dative
    "ban", "ben", "ba", "be",          # inessive, illative
    "ból", "ből",                      # elative
    "hoz", "hez", "höz",               # allative
    "nál", "nél",                      # adessive
    "tól", "től",                      # ablative
    "ra", "re", "ról", "ről",          # sublative, delative
    "on", "en", "ön", "n",             # superessive
    "ig", "ért", "ként",               # terminative, causal-final, formal
    "ot", "et", "öt", "at", "t",       # accusative
    "éig", "ék", "éi", "é",            # possessive / family
)  # fmt: skip
_HU_VOWELS = frozenset("aáeéiíoóöőuúüű")
# Digraphs double their first letter (``Kovács`` -> ``Kováccsal``), so the stem changes.
_HU_DIGRAPHS = ("cs", "dz", "gy", "ly", "ny", "sz", "ty", "zs")


class HungarianSuffixMatcher:
    """Common Hungarian case suffixes that leave the value intact.

    Also covers instrumental and translative forms with consonant doubling when the value
    ends in a single consonant (``Elek`` -> ``Elekkel``, ``Elekké``), ``-val``/``-vel``
    after a vowel, and hyphenated suffixes after codes and numbers (``ABC-123-nak``).
    """

    def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
        suffixes = set(_HU_SUFFIXES)
        hyphenated = {"val", "vel", "vá", "vé"}
        last = value[-1:].casefold()
        if last in _HU_VOWELS:
            suffixes |= {"val", "vel", "vá", "vé"}
        elif last.isalpha() and not value.casefold().endswith(_HU_DIGRAPHS):
            suffixes |= {f"{last}al", f"{last}el", f"{last}á", f"{last}é"}
        plain = "|".join(re.escape(s) for s in sorted(suffixes, key=len, reverse=True))
        after_hyphen = "|".join(
            re.escape(s) for s in sorted(suffixes | hyphenated, key=len, reverse=True)
        )
        return f"(?:-(?:{after_hyphen})|(?:{plain}))"


class EnglishPossessiveMatcher:
    """English: the possessive ``'s`` (or a bare apostrophe), straight or typographic (U+2019).

    ``Smith's``, ``James'`` and their typographic forms keep the apostrophe and ``s`` outside
    the placeholder.
    Plurals (``the Smiths``) are not matched: a trailing ``s`` turns too many names into other
    words (``Will`` -> ``wills``).
    """

    def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
        return "(?:['\u2019]s|['\u2019])"


_INFLECTIONS: dict[str, InflectionMatcher] = {
    "hu": HungarianSuffixMatcher(),
    "en": EnglishPossessiveMatcher(),
}
_EXACT = ExactMatcher()


def _primary(language: str) -> str:
    return (language or "").strip().lower().replace("_", "-").split("-")[0]


def register_inflection(language: str, matcher: InflectionMatcher) -> None:
    """Use ``matcher`` for ``language`` (ISO 639-1), replacing any existing one."""
    _INFLECTIONS[language] = matcher


def inflection_for(language: str) -> InflectionMatcher:
    """The matcher for ``language`` (``"en-GB"`` falls back to ``"en"``).

    :class:`ExactMatcher` for languages without one.
    """
    matcher = _INFLECTIONS.get(language) or _INFLECTIONS.get(_primary(language))
    return matcher if matcher is not None else _EXACT
