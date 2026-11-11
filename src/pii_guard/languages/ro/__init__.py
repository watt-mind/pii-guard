"""The Romanian language pack (``ro``, LAB-1778), built by following ``docs/languages.md``.

- rules (:mod:`.rules`): the CNP (date of birth, county code and check digit) everywhere; a
  labelled CIF/CUI, a labelled identity card series and number, national phone numbers and
  addresses (``Strada Teilor nr. 15, ap. 7, 400123 Cluj-Napoca``) in Romanian text (Romanian
  IBANs and ``+40`` numbers are covered by the language-independent rules);
- checksums (:mod:`.checksums`): the CNP and the CIF/CUI;
- cue words (``cues.tsv``), so a labelled number is masked even when its check digit fails,
  and a passport or driving-licence number (no check digit) after ``pașaport`` or ``permis de
  conducere``; the ``-`` cues and reference words for orders, invoices, receipts, customers,
  references and shipments;
- inflection (:mod:`.inflection`): the genitive/dative and vocative endings and the ``-a`` ->
  ``-ei`` stem change of feminine names (``Maria`` -> ``Mariei``);
- LLM prompt notes (``prompt.md``), identity card and passport captions (``captions.tsv``),
  brand names (``brands.tsv``), eval stopwords and stem variants (:mod:`.forms`) and the
  hand-written smoke set ``eval/fixtures/ro-smoke.jsonl``, with the EU-wave gates
  ``eval/fixtures/eu/ro-*.jsonl``.

No lexicons: the Romanian pack does not generate a synthetic corpus yet.
"""

from __future__ import annotations

from importlib.resources import files

from pii_guard.languages import LanguagePack

__all__ = ["pack"]


def pack() -> LanguagePack:
    from pii_guard.languages.ro import forms, inflection, rules

    return LanguagePack(
        code="ro",
        name="Romanian",
        prompt=files(__name__).joinpath("prompt.md"),
        smoke_fixtures=("ro-smoke.jsonl", "eu/ro-smoke.jsonl", "eu/ro-inflection.jsonl"),
        everywhere=rules.EVERYWHERE,
        rules=rules.RULES,
        inflection=inflection.RomanianCaseMatcher(),
        surface_forms=forms.SURFACE_FORMS,
        allow_suffix=True,  # "Popescului": a name runs on into its case ending
        captions=files(__name__).joinpath("captions.tsv"),
        cues=files(__name__).joinpath("cues.tsv"),
        brands=files(__name__).joinpath("brands.tsv"),
        references=files(__name__).joinpath("references.tsv"),
    )
