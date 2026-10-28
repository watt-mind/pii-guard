"""Polish surface forms for the evaluation: stopwords. Part of the Polish language pack.

Street-type words, month names (nominative and genitive, as dates write them), legal forms and
forms of address, which the partial-leak check ignores. No stem variants: the evaluation's
leak check matches the written forms the fixtures label.
"""

from __future__ import annotations

from pii_guard.languages import SurfaceForms

__all__ = ["STOPWORDS", "SURFACE_FORMS"]

STOPWORDS = frozenset(
    {
        "ul",
        "ulica",
        "ulicy",
        "al",
        "aleja",
        "alei",
        "aleje",
        "os",
        "osiedle",
        "pl",
        "plac",
        "placu",
        "m",
        "lok",
        "nr",
        "w",
        "we",
        "z",
        "przy",
        "styczeń",
        "luty",
        "marzec",
        "kwiecień",
        "maj",
        "czerwiec",
        "lipiec",
        "sierpień",
        "wrzesień",
        "październik",
        "listopad",
        "grudzień",
        "stycznia",
        "lutego",
        "marca",
        "kwietnia",
        "maja",
        "czerwca",
        "lipca",
        "sierpnia",
        "września",
        "października",
        "listopada",
        "grudnia",
        "sp",
        "o.o",
        "s.a",
        "sa",
        "spółka",
        "pan",
        "pani",
        "dr",
        "mgr",
        "inż",
        "prof",
    }
)

SURFACE_FORMS = SurfaceForms(stopwords=STOPWORDS)
