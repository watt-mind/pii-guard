"""Dutch surface forms for the evaluation: stopwords. Part of the Dutch language pack.

Street-type words, surname prefixes, month names, legal forms and forms of address, which the
partial-leak check ignores. Dutch names keep their stem (the genitive ``-s`` is a detachable
suffix from the vault's matcher), so there are no stem variants.
"""

from __future__ import annotations

from pii_guard.languages import SurfaceForms

__all__ = ["STOPWORDS", "SURFACE_FORMS"]

STOPWORDS = frozenset(
    {
        "straat",
        "laan",
        "weg",
        "plein",
        "gracht",
        "kade",
        "singel",
        "dijk",
        "steeg",
        "markt",
        "hs",
        "bis",
        "van",
        "de",
        "der",
        "den",
        "het",
        "ten",
        "ter",
        "'t",
        "'s",
        "in",
        "op",
        "aan",
        "bij",
        "januari",
        "februari",
        "maart",
        "april",
        "mei",
        "juni",
        "juli",
        "augustus",
        "september",
        "oktober",
        "november",
        "december",
        "bv",
        "b.v",
        "nv",
        "n.v",
        "vof",
        "v.o.f",
        "cv",
        "c.v",
        "dhr",
        "mevr",
        "mw",
        "heer",
        "mevrouw",
        "dr",
        "mr",
        "drs",
        "ir",
        "ing",
        "prof",
    }
)

SURFACE_FORMS = SurfaceForms(stopwords=STOPWORDS)
