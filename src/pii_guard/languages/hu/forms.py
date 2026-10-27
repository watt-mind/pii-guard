"""Hungarian surface forms for the evaluation: stopwords and stem-changing forms.

Part of the Hungarian language pack. Deliberately separate from the vault's
:class:`~pii_guard.languages.hu.inflection.HungarianSuffixMatcher`, so the leak rate is not
measured with the code it checks (ADR 0008).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pii_guard.languages import SurfaceForms
from pii_guard.types import EntityType

__all__ = ["STOPWORDS", "HungarianSurfaceForms"]

_HU_LENGTHENED_SUFFIXES = (
    "nak", "nek", "ban", "ben", "ba", "be", "ból", "ből", "hoz", "hez", "höz", "nál", "nél",
    "tól", "től", "ra", "re", "ról", "ről", "n", "ig", "ért", "ként", "t", "val", "vel", "vá",
    "vé", "é", "ék", "éi", "i", "k",
)  # fmt: skip
_HU_DIGRAPHS = ("cs", "dz", "gy", "ly", "ny", "sz", "ty", "zs")
STOPWORDS = frozenset(
    [
        "utca",
        "u",
        "út",
        "útja",
        "tér",
        "tere",
        "körút",
        "krt",
        "köz",
        "sor",
        "sétány",
        "fasor",
        "rakpart",
        "lakótelep",
        "emelet",
        "em",
        "ajtó",
        "hrsz",
        "szám",
        "kerület",
        "ker",
        "fszt",
        "földszint",
        "lph",
        "lépcsőház",
        "január",
        "február",
        "március",
        "április",
        "május",
        "június",
        "július",
        "augusztus",
        "szeptember",
        "október",
        "november",
        "december",
        "jan",
        "febr",
        "márc",
        "ápr",
        "máj",
        "jún",
        "júl",
        "aug",
        "szept",
        "okt",
        "nov",
        "dec",
        "kft",
        "zrt",
        "nyrt",
        "bt",
    ]
)


def _words(value: str) -> str:
    return r"\s+".join(re.escape(token) for token in value.split())


@dataclass(frozen=True, slots=True)
class HungarianSurfaceForms(SurfaceForms):
    """Hungarian: the vault's case suffixes plus stem-changing forms.

    - final ``a``/``e`` lengthens before most suffixes: ``Anna`` -> ``Annának``;
    - a final digraph doubles before ``-val``/``-vá``: ``Kovács`` -> ``Kováccsal``.
    """

    stopwords: frozenset[str] = STOPWORDS

    def stem_variants(self, value: str, entity_type: EntityType) -> list[str]:
        value = value.strip()
        if not value or not value[-1].isalpha():
            return []
        variants: list[str] = []
        last = value[-1].casefold()
        suffixes = "|".join(sorted(_HU_LENGTHENED_SUFFIXES, key=len, reverse=True))
        if last in {"a", "e"}:
            long_vowel = "á" if last == "a" else "é"
            variants.append(_words(value[:-1]) + long_vowel + f"(?:{suffixes})")
        for digraph in _HU_DIGRAPHS:
            if value.casefold().endswith(digraph):
                doubled = value[:-2] + digraph[0] + value[-2:]
                variants.append(_words(doubled) + "(?:al|el|á|é)")
                break
        return variants
