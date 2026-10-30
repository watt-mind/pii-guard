"""The German language pack (``de``): the worked example of ``docs/languages.md``.

- rules (:mod:`.rules`): Sozialversicherungsnummer and labelled Steuer-ID everywhere;
  unlabelled Steuer-ID, national phone numbers and addresses in German text (German IBANs and
  ``+49`` numbers are covered by the language-independent rules);
- checksums (:mod:`.checksums`): Steuer-ID (ISO 7064 MOD 11,10) and Versicherungsnummer;
- inflection (:mod:`.inflection`): the genitive ``-s``;
- LLM prompt notes (``prompt.md``) with the generic entity types; NER and the LLM need nothing
  else, they are multilingual;
- eval stopwords (:mod:`.forms`) and the hand-written smoke set ``eval/fixtures/de-smoke.jsonl``;
- the synthetic corpus: fictional identities (:mod:`.identities`, hand-curated name, street and
  town lists) and document templates (``corpus.toml``); a sample is committed as
  ``eval/fixtures/de-synth-sample.jsonl``.

No lexicons (``pii_guard.lang``): the generator's lists live in :mod:`.identities`.
"""

from __future__ import annotations

from importlib.resources import files
from typing import TYPE_CHECKING

from pii_guard.languages import LanguagePack

if TYPE_CHECKING:
    import random

    from pii_guard.eval.identities import IdentityGenerator

__all__ = ["pack"]


def _identities(rng: random.Random) -> IdentityGenerator:
    from pii_guard.languages.de.identities import GermanIdentities

    return GermanIdentities(rng)


def pack() -> LanguagePack:
    from pii_guard.languages.de import forms, inflection, rules

    return LanguagePack(
        code="de",
        name="German",
        prompt=files(__name__).joinpath("prompt.md"),
        smoke_fixtures=("de-smoke.jsonl",),
        everywhere=rules.EVERYWHERE,
        rules=rules.RULES,
        inflection=inflection.GermanGenitiveMatcher(),
        surface_forms=forms.SURFACE_FORMS,
        allow_suffix=True,  # "Annas": a name runs on into the genitive
        captions=files(__name__).joinpath("captions.tsv"),
        cues=files(__name__).joinpath("cues.tsv"),
        brands=files(__name__).joinpath("brands.tsv"),
        identity_generator=_identities,
        corpus_templates=files(__name__).joinpath("corpus.toml"),
    )
