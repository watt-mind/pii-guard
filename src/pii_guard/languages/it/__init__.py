"""The Italian language pack (``it``, LAB-1776), built by following ``docs/languages.md``.

- rules (:mod:`.rules`): the codice fiscale (omocodia included), the EU VAT number ``IT`` +
  partita IVA and a labelled CIE number everywhere; a labelled partita IVA, an unlabelled CIE
  number, national phone numbers and addresses (``Via dei Mille 27, 40121 Bologna``) in Italian
  text (Italian IBANs and ``+39`` numbers are covered by the language-independent rules);
- checksums (:mod:`.checksums`): the codice fiscale check letter (odd/even tables, mod 26) and
  the partita IVA (Luhn, office code);
- cue words (``cues.tsv``), so a labelled number is masked even when its check character fails,
  and a passport or driving-licence number (no check character) after ``passaporto`` or
  ``patente``; the ``-`` cues and reference words for orders, invoices, customers, references
  and protocol numbers;
- LLM prompt notes (``prompt.md``), CIE and passport captions (``captions.tsv``), brand names
  (``brands.tsv``), eval stopwords (:mod:`.forms`) and the hand-written smoke set
  ``eval/fixtures/it-smoke.jsonl``, with the EU-wave gates ``eval/fixtures/eu/it-*.jsonl``.

No inflection matcher: Italian names do not inflect, and a name never runs on into a longer
word (``allow_suffix=False``); elision (``dell'avv. Rinaldi``) leaves the name intact. No
lexicons: the Italian pack does not generate a synthetic corpus yet.
"""

from __future__ import annotations

from importlib.resources import files

from pii_guard.languages import LanguagePack

__all__ = ["pack"]


def pack() -> LanguagePack:
    from pii_guard.languages.it import forms, rules

    return LanguagePack(
        code="it",
        name="Italian",
        prompt=files(__name__).joinpath("prompt.md"),
        smoke_fixtures=("it-smoke.jsonl", "eu/it-smoke.jsonl", "eu/it-inflection.jsonl"),
        everywhere=rules.EVERYWHERE,
        rules=rules.RULES,
        surface_forms=forms.SURFACE_FORMS,
        allow_suffix=False,  # names do not inflect: "Ricci" never runs on into a longer word
        captions=files(__name__).joinpath("captions.tsv"),
        cues=files(__name__).joinpath("cues.tsv"),
        brands=files(__name__).joinpath("brands.tsv"),
        references=files(__name__).joinpath("references.tsv"),
    )
