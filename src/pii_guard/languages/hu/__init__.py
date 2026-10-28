"""The Hungarian language pack (``hu``).

- rules (:mod:`.rules`): tax ID, TAJ, personal ID, giro accounts, company numbers, ``+36``
  phone numbers, ID documents, MRZ and parcel numbers everywhere; addresses validated against
  the gazetteer, postcodes, plates and unlabelled ID card numbers in Hungarian text; person
  names inside company names (:mod:`.companies`: ``Tóth és Társa Bt.``, ``... e.v.``);
- inflection (:mod:`.inflection`): case suffixes and the stem changes they cause;
- LLM prompt notes (``prompt.md``) and every Hungarian-specific entity type;
- eval surface forms (:mod:`.forms`) and the lexicons in ``pii_guard/lang/data/hu``.
"""

from __future__ import annotations

from importlib.resources import files

from pii_guard.languages import LanguagePack, LexiconSpec
from pii_guard.types import EntityType

__all__ = ["pack"]


def pack() -> LanguagePack:
    from pii_guard.lang import LEXICON_KINDS
    from pii_guard.languages.hu import forms, inflection, rules

    return LanguagePack(
        code="hu",
        name="Hungarian",
        prompt=files(__name__).joinpath("prompt.md"),
        smoke_fixtures=("hu-smoke.jsonl", "hu-inflection.jsonl", "hu-company-names.jsonl"),
        everywhere=rules.EVERYWHERE,
        rules=rules.RULES,
        inflection=inflection.HungarianSuffixMatcher(),
        surface_forms=forms.HungarianSurfaceForms(),
        country_entity_types=(
            EntityType.NATIONAL_ID_HU_TAX,
            EntityType.NATIONAL_ID_HU_TAJ,
            EntityType.COMPANY_ID_HU,
            EntityType.PARCEL_NUMBER_HU,
        ),
        allow_suffix=True,
        lexicons=LexiconSpec(
            directory=files("pii_guard.lang").joinpath("data", "hu"),
            kinds=(
                *LEXICON_KINDS,
                "recent_given_names_m",
                "recent_given_names_f",
                "common_word_surnames",
            ),
            merges={
                "given_names_m": ("given_names_m", "recent_given_names_m"),
                "given_names_f": ("given_names_f", "recent_given_names_f"),
            },
            structural={
                "budapest": "1",
                "debrecen": "40",
                "szeged": "67",
                "pécs": "76",
                "győr": "90",
                "miskolc": "35",
            },
        ),
        captions=files(__name__).joinpath("captions.tsv"),
        cues=files(__name__).joinpath("cues.tsv"),
        brands=files(__name__).joinpath("brands.tsv"),
    )
