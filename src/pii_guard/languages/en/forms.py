"""English surface forms for the evaluation: stopwords. Part of the English language pack."""

from __future__ import annotations

from pii_guard.languages import SurfaceForms

__all__ = ["STOPWORDS", "SURFACE_FORMS"]

_MONTHS_EN = "january february march april may june july august september october november december"
STOPWORDS = frozenset(
    (
        "street st road rd avenue ave lane ln drive dr close court ct place pl square flat apt "
        "apartment floor suite unit house the and of ltd llc inc plc " + _MONTHS_EN
    ).split()
)


SURFACE_FORMS = SurfaceForms(stopwords=STOPWORDS)
