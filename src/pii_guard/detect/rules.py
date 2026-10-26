"""Rule detector: regular expressions plus validation for structured identifiers.

The first, deterministic detection layer (``docs/architecture.md`` → detect/Rules). Every rule
finds candidates with a regular expression and keeps only those that pass validation
(checksums, known country/area codes, address context), so precision is high and the output is
fully reproducible.

Covered: Hungarian personal tax ID and TAJ number, IBAN (any country), Hungarian giro account
numbers, email addresses, phone numbers (Hungarian national and international formats),
Hungarian postcodes in an address context, Hungarian vehicle plates, and Hungarian company
registration and tax numbers.

Look-alikes are rejected on purpose: wrong check digits, digits that are part of a longer
digit run (``12345678901`` contains no 10-digit tax ID), and dates. Rules for Hungarian
identifiers run for every ``language``: a Hungarian ID inside an English text is still
personal data.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import NamedTuple

from pii_guard.detect.checksums import (
    IBAN_LENGTHS,
    is_valid_giro,
    is_valid_hu_tax_id,
    is_valid_hu_tax_number,
    is_valid_iban,
    is_valid_taj,
)
from pii_guard.types import DetectionError, EntityType, Span

__all__ = ["DETECTOR_CLASS", "RuleDetector"]


class _Hit(NamedTuple):
    start: int
    end: int
    entity_type: EntityType
    score: float


_Rule = Callable[[str], Iterator[_Hit]]

# A number must not continue a longer digit run, directly or through a date/decimal separator
# ("2026-10-26", "1.234.567"), or be followed by a currency (an amount, not an identifier).
_NUM_START = r"(?<!\d)(?<!\d[-./,])"
_NUM_END = r"(?!\d)(?![-./,]\d)"
_NOT_AMOUNT = r"(?!\s?(?:Ft|HUF|forint|EUR|€)(?!\w))"
# Space-grouped numbers must not be part of a longer space-grouped number ("1 234 567 890").
_NO_GROUP_BEFORE = r"(?<!\d )"
_NO_GROUP_AFTER = r"(?! \d)"


def _context_before(text: str, start: int, keywords: tuple[str, ...], window: int = 40) -> bool:
    """True if one of ``keywords`` (lowercase) appears in the ``window`` chars before ``start``."""
    before = text[max(0, start - window) : start].casefold()
    return any(k in before for k in keywords)


# --- National identifiers ---------------------------------------------------

_TAX_ID_RE = re.compile(_NUM_START + r"(8\d{9})" + _NUM_END + _NOT_AMOUNT)
_TAX_ID_CONTEXT = ("adóazonosító", "adóaz", "adószám", "tax id", "tax number")


def _find_hu_tax_id(text: str) -> Iterator[_Hit]:
    for m in _TAX_ID_RE.finditer(text):
        if is_valid_hu_tax_id(m.group(1)):
            score = 0.99 if _context_before(text, m.start(), _TAX_ID_CONTEXT) else 0.95
            yield _Hit(m.start(1), m.end(1), EntityType.NATIONAL_ID_HU_TAX, score)


_TAJ_RE = re.compile(
    _NUM_START + _NO_GROUP_BEFORE + r"(\d{3})([ -]?)(\d{3})\2(\d{3})"
    r"(?!\d)(?![-./,]\d)" + _NO_GROUP_AFTER + _NOT_AMOUNT
)
_TAJ_CONTEXT = ("taj", "társadalombiztosítási", "social security")


def _find_taj(text: str) -> Iterator[_Hit]:
    for m in _TAJ_RE.finditer(text):
        if is_valid_taj(m.group(1) + m.group(3) + m.group(4)):
            # A mod-10 check passes for 1 in 10 random numbers: context matters more here.
            score = 0.95 if _context_before(text, m.start(), _TAJ_CONTEXT) else 0.8
            yield _Hit(m.start(), m.end(), EntityType.NATIONAL_ID_HU_TAJ, score)


# --- Bank accounts ----------------------------------------------------------

_IBAN_START_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2})(\d{2})")


def _find_iban(text: str) -> Iterator[_Hit]:
    """IBANs, compact or printed in groups (single spaces between characters allowed)."""
    for m in _IBAN_START_RE.finditer(text):
        expected = IBAN_LENGTHS.get(m.group(1))
        if expected is None:
            continue
        chars = [m.group(1), m.group(2)]
        count, pos = 4, m.end()
        while count < expected and pos < len(text):
            ch = text[pos]
            if ch == " " and pos + 1 < len(text) and _is_iban_char(text[pos + 1]):
                pos += 1
                continue
            if not _is_iban_char(ch):
                break
            chars.append(ch)
            count += 1
            pos += 1
        if count != expected:
            continue
        # The IBAN must end here, not run on into more account characters.
        if pos < len(text) and text[pos].isalnum():
            continue
        if is_valid_iban("".join(chars)):
            yield _Hit(m.start(), pos, EntityType.BANK_ACCOUNT, 0.99)


def _is_iban_char(ch: str) -> bool:
    return ch.isascii() and (ch.isdigit() or ch.isupper())


_GIRO_RE = re.compile(_NUM_START + r"(\d{8})([- ]?)(\d{8})(?:\2(\d{8}))?" + _NUM_END)


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

# Pragmatic, not RFC 5322: Unicode letters allowed, the TLD is letters only. A Hungarian case
# suffix attached with a hyphen ("…@example.com-ra") is not part of the address.
_EMAIL_RE = re.compile(
    r"(?<![\w.%+-])"
    r"[\w%+-](?:[\w.%+-]*[\w%+-])?"
    r"@"
    r"(?:[^\W_](?:[\w-]*[^\W_])?\.)+"
    r"[^\W\d_]{2,}"
    r"(?!\w)(?!\.[^\W_])"
)


def _find_email(text: str) -> Iterator[_Hit]:
    for m in _EMAIL_RE.finditer(text):
        if ".." not in m.group():
            yield _Hit(m.start(), m.end(), EntityType.EMAIL, 0.99)


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


# Other countries: "+" and a country code, 8-15 digits in total (E.164). +36 is handled above.
_INTL_PHONE_RE = re.compile(
    r"(?<![\w+])\+(?!36)[1-9]\d{0,2}(?:[ \-./]?(?:\(\d{1,4}\)|\d{1,4})){2,6}(?!\d)"
)


def _find_intl_phone(text: str) -> Iterator[_Hit]:
    for m in _INTL_PHONE_RE.finditer(text):
        if 8 <= sum(ch.isdigit() for ch in m.group()) <= 15:
            yield _Hit(m.start(), m.end(), EntityType.PHONE, 0.85)


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
        elif _context_before(text, m.start(), _POSTCODE_CONTEXT, window=25):
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
    + _NUM_START
    + r"(?P<number>(?:0[1-9]|1\d|20)-(?:0[1-9]|1\d|2[0-3])-\d{6})"
    + _NUM_END
)


def _find_company_reg(text: str) -> Iterator[_Hit]:
    for m in _COMPANY_REG_RE.finditer(text):
        score = 0.95 if m.group("prefix") else 0.85
        yield _Hit(m.start("number"), m.end("number"), EntityType.COMPANY_ID_HU, score)


# Adószám "12345678-2-42": base number with check digit, VAT code, area code.
_TAX_NUMBER_RE = re.compile(_NUM_START + r"(\d{8})-(\d)-(\d{2})" + _NUM_END)


def _find_hu_tax_number(text: str) -> Iterator[_Hit]:
    for m in _TAX_NUMBER_RE.finditer(text):
        if is_valid_hu_tax_number(m.group(1), m.group(2), m.group(3)):
            yield _Hit(m.start(), m.end(), EntityType.COMPANY_ID_HU, 0.95)


_RULES: tuple[_Rule, ...] = (
    _find_iban,
    _find_email,
    _find_hu_tax_number,
    _find_company_reg,
    _find_giro,
    _find_hu_tax_id,
    _find_taj,
    _find_hu_phone,
    _find_intl_phone,
    _find_vehicle_plate,
    _find_postcode,
)


def _drop_contained(hits: list[_Hit]) -> list[_Hit]:
    """Remove hits that lie entirely inside another hit (e.g. digits inside an IBAN).

    Partial overlaps are kept: the resolver decides those.
    """
    ordered = sorted(set(hits), key=lambda h: (h.start, -(h.end - h.start), -h.score))
    kept: list[_Hit] = []
    for hit in ordered:
        if any(k.start <= hit.start and hit.end <= k.end for k in kept):
            continue
        kept.append(hit)
    return kept


class RuleDetector:
    """Deterministic, checksum-validated detector for structured identifiers.

    Stateless and safe to share between threads. Any unexpected error is raised as
    :class:`DetectionError` without the input text (ADR 0006: fail closed).
    """

    name = "rules"

    def __init__(self) -> None:
        self._rules = _RULES

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        if not isinstance(text, str):
            raise DetectionError(f"rules detector expects str, got {type(text).__name__}")
        try:
            hits = [hit for rule in self._rules for hit in rule(text)]
            return [
                Span(h.start, h.end, h.entity_type, text[h.start : h.end], h.score, self.name)
                for h in _drop_contained(hits)
            ]
        except Exception as exc:
            raise DetectionError("rules detector failed") from exc


DETECTOR_CLASS = RuleDetector
