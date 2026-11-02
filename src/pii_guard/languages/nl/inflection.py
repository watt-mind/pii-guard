"""Dutch inflection: the genitive ``-s`` of names (vault, LLM alignment).

``Pieters fiets``, ``Jansens huis``, ``Utrechts centrum``: the ``s`` attaches to the name
without an apostrophe. After a long vowel (``a``, ``i``, ``o``, ``u``, ``y``) the spelling
rules want an apostrophe (``Anna's``, ``Jo's``, ``Rudy's``), and after a sibilant (``s``,
``sh``, ``x``, ``z``, ``ce``) an apostrophe alone replaces it (``Joris' fiets``, ``Max'
boek``). People write the other forms as well, so every name accepts ``s``, ``'s`` and ``'``
except the sibilant ones, which accept the apostrophe only (``Hendriks`` + ``s`` would be
another surname). The suffix stays outside the placeholder (``[[PERSON_7f3a]]s``) and the
stem never changes, so the optional ``variant_stems``/``splits``/``restore`` methods are not
needed.

Surname prefixes (``van``, ``de``, ``van der``) are part of the name span, so the suffix
follows the surname: ``Van Dijks auto``.

Values that end in a digit or another non-letter (codes, numbers) take no suffix.
"""

from __future__ import annotations

from pii_guard.types import EntityType

__all__ = ["DutchGenitiveMatcher"]

_SIBILANT_ENDINGS = ("s", "sh", "x", "z", "ce")


class DutchGenitiveMatcher:
    """The genitive ``s``, ``'s`` (or an apostrophe after a sibilant), straight or typographic."""

    def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
        value = value.rstrip()
        if not value or not value[-1].isalpha():
            return ""
        if value.casefold().endswith(_SIBILANT_ENDINGS):
            return "(?:['\u2019])"
        return "(?:['\u2019]s|s|['\u2019])"
