"""Hungarian language pack: rules for Hungarian identifiers and formats.

Personal tax ID (adóazonosító jel) and TAJ number, giro account numbers, phone numbers with
the ``+36`` / ``0036`` / ``06`` prefix (validated against the area code), company registration
(cégjegyzékszám) and company tax numbers (adószám): these carry a checksum or an unambiguous
prefix and run for **every** language (``EVERYWHERE``): a Hungarian ID inside an English text
is still personal data.

Postcodes (four digits before a settlement name, or in context) and vehicle plates are formats
without a checksum, so they run only when the text is Hungarian (``RULES``); in other
languages "2019 Robin" or "ISO-900" style look-alikes would be false positives.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from pii_guard.detect.checksums import (
    is_valid_giro,
    is_valid_hu_tax_id,
    is_valid_hu_tax_number,
    is_valid_taj,
)
from pii_guard.detect.rules._base import (
    NO_GROUP_AFTER,
    NO_GROUP_BEFORE,
    NOT_AMOUNT,
    NUM_END,
    NUM_START,
    Rule,
    _Hit,
    context_before,
)
from pii_guard.types import EntityType

__all__ = ["EVERYWHERE", "RULES"]


# --- National identifiers ---------------------------------------------------

_TAX_ID_RE = re.compile(NUM_START + r"(8\d{9})" + NUM_END + NOT_AMOUNT)
_TAX_ID_CONTEXT = ("adóazonosító", "adóaz", "adószám", "tax id", "tax number")


def _find_hu_tax_id(text: str) -> Iterator[_Hit]:
    for m in _TAX_ID_RE.finditer(text):
        if is_valid_hu_tax_id(m.group(1)):
            score = 0.99 if context_before(text, m.start(), _TAX_ID_CONTEXT) else 0.95
            yield _Hit(m.start(1), m.end(1), EntityType.NATIONAL_ID_HU_TAX, score)


_TAJ_RE = re.compile(
    NUM_START + NO_GROUP_BEFORE + r"(\d{3})([ -]?)(\d{3})\2(\d{3})"
    r"(?!\d)(?![-./,]\d)" + NO_GROUP_AFTER + NOT_AMOUNT
)
_TAJ_CONTEXT = ("taj", "társadalombiztosítási", "social security")


def _find_taj(text: str) -> Iterator[_Hit]:
    for m in _TAJ_RE.finditer(text):
        if is_valid_taj(m.group(1) + m.group(3) + m.group(4)):
            # A mod-10 check passes for 1 in 10 random numbers: context matters more here.
            score = 0.95 if context_before(text, m.start(), _TAJ_CONTEXT) else 0.8
            yield _Hit(m.start(), m.end(), EntityType.NATIONAL_ID_HU_TAJ, score)


# --- Bank accounts ----------------------------------------------------------

_GIRO_RE = re.compile(NUM_START + r"(\d{8})([- ]?)(\d{8})(?:\2(\d{8}))?" + NUM_END)


def _find_giro(text: str) -> Iterator[_Hit]:
    for m in _GIRO_RE.finditer(text):
        first, second, third = m.group(1), m.group(3), m.group(4)
        if third is not None and is_valid_giro(first + second + third):
            yield _Hit(m.start(), m.end(), EntityType.BANK_ACCOUNT, 0.95)
        elif is_valid_giro(first + second):
            end = m.end(3)
            # A 16-digit account followed directly by more digits is part of a longer number.
            if third is not None and not m.group(2):
                continue
            yield _Hit(m.start(), end, EntityType.BANK_ACCOUNT, 0.95)


# --- Contact details --------------------------------------------------------

# Hungarian numbers: prefix +36 / 0036 / 06, then the national significant number with
# optional separators and parentheses. Its length is checked against the area code below.
_HU_PHONE_RE = re.compile(
    r"(?<![\w+])(?<!\d[-./])"
    r"(?P<open>\()?"
    r"(?P<prefix>\+36|0036|06)"
    r"(?P<nsn>[ \-/]?\(?\d(?:(?:[ \-/.]|\)[ \-/]?)?\d){5,9})"
    r"(?!\d)"
)
_HU_MOBILE_CODES = frozenset({"20", "21", "30", "31", "50", "70"})
_HU_GEO_CODES = frozenset({
    "22", "23", "24", "25", "26", "27", "28", "29", "32", "33", "34", "35", "36",
    "37", "42", "44", "45", "46", "47", "48", "49", "52", "53", "54", "56", "57",
    "59", "62", "63", "66", "68", "69", "72", "73", "74", "75", "76", "77", "78",
    "79", "82", "83", "84", "85", "87", "88", "89", "92", "93", "94", "95", "96",
    "99",
})  # fmt: skip


def _hu_nsn_length(digits: str) -> int | None:
    """Expected national number length for the area code ``digits`` starts with."""
    if digits.startswith("1"):
        return 8  # Budapest: 1 + 7 digits
    if digits[:2] in _HU_MOBILE_CODES:
        return 9  # mobile: 2 + 7 digits
    if digits[:2] in _HU_GEO_CODES:
        return 8  # other areas: 2 + 6 digits
    return None


def _find_hu_phone(text: str) -> Iterator[_Hit]:
    for m in _HU_PHONE_RE.finditer(text):
        nsn_start = m.start("nsn")
        positions = [nsn_start + i for i, ch in enumerate(m.group("nsn")) if ch.isdigit()]
        digits = "".join(text[p] for p in positions)
        expected = _hu_nsn_length(digits)
        if expected is None or len(digits) < expected:
            continue
        end = positions[expected - 1] + 1
        if len(digits) > expected and positions[expected] == end:
            continue  # more digits run on without a separator: not this number
        start = m.start("prefix")
        if m.group("open") and ")" in text[start:end]:
            start = m.start("open")
        yield _Hit(start, end, EntityType.PHONE, 0.9)


# --- Addresses --------------------------------------------------------------

_UPPER = "A-ZÁÉÍÓÖŐÚÜŰ"
_LOWER = "a-záéíóöőúüű"
_POSTCODE_RE = re.compile(
    r"(?<![\w\-./,])(?P<prefix>HU?-)?(?P<code>[1-9]\d{3})(?![\w\-./,]|\s?(?:Ft|HUF|EUR|€))"
)
# A settlement name after the postcode: "1051 Budapest", "6720 Szeged", "3300 Eger".
_PLACE_AFTER_RE = re.compile(rf"[ \t]+([{_UPPER}][{_LOWER}]{{2,}})")
_POSTCODE_CONTEXT = ("irányítószám", "ir.sz", "irsz", "postcode", "postal code", "zip")
_NOT_PLACES = frozenset({
    "Euro", "Euró", "Forint", "Darab", "Január", "Február", "Március", "Április",
    "Május", "Június", "Július", "Augusztus", "Szeptember", "Október", "November", "December",
    "Ezer", "Millió",
})  # fmt: skip


def _find_postcode(text: str) -> Iterator[_Hit]:
    for m in _POSTCODE_RE.finditer(text):
        place = _PLACE_AFTER_RE.match(text, m.end())
        if m.group("prefix"):
            score = 0.9
        elif context_before(text, m.start(), _POSTCODE_CONTEXT, window=25):
            score = 0.85
        elif place and place.group(1) not in _NOT_PLACES:
            score = 0.75
        else:
            continue
        yield _Hit(m.start("code"), m.end("code"), EntityType.ADDRESS, score)


# --- Vehicles ---------------------------------------------------------------

# Old format "ABC-123", new (2022) format "AA BC-123". A suffix may follow with a hyphen
# ("ABC-123-as"), but not more letters or digits.
_PLATE_END = r"(?![\w])(?!-[A-Z\d])"
_PLATE_OLD_RE = re.compile(r"(?<![\w\-])[A-Z]{3}-\d{3}" + _PLATE_END)
_PLATE_NEW_RE = re.compile(r"(?<![\w\-])[A-Z]{2} ?[A-Z]{2}-\d{3}" + _PLATE_END)


def _find_vehicle_plate(text: str) -> Iterator[_Hit]:
    for m in _PLATE_NEW_RE.finditer(text):
        yield _Hit(m.start(), m.end(), EntityType.VEHICLE_PLATE, 0.85)
    for m in _PLATE_OLD_RE.finditer(text):
        yield _Hit(m.start(), m.end(), EntityType.VEHICLE_PLATE, 0.8)


# --- Companies --------------------------------------------------------------

# Cégjegyzékszám "Cg. 01-09-123456": court 01-20, company form 01-23, 6-digit serial.
_COMPANY_REG_RE = re.compile(
    r"(?P<prefix>Cg\.\s?)?"
    + NUM_START
    + r"(?P<number>(?:0[1-9]|1\d|20)-(?:0[1-9]|1\d|2[0-3])-\d{6})"
    + NUM_END
)


def _find_company_reg(text: str) -> Iterator[_Hit]:
    for m in _COMPANY_REG_RE.finditer(text):
        score = 0.95 if m.group("prefix") else 0.85
        yield _Hit(m.start("number"), m.end("number"), EntityType.COMPANY_ID_HU, score)


# Adószám "12345678-2-42": base number with check digit, VAT code, area code.
_TAX_NUMBER_RE = re.compile(NUM_START + r"(\d{8})-(\d)-(\d{2})" + NUM_END)


def _find_hu_tax_number(text: str) -> Iterator[_Hit]:
    for m in _TAX_NUMBER_RE.finditer(text):
        if is_valid_hu_tax_number(m.group(1), m.group(2), m.group(3)):
            yield _Hit(m.start(), m.end(), EntityType.COMPANY_ID_HU, 0.95)


EVERYWHERE: tuple[Rule, ...] = (
    _find_hu_tax_number,
    _find_company_reg,
    _find_giro,
    _find_hu_tax_id,
    _find_taj,
    _find_hu_phone,
)
RULES: tuple[Rule, ...] = (_find_vehicle_plate, _find_postcode)
