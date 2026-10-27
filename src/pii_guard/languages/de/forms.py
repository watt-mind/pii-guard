"""German surface forms for the evaluation: stopwords. Part of the German language pack.

German names keep their stem (the genitive ``-s`` is a detachable suffix from the vault's
matcher), so there are no stem variants.
"""

from __future__ import annotations

from pii_guard.languages import SurfaceForms

__all__ = ["STOPWORDS", "SURFACE_FORMS"]

STOPWORDS = frozenset(
    {
        "straße",
        "strasse",
        "str",
        "weg",
        "platz",
        "allee",
        "gasse",
        "ring",
        "damm",
        "ufer",
        "am",
        "an",
        "der",
        "die",
        "das",
        "im",
        "in",
        "hausnummer",
        "etage",
        "og",
        "eg",
        "wohnung",
        "whg",
        "postfach",
        "januar",
        "februar",
        "märz",
        "april",
        "mai",
        "juni",
        "juli",
        "august",
        "september",
        "oktober",
        "november",
        "dezember",
        "jan",
        "feb",
        "mär",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "okt",
        "nov",
        "dez",
        "gmbh",
        "ag",
        "kg",
        "ohg",
        "mbh",
        "ev",
        "e.v",
        "gbr",
        "ug",
        "co",
        "herr",
        "frau",
        "dr",
    }
)

SURFACE_FORMS = SurfaceForms(stopwords=STOPWORDS)
