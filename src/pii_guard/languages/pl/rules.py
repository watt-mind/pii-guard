"""Polish language pack: rules for Polish identifiers and formats (LAB-1400).

Polish IBANs (``PL`` + 26 digits) and ``+48`` phone numbers need nothing here: the
language-independent rules (:mod:`pii_guard.detect.rules.common`) already find them.

Run for every language (``EVERYWHERE``), because the value validates and a label or prefix
says what it is:

- PESEL, NIP, REGON, ID card (dowód osobisty) and passport numbers **next to their label**
  (``PESEL``, ``NIP``, ``REGON``, ``nr dowodu``, ``seria i numer``, ``paszport`` ...);
- an EU VAT number ``PL`` + a valid NIP (``PL1234563218``).

Run only for Polish text (``RULES``), because the format alone is ambiguous elsewhere:

- an unlabelled PESEL (date of birth and check digit valid), NIP (``123-456-32-18``,
  ``123-45-63-218``, compact), ID card (``ABA 300000``) or passport number (``AA 0000000``);
- national phone numbers: mobile ``600 123 456`` (grouped) and landline ``22 123 45 67``;
- addresses: ``ul. Kwiatowa 12/5``, optionally followed by ``, 00-950 Warszawa``, and a postcode
  before a place name (``31-008 Kraków``).

Every identifier is ``ID_DOCUMENT`` (the taxonomy has no Polish type, as for German and US
identifiers); a REGON is a business number, but a sole trader's identifies a person, as a
NIP does. A driving-licence number has no check digit: it is masked after its cue
(``prawo jazdy``, ``cues.tsv``). Bad check digits are found by the cues too.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

from pii_guard.detect.rules._base import (
    NO_GROUP_AFTER,
    NO_GROUP_BEFORE,
    NOT_IN_WORD_AFTER,
    NUM_END,
    NUM_START,
    Rule,
    _Hit,
    context_before,
    legal_form_after,
    reference_or_amount_before,
)
from pii_guard.languages.pl.checksums import (
    is_valid_id_card,
    is_valid_nip,
    is_valid_passport,
    is_valid_pesel,
    is_valid_regon,
)
from pii_guard.types import EntityType

__all__ = ["EVERYWHERE", "RULES"]

_UPPER = "A-ZĄĆĘŁŃÓŚŹŻ"
_LOWER = "a-ząćęłńóśźż"
# A Polish amount: a currency word or sign right after the number.
_NOT_AMOUNT_PL = r"(?!\s?(?:zł|PLN|złotych|gr|EUR|€)(?!\w))"

# Labels, lower case. ``context_before`` looks in the 40 characters before the value.
_PESEL_CONTEXT = ("pesel",)
_NIP_CONTEXT = ("nip", "numer identyfikacji podatkowej", "tax id", "vat id")
_REGON_CONTEXT = ("regon",)
_ID_CARD_CONTEXT = (
    "dowod",
    "dowód",
    "seria i numer",
    "seria i nr",
    "nr dokumentu",
    "numer dokumentu",
    "dokument tożsamości",
    "dokumentu tożsamości",
)
_PASSPORT_CONTEXT = ("paszport", "passport", *_ID_CARD_CONTEXT[2:])

# A Polish order, invoice, shipment, case or amount label right before a number makes it a
# business number ("Faktura nr 7770001246", "numer zamówienia: ...", "sygn. akt ..."): the
# shared ``reference_or_amount_before`` knows the Polish words (LAB-1433).
_reference_before = reference_or_amount_before


# --- Numbers: PESEL, NIP, REGON -------------------------------------------------------

_PESEL_RE = re.compile(
    NUM_START + NO_GROUP_BEFORE + r"(?P<value>\d{11})" + NUM_END + NO_GROUP_AFTER
)
_NIP_RE = re.compile(
    NUM_START + NO_GROUP_BEFORE + r"(?P<value>\d{3}(?P<sep>[- ])"
    r"(?:\d{3}(?P=sep)\d{2}(?P=sep)\d{2}|\d{2}(?P=sep)\d{2}(?P=sep)\d{3})"
    r"|\d{10})" + NUM_END + NO_GROUP_AFTER + _NOT_AMOUNT_PL
)
_VAT_RE = re.compile(r"(?<![\w-])PL ?(?P<value>\d{10})(?![\w-])")
_REGON_RE = re.compile(
    NUM_START
    + NO_GROUP_BEFORE
    + r"(?P<value>\d{14}|\d{9}|\d{3} \d{3} \d{3})"
    + NUM_END
    + NO_GROUP_AFTER
    + _NOT_AMOUNT_PL
)


def _compact(value: str) -> str:
    return value.replace(" ", "").replace("-", "")


def _numbers(
    pattern: re.Pattern[str], valid: Callable[[str], bool], context: tuple[str, ...], text: str
) -> Iterator[tuple[re.Match[str], bool]]:
    """Validated matches of ``pattern``, each with whether its label stands before it."""
    for m in pattern.finditer(text):
        if valid(_compact(m.group("value"))):
            yield m, context_before(text, m.start("value"), context)


def _labelled(
    pattern: re.Pattern[str], valid: Callable[[str], bool], context: tuple[str, ...]
) -> Rule:
    def rule(text: str) -> Iterator[_Hit]:
        for m, labelled in _numbers(pattern, valid, context, text):
            if labelled:
                yield _Hit(m.start("value"), m.end("value"), EntityType.ID_DOCUMENT, 0.97)

    return rule


def _unlabelled(
    pattern: re.Pattern[str], valid: Callable[[str], bool], context: tuple[str, ...], score: float
) -> Rule:
    def rule(text: str) -> Iterator[_Hit]:
        for m, labelled in _numbers(pattern, valid, context, text):
            if not labelled and not _reference_before(text, m.start("value")):
                yield _Hit(m.start("value"), m.end("value"), EntityType.ID_DOCUMENT, score)

    return rule


_find_labelled_pesel = _labelled(_PESEL_RE, is_valid_pesel, _PESEL_CONTEXT)
_find_labelled_nip = _labelled(_NIP_RE, is_valid_nip, _NIP_CONTEXT)
_find_labelled_regon = _labelled(_REGON_RE, is_valid_regon, _REGON_CONTEXT)
_find_pesel = _unlabelled(_PESEL_RE, is_valid_pesel, _PESEL_CONTEXT, 0.85)
_find_nip = _unlabelled(_NIP_RE, is_valid_nip, _NIP_CONTEXT, 0.8)


def _find_vat_number(text: str) -> Iterator[_Hit]:
    for m in _VAT_RE.finditer(text):
        if is_valid_nip(m.group("value")):
            yield _Hit(m.start(), m.end(), EntityType.ID_DOCUMENT, 0.95)


# --- Documents: ID card, passport ----------------------------------------------------

_ID_CARD_RE = re.compile(r"(?<![\w-])(?P<value>[A-Z]{3} ?\d{6})(?![\w-])")
_PASSPORT_RE = re.compile(r"(?<![\w-])(?P<value>[A-Z]{2} ?\d{7})(?![\w-])")

_find_labelled_id_card = _labelled(_ID_CARD_RE, is_valid_id_card, _ID_CARD_CONTEXT)
_find_labelled_passport = _labelled(_PASSPORT_RE, is_valid_passport, _PASSPORT_CONTEXT)
_find_id_card = _unlabelled(_ID_CARD_RE, is_valid_id_card, _ID_CARD_CONTEXT, 0.8)
_find_passport = _unlabelled(_PASSPORT_RE, is_valid_passport, _PASSPORT_CONTEXT, 0.8)


# --- Phone numbers --------------------------------------------------------------------

# Mobile: nine digits starting 4-8 in groups of three (compact ones need a cue, cues.tsv: a
# bare nine-digit run is as often a REGON or a reference). Landline: a two-digit area code,
# then 3-2-2 digits, the area code optionally in parentheses. An unlabelled Hungarian TAJ
# (also nine digits in groups of three) runs only for Hungarian text (LAB-1433), so it no
# longer competes here; a labelled TAJ (0.95) still wins.
_PHONE_RE = re.compile(
    r"(?<![\w+(])(?<!\d[-./ ])"
    r"(?:[4-8]\d{2}(?P<sep>[ -])\d{3}(?P=sep)\d{3}"
    r"|(?:\([1-9]\d\)|[1-9]\d)[ -]\d{3}[ -]\d{2}[ -]\d{2})"
    r"(?!\d)(?![-./ ]\d)" + _NOT_AMOUNT_PL + NOT_IN_WORD_AFTER
)


def _find_phone(text: str) -> Iterator[_Hit]:
    for m in _PHONE_RE.finditer(text):
        if not _reference_before(text, m.start()):
            yield _Hit(m.start(), m.end(), EntityType.PHONE, 0.8)


# --- Addresses ------------------------------------------------------------------------

_STREET_TYPE = r"(?:ul\.|al\.|os\.|pl\.|ulica|ulicy|aleja|alei|aleje|osiedle|plac|placu)"
# Words of a street name: capitalised words and abbreviations ("Jana Pawła II", "gen. Andersa",
# "Marii Skłodowskiej-Curie"), a day number before a month ("3 Maja", "11 Listopada").
_NAME_WORD = (
    rf"(?:[{_UPPER}][{_LOWER}]*\.?(?:-[{_UPPER}][{_LOWER}]+)?|[IVX]{{1,4}}|[{_LOWER}]{{2,4}}\.)"
)
_STREET_NAME = rf"(?:\d{{1,2}}[ \t]+)?{_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,3}}"
_HOUSE_NUMBER = (
    r"\d{1,4}[a-zA-Z]?(?![\w])(?:[ \t]?/[ \t]?\d{1,4}[a-zA-Z]?)?"
    r"(?:[ \t]+(?:m\.|lok\.|m|lok)[ \t]?\d{1,4}[a-zA-Z]?)?"
)
_PLACE = rf"[{_UPPER}][{_LOWER}]+(?:[- ][{_UPPER}][{_LOWER}]+)?"
_POSTCODE_PLACE = rf"(?P<code>\d{{2}}-\d{{3}})[ \t]+{_PLACE}"
_ADDRESS_RE = re.compile(
    rf"(?<![\w.])(?i:{_STREET_TYPE})[ \t]*{_STREET_NAME}[ \t]+{_HOUSE_NUMBER}(?![\w/])"
    rf"(?:(?:,[ \t]*|[ \t]+|[ \t]*\n[ \t]*){_POSTCODE_PLACE}(?![\w-]))?"
)
_POSTCODE_RE = re.compile(rf"(?<![\w./-])(?P<line>{_POSTCODE_PLACE})(?![\w-])")


def _find_address(text: str) -> Iterator[_Hit]:
    for m in _ADDRESS_RE.finditer(text):
        yield _Hit(m.start(), m.end(), EntityType.ADDRESS, 0.85 if m.group("code") else 0.75)


def _find_postcode(text: str) -> Iterator[_Hit]:
    for m in _POSTCODE_RE.finditer(text):
        if legal_form_after(text, m.end("line")):
            continue  # "00-950 Warszawa GmbH": a company name, not an address line
        yield _Hit(m.start("line"), m.end("line"), EntityType.ADDRESS, 0.7)


EVERYWHERE: tuple[Rule, ...] = (
    _find_labelled_pesel,
    _find_labelled_nip,
    _find_labelled_regon,
    _find_vat_number,
    _find_labelled_id_card,
    _find_labelled_passport,
)
RULES: tuple[Rule, ...] = (
    _find_pesel,
    _find_nip,
    _find_id_card,
    _find_passport,
    _find_phone,
    _find_address,
    _find_postcode,
)
