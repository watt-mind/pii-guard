"""Building blocks shared by every rule module: the hit tuple and regex fragments."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from functools import lru_cache
from typing import NamedTuple

from pii_guard.languages import on_change
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
# ("1,234,567", "27358,76"). Otherwise it separates CSV fields ("…6714,8461269321,ORD-…": a phone
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
# an order, invoice or reference label ("Order number:", "Rendelésszám:", "Rechnung",
# "Faktura nr", "numer zamówienia:"), an
# identifier prefix ("INV-", "SZ-", "#") or a currency ("$", "EUR"). Only the label's last
# word and a little punctuation may stand between it and the number.
#
# The labels are language-pack data (``references.tsv``, :mod:`pii_guard.languages.references`),
# so a new pack's reference words reach this check (LAB-1345, ADR 0008). The pattern below
# is the fallback for deployments without language packs; the active one is built from the
# packs (see :func:`_reference_word`).
_REFERENCE_WORD = (
    r"order|invoice|inv|receipt|reference|ref|booking|tracking|shipment|ticket|item|sku"
    r"|article|case|total|amount|price|balance"
    r"|\w*rendel[ée]s\w*|sz[áa]ml[áa]\w*|nyugta\w*|hivatkoz[áa]s\w*|sorsz[áa]m\w*"
    r"|ügysz[áa]m\w*|iktat[óo]sz[áa]m\w*|cikksz[áa]m\w*|össz?eg\w*|v[ée]g[öo]sszeg\w*"
    r"|bestell\w*|rechnung\w*|auftrag\w*|referenz\w*|artikel\w*|vorgang\w*|betrag\w*"
    r"|summe\w*"
    r"|faktur\w*|zam[óo]wieni\w*|paragon\w*|przesy[łl]k\w*|sygn\.?(?:[ \t]*akt)?|sygnatur\w*"
    r"|zleceni\w*|rezerwacj\w*|paczk\w*|zg[łl]oszeni\w*|transakcj\w*|kwot\w*|suma|saldo"
    r"|uchwa[łl]\w*|referencyjn\w*|klienta"
)


def _reference_word() -> str:
    """The reference-label alternation: every pack's ``rules``-scoped entries, or the fallback.

    Pack entries match their accented and unaccented spellings
    (:func:`pii_guard.languages.references.accent_pattern`); a ``*`` entry takes word
    suffixes. With no pack providing ``references.tsv`` the built-in :data:`_REFERENCE_WORD`
    applies, so a language without a pack keeps its behavior (LAB-1345).
    """
    from pii_guard.languages.references import pack_references, reference_alternation

    sets = [
        (code, [e for e in es if e.scope in ("both", "rules")]) for code, es in pack_references()
    ]
    sets = [(code, es) for code, es in sets if es]
    if not sets:
        return _REFERENCE_WORD
    return "|".join(reference_alternation(es, code) for code, es in sets)


_REFERENCE_BEFORE_TEMPLATE = (
    r"(?:(?i:(?<!\w)(?:{words})"
    r"(?:[ \t]*(?:number|no|nr|num|id|sz[áa]m|sz[áa]ma|nummer|numer)(?!\w)\.?)?)"
    r"[ \t:#=()\-]*(?:[A-Z]{{1,6}}[-/#][ \t]?)?"
    r"|(?<![\w-])[A-Z]{{1,6}}-|#[ \t]?"
    r"|(?:[$€£¥]|(?<!\w)(?:USD|EUR|GBP|CHF|HUF|Ft|forint|PLN|zł)(?!\w)\.?)[ \t]?)$"
)


@lru_cache(maxsize=1)
def _reference_before_re() -> re.Pattern[str]:
    """The compiled reference/amount/invoice-prefix lookbehind (LAB-1345: pack-sourced)."""
    return re.compile(_REFERENCE_BEFORE_TEMPLATE.format(words=_reference_word()))


# Rebuild the pattern when the set of packs changes (a registered pack's reference words
# apply to detectors created afterwards, like the packs' cue words).
on_change(_reference_before_re.cache_clear)
_REFERENCE_WINDOW = 40


def reference_or_amount_before(text: str, start: int) -> bool:
    """True if an order/invoice/reference label, an ID prefix or a currency ends at ``start``."""
    return _reference_before_re().search(text, max(0, start - _REFERENCE_WINDOW), start) is not None


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
