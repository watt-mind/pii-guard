"""The Polish language pack (``pl``, LAB-1400), built by following ``docs/languages.md``.

- rules (:mod:`.rules`): PESEL, NIP, REGON, ID-card and passport numbers next to their label
  everywhere, and the EU VAT number ``PL`` + NIP; unlabelled identifiers, national phone
  numbers and addresses (``ul. Kwiatowa 12/5, 00-950 Warszawa``) in Polish text (Polish IBANs
  and ``+48`` numbers are covered by the language-independent rules);
- checksums (:mod:`.checksums`): PESEL (with its date of birth), NIP, REGON 9/14, ID card and
  passport;
- cue words (``cues.tsv``), so a labelled number is masked even when its check digit fails, and
  a driving-licence number (no check digit) after ``prawo jazdy``;
- inflection (:mod:`.inflection`): the case endings that leave a name intact;
- LLM prompt notes (``prompt.md``), ID-card captions (``captions.tsv``), brand names
  (``brands.tsv``), eval stopwords (:mod:`.forms`) and the hand-written smoke set
  ``eval/fixtures/pl-smoke.jsonl``.

No lexicons: the Polish pack does not generate a synthetic corpus yet.
"""

from __future__ import annotations

from importlib.resources import files

from pii_guard.languages import LanguagePack

__all__ = ["pack"]


def pack() -> LanguagePack:
    from pii_guard.languages.pl import forms, inflection, rules

    return LanguagePack(
        code="pl",
        name="Polish",
        prompt=files(__name__).joinpath("prompt.md"),
        smoke_fixtures=("pl-smoke.jsonl",),
        everywhere=rules.EVERYWHERE,
        rules=rules.RULES,
        inflection=inflection.PolishCaseMatcher(),
        surface_forms=forms.SURFACE_FORMS,
        allow_suffix=True,  # "Nowaka": a name runs on into its case ending
        captions=files(__name__).joinpath("captions.tsv"),
        cues=files(__name__).joinpath("cues.tsv"),
        brands=files(__name__).joinpath("brands.tsv"),
    )
