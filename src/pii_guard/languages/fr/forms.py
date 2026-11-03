"""French surface forms for the evaluation: stopwords. Part of the French language pack.

Street-type words, the articles and prepositions of street names, month names, legal forms
and forms of address, which the partial-leak check ignores. No stem variants: French names
do not inflect, so the leak check matches the written forms the fixtures label.
"""

from __future__ import annotations

from pii_guard.languages import SurfaceForms

__all__ = ["STOPWORDS", "SURFACE_FORMS"]

STOPWORDS = frozenset(
    {
        "rue",
        "avenue",
        "av",
        "boulevard",
        "bd",
        "place",
        "allée",
        "chemin",
        "impasse",
        "quai",
        "cours",
        "route",
        "square",
        "passage",
        "faubourg",
        "cedex",
        "bis",
        "ter",
        "de",
        "du",
        "des",
        "la",
        "le",
        "les",
        "d",
        "l",
        "à",
        "au",
        "aux",
        "en",
        "sur",
        "et",
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
        "sa",
        "sas",
        "sasu",
        "sarl",
        "eurl",
        "sci",
        "snc",
        "m",
        "mme",
        "mlle",
        "monsieur",
        "madame",
        "mademoiselle",
        "me",
        "dr",
        "pr",
    }
)

SURFACE_FORMS = SurfaceForms(stopwords=STOPWORDS)
