"""Italian surface forms for the evaluation: stopwords. Part of the Italian language pack.

Street-type words, month names, articles and prepositions inside names and addresses, legal
forms and forms of address, which the partial-leak check ignores. No stem variants: Italian
names do not inflect.
"""

from __future__ import annotations

from pii_guard.languages import SurfaceForms

__all__ = ["STOPWORDS", "SURFACE_FORMS"]

STOPWORDS = frozenset(
    {
        "via",
        "viale",
        "piazza",
        "piazzale",
        "corso",
        "largo",
        "vicolo",
        "strada",
        "contrada",
        "lungomare",
        "borgo",
        "località",
        "frazione",
        "n",
        "nr",
        "int",
        "scala",
        "di",
        "de",
        "del",
        "dei",
        "degli",
        "della",
        "delle",
        "dello",
        "da",
        "e",
        "in",
        "il",
        "la",
        "lo",
        "san",
        "santa",
        "gennaio",
        "febbraio",
        "marzo",
        "aprile",
        "maggio",
        "giugno",
        "luglio",
        "agosto",
        "settembre",
        "ottobre",
        "novembre",
        "dicembre",
        "srl",
        "s.r.l",
        "srls",
        "spa",
        "s.p.a",
        "snc",
        "s.n.c",
        "sas",
        "s.a.s",
        "sig",
        "sig.ra",
        "signor",
        "signora",
        "dott",
        "dott.ssa",
        "avv",
        "ing",
        "prof",
        "geom",
        "rag",
    }
)

SURFACE_FORMS = SurfaceForms(stopwords=STOPWORDS)
