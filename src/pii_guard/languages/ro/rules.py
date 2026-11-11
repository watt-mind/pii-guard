"""Romanian language pack: rules for Romanian identifiers and formats (LAB-1778).

Romanian IBANs (``RO`` + 22 characters) and ``+40`` phone numbers need nothing here: the
language-independent rules (:mod:`pii_guard.detect.rules.common`) already find them.

Run for every language (``EVERYWHERE``), because the value validates:

- the CNP (cod numeric personal): 13 digits with a sex/century digit, a date of birth, a
  county code 01-52 and a check digit (mod 11). Fully validated it is distinctive enough for
  any text; an unlabelled one right after an order, invoice or amount label is left alone (a
  13-digit EAN barcode can pass the checks).

Run only for Romanian text (``RULES``), because the format alone is ambiguous elsewhere:

- a CIF / CUI (company tax code, 2-10 digits with a weighted check digit) **next to its
  label** (``CIF``, ``CUI``, ``cod fiscal`` ...), optionally with its ``RO`` VAT prefix: a
  one-in-eleven check is far too weak without one. A sole trader's code identifies a person,
  so it is masked like the Polish NIP and the Italian partita IVA;
- an identity card (carte de identitate, "buletin") series and number next to its label
  (``CI seria RX nr. 123456``): two letters and six digits, no check digit;
- national phone numbers: mobile ``0721 234 567`` (also compact, ``0721234567``) and landline
  ``021 555 0123``, ``0264 555 012``, ``(021) 312 34 56``;
- addresses: ``Strada Teilor nr. 15, ap. 7, 400123 Cluj-Napoca`` (also ``Str.``, ``Bd.``,
  ``Calea``, ``Șoseaua``, ``Aleea`` ...), and a six-digit postcode before a place name where an
  address line starts.

Every identifier is ``ID_DOCUMENT`` (the taxonomy has no Romanian type, as for the German,
Polish and Italian identifiers). A passport or driving-licence number has no check digit: it
is masked after its cue (``pașaport``, ``permis de conducere``, ``cues.tsv``), and so are a CNP
whose check digit fails and an identity card number after ``buletin``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from pii_guard.detect.rules._base import (
    NO_GROUP_AFTER,
    NO_GROUP_BEFORE,
    NOT_IN_WORD_AFTER,
    NUM_END,
    NUM_START,
    VALIDATED_ID_DOCUMENT,
    Rule,
    _Hit,
    legal_form_after,
    reference_or_amount_before,
)
from pii_guard.languages.ro.checksums import is_valid_cif, is_valid_cnp
from pii_guard.types import EntityType

__all__ = ["EVERYWHERE", "RULES"]

# Both spellings of ș and ț: comma below (the standard) and cedilla (older fonts and keyboards).
_UPPER = "A-ZĂÂÎȘŞȚŢ"
_LOWER = "a-zăâîșşțţ"
# A Romanian amount: a currency word or sign right after the number.
_NOT_AMOUNT_RO = r"(?!\s?(?:lei|RON|EUR|€|euro|bani)(?!\w))"
_LABEL_WINDOW = 40


def _label_before(pattern: re.Pattern[str], text: str, start: int) -> bool:
    """True if ``pattern`` (a label, whole words) occurs in the 40 characters before ``start``."""
    return pattern.search(text, max(0, start - _LABEL_WINDOW), start) is not None


# --- CNP ------------------------------------------------------------------------------

_CNP_RE = re.compile(
    NUM_START + NO_GROUP_BEFORE + r"(?P<value>[1-9]\d{12})" + NUM_END + NO_GROUP_AFTER
)
_CNP_LABEL_RE = re.compile(
    r"(?i:(?<!\w)(?:cnp|c\.n\.p\.?|cod(?:ul)?[ \t]+numeric[ \t]+personal)(?!\w))"
)


def _find_cnp(text: str) -> Iterator[_Hit]:
    for m in _CNP_RE.finditer(text):
        if not is_valid_cnp(m.group("value")):
            continue
        labelled = _label_before(_CNP_LABEL_RE, text, m.start())
        if not labelled and reference_or_amount_before(text, m.start()):
            continue  # "Factura nr. ...", "EAN ...": a 13-digit business number
        score = 0.97 if labelled else 0.95
        yield _Hit(m.start(), m.end(), EntityType.ID_DOCUMENT, score, VALIDATED_ID_DOCUMENT)


# --- CIF / CUI ------------------------------------------------------------------------

_CIF_RE = re.compile(
    r"(?<![\w-])(?P<value>(?:RO[ \t]?)?[1-9]\d{1,9})" + NUM_END + NO_GROUP_AFTER + _NOT_AMOUNT_RO
)
# "CIF", "C.I.F.", "CUI", "C.U.I.", "cod fiscal", "cod de identificare fiscală", "cod unic de
# înregistrare", "cod TVA": the label must be the last words before the value.
_CIF_LABEL_RE = re.compile(
    r"(?i:(?<!\w)(?:c\.?i\.?f\.?|c\.?u\.?i\.?|cod(?:ul)?[ \t]+fiscal|cod(?:ul)?[ \t]+de[ \t]+"
    r"identificare[ \t]+fiscal[ăa]|cod(?:ul)?[ \t]+unic[ \t]+de[ \t]+[îi]nregistrare"
    r"|cod(?:ul)?[ \t]+(?:de[ \t]+)?TVA)(?!\w)[ \t:.]*(?:nr\.?[ \t]*)?)$"
)


def _find_cif(text: str) -> Iterator[_Hit]:
    for m in _CIF_RE.finditer(text):
        digits = m.group("value").removeprefix("RO").strip()
        if not is_valid_cif(digits):
            continue
        if _CIF_LABEL_RE.search(text, max(0, m.start() - _LABEL_WINDOW), m.start()):
            yield _Hit(m.start(), m.end(), EntityType.ID_DOCUMENT, 0.95, VALIDATED_ID_DOCUMENT)


# --- Identity card (carte de identitate) ----------------------------------------------

# "seria RX nr. 123456", "RX 123456", "RX123456": two capital letters (the issuing county's
# series) and six digits.
_ID_CARD_RE = re.compile(
    r"(?<![\w-])(?P<value>[A-Z]{2}(?:[ \t]*(?:nr\.?|numărul|număr|numar)[ \t]*|[ \t]?)\d{6})"
    r"(?![\w-])"
)
_ID_CARD_LABEL_RE = re.compile(
    r"(?i:(?<!\w)(?:seria|serie|c\.?i\.?|b\.?i\.?|buletin\w*|cart(?:e|ea)[ \t]+de"
    r"[ \t]+identitate|act(?:ul)?[ \t]+de[ \t]+identitate|identity[ \t]+card)(?!\w))"
)


def _find_id_card(text: str) -> Iterator[_Hit]:
    for m in _ID_CARD_RE.finditer(text):
        if _label_before(_ID_CARD_LABEL_RE, text, m.start()):
            yield _Hit(m.start(), m.end(), EntityType.ID_DOCUMENT, 0.9)


# --- Phone numbers --------------------------------------------------------------------

# Mobile: 07 and eight digits, grouped 4-3-3 ("0721 234 567", "0721-234-567", "0721.234.567")
# or compact ("0721234567": ten digits starting 07 are a mobile number in Romanian text).
_MOBILE_RE = re.compile(
    r"(?<![\w+(])(?<!\d[-./ ])"
    r"(?P<value>07\d{2}(?:(?P<sep>[ .-])\d{3}(?P=sep)\d{3}|\d{6}))"
    r"(?!\d)(?![-./ ]\d)" + _NOT_AMOUNT_RO + NOT_IN_WORD_AFTER
)
# Landline: Bucharest 021/031 and seven digits, other areas 02xx/03xx and six digits, so ten
# digits in all; the area code optionally in parentheses, then groups split by spaces or
# hyphens ("021 555 0123", "021 312 34 56", "0264 555 012", "0264/555012"). A compact landline
# needs a cue: ten bare digits are as often an order number. Dots never separate the groups
# ("02.11.2026" is a date).
_LANDLINE_RE = re.compile(
    r"(?<![\w+(/.])(?<!\d[-./ ])"
    r"(?P<value>(?:\(0[23]\d{1,2}\)|0[23]\d{1,2})[ \t/-]\d{2,7}(?:[ \t-]\d{2,4}){0,3})"
    r"(?!\d)(?![-./ ]\d)" + _NOT_AMOUNT_RO + NOT_IN_WORD_AFTER
)


def _find_phone(text: str) -> Iterator[_Hit]:
    for pattern in (_MOBILE_RE, _LANDLINE_RE):
        for m in pattern.finditer(text):
            value = m.group("value")
            if sum(ch.isdigit() for ch in value) != 10:
                continue
            if not reference_or_amount_before(text, m.start("value")):
                yield _Hit(m.start("value"), m.end("value"), EntityType.PHONE, 0.8)


# --- Addresses ------------------------------------------------------------------------

_STREET_TYPE = (
    r"(?:strada|str\.|bulevardul|bd\.|b-dul|bdul\.?|calea|[șş]oseaua|[șş]os\.|aleea|al\."
    r"|pia[țţ]a|p-[țţ]a|splaiul|intrarea|drumul|prelungirea|fund[ăa]tura|pasajul)"
)
# A capitalised word of a street or place name ("Mihai Eminescu", "Cluj-Napoca"), not an
# abbreviation before a number or a lowercase word ("Tel. 021").
_CAP_WORD = (
    rf"[{_UPPER}][{_LOWER}]+(?:-[{_UPPER}][{_LOWER}]+)*(?![{_LOWER}])"
    rf"(?!\.[ \t]*[\d{_LOWER}])"
)
_PARTICLE = r"(?:lui|de|din|cel|cea|la)"
# One word of a street name: a capitalised word after optional particles ("Calea lui Traian",
# "Strada Ion Creangă"), a year ("Bulevardul 1 Decembrie 1918") or a Roman numeral; a day
# number may open it ("Strada 13 Septembrie").
_UNIT = rf"(?:{_PARTICLE}[ \t]+)*(?:{_CAP_WORD}|[IVX]{{1,4}}(?!\w))"
_STREET_NAME = rf"(?:\d{{1,2}}[ \t]+)?{_UNIT}(?:[ \t]+(?:{_UNIT}|1[89]\d\d(?!\d))){{0,3}}"
_HOUSE_NUMBER = r"(?:nr\.?[ \t]*|număr(?:ul)?[ \t]+)?\d{1,4}[A-Za-z]?(?:-\d{1,4}[A-Za-z]?)?"
# Building, staircase, floor and flat after the house number: "bl. A3, sc. 2, et. 4, ap. 7".
_FLAT = r"(?:,?[ \t]*(?:bl|sc|et|ap|bloc|scara|etaj|apartament)\.?[ \t]*[A-Z0-9]{1,4}(?!\w))"
_PLACE = rf"{_CAP_WORD}(?:[ \t]+{_CAP_WORD}){{0,2}}"
# "sector 3" / "Sectorul 3" in Bucharest, "jud. Cluj" / "județul Cluj" elsewhere.
_DISTRICT = rf"(?:,?[ \t]*(?:(?i:sector(?:ul)?)[ \t]*[1-6]|(?i:jud\.|jude[țţ]ul)[ \t]*{_CAP_WORD}))"
_POSTCODE_PLACE = rf"(?P<code>\d{{6}})[ \t]+{_PLACE}{_DISTRICT}?"
_ADDRESS_RE = re.compile(
    rf"(?<![\w.])(?i:{_STREET_TYPE})[ \t]*{_STREET_NAME}(?:,[ \t]*|[ \t]+){_HOUSE_NUMBER}"
    rf"(?![\w/]){_FLAT}*{_DISTRICT}?"
    rf"(?:(?:,[ \t]*|[ \t]+|[ \t]*\n[ \t]*){_POSTCODE_PLACE}(?![\w-]))?"
)
# A bare postcode counts only where an address line starts.
_POSTCODE_RE = re.compile(
    r"(?:(?<=^)|(?<=\n)|(?<=,)|(?<=, ))[ \t]*(?P<line>" + _POSTCODE_PLACE + r")(?![\w-])",
    re.MULTILINE,
)
# Lowercase words right after a house number that make it a count ("pe Calea Zoom 3 ori").
_COUNT_AFTER_RE = re.compile(
    r"[ \t]+(?:zile|zi|ore|ori|luni|ani|minute|persoane|lei|bucăți|pagini)(?!\w)"
)
# Capitalised words after six digits that are not a place: amounts, counts.
_NOT_PLACES = frozenset({"lei", "ron", "euro", "eur", "persoane", "locuitori", "bucăți"})
# A Romanian legal form after the place makes it a company name ("400123 Cluj SRL").
_RO_LEGAL_FORM_AFTER_RE = re.compile(r"[ \t]+(?:S\.?R\.?L\.?|S\.?A\.?|PFA|II)(?!\w)")


def _company_after(text: str, end: int) -> bool:
    return legal_form_after(text, end) or _RO_LEGAL_FORM_AFTER_RE.match(text, end) is not None


def _find_address(text: str) -> Iterator[_Hit]:
    for m in _ADDRESS_RE.finditer(text):
        if not m.group("code") and _COUNT_AFTER_RE.match(text, m.end()):
            continue  # a count, not a house number
        yield _Hit(m.start(), m.end(), EntityType.ADDRESS, 0.85 if m.group("code") else 0.75)


def _find_postcode(text: str) -> Iterator[_Hit]:
    for m in _POSTCODE_RE.finditer(text):
        place = m.group("line").split()[1].casefold()
        if place in _NOT_PLACES or _company_after(text, m.end("line")):
            continue
        yield _Hit(m.start("line"), m.end("line"), EntityType.ADDRESS, 0.7)


EVERYWHERE: tuple[Rule, ...] = (_find_cnp,)
RULES: tuple[Rule, ...] = (
    _find_cif,
    _find_id_card,
    _find_phone,
    _find_address,
    _find_postcode,
)
