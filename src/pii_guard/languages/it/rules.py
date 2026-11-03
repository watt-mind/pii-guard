"""Italian language pack: rules for Italian identifiers and formats (LAB-1776).

Italian IBANs (``IT`` + 25 characters) and ``+39`` phone numbers need nothing here: the
language-independent rules (:mod:`pii_guard.detect.rules.common`) already find them.

Run for every language (``EVERYWHERE``), because the value validates or a label says what it
is:

- the codice fiscale: 16 characters with a month letter, a day, a check letter (mod 26) and
  omocodia letters in place of digits. Sixteen characters in that letter/digit pattern with a
  valid check letter are an Italian tax code in any text;
- an EU VAT number ``IT`` + a valid partita IVA;
- a carta d'identità elettronica number (``CA00000AA``) **next to its label** (``carta
  d'identità``, ``CIE``, ``documento``).

Run only for Italian text (``RULES``), because the format alone is ambiguous elsewhere:

- a partita IVA next to its label (``P.IVA``, ``partita IVA``): a bare 11-digit number with a
  Luhn digit is as often a Hungarian personal ID or a German Steuer-ID, so an unlabelled one is
  never matched, and in another language's text the label is a cue (``cues.tsv``, 0.6);
- an unlabelled CIE number (``C``, a letter, five digits, two letters);
- national phone numbers: mobile ``347 123 4567`` (grouped; a compact one needs a cue) and
  landline ``02 5550 1234``, ``(011) 555 0123``;
- addresses: ``Via dei Mille 27``, optionally followed by ``, 40121 Bologna (BO)``, and a CAP
  before a place name where an address line starts (``40121 Bologna``).

Every identifier is ``ID_DOCUMENT`` (the taxonomy has no Italian type, as for German and
Polish identifiers). A passport (two letters, seven digits) and a driving licence have no check
character: they are masked after their cue (``passaporto``, ``patente``, ``cues.tsv``), and so
are identifiers whose check character fails.
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
from pii_guard.languages.it.checksums import is_valid_codice_fiscale, is_valid_partita_iva
from pii_guard.types import EntityType

__all__ = ["EVERYWHERE", "RULES"]

_UPPER = "A-ZÀÈÉÌÒÙ"
_LOWER = "a-zàèéìíòóù"
# An Italian amount: a currency word or sign right after the number.
_NOT_AMOUNT_IT = r"(?!\s?(?:EUR|€|euro)(?!\w))"
_LABEL_WINDOW = 40
# An apostrophe, straight or typographic (elision: "d'identità", "dell'Indipendenza").
_APOS = "['\u2019]"


def _label_before(pattern: re.Pattern[str], text: str, start: int) -> bool:
    """True if ``pattern`` (a label, whole words) occurs in the 40 characters before ``start``."""
    return pattern.search(text, max(0, start - _LABEL_WINDOW), start) is not None


# --- Codice fiscale -------------------------------------------------------------------

# Letters at the name, month, place and check positions; a digit or an omocodia letter at the
# seven digit positions. Capitals only: a lowercase run of sixteen letters is a word.
_D = "[0-9LMNPQRSTUV]"
_CF_RE = re.compile(
    rf"(?<![\w-])(?P<value>[A-Z]{{6}}{_D}{{2}}[ABCDEHLMPRST]{_D}{{2}}[A-Z]{_D}{{3}}[A-Z])(?![\w-])"
)


def _find_codice_fiscale(text: str) -> Iterator[_Hit]:
    for m in _CF_RE.finditer(text):
        if is_valid_codice_fiscale(m.group("value")):
            yield _Hit(m.start(), m.end(), EntityType.ID_DOCUMENT, 0.97, VALIDATED_ID_DOCUMENT)


# --- Partita IVA ----------------------------------------------------------------------

_PIVA_RE = re.compile(
    NUM_START + NO_GROUP_BEFORE + r"(?P<value>\d{11})" + NUM_END + NO_GROUP_AFTER + _NOT_AMOUNT_IT
)
_VAT_RE = re.compile(r"(?<![\w-])IT ?(?P<value>\d{11})(?![\w-])")
# "P.IVA", "P. IVA", "P.I.", "partita IVA", "part. IVA", "C.F./P.IVA", "codice IVA".
_PIVA_LABEL_RE = re.compile(
    r"(?i:(?<!\w)(?:p\.?[ \t]?iva|p\.[ \t]?i\.|partita[ \t]+iva|part\.[ \t]?iva|codice[ \t]+iva"
    r"|piva)(?!\w))"
)


def _find_labelled_partita_iva(text: str) -> Iterator[_Hit]:
    for m in _PIVA_RE.finditer(text):
        value = m.group("value")
        if is_valid_partita_iva(value) and _label_before(_PIVA_LABEL_RE, text, m.start("value")):
            yield _Hit(m.start(), m.end(), EntityType.ID_DOCUMENT, 0.95, VALIDATED_ID_DOCUMENT)


def _find_vat_number(text: str) -> Iterator[_Hit]:
    for m in _VAT_RE.finditer(text):
        if is_valid_partita_iva(m.group("value")):
            yield _Hit(m.start(), m.end(), EntityType.ID_DOCUMENT, 0.95, VALIDATED_ID_DOCUMENT)


# --- Carta d'identità elettronica -----------------------------------------------------

# CIE 3.0: "CA00000AA", the series starting with C. A paper ID card ("AU 1234567") and a
# passport ("YA1234567") have the shape of many codes: they are left to the cues.
_CIE_RE = re.compile(r"(?<![\w-])(?P<value>C[A-Z] ?\d{5} ?[A-Z]{2})(?![\w-])")
_CIE_LABEL_RE = re.compile(
    rf"(?i:(?<!\w)(?:carta[ \t]+(?:d{_APOS}[ \t]?|di[ \t]+)identit[àa]|c\.?i\.?e\.?"
    rf"|documento(?:[ \t]+(?:d{_APOS}[ \t]?|di[ \t]+)identit[àa])?|identity[ \t]+card"
    r"|id[ \t]+card)(?!\w))"
)


def _find_cie(text: str) -> Iterator[_Hit]:
    for m in _CIE_RE.finditer(text):
        if _label_before(_CIE_LABEL_RE, text, m.start()):
            yield _Hit(m.start(), m.end(), EntityType.ID_DOCUMENT, 0.95, VALIDATED_ID_DOCUMENT)


def _find_unlabelled_cie(text: str) -> Iterator[_Hit]:
    for m in _CIE_RE.finditer(text):
        if _label_before(_CIE_LABEL_RE, text, m.start()):
            continue  # the labelled rule's
        if not reference_or_amount_before(text, m.start()):
            yield _Hit(m.start(), m.end(), EntityType.ID_DOCUMENT, 0.8)


# --- Phone numbers --------------------------------------------------------------------

# Mobile: ten digits (some nine) starting 3, grouped 3-3-4, 3-7 or 3-3-3; a compact run needs
# a cue (cues.tsv), since a bare ten-digit number is as often an order or a customer number.
# "345.123.456" is a thousands-grouped count, not a phone: dots only with a 4- or 7-digit tail.
_MOBILE_RE = re.compile(
    r"(?<![\w+(])(?<!\d[-./ ])"
    r"(?P<value>3[1-9]\d(?P<sep>[ .-])(?:\d{3}(?P=sep)\d{3,4}|\d{7}))"
    r"(?!\d)(?![-./ ]\d)" + _NOT_AMOUNT_IT + NOT_IN_WORD_AFTER
)
# Landline: the trunk 0 and an area code (two to four digits, optionally in parentheses), a
# space, slash or hyphen, then 5-8 digits compact or in two to four groups split by spaces.
# Dots never separate the groups: "05.11.2026" and "08.30-12.30" are a date and a time.
_LANDLINE_RE = re.compile(
    r"(?<![\w+(/.])(?<!\d[-./ ])"
    r"(?P<value>(?:\(0\d{1,3}\)[ \t]?|0\d{1,3}[ \t/-])"
    r"(?:\d{5,8}|\d{2,4}(?:[ \t]\d{2,4}){1,3}))"
    r"(?!\d)(?![-./ ]\d)" + _NOT_AMOUNT_IT + NOT_IN_WORD_AFTER
)
_DIGIT_COUNTS = ((_MOBILE_RE, 9, 10), (_LANDLINE_RE, 8, 11))


def _find_phone(text: str) -> Iterator[_Hit]:
    for pattern, low, high in _DIGIT_COUNTS:
        for m in pattern.finditer(text):
            value = m.group("value")
            if not low <= sum(ch.isdigit() for ch in value) <= high:
                continue
            if "." in value and not re.search(r"\d{4}$", value):
                continue  # "345.123.456": thousands
            if not reference_or_amount_before(text, m.start("value")):
                yield _Hit(m.start("value"), m.end("value"), EntityType.PHONE, 0.8)


# --- Addresses ------------------------------------------------------------------------

_STREET_TYPE = (
    r"(?:via|viale|v\.le|piazza|p\.zza|p\.za|piazzale|p\.le|corso|c\.so|largo|vicolo|vico"
    r"|strada|contrada|c\.da|lungomare|lungotevere|lungarno|borgo|salita|galleria|calle"
    r"|campo|fondamenta|località|loc\.|frazione|fraz\.)"
)
# A capitalised word, not an abbreviation before a number or a lowercase word ("Tel. 051").
_CAP_WORD = (
    rf"[{_UPPER}][{_LOWER}]+(?:{_APOS}[{_UPPER}][{_LOWER}]+)?(?![{_LOWER}])(?!\.[ \t]*[\d{_LOWER}])"
)
_PARTICLE = r"(?:dei|degli|delle|della|dello|del|dai|dalla|da|di|de|e|ai|alla|al|sul|sulla|san)"
_ELIDED = rf"(?:dell|dall|all|sull|nell|d|l|sant){_APOS}"
# One word of a street name: particles and an elided article before a capitalised word, or a
# Roman numeral ("Via XX Settembre", "Via Pio IX"); a day number may open it ("Via 4 Novembre").
_UNIT = rf"(?:{_PARTICLE}[ \t]+)*(?:{_ELIDED})?(?:{_CAP_WORD}|[IVXL]{{1,5}}(?![\w']))"
_STREET_NAME = rf"(?:\d{{1,2}}[ \t]+)?{_UNIT}(?:[ \t]+{_UNIT}){{0,3}}"
_HOUSE_NUMBER = r"(?:nr?\.?[ \t]?)?\d{1,4}(?:[ \t]?/[ \t]?(?:[A-Za-z]|\d{1,3})|[A-Za-z])?"
_PLACE = (
    rf"{_CAP_WORD}(?:(?:[ \t]+|-)"
    rf"(?:(?:in|di|del|della|sul|al|de)[ \t]+|(?:nell|dell|d|sull){_APOS})?{_CAP_WORD}){{0,2}}"
    r"(?:[ \t]*\([A-Z]{2}\))?"
)
_CAP_PLACE = rf"(?P<code>\d{{5}})[ \t]+{_PLACE}"
_ADDRESS_RE = re.compile(
    rf"(?<![\w.])(?i:{_STREET_TYPE})[ \t]+{_STREET_NAME}(?:,[ \t]*|[ \t]+){_HOUSE_NUMBER}"
    rf"(?![\w/])(?:(?:,[ \t]*|[ \t]+-[ \t]+|[ \t]+|[ \t]*\n[ \t]*){_CAP_PLACE}(?![\w-]))?"
)
# Italian nouns are not capitalised, but a sentence may start after a number ("20000
# Partecipanti", "10000 Euro"): a bare CAP counts only where an address line starts.
_POSTCODE_RE = re.compile(
    r"(?:(?<=^)|(?<=\n)|(?<=,)|(?<=, ))[ \t]*(?P<line>" + _CAP_PLACE + r")(?![\w-])",
    re.MULTILINE,
)
# Lowercase words right after a house number that make it a count ("via Zoom 3 volte").
_COUNT_AFTER_RE = re.compile(
    r"[ \t]+(?:volt[ae]|or[ae]|giorn[oi]|minut[oi]|ann[oi]|mes[ei]|settiman[ae]|person[ae]"
    r"|euro|pagin[ae]|copi[ae]|pezz[oi])(?!\w)"
)
# Capitalised words after five digits that are not a place: amounts, counts.
_NOT_PLACES = frozenset({"euro", "eur", "abitanti", "persone", "pezzi", "utenti", "dipendenti"})
# An Italian legal form after the place makes it a company name ("20121 Milano S.r.l.").
_IT_LEGAL_FORM_AFTER_RE = re.compile(
    r"[ \t]+(?i:s\.?r\.?l\.?s?|s\.?p\.?a\.?|s\.?n\.?c\.?|s\.?a\.?s\.?)(?!\w)"
)


def _company_after(text: str, end: int) -> bool:
    return legal_form_after(text, end) or _IT_LEGAL_FORM_AFTER_RE.match(text, end) is not None


def _find_address(text: str) -> Iterator[_Hit]:
    for m in _ADDRESS_RE.finditer(text):
        if not m.group("code") and _COUNT_AFTER_RE.match(text, m.end()):
            continue  # "via Zoom 3 volte": a count, not a house number
        yield _Hit(m.start(), m.end(), EntityType.ADDRESS, 0.85 if m.group("code") else 0.75)


def _find_postcode(text: str) -> Iterator[_Hit]:
    for m in _POSTCODE_RE.finditer(text):
        place = m.group("line").split()[1].casefold()
        if place in _NOT_PLACES or _company_after(text, m.end("line")):
            continue
        yield _Hit(m.start("line"), m.end("line"), EntityType.ADDRESS, 0.7)


EVERYWHERE: tuple[Rule, ...] = (
    _find_codice_fiscale,
    _find_vat_number,
    _find_cie,
)
RULES: tuple[Rule, ...] = (
    _find_labelled_partita_iva,
    _find_unlabelled_cie,
    _find_phone,
    _find_address,
    _find_postcode,
)
