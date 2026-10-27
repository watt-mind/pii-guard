"""English inflection: the possessive (vault, LLM alignment). Part of the English pack."""

from __future__ import annotations

from pii_guard.types import EntityType

__all__ = ["EnglishPossessiveMatcher"]


class EnglishPossessiveMatcher:
    """English: the possessive ``'s`` (or a bare apostrophe), straight or typographic (U+2019).

    ``Smith's``, ``James'`` and their typographic forms keep the apostrophe and ``s`` outside
    the placeholder.
    Plurals (``the Smiths``) are not matched: a trailing ``s`` turns too many names into other
    words (``Will`` -> ``wills``).
    """

    def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
        return "(?:['\u2019]s|['\u2019])"
