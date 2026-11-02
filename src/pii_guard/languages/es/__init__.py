"""The Spanish language pack (``es``, LAB-1775), built by following ``docs/languages.md``.

- rules (:mod:`.rules`): DNI / NIF and NIE everywhere (eight digits or ``X``/``Y``/``Z`` and
  seven, with the mod-23 check letter), and a company CIF next to its label; national phone
  numbers and addresses (``Calle del Olmo 14, 3.º B, 28012 Madrid``) in Spanish text (Spanish
  IBANs and ``+34`` numbers are covered by the language-independent rules);
- checksums (:mod:`.checksums`): DNI, NIE and CIF;
- cue words (``cues.tsv``), so a labelled number is masked even when its check letter fails,
  and a passport, social security or driving-licence number after its label;
- LLM prompt notes (``prompt.md``), ID-card captions (``captions.tsv``), brand names
  (``brands.tsv``), reference words (``references.tsv``), eval stopwords (:mod:`.forms`) and
  the hand-written smoke set ``eval/fixtures/es-smoke.jsonl``, plus the phase-1 gates
  ``eval/fixtures/eu/es-*.jsonl``.

No inflection matcher: Spanish names do not decline, so a value never runs on into a longer
word (``allow_suffix=False``). No lexicons: the Spanish pack does not generate a synthetic
corpus yet.
"""

from __future__ import annotations

from importlib.resources import files

from pii_guard.languages import LanguagePack

__all__ = ["pack"]


def pack() -> LanguagePack:
    from pii_guard.languages.es import forms, rules

    return LanguagePack(
        code="es",
        name="Spanish",
        prompt=files(__name__).joinpath("prompt.md"),
        smoke_fixtures=("es-smoke.jsonl", "eu/es-smoke.jsonl", "eu/es-inflection.jsonl"),
        everywhere=rules.EVERYWHERE,
        rules=rules.RULES,
        surface_forms=forms.SURFACE_FORMS,
        allow_suffix=False,  # "García" never runs on into a longer word
        captions=files(__name__).joinpath("captions.tsv"),
        cues=files(__name__).joinpath("cues.tsv"),
        brands=files(__name__).joinpath("brands.tsv"),
        references=files(__name__).joinpath("references.tsv"),
    )
