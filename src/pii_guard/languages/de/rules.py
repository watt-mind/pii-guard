"""German language pack: rules for German identifiers and formats.

The worked example of ``docs/languages.md``: two checksummed national identifiers, the
national phone format and addresses. German IBANs (``DE`` + 20 digits) and ``+49`` phone
numbers need nothing here: the language-independent rules (:mod:`pii_guard.detect.rules.common`)
already find them for every language.

Run for every language (``EVERYWHERE``), because the format is distinctive and validated:

- Sozialversicherungsnummer (``12 150885 M 01 2``): area number, date of birth, a letter and a
  check digit;
- Steuer-ID (11 digits with a check digit) **next to its label** (``Steuer-ID``,
  ``Steueridentifikationsnummer``, ``IdNr``). Bare 11-digit numbers are too common in other
  languages' texts (Hungarian personal ID numbers are 11 digits too).

Run only for German text (``RULES``), because the format alone is ambiguous:

- an unlabelled Steuer-ID (checksum valid, grouped ``12 345 678 901`` or compact);
- national phone numbers with the trunk prefix ``0`` (``030 12345678``, ``(0221) 123456``,
  ``0171/2345678``);
- addresses: ``Musterstraße 12``, optionally followed by ``, 10115 Berlin``, and a postcode
  before a place name where an address line starts (``10115 Berlin`` on its own line or
  after a comma).

Steuer-IDs and Sozialversicherungsnummern are ``ID_DOCUMENT`` (the taxonomy has no German
type, as for US SSNs and UK NINOs); postcodes and street addresses are ``ADDRESS``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from pii_guard.detect.rules._base import NUM_END, NUM_START, Rule, _Hit, context_before
from pii_guard.languages.de.checksums import is_valid_steuer_id, is_valid_sv_number
from pii_guard.types import EntityType

__all__ = ["EVERYWHERE", "RULES"]

_UPPER = "A-ZÄÖÜ"
_LOWER = "a-zäöüß"


# --- Sozialversicherungsnummer ----------------------------------------------

_SV_RE = re.compile(
    r"(?<![\w-])"
    r"(?P<value>\d{2}( ?)\d{6}\2[A-Z]\2\d{2}\2\d)"
    r"(?![\w-])"
)
_SV_CONTEXT = ("sozialversicherung", "versicherungsnummer", "rentenversicherung", "sv-nr")


def _find_sv_number(text: str) -> Iterator[_Hit]:
    for m in _SV_RE.finditer(text):
        if is_valid_sv_number(m.group("value")):
            score = 0.97 if context_before(text, m.start(), _SV_CONTEXT) else 0.9
            yield _Hit(m.start("value"), m.end("value"), EntityType.ID_DOCUMENT, score)


# --- Steuer-ID ----------------------------------------------------------------

_STEUER_ID_RE = re.compile(
    NUM_START + r"(?P<value>[1-9]\d(?P<sep> ?)\d{3}(?P=sep)\d{3}(?P=sep)\d{3})" + NUM_END
)
_STEUER_ID_CONTEXT = (
    "steuer-id",
    "steuerid",
    "steuer-identifikationsnummer",
    "steueridentifikationsnummer",
    "identifikationsnummer",
    "idnr",
)


def _steuer_ids(text: str) -> Iterator[tuple[re.Match[str], bool]]:
    for m in _STEUER_ID_RE.finditer(text):
        if is_valid_steuer_id(m.group("value").replace(" ", "")):
            yield m, context_before(text, m.start(), _STEUER_ID_CONTEXT)


def _find_labelled_steuer_id(text: str) -> Iterator[_Hit]:
    for m, labelled in _steuer_ids(text):
        if labelled:
            yield _Hit(m.start("value"), m.end("value"), EntityType.ID_DOCUMENT, 0.97)


def _find_steuer_id(text: str) -> Iterator[_Hit]:
    for m, labelled in _steuer_ids(text):
        if not labelled:
            yield _Hit(m.start("value"), m.end("value"), EntityType.ID_DOCUMENT, 0.85)


# --- Phone numbers ------------------------------------------------------------

# Trunk prefix 0, an area code of 2-5 digits (mobile: 15x/16x/17x), then the subscriber number.
_PHONE_RE = re.compile(
    r"(?<![\w+])(?<!\d[-./])"
    r"(?:\(0[1-9]\d{1,4}\)|0[1-9]\d{1,4})"
    r"(?:[ /-]|\s?/\s?)?\d{3,8}(?:[ -]\d{1,5})?"
    r"(?!\d)(?![-./]\d)(?!\s?(?:€|EUR|Euro)(?!\w))"
)


def _find_phone(text: str) -> Iterator[_Hit]:
    for m in _PHONE_RE.finditer(text):
        digits = sum(ch.isdigit() for ch in m.group())
        if 9 <= digits <= 12:
            yield _Hit(m.start(), m.end(), EntityType.PHONE, 0.8)


# --- Addresses ----------------------------------------------------------------

_STREET_WORDS = (
    "straße|strasse|str\\.|weg|platz|allee|gasse|ring|damm|ufer|chaussee|steig|pfad|markt"
)
_HOUSE_NUMBER = r"\d{1,4}(?:\s?[a-h](?![\w]))?(?:\s?[-/]\s?\d{1,4})?"
_POSTCODE_CITY = (
    rf"(?:D-)?(?P<code>(?!00)\d{{5}})[ \t]+[{_UPPER}][{_LOWER}]+(?:-[{_UPPER}][{_LOWER}]+)?"
)
_ADDRESS_RE = re.compile(
    r"(?<![\w-])"
    rf"(?:[{_UPPER}][{_LOWER}]+[ -])?"  # "Lange Straße", "Am Beispielweg"
    rf"(?:[{_UPPER}][{_LOWER}\-]*(?:{_STREET_WORDS})|(?:Straße|Weg|Platz|Allee|Gasse))"
    rf"[ \t]+{_HOUSE_NUMBER}(?![\w])"
    rf"(?:,?[ \t]+{_POSTCODE_CITY})?"
)
# Every German noun is capitalised, so "20000 Teilnehmer" looks like "10115 Berlin": a bare
# postcode counts only where an address line starts (start of a line, or after a comma).
_POSTCODE_RE = re.compile(
    r"(?:(?<=^)|(?<=\n)|(?<=,)|(?<=, ))[ \t]*(?P<line>" + _POSTCODE_CITY + r")(?![\w-])",
    re.MULTILINE,
)
# Capitalised words after five digits that are not a place: amounts, counts.
_NOT_PLACES = frozenset(
    {"euro", "eur", "stück", "einwohner", "mitarbeiter", "menschen", "personen", "seiten"}
)


def _find_address(text: str) -> Iterator[_Hit]:
    for m in _ADDRESS_RE.finditer(text):
        yield _Hit(m.start(), m.end(), EntityType.ADDRESS, 0.85 if m.group("code") else 0.75)


def _find_postcode(text: str) -> Iterator[_Hit]:
    for m in _POSTCODE_RE.finditer(text):
        if m.group("line").split()[-1].casefold() in _NOT_PLACES:
            continue
        yield _Hit(m.start("line"), m.end("line"), EntityType.ADDRESS, 0.7)


EVERYWHERE: tuple[Rule, ...] = (_find_sv_number, _find_labelled_steuer_id)
RULES: tuple[Rule, ...] = (_find_steuer_id, _find_phone, _find_address, _find_postcode)
