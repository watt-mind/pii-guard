"""Dutch language pack: rules for Dutch identifiers and formats (LAB-1777).

Dutch IBANs (``NL`` + 2 check digits + a 4-letter bank code + 10 digits) and ``+31`` phone
numbers need nothing here: the language-independent rules
(:mod:`pii_guard.detect.rules.common`) already find them.

Run for every language (``EVERYWHERE``), because a label says what the value is:

- a BSN (burgerservicenummer, also the old sofinummer) **next to its label** (``BSN``,
  ``burgerservicenummer``, ``sofinummer``), compact or grouped (``1234.56.782``,
  ``123 456 782``), with a valid elfproef.

Run only for Dutch text (``RULES``), because the format alone is ambiguous elsewhere:

- an unlabelled BSN (nine digits, compact, elfproef). One number in eleven passes the check,
  so in another language's text a nine-digit number is as often a Polish phone number or a
  Hungarian TAJ (the lesson of LAB-1433); there, only the label makes it a BSN;
- national phone numbers with the trunk prefix ``0``, ten digits: mobile ``06-12345678``,
  ``06 1234 5678`` (and compact ``0612345678``), landline ``020-555 0193``, ``(010) 1234567``,
  ``0471-555012``; service numbers (``0800``, ``0900``) are companies';
- addresses: ``Lindelaan 42``, ``Van Goghstraat 7-II``, optionally followed by
  ``, 3521 AB Utrecht``; a postcode with its place anywhere (``3521 AB Utrecht``), and a bare
  postcode after its label (``postcode 3521 AB``). PostNL never issues the letter pairs
  ``SA``, ``SD`` and ``SS``.

A BSN is ``ID_DOCUMENT`` (the taxonomy has no Dutch type, as for German and Polish
identifiers). Passport, ID-card and driving-licence numbers have no check digit: they are
masked after their cue (``paspoort``, ``identiteitskaart``, ``rijbewijs``, ``cues.tsv``), and
so is a labelled BSN whose elfproef fails. The KvK number (8 digits, Chamber of Commerce) is a
company's, not personal data: it is a ``-`` cue and a reference word.
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
from pii_guard.languages.nl.checksums import is_valid_bsn
from pii_guard.types import EntityType

__all__ = ["EVERYWHERE", "RULES"]

_UPPER = "A-ZÀ-ÖØ-Þ"
_LOWER = "a-zß-öø-ÿ"
# A Dutch amount: a currency word or sign right after the number.
_NOT_AMOUNT_NL = r"(?!\s?(?:EUR|€|euro)(?!\w))"
_LABEL_WINDOW = 40
# An apostrophe, straight or typographic ("'s-Hertogenbosch").
_APOS = "['\u2019]"


def _label_before(pattern: re.Pattern[str], text: str, start: int) -> bool:
    """True if ``pattern`` (a label, whole words) occurs in the 40 characters before ``start``."""
    return pattern.search(text, max(0, start - _LABEL_WINDOW), start) is not None


# --- BSN ------------------------------------------------------------------------------

# Compact, or grouped 4-2-3 ("1234.56.782") or 3-3-3 ("123 456 782") with dots or spaces.
_BSN_RE = re.compile(
    NUM_START
    + NO_GROUP_BEFORE
    + r"(?P<value>\d{9}|\d{4}(?P<sep>[. ])\d{2}(?P=sep)\d{3}"
    + r"|\d{3}(?P<sep3>[. ])\d{3}(?P=sep3)\d{3})"
    + NUM_END
    + NO_GROUP_AFTER
    + _NOT_AMOUNT_NL
)
_BSN_COMPACT_RE = re.compile(
    NUM_START + NO_GROUP_BEFORE + r"(?P<value>\d{9})" + NUM_END + NO_GROUP_AFTER + _NOT_AMOUNT_NL
)
# Whole words: "BSN", "BSN-nummer", "burgerservicenummer", "burger service nummer",
# "sofinummer", "sofi-nummer", "sofi-nr.", "sociaal-fiscaal nummer".
_BSN_LABEL_RE = re.compile(
    r"(?i:(?<!\w)(?:bsn|burger[ \t-]?service[ \t-]?nummer|sofi[ \t-]?(?:nummer|nr)"
    r"|sociaal[ \t-]fiscaal[ \t-]?nummer)(?!\w))"
)


def _find_labelled_bsn(text: str) -> Iterator[_Hit]:
    for m in _BSN_RE.finditer(text):
        value = m.group("value").replace(".", "").replace(" ", "")
        if is_valid_bsn(value) and _label_before(_BSN_LABEL_RE, text, m.start("value")):
            yield _Hit(
                m.start("value"),
                m.end("value"),
                EntityType.ID_DOCUMENT,
                0.97,
                VALIDATED_ID_DOCUMENT,
            )


def _find_unlabelled_bsn(text: str) -> Iterator[_Hit]:
    # Compact only: a dotted or spaced run of nine digits is as often an amount or a count.
    for m in _BSN_COMPACT_RE.finditer(text):
        start = m.start("value")
        if not is_valid_bsn(m.group("value")) or _label_before(_BSN_LABEL_RE, text, start):
            continue  # not a BSN, or the labelled rule's
        if not reference_or_amount_before(text, start):
            yield _Hit(start, m.end("value"), EntityType.ID_DOCUMENT, 0.85)


# --- Phone numbers --------------------------------------------------------------------

# Mobile: 06 and eight digits, compact or grouped 4-4, 2-2-2-2 or 3-3-2 after the prefix; the
# prefix set off by a hyphen or a space, or in parentheses ("(06) 12345678"). "06-12-2026" is
# a date: the groups after the prefix are never 2-4.
_MOBILE_RE = re.compile(
    r"(?<![\w+(/.])(?<!\d[-./ ])"
    r"(?P<value>(?:\(06\)[ \t]?|06(?:[ \t]?-[ \t]?|[ \t])?)"
    r"(?:\d{8}|\d{4}[ \t]\d{4}|\d{2}(?:[ \t]\d{2}){3}|\d{3}[ \t]\d{3}[ \t]\d{2}))"
    r"(?!\d)(?![-./ ]\d)" + _NOT_AMOUNT_NL + NOT_IN_WORD_AFTER
)
# Landline: the trunk 0 and an area code of two or three more digits (010, 020, 0471), set off
# by a hyphen, a space or parentheses, then the subscriber number: ten digits in all. Dots
# never separate the groups: "05.11.2026" and "08.30" are a date and a time.
_LANDLINE_RE = re.compile(
    r"(?<![\w+(/.])(?<!\d[-./ ])"
    r"(?P<value>(?:\((?P<area_p>0[1-9]\d{1,2})\)[ \t]?|(?P<area>0[1-9]\d{1,2})[ \t]?-[ \t]?"
    r"|(?P<area_s>0[1-9]\d{1,2})[ \t])"
    r"(?:\d{6,7}|\d{3}[ \t]\d{3,4}|\d{2}[ \t]\d{2}[ \t]\d{2,3}|\d{3}[ \t]\d{2}[ \t]\d{2}))"
    r"(?!\d)(?![-./ ]\d)" + _NOT_AMOUNT_NL + NOT_IN_WORD_AFTER
)
# Free-phone and premium numbers (0800, 0900, 0906, 0909) belong to companies; 06 is the
# mobile rule's.
_NOT_LANDLINE_AREAS = ("06", "080", "090")


def _find_phone(text: str) -> Iterator[_Hit]:
    for m in _MOBILE_RE.finditer(text):
        if not reference_or_amount_before(text, m.start("value")):
            yield _Hit(m.start("value"), m.end("value"), EntityType.PHONE, 0.8)
    for m in _LANDLINE_RE.finditer(text):
        value = m.group("value")
        area = m.group("area_p") or m.group("area") or m.group("area_s")
        if sum(ch.isdigit() for ch in value) != 10 or area.startswith(_NOT_LANDLINE_AREAS):
            continue
        if not reference_or_amount_before(text, m.start("value")):
            yield _Hit(m.start("value"), m.end("value"), EntityType.PHONE, 0.8)


# --- Addresses ------------------------------------------------------------------------

# A street name is usually one word ending in its type ("Lindelaan", "Havenweg",
# "Prinsengracht"). "dam" and "haven" are left out: they end too many place names
# ("Amsterdam 12").
_STREET_TYPE = (
    r"(?:straat|laan|weg|plein|gracht|kade|singel|dijk|steeg|pad|hof|markt|park|dreef"
    r"|plantsoen|wal|baan|boulevard|kanaal|erf)"
)
# Words that may stand before it: particles, titles and adjectives of street names ("Van
# Goghstraat", "Burgemeester de Withstraat", "Prins Hendrikkade", "Oude Gracht").
_STREET_PREFIX = (
    r"(?:Van|De|Den|Der|Ter|Ten|Het|van|de|den|der|ter|ten|het|'t|Sint|St\.|Prins|Prinses"
    r"|Koning|Koningin|Burgemeester|Burg\.|Dokter|Dr\.|Graaf|Jonkheer|Oude|Nieuwe|Korte|Lange"
    r"|Grote|Kleine|Hoge|Lage|Noord|Zuid|Oost|West|Eerste|Tweede|Derde)"
)
# A street type may also stand as a word of its own after a prefix ("Oude Gracht").
_STREET_WORD = r"(?:Straat|Laan|Weg|Plein|Gracht|Kade|Singel|Dijk|Markt|Wal|Boulevard)"
_STREET_NAME = (
    rf"(?:{_STREET_PREFIX}[ \t]+){{0,3}}"
    rf"(?:[{_UPPER}][{_LOWER}\-]*{_STREET_TYPE}|{_STREET_WORD})"
)
# "42", "42a", "42-II", "42-2", "42 hs", "42 bis"; a four-digit number that reads as a year
# is no house number.
_HOUSE_NUMBER = (
    r"(?!(?:19|20)\d\d(?!\d))\d{1,4}"
    r"(?:-?[A-Za-z](?![\w])|-(?:I{1,3}|IV|\d{1,3})(?![\w])|[ \t](?:hs|bis|huis|I{1,3})(?![\w]))?"
)
# A place: optionally an article or "'s-", one to three capitalised words joined by a hyphen
# or a particle ("Den Haag", "'s-Hertogenbosch", "Bergen op Zoom", "Alphen aan den Rijn").
_PLACE_WORD = rf"(?:IJ[{_LOWER}]+|[{_UPPER}][{_LOWER}]+)"
_PLACE = (
    rf"(?:(?:Den|De|Het|Ter|Ten)[ \t]+|{_APOS}[st]-)?{_PLACE_WORD}"
    r"(?:(?:-|[ \t]+(?:aan[ \t]+de[nr]?|op[ \t]+de|in[ \t]+de|aan|op|bij|in|onder|over)[ \t]+)"
    rf"{_PLACE_WORD}){{0,2}}"
)
# Four digits (no leading 0) and two capital letters, never SA, SD or SS.
_POSTCODE = r"(?P<code>[1-9]\d{3}[ \t]?(?!S[ADS])[A-Z]{2})(?![\w])"
_POSTCODE_PLACE = rf"{_POSTCODE}[ \t]+{_PLACE}"
_ADDRESS_RE = re.compile(
    rf"(?<![\w.-]){_STREET_NAME}[ \t]+{_HOUSE_NUMBER}(?![\w/])"
    rf"(?:(?:,[ \t]*|[ \t]+|[ \t]*\n[ \t]*){_POSTCODE_PLACE}(?![\w-]))?"
)
_POSTCODE_RE = re.compile(rf"(?<![\w-]){_POSTCODE_PLACE}(?![\w-])")
_BARE_POSTCODE_RE = re.compile(rf"(?<![\w-]){_POSTCODE}(?![\w-])")
_POSTCODE_LABEL_RE = re.compile(r"(?i:(?<!\w)postcode(?!\w))[ \t:]*$")
# Lowercase words right after a house number that make it a count ("de weg 3 keer").
_COUNT_AFTER_RE = re.compile(
    r"[ \t]+(?:keer|maal|uur|minuten|dagen|weken|maanden|jaar|jaren|euro|procent|personen"
    r"|mensen|km|kilometer|meter|stuks|kamers)(?!\w)"
)
# Letter pairs after four digits that are units or abbreviations ("1000 KB", "2026 EU").
_NOT_POSTCODE_LETTERS = frozenset(
    {"KB", "MB", "GB", "TB", "PB", "EU", "NL", "BV", "NV", "KM", "CM", "MM", "KW", "MW", "GW"}
)
# A Dutch legal form after the place makes it a company name ("3521 AB Utrecht B.V.").
_NL_LEGAL_FORM_AFTER_RE = re.compile(r"[ \t]+(?i:b\.?v\.?|n\.?v\.?|v\.?o\.?f\.?|c\.?v\.?)(?!\w)")


def _postcode_ok(m: re.Match[str], text: str, end: int) -> bool:
    if m.group("code")[-2:] in _NOT_POSTCODE_LETTERS:
        return False
    return not (legal_form_after(text, end) or _NL_LEGAL_FORM_AFTER_RE.match(text, end))


def _find_address(text: str) -> Iterator[_Hit]:
    for m in _ADDRESS_RE.finditer(text):
        if m.group("code"):
            if not _postcode_ok(m, text, m.end()):
                continue
        elif _COUNT_AFTER_RE.match(text, m.end()):
            continue  # "de weg 3 keer": a count, not a house number
        yield _Hit(m.start(), m.end(), EntityType.ADDRESS, 0.85 if m.group("code") else 0.75)


def _find_postcode(text: str) -> Iterator[_Hit]:
    for m in _POSTCODE_RE.finditer(text):
        if _postcode_ok(m, text, m.end()) and not reference_or_amount_before(text, m.start()):
            yield _Hit(m.start(), m.end(), EntityType.ADDRESS, 0.75)
    for m in _BARE_POSTCODE_RE.finditer(text):
        before = text[max(0, m.start() - _LABEL_WINDOW) : m.start()]
        if _POSTCODE_LABEL_RE.search(before) and _postcode_ok(m, text, m.end()):
            yield _Hit(m.start(), m.end(), EntityType.ADDRESS, 0.7)


EVERYWHERE: tuple[Rule, ...] = (_find_labelled_bsn,)
RULES: tuple[Rule, ...] = (_find_unlabelled_bsn, _find_phone, _find_address, _find_postcode)
