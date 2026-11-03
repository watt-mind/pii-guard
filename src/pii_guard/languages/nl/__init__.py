"""The Dutch language pack (``nl``, LAB-1777), built by following ``docs/languages.md``.

- rules (:mod:`.rules`): a labelled BSN (burgerservicenummer, sofinummer) everywhere; an
  unlabelled BSN, national phone numbers, postcodes (``3521 AB Utrecht``) and addresses
  (``Lindelaan 42, 3521 AB Utrecht``) in Dutch text (Dutch IBANs and ``+31`` numbers are
  covered by the language-independent rules);
- checksums (:mod:`.checksums`): the BSN elfproef;
- cue words (``cues.tsv``), so a labelled BSN is masked even when its elfproef fails, and a
  passport, ID-card or driving-licence number (no check digit) after ``paspoort``,
  ``identiteitskaart`` or ``rijbewijs``; the ``-`` cues and reference words for orders,
  invoices, customers, payment references and the company register (KvK, btw);
- inflection (:mod:`.inflection`): the genitive ``-s`` (``Pieters fiets``, ``Anna's``);
- LLM prompt notes (``prompt.md``), ID-card and passport captions (``captions.tsv``), brand
  names (``brands.tsv``), eval stopwords (:mod:`.forms`) and the hand-written smoke set
  ``eval/fixtures/nl-smoke.jsonl``, with the EU-wave gates ``eval/fixtures/eu/nl-*.jsonl``.

No lexicons: the Dutch pack does not generate a synthetic corpus yet.
"""

from __future__ import annotations

from importlib.resources import files

from pii_guard.languages import LanguagePack

__all__ = ["pack"]


def pack() -> LanguagePack:
    from pii_guard.languages.nl import forms, inflection, rules

    return LanguagePack(
        code="nl",
        name="Dutch",
        prompt=files(__name__).joinpath("prompt.md"),
        smoke_fixtures=("nl-smoke.jsonl", "eu/nl-smoke.jsonl", "eu/nl-inflection.jsonl"),
        everywhere=rules.EVERYWHERE,
        rules=rules.RULES,
        inflection=inflection.DutchGenitiveMatcher(),
        surface_forms=forms.SURFACE_FORMS,
        allow_suffix=True,  # "Pieters": a name runs on into the genitive
        captions=files(__name__).joinpath("captions.tsv"),
        cues=files(__name__).joinpath("cues.tsv"),
        brands=files(__name__).joinpath("brands.tsv"),
        references=files(__name__).joinpath("references.tsv"),
    )
