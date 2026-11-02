"""Spanish surface forms for the evaluation: stopwords. Part of the Spanish language pack.

Street-type words, the connectors inside street and place names, month names, legal forms
and forms of address, which the partial-leak check ignores. No stem variants: Spanish names
do not decline.
"""

from __future__ import annotations

from pii_guard.languages import SurfaceForms

__all__ = ["STOPWORDS", "SURFACE_FORMS"]

STOPWORDS = frozenset(
    {
        "calle",
        "c",
        "avenida",
        "avda",
        "av",
        "plaza",
        "pza",
        "paseo",
        "camino",
        "carretera",
        "ctra",
        "ronda",
        "travesía",
        "glorieta",
        "urbanización",
        "urb",
        "pasaje",
        "rambla",
        "vía",
        "de",
        "del",
        "la",
        "las",
        "los",
        "el",
        "y",
        "n",
        "nº",
        "núm",
        "s/n",
        "bajo",
        "piso",
        "puerta",
        "izda",
        "dcha",
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
        "s.l",
        "sl",
        "s.a",
        "sa",
        "s.l.u",
        "slu",
        "sociedad",
        "limitada",
        "anónima",
        "sr",
        "sra",
        "srta",
        "d",
        "dña",
        "don",
        "doña",
        "dr",
        "dra",
    }
)

SURFACE_FORMS = SurfaceForms(stopwords=STOPWORDS)
