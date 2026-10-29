"""German inflection: the genitive ``-s`` of names (vault, LLM alignment).

``Annas Wohnung``, ``Müllers Auto``, ``Berlins Bezirke``: the ``s`` attaches to the name
without an apostrophe; after ``s``, ``ß``, ``x``, ``z`` and ``ce`` an apostrophe replaces it
(``Hans' Fahrrad``, ``Grass\u2019 Roman``). The colloquial ``Anna's`` is accepted too. The suffix
stays outside the placeholder (``[[PERSON_7f3a]]s``) and the stem never changes, so the
optional ``variant_stems``/``splits``/``restore`` methods are not needed.

Values that end in a digit or another non-letter (codes, numbers) take no suffix.
"""

from __future__ import annotations

from pii_guard.types import EntityType

__all__ = ["GermanGenitiveMatcher"]

_SIBILANT_ENDINGS = ("s", "ß", "x", "z", "ce")


class GermanGenitiveMatcher:
    """The genitive ``s`` (or an apostrophe after a sibilant), straight or typographic."""

    def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
        value = value.rstrip()
        if not value or not value[-1].isalpha():
            return ""
        if value.casefold().endswith(_SIBILANT_ENDINGS):
            return "(?:['\u2019])"
        return "(?:['\u2019]s|s|['\u2019])"
