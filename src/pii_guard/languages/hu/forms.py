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
# The family / possessive suffix chain after a lengthened stem: ``-é`` ("Hajna's"), ``-ék``
# ("the Hajna family"), ``-éi`` ("Hajna's things"), each with an optional case ending:
# ``Hajnáéknál``, ``Kendééknek``, ``Hubáéval``, ``Hajnáéit``. Written out from the grammar,
# not taken from the vault's matcher (ADR 0008). ``-ék`` takes a linking vowel before ``-t``
# and assimilates ``-val``/``-vá`` (``Hajnáékat``, ``Hajnáékkal``); ``-é``/``-éi`` take the
# endings as they are (``Hajnáét``, ``Hajnáéval``, ``Hajnáéinak``).
_HU_CHAIN_CASES = (
    "nak", "nek", "ban", "ben", "ba", "be", "ból", "ből", "hoz", "hez", "höz", "nál", "nél",
    "tól", "től", "ra", "re", "ról", "ről", "n", "ig", "ért", "ként", "é",
)  # fmt: skip
_HU_AFTER_EK = (*_HU_CHAIN_CASES, "at", "et", "kal", "kel", "ká", "ké")
_HU_AFTER_E = (*_HU_CHAIN_CASES, "t", "val", "vel", "vá", "vé")


def _alternation(options: tuple[str, ...]) -> str:
    return "|".join(sorted(set(options), key=lambda s: (-len(s), s)))


_HU_CHAIN = (
    f"é(?:k(?:{_alternation(_HU_AFTER_EK)})?"
    f"|i(?:{_alternation(_HU_AFTER_E)})?"
    f"|(?:{_alternation(_HU_AFTER_E)}))?"
)
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

    - final ``a``/``e`` lengthens before most suffixes: ``Anna`` -> ``Annának``, also before
      the family / possessive chain: ``Hajna`` -> ``Hajnáéknál``, ``Kende`` -> ``Kendééknek``;
    - a final digraph doubles before ``-val``/``-vá``: ``Kovács`` -> ``Kováccsal``.
    """

    stopwords: frozenset[str] = STOPWORDS

    def stem_variants(self, value: str, entity_type: EntityType) -> list[str]:
        value = value.strip()
        if not value or not value[-1].isalpha():
            return []
        variants: list[str] = []
        last = value[-1].casefold()
        suffixes = _alternation(_HU_LENGTHENED_SUFFIXES)
        if last in {"a", "e"}:
            long_vowel = "á" if last == "a" else "é"
            variants.append(_words(value[:-1]) + long_vowel + f"(?:{_HU_CHAIN}|{suffixes})")
        for digraph in _HU_DIGRAPHS:
            if value.casefold().endswith(digraph):
                doubled = value[:-2] + digraph[0] + value[-2:]
                variants.append(_words(doubled) + "(?:al|el|á|é)")
                break
        return variants
