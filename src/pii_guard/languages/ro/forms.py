"""Romanian surface forms for the evaluation: stopwords and stem-changing forms.

Part of the Romanian language pack. Deliberately separate from the vault's
:class:`~pii_guard.languages.ro.inflection.RomanianCaseMatcher`, so the leak rate is not
measured with the code it checks (ADR 0008).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pii_guard.languages import SurfaceForms
from pii_guard.types import EntityType

__all__ = ["STOPWORDS", "SURFACE_FORMS", "RomanianSurfaceForms"]

STOPWORDS = frozenset(
    {
        "strada",
        "str",
        "bulevardul",
        "bd",
        "b-dul",
        "calea",
        "șoseaua",
        "şoseaua",
        "șos",
        "aleea",
        "al",
        "piața",
        "piaţa",
        "splaiul",
        "intrarea",
        "drumul",
        "nr",
        "bl",
        "sc",
        "et",
        "ap",
        "sector",
        "sectorul",
        "jud",
        "județul",
        "judeţul",
        "lui",
        "de",
        "din",
        "ianuarie",
        "februarie",
        "martie",
        "aprilie",
        "mai",
        "iunie",
        "iulie",
        "august",
        "septembrie",
        "octombrie",
        "noiembrie",
        "decembrie",
        "srl",
        "s.r.l",
        "sa",
        "s.a",
        "pfa",
        "domnul",
        "domnului",
        "doamna",
        "doamnei",
        "dl",
        "dna",
        "d-na",
        "dr",
        "prof",
        "ing",
        "av",
    }
)

#: Entity types whose values decline, so a stem change is a surface form of them.
_DECLINING = frozenset({EntityType.PERSON, EntityType.ADDRESS, EntityType.ORGANIZATION})


def _words(value: str) -> str:
    return r"\s+".join(re.escape(token) for token in value.split())


def _genitive(word: str) -> str | None:
    """The genitive/dative of a word in ``-a`` as a regex, written from the grammar.

    ``Maria`` -> ``Mariei``, ``Ioana`` -> ``Ioanei``, ``Andreea`` -> ``Andreei``, ``Monica`` ->
    ``Monicăi``, ``Olga`` -> ``Olgăi``. ``None`` for any other word.
    """
    folded = word.casefold()
    if len(word) < 3 or not word.isalpha() or not folded.endswith("a") or word.isupper():
        return None
    stem = re.escape(word[:-1])
    if folded.endswith("ea"):
        return stem + "i"
    if folded.endswith(("ca", "ga")):
        return stem + "ăi"
    return stem + "ei"


@dataclass(frozen=True, slots=True)
class RomanianSurfaceForms(SurfaceForms):
    """Romanian: a feminine ``-a`` name in the genitive/dative, in any word of the value.

    ``Maria Popescu`` -> ``Mariei Popescu`` (the given name declines, the surname does not),
    ``Popescu Maria`` -> ``Popescu Mariei``, ``Ioana`` -> ``Ioanei``. Unlike the vault, the
    evaluation sees the whole labelled value, so it can match a change inside it.
    """

    stopwords: frozenset[str] = STOPWORDS

    def stem_variants(self, value: str, entity_type: EntityType) -> list[str]:
        if entity_type not in _DECLINING:
            return []
        words = value.split()
        variants: list[str] = []
        for i, word in enumerate(words):
            genitive = _genitive(word)
            if genitive is not None:
                before, after = _words(" ".join(words[:i])), _words(" ".join(words[i + 1 :]))
                parts = [p for p in (before, genitive, after) if p]
                variants.append(r"\s+".join(parts))
        return variants


SURFACE_FORMS = RomanianSurfaceForms()
