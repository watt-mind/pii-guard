"""Building blocks shared by every rule module: the hit tuple and regex fragments."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import NamedTuple

from pii_guard.types import EntityType


class _Hit(NamedTuple):
    start: int
    end: int
    entity_type: EntityType
    score: float
    subtype: str | None = None  # e.g. the SECRET rule that matched (``Span.subtype``)


#: A rule takes the whole text and yields validated hits.
Rule = Callable[[str], Iterator[_Hit]]

# A number must not continue a longer digit run, directly or through a date/decimal separator
# ("2026-10-26", "1.234.567"), or be followed by a currency (an amount, not an identifier),
# also after the Hungarian ",-" of a round amount ("123 456 788,- Ft").
#
# Nor may it touch a letter or "_": digits glued to letters are part of a longer token, such as
# a sha256 or git hash ("…885d392771036a9d…"), a base64 digest or a code name, and one digit
# run in ten passes a mod-10 check by chance (LAB-1282). Cued numbers refuse the same ("Nr123",
# ``languages/cues.py``).
#
# A comma between digits is a thousands or decimal mark only when 1-3 digits follow it
# ("1,234,567", "27358,76"). Otherwise it separates CSV fields ("…6714,8461269322,ORD-…": a phone
# field, then a tax number), and the number on either side is found as on its own (LAB-1367).
NOT_IN_WORD_BEFORE = r"(?<![^\W\d])"
NOT_IN_WORD_AFTER = r"(?![^\W\d])"
NUM_START = r"(?<!\d)(?<!\d[-./])(?:(?<!\d,)|(?=\d{4}))" + NOT_IN_WORD_BEFORE
NUM_END = r"(?!\d)(?![-./]\d)(?!,\d{1,3}(?!\d))" + NOT_IN_WORD_AFTER
NOT_AMOUNT = r"(?!\s?(?:,-\s?)?(?:Ft|HUF|forint|EUR|€)(?!\w))"
# Space-grouped numbers must not be part of a longer space-grouped number ("1 234 567 890").
NO_GROUP_BEFORE = r"(?<!\d )"
NO_GROUP_AFTER = r"(?! \d)"


def context_before(text: str, start: int, keywords: tuple[str, ...], window: int = 40) -> bool:
    """True if one of ``keywords`` (lowercase) appears in the ``window`` chars before ``start``."""
    before = text[max(0, start - window) : start].casefold()
    return any(k in before for k in keywords)


# What directly before a number makes it a business number or an amount, not personal data:
# an order, invoice or reference label ("Order number:", "Rendelésszám:", "Rechnung"), an
# identifier prefix ("INV-", "SZ-", "#") or a currency ("$", "EUR"). Only the label's last
# word and a little punctuation may stand between it and the number.
_REFERENCE_WORD = (
    r"order|invoice|inv|receipt|reference|ref|booking|tracking|shipment|ticket|item|sku"
    r"|article|case|total|amount|price|balance"
    r"|\w*rendel[ée]s\w*|sz[áa]ml[áa]\w*|nyugta\w*|hivatkoz[áa]s\w*|sorsz[áa]m\w*"
    r"|ügysz[áa]m\w*|iktat[óo]sz[áa]m\w*|cikksz[áa]m\w*|össz?eg\w*|v[ée]g[öo]sszeg\w*"
    r"|bestell\w*|rechnung\w*|auftrag\w*|referenz\w*|artikel\w*|vorgang\w*|betrag\w*"
    r"|summe\w*"
)
_REFERENCE_BEFORE_RE = re.compile(
    rf"(?:(?i:(?<!\w)(?:{_REFERENCE_WORD})"
    r"(?:[ \t]*(?:number|no|nr|num|id|sz[áa]m|sz[áa]ma|nummer)(?!\w)\.?)?)"
    r"[ \t:#=()\-]*(?:[A-Z]{1,6}[-/#][ \t]?)?"
    r"|(?<![\w-])[A-Z]{1,6}-|#[ \t]?"
    r"|(?:[$€£¥]|(?<!\w)(?:USD|EUR|GBP|CHF|HUF|Ft|forint)(?!\w)\.?)[ \t]?)$"
)
_REFERENCE_WINDOW = 40


def reference_or_amount_before(text: str, start: int) -> bool:
    """True if an order/invoice/reference label, an ID prefix or a currency ends at ``start``."""
    return _REFERENCE_BEFORE_RE.search(text, max(0, start - _REFERENCE_WINDOW), start) is not None


# A legal-form word after a settlement makes it part of a company name ("1999 Budapest Kft.",
# "Budapest Bank Zrt.", "10115 Berlin GmbH"), so the number before it is not a postcode. Up to
# two more capitalised words of the name may stand between the place and the form (LAB-1227).
_LEGAL_FORM = (
    r"nonprofit[ \t]+kft|kft|zrt|nyrt|bt|kkt|kht|rt|gmbh|mbh|ag|kg|ohg|ug|ltd|llc|inc|plc|corp"
)
_LEGAL_FORM_AFTER_RE = re.compile(
    r"(?:[ \t]+(?=[A-ZÀ-ÖØ-ÞŐŰ])\w[\w&\-]*){0,2}?"
    rf"[ \t]+(?i:{_LEGAL_FORM})\.?(?![\w])"
)


def legal_form_after(text: str, end: int) -> bool:
    """True if a legal-form word (``Kft.``, ``GmbH``, ``Ltd``) follows ``end`` within a name."""
    return _LEGAL_FORM_AFTER_RE.match(text, end) is not None
