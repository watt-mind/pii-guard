"""The English language pack (``en``).

- rules (:mod:`.rules`): US SSN and UK NINO everywhere; UK/US phone numbers, UK postcodes, US
  ZIP codes, UK plates and labelled passport/licence numbers in English text;
- inflection (:mod:`.inflection`): the possessive ``'s``;
- LLM prompt notes (``prompt.md``); names do not run on into longer words;
- eval stopwords (:mod:`.forms`) and a street-type lexicon in ``pii_guard/lang/data/en``;
- the synthetic corpus: ``EnglishIdentities`` and ``eval/templates/en.toml``.
"""

from __future__ import annotations

from importlib.resources import files
from typing import TYPE_CHECKING

from pii_guard.languages import LanguagePack, LexiconSpec

if TYPE_CHECKING:
    import random

    from pii_guard.eval.identities import IdentityGenerator

__all__ = ["pack"]


def _identities(rng: random.Random) -> IdentityGenerator:
    from pii_guard.eval.identities import EnglishIdentities

    return EnglishIdentities(rng)


def pack() -> LanguagePack:
    from pii_guard.languages.en import forms, inflection, rules

    return LanguagePack(
        code="en",
        name="English",
        prompt=files(__name__).joinpath("prompt.md"),
        smoke_fixtures=("en-smoke.jsonl",),
        everywhere=rules.EVERYWHERE,
        rules=rules.RULES,
        inflection=inflection.EnglishPossessiveMatcher(),
        surface_forms=forms.SURFACE_FORMS,
        allow_suffix=False,
        lexicons=LexiconSpec(
            directory=files("pii_guard.lang").joinpath("data", "en"),
            kinds=("street_types",),
        ),
        captions=files(__name__).joinpath("captions.tsv"),
        cues=files(__name__).joinpath("cues.tsv"),
        brands=files(__name__).joinpath("brands.tsv"),
        references=files(__name__).joinpath("references.tsv"),
        identity_generator=_identities,
        corpus_templates=files("pii_guard.eval").joinpath("templates", "en.toml"),
    )
