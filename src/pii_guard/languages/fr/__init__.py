"""The French language pack (``fr``, LAB-1774), built by following ``docs/languages.md``.

- rules (:mod:`.rules`): the NIR (numéro de sécurité sociale) everywhere, next to its label or
  unlabelled with a calendar month, and the numéro fiscal (SPI) next to its label; national
  phone numbers and addresses (``12 rue des Lilas, 69003 Lyon``) in French text (French IBANs
  and ``+33`` numbers are covered by the language-independent rules);
- checksums (:mod:`.checksums`): the NIR key (with Corsica's 2A/2B) and the SPI's mod 511;
- cue words (``cues.tsv``), so a labelled number is masked even when its key fails, and
  passport, CNI and driving-licence numbers (no printed check digit) after their label;
- no inflection matcher: French names do not inflect, so the vault matches them exactly, and
  an elided article stays outside the placeholder (``d'[[PERSON_7f3a]]``);
- LLM prompt notes (``prompt.md``), ID-card captions (``captions.tsv``), brand names
  (``brands.tsv``), reference words (``references.tsv``), eval stopwords (:mod:`.forms`) and
  the hand-written smoke set ``eval/fixtures/fr-smoke.jsonl``, plus the EU gates
  ``eval/fixtures/eu/fr-smoke.jsonl`` and ``eu/fr-inflection.jsonl``.

No lexicons: the French pack does not generate a synthetic corpus yet.
"""

from __future__ import annotations

from importlib.resources import files

from pii_guard.languages import LanguagePack

__all__ = ["pack"]


def pack() -> LanguagePack:
    from pii_guard.languages.fr import forms, rules

    return LanguagePack(
        code="fr",
        name="French",
        prompt=files(__name__).joinpath("prompt.md"),
        smoke_fixtures=("fr-smoke.jsonl", "eu/fr-smoke.jsonl", "eu/fr-inflection.jsonl"),
        everywhere=rules.EVERYWHERE,
        rules=rules.RULES,
        surface_forms=forms.SURFACE_FORMS,
        allow_suffix=False,  # "Garnier" never runs on into a longer word
        captions=files(__name__).joinpath("captions.tsv"),
        cues=files(__name__).joinpath("cues.tsv"),
        brands=files(__name__).joinpath("brands.tsv"),
        references=files(__name__).joinpath("references.tsv"),
    )
