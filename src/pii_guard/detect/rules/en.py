"""English language pack: UK and US identifiers and formats.

Run for every language (``EVERYWHERE``), because the format is distinctive and validated:

- US Social Security numbers written ``123-45-6789``, with the structural checks the SSA
  applies (area not ``000``, ``666`` or ``9xx``; group not ``00``; serial not ``0000``);
- UK National Insurance numbers (``AB 12 34 56 C``), with the prefix rules (no ``D F I Q U V``
  first, no ``D F I O Q U V`` second, no ``BG GB KN NK NT TN ZZ``) and suffix ``A``-``D``.

Run only for English text (``RULES``), because the format alone is ambiguous:

- UK national phone numbers (``020 7946 0000``, ``07700 900000``) and US/NANP numbers
  (``(202) 555-0100``, ``202-555-0100``, ``1-202-555-0100``); ``+44``/``+1`` numbers are found
  by the language-independent international rule;
- UK postcodes (``SW1A 1AA``) and US ZIP codes after a state abbreviation or a "ZIP" label;
- UK vehicle registrations in the current format (``AB12 CDE``);
- SSNs written with spaces or without separators, after an "SSN" / "social security" label;
- passport and driving licence numbers after a "passport" / "driving licence" label.

SSNs, NINOs, passport and licence numbers are ``ID_DOCUMENT`` (the taxonomy has no
country-specific type for them yet); postcodes and ZIP codes are ``ADDRESS``, like the
Hungarian postcode rule.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from pii_guard.detect.rules._base import (
    NO_GROUP_AFTER,
    NO_GROUP_BEFORE,
    NUM_END,
    NUM_START,
    Rule,
    _Hit,
    context_before,
)
from pii_guard.types import EntityType

__all__ = ["EVERYWHERE", "RULES", "is_valid_nino", "is_valid_ssn"]


# --- US Social Security number ----------------------------------------------


def is_valid_ssn(area: str, group: str, serial: str) -> bool:
    """Structural validity: ``AAA-GG-SSSS`` with no all-zero part, no 666 or 9xx area."""
    if (len(area), len(group), len(serial)) != (3, 2, 4):
        return False
    if not (area + group + serial).isdigit():
        return False
    return area not in {"000", "666"} and area[0] != "9" and group != "00" and serial != "0000"


_SSN_DASHED_RE = re.compile(
    NUM_START + NO_GROUP_BEFORE + r"(\d{3})-(\d{2})-(\d{4})" + NUM_END + NO_GROUP_AFTER
)
_SSN_LOOSE_RE = re.compile(
    NUM_START + NO_GROUP_BEFORE + r"(\d{3})( ?)(\d{2})\2(\d{4})" + NUM_END + NO_GROUP_AFTER
)
_SSN_CONTEXT = ("ssn", "social security", "soc. sec", "ss#", "ss #")


def _find_ssn(text: str) -> Iterator[_Hit]:
    for m in _SSN_DASHED_RE.finditer(text):
        if is_valid_ssn(m.group(1), m.group(2), m.group(3)):
            score = 0.95 if context_before(text, m.start(), _SSN_CONTEXT) else 0.85
            yield _Hit(m.start(), m.end(), EntityType.ID_DOCUMENT, score)


def _find_ssn_in_context(text: str) -> Iterator[_Hit]:
    """Spaced or unseparated SSNs need a label: 9 digits alone are too common."""
    for m in _SSN_LOOSE_RE.finditer(text):
        if is_valid_ssn(m.group(1), m.group(3), m.group(4)) and context_before(
            text, m.start(), _SSN_CONTEXT, window=30
        ):
            yield _Hit(m.start(), m.end(), EntityType.ID_DOCUMENT, 0.9)


# --- UK National Insurance number -------------------------------------------

_NINO_RE = re.compile(r"(?<![\w-])[A-Z]{2}( ?)\d{2}\1\d{2}\1\d{2}\1[A-D](?![\w-])")
_NINO_BAD_FIRST = frozenset("DFIQUV")
_NINO_BAD_SECOND = frozenset("DFIOQUV")
_NINO_BAD_PREFIXES = frozenset({"BG", "GB", "KN", "NK", "NT", "TN", "ZZ"})
_NINO_CONTEXT = ("national insurance", "nino", "ni number", "ni no")


def is_valid_nino(value: str) -> bool:
    """``AB123456C`` (no spaces): valid prefix letters, six digits, suffix A-D."""
    if len(value) != 9 or not value.isascii():
        return False
    prefix, digits, suffix = value[:2], value[2:8], value[8]
    return (
        prefix.isalpha()
        and prefix.isupper()
        and prefix[0] not in _NINO_BAD_FIRST
        and prefix[1] not in _NINO_BAD_SECOND
        and prefix not in _NINO_BAD_PREFIXES
        and digits.isdigit()
        and suffix in "ABCD"
    )


def _find_nino(text: str) -> Iterator[_Hit]:
    for m in _NINO_RE.finditer(text):
        compact = "".join(ch for ch in m.group() if ch.isalnum())
        if is_valid_nino(compact):
            score = 0.95 if context_before(text, m.start(), _NINO_CONTEXT) else 0.9
            yield _Hit(m.start(), m.end(), EntityType.ID_DOCUMENT, score)


# --- Phone numbers (national formats) ---------------------------------------

# UK: a trunk "0", an area code of 2-4 more digits (optionally in parentheses), then the
# subscriber number in one or two groups: 10 or 11 digits in all.
_UK_PHONE_RE = re.compile(
    r"(?<![\w+])(?<!\d[-./])"
    r"(?:\(0\d{2,4}\)|0\d{2,4})[ -]?\d{3,4}(?:[ -]?\d{3,4})?"
    r"(?!\d)(?![-./]\d)"
)
_UK_TRUNK_SECOND = frozenset("123789")


def _find_uk_phone(text: str) -> Iterator[_Hit]:
    for m in _UK_PHONE_RE.finditer(text):
        value = m.group()
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits[1] not in _UK_TRUNK_SECOND:
            continue
        separated = not value.isdigit()
        if len(digits) == 11 or (len(digits) == 10 and separated):
            yield _Hit(m.start(), m.end(), EntityType.PHONE, 0.85 if separated else 0.8)


# NANP: optional "1", area code and exchange code [2-9]XX (not N11), line number.
_US_PHONE_RE = re.compile(
    r"(?<![\w+])(?<!\d[-./])"
    r"(?:1[ .-]?)?"
    r"(?:\((?P<area>[2-9]\d{2})\)[ .-]?|(?P<area2>[2-9]\d{2})(?P<sep>[ .-]))"
    r"(?P<exchange>[2-9]\d{2})[ .-](?P<line>\d{4})"
    r"(?!\d)(?![-./]\d)"
)


def _find_us_phone(text: str) -> Iterator[_Hit]:
    for m in _US_PHONE_RE.finditer(text):
        area = m.group("area") or m.group("area2")
        if area[1:] == "11" or m.group("exchange")[1:] == "11":
            continue
        yield _Hit(m.start(), m.end(), EntityType.PHONE, 0.8)


# --- Postcodes --------------------------------------------------------------

# Outward code A9, A99, A9A, AA9, AA99, AA9A; inward code 9AA (no C I K M O V).
_UK_POSTCODE_RE = re.compile(
    r"(?<![\w-])"
    r"(?:[A-PR-UWYZ](?:\d[A-HJKPSTUW\d]?|[A-HK-Y]\d[ABEHMNPRVWXY\d]?)( ?)\d[ABD-HJLNP-UW-Z]{2}"
    r"|GIR( ?)0AA)"
    r"(?![\w-])"
)


def _find_uk_postcode(text: str) -> Iterator[_Hit]:
    for m in _UK_POSTCODE_RE.finditer(text):
        spaced = bool(m.group(1) or m.group(2))
        yield _Hit(m.start(), m.end(), EntityType.ADDRESS, 0.85 if spaced else 0.75)


_US_STATES = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VA", "WA", "WV", "WI", "WY", "PR",
)  # fmt: skip
_US_ZIP = r"(?P<zip>\d{5}(?:-\d{4})?)(?![\w-])(?!\.\d)"
_US_ZIP_AFTER_STATE_RE = re.compile(
    r"(?<![\w-])(?:" + "|".join(_US_STATES) + r")\.?,?[ \t]+" + _US_ZIP
)
_US_ZIP_LABELLED_RE = re.compile(
    r"(?i:\bzip(?:\s*code)?|\bpostal\s+code)\s*[:#]?\s*" + NUM_START + _US_ZIP
)


def _find_us_zip(text: str) -> Iterator[_Hit]:
    for m in _US_ZIP_AFTER_STATE_RE.finditer(text):
        yield _Hit(m.start("zip"), m.end("zip"), EntityType.ADDRESS, 0.8)
    for m in _US_ZIP_LABELLED_RE.finditer(text):
        yield _Hit(m.start("zip"), m.end("zip"), EntityType.ADDRESS, 0.85)


# --- Vehicles ---------------------------------------------------------------

# Current UK format (2001-): two area letters, a two-digit age identifier (02-29 for March,
# 51-79 for September registrations), three letters. I and Q are never used.
_UK_PLATE_RE = re.compile(
    r"(?<![\w-])[A-HJ-PR-Y][A-HJ-PR-Z](?:0[2-9]|[12]\d|5[1-9]|[67]\d) ?[A-HJ-PR-Z]{3}(?![\w-])"
)


def _find_uk_plate(text: str) -> Iterator[_Hit]:
    for m in _UK_PLATE_RE.finditer(text):
        yield _Hit(m.start(), m.end(), EntityType.VEHICLE_PLATE, 0.8)


# --- ID documents in context ------------------------------------------------

_ID_DOCUMENT_RE = re.compile(
    r"(?i:\b(?:passport|driving\s+licen[cs]e|driver'?s\s+licen[cs]e)"
    r"(?:\s+(?:number|no\.?|num\.?|#))?(?:\s+(?:is|was))?)"
    r"\s*[:#]?\s*"
    r"(?P<id>(?=[A-Z]*\d)[A-Z0-9]{6,18})(?![\w-])"
)


def _find_id_document(text: str) -> Iterator[_Hit]:
    for m in _ID_DOCUMENT_RE.finditer(text):
        yield _Hit(m.start("id"), m.end("id"), EntityType.ID_DOCUMENT, 0.85)


EVERYWHERE: tuple[Rule, ...] = (_find_ssn, _find_nino)
RULES: tuple[Rule, ...] = (
    _find_ssn_in_context,
    _find_uk_phone,
    _find_us_phone,
    _find_uk_postcode,
    _find_us_zip,
    _find_uk_plate,
    _find_id_document,
)
