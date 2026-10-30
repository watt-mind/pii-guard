"""Language hooks for finding inflected occurrences of a confirmed value.

Once a value is confirmed (a detector found it), the vault masks every occurrence of it,
not only the detected span. In an agglutinative language such as Hungarian the value is
often followed by a case suffix (``Teszt Eleknek``, ``Kovácsnál``), so a plain word-boundary
match would miss it. An :class:`InflectionMatcher` says which suffixes may follow a value;
the vault replaces only the value itself and keeps the suffix, so
``Teszt Eleknek`` becomes ``[[PERSON_7f3a]]nek`` and re-identification is exact.

Hungarian also changes the value itself before some suffixes: a final ``a``/``e`` lengthens
(``Próba Zsuzsanna`` -> ``Próba Zsuzsannának``, ``Minta Kendét``) and a final digraph doubles
before ``-val``/``-vel`` (``Kovács`` -> ``Kováccsal``). Three optional matcher methods cover
these forms, so every form of one value maps to one vault entry keyed on its lemma:

- :meth:`~HungarianSuffixMatcher.variant_stems`: the changed stems of a lemma and the suffixes
  that must follow them (occurrence expansion in the vault and ``LlmDetector.align``);
- :meth:`~HungarianSuffixMatcher.splits`: ways to split a detected surface form into
  ``lemma + suffix`` (``Próba Zsuzsannának`` -> ``Próba Zsuzsanna`` + ``nak``), so the
  placeholder covers the stem and the suffix stays outside: ``[[PERSON_7f3a]]nak``;
- :meth:`~HungarianSuffixMatcher.restore`: re-inflection on unmask, also for suffixes the
  upstream model attached itself (``[[PERSON_7f3a]]nak`` -> ``Próba Zsuzsannának``).

Matchers without these methods (a custom :func:`register_inflection` hook that only has
``suffix_pattern``) keep the exact-stem behaviour; use the module functions
:func:`variant_stems`, :func:`splits` and :func:`restore`, which fall back for them.

English adds only the possessive (``Smith's`` -> ``[[PERSON_7f3a]]'s``, ``James'``); see
:class:`EnglishPossessiveMatcher`. Matchers are part of a language pack (ADR 0008) and are
looked up by primary language, so ``en-GB`` uses the ``en`` matcher.
"""

from __future__ import annotations

import re

from pii_guard.languages import get_pack
from pii_guard.languages.inflection import ExactMatcher, InflectionMatcher, Split
from pii_guard.types import EntityType

__all__ = [
    "MAX_SUFFIX_LENGTH",
    "ExactMatcher",
    "InflectionMatcher",
    "Split",
    "following_suffix",
    "inflection_for",
    "register_inflection",
    "restore",
    "splits",
    "variant_stems",
]

#: Longest run of word characters after a placeholder that can still be a suffix. A longer run
#: is never treated as one, which bounds what a streaming unmasker has to hold back.
MAX_SUFFIX_LENGTH = 12

_FOLLOWING_RE = re.compile(r"(?:-(?=\w))?\w*")


def following_suffix(text: str, pos: int) -> str:
    """The suffix-like run at ``text[pos:]``: word characters, optionally after one hyphen.

    ``""`` when nothing word-like follows or the run is longer than :data:`MAX_SUFFIX_LENGTH`.
    """
    match = _FOLLOWING_RE.match(text, pos)
    run = match.group(0) if match else ""
    return run if len(run) <= MAX_SUFFIX_LENGTH else ""


#: Matchers registered with :func:`register_inflection`; they take precedence over packs.
_INFLECTIONS: dict[str, InflectionMatcher] = {}
_EXACT = ExactMatcher()


def _primary(language: str) -> str:
    return (language or "").strip().lower().replace("_", "-").split("-")[0]


def register_inflection(language: str, matcher: InflectionMatcher) -> None:
    """Use ``matcher`` for ``language`` (ISO 639-1), replacing the pack's matcher."""
    _INFLECTIONS[language] = matcher


def variant_stems(
    matcher: InflectionMatcher, value: str, entity_type: EntityType
) -> list[tuple[str, str]]:
    """``matcher.variant_stems`` if it has one, else no changed stems."""
    method = getattr(matcher, "variant_stems", None)
    return list(method(value, entity_type)) if method is not None else []


def splits(matcher: InflectionMatcher, surface: str, entity_type: EntityType) -> list[Split]:
    """``matcher.splits`` if it has one, else no splits (the surface is its own lemma)."""
    method = getattr(matcher, "splits", None)
    return list(method(surface, entity_type)) if method is not None else []


def restore(matcher: InflectionMatcher, lemma: str, suffix: str, entity_type: EntityType) -> str:
    """``matcher.restore`` if it has one, else ``lemma + suffix``."""
    method = getattr(matcher, "restore", None)
    return method(lemma, suffix, entity_type) if method is not None else lemma + suffix


def inflection_for(language: str) -> InflectionMatcher:
    """The matcher for ``language`` (``"en-GB"`` falls back to ``"en"``).

    A matcher registered with :func:`register_inflection` first, then the language pack's
    (:mod:`pii_guard.languages`), :class:`ExactMatcher` for languages without one.
    """
    matcher = _INFLECTIONS.get(language) or _INFLECTIONS.get(_primary(language))
    if matcher is None:
        pack = get_pack(language)
        matcher = pack.inflection if pack is not None else None
    return matcher if matcher is not None else _EXACT
