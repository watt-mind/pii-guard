"""Hungarian language pack: rules for Hungarian identifiers and formats.

Personal tax ID (adóazonosító jel) and TAJ number, giro account numbers, phone numbers with
the ``+36`` / ``0036`` / ``06`` prefix (validated against the area code), company registration
(cégjegyzékszám) and company tax numbers (adószám): these carry a checksum or an unambiguous
prefix and run for **every** language (``EVERYWHERE``): a Hungarian ID inside an English text
is still personal data.

The personal identification number (személyi azonosító, 11 digits with a date of birth and a
check digit), ID document numbers next to their label (személyi igazolvány, útlevél, vezetői
engedély, tartózkodási engedély, or ``... számú személyi igazolvány`` after the number),
machine-readable zones of ID cards and passports (TD1 and TD3, with their check digits) and
land registry parcel numbers next to ``hrsz.`` / ``helyrajzi szám`` also run everywhere: the
checksum or the label makes them unambiguous.

Addresses, postcodes (four digits before a settlement name, or in context), vehicle plates, a
TAJ number without its label (its mod-10 check passes one nine-digit run in ten) and an ID
card number without its label (``123456AB``) have no checksum, or too weak a one, so they run
only when the text is Hungarian (``RULES``); in other languages "2019 Robin" or "ISO-900" style
look-alikes would be false positives. A full address is validated against the gazetteer
instead (``pii_guard.lang``, ADR 0009): its postcode must belong to its settlement.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from functools import cache

from pii_guard.detect.checksums import (
    is_valid_giro,
    is_valid_hu_personal_id,
    is_valid_hu_tax_id,
    is_valid_hu_tax_number,
    is_valid_mrz_td1,
    is_valid_mrz_td3,
    is_valid_taj,
)
from pii_guard.detect.rules._base import (
    NO_GROUP_AFTER,
    NO_GROUP_BEFORE,
    NOT_AMOUNT,
    NOT_IN_WORD_AFTER,
    NUM_END,
    NUM_START,
    VALIDATED_ID_DOCUMENT,
    Rule,
    _Hit,
    context_before,
    legal_form_after,
    reference_or_amount_before,
)
from pii_guard.lang import LexiconUnavailable, lexicon, postcode_index
from pii_guard.languages.hu.companies import find_company_person
from pii_guard.types import EntityType
from pii_guard.vault.inflection import inflection_for

__all__ = ["EVERYWHERE", "RULES"]


# --- National identifiers ---------------------------------------------------

_TAX_ID_RE = re.compile(NUM_START + r"(8\d{9})" + NUM_END + NOT_AMOUNT)
_TAX_ID_CONTEXT = ("adóazonosító", "adóaz", "adószám", "tax id", "tax number")


def _find_hu_tax_id(text: str) -> Iterator[_Hit]:
    for m in _TAX_ID_RE.finditer(text):
        if is_valid_hu_tax_id(m.group(1)):
            if context_before(text, m.start(), _TAX_ID_CONTEXT):
                score = 0.99
            elif reference_or_amount_before(text, m.start()):
                continue  # "ticket 8123456786", "Order #8123456786": a reference (LAB-1227)
            else:
                score = 0.95
            yield _Hit(m.start(1), m.end(1), EntityType.NATIONAL_ID_HU_TAX, score)


_TAJ_RE = re.compile(
    NUM_START
    + NO_GROUP_BEFORE
    + r"(\d{3})([ -]?)(\d{3})\2(\d{3})"
    + NUM_END
    + NO_GROUP_AFTER
    + NOT_AMOUNT
)
# ``123.456.788`` and ``123/456/788``: printed this way too, but a dotted nine-digit number is
# far more often a thousands-grouped amount or count and a slashed one a file reference, so
# these two forms count only right after a TAJ cue (LAB-1216).
_TAJ_DOTTED_RE = re.compile(NUM_START + r"(\d{3})([./])(\d{3})\2(\d{3})" + NUM_END + NOT_AMOUNT)
_TAJ_CONTEXT = ("taj", "társadalombiztosítási", "social security")


def _taj_hits(text: str, *, labelled: bool) -> Iterator[_Hit]:
    for m in _TAJ_RE.finditer(text):
        if is_valid_taj(m.group(1) + m.group(3) + m.group(4)):
            # A mod-10 check passes for 1 in 10 random numbers: context matters more here.
            if context_before(text, m.start(), _TAJ_CONTEXT):
                if labelled:
                    yield _Hit(m.start(), m.end(), EntityType.NATIONAL_ID_HU_TAJ, 0.95)
            elif not labelled and not reference_or_amount_before(text, m.start()):
                # Not "Order number: 123456788", "INV-123456788", "$123 456 788".
                yield _Hit(m.start(), m.end(), EntityType.NATIONAL_ID_HU_TAJ, 0.8)
    if labelled:
        for m in _TAJ_DOTTED_RE.finditer(text):
            if is_valid_taj(m.group(1) + m.group(3) + m.group(4)) and context_before(
                text, m.start(), _TAJ_CONTEXT
            ):
                yield _Hit(m.start(), m.end(), EntityType.NATIONAL_ID_HU_TAJ, 0.95)


def _find_taj(text: str) -> Iterator[_Hit]:
    """A TAJ number after its label (``TAJ``, ``társadalombiztosítási``), in any language."""
    return _taj_hits(text, labelled=True)


def _find_bare_taj(text: str) -> Iterator[_Hit]:
    """A TAJ number without its label: Hungarian text only (LAB-1433).

    One nine-digit run in ten passes the check, so in another language an unlabelled one is
    far more often that language's own number (a Polish phone number or REGON) than a TAJ.
    """
    return _taj_hits(text, labelled=False)


# --- Personal identification number (személyi azonosító) --------------------

# ``1-710304-1234``, ``1 710304 1234`` or ``17103041234``: sex/century digit, date of birth,
# serial and check digit. The check digit and the date make it unambiguous everywhere; there
# is no type of its own, so like other national numbers it is an ID_DOCUMENT.
_PERSONAL_ID_RE = re.compile(
    NUM_START
    + NO_GROUP_BEFORE
    + r"([1-8])([ -]?)(\d{6})\2(\d{4})"
    + NUM_END
    + NO_GROUP_AFTER
    + NOT_AMOUNT
)
_PERSONAL_ID_CONTEXT = ("személyi azonosító", "személyi szám", "személyiszám", "personal id")


def _find_hu_personal_id(text: str) -> Iterator[_Hit]:
    for m in _PERSONAL_ID_RE.finditer(text):
        if is_valid_hu_personal_id(m.group(1) + m.group(3) + m.group(4)):
            if context_before(text, m.start(), _PERSONAL_ID_CONTEXT):
                score = 0.99
            elif reference_or_amount_before(text, m.start()):
                continue  # "Order 75302022056", "ticket: 28309121692": a reference (LAB-1327)
            else:
                score = 0.85
            yield _Hit(m.start(), m.end(), EntityType.ID_DOCUMENT, score, VALIDATED_ID_DOCUMENT)


# --- ID document numbers ----------------------------------------------------

# Hungarian document number formats: ID card ``123456AB`` (six digits, two letters), driving
# licence ``AB123456`` and passport ``AB1234567`` (two letters, six or seven digits).
_ID_CARD = r"\d{6}[A-Z]{2}"
_LETTERS_FIRST = r"[A-Z]{2}\d{6,7}"
_ID_FORMAT_RE = re.compile(rf"(?<![\w\-./])(?:{_ID_CARD}|{_LETTERS_FIRST})(?![\w\-]|[./]\w)")

# The document's name, in Hungarian (also inflected and abbreviated) and English. Matched at a
# word start, so "szig." doesn't fire inside "szigorú".
_ID_LABEL = (
    r"(?:szem[ée]ly(?:i|azonos[íi]t[óo])[ \t]+(?:igazolv[áa]ny\w*|ig\.?)"
    r"(?:[ \t]*(?:sz\.|sz[áa]m\w*))?"
    r"|szig(?:\.|sz[áa]m\w*|\b)"
    r"|igazolv[áa]nysz[áa]m\w*|okm[áa]ny(?:azonos[íi]t[óo]|sz[áa]m)\w*|okm[áa]ny[ \t]+sz[áa]m\w*"
    r"|[úu]tlev[ée]l\w*"
    r"|vezet[őo]i[ \t]+eng(?:ed[ée]ly\w*|\.)|jogos[íi]tv[áa]ny\w*|jogsi\w*"
    r"|tart[óo]zkod[áa]si[ \t]+(?:enged[ée]ly\w*|k[áa]rty[áa]\w*)"
    r"|(?:id(?:entity)?[ \t]+card|passport|driving[ \t]+licen[cs]e|driver'?s[ \t]+licen[cs]e"
    r"|residence[ \t]+(?:permit|card)))"
)
# Hungarian labels are also matched without accents, as people type them in chat ("szemelyi").
_ID_LABEL_RE = re.compile(rf"(?i:(?<!\w){_ID_LABEL})")
# The value right after its label: "személyi igazolvány száma: 123456AB", "útlevél (BA1234567)".
# Any 6-12 letters and digits with at least one of each (residence permits and foreign
# documents have other formats); a known Hungarian format scores higher.
_ID_AFTER_LABEL_RE = re.compile(
    rf"(?i:(?<!\w){_ID_LABEL})"
    r"(?:[ \t]+(?i:száma|szám|sz\.|no\.?|number|nr\.?))?"
    r"[ \t]*[:#(]?[ \t]*"
    r"(?P<id>(?=[A-Z]*\d)(?=\d*[A-Z])[A-Z\d]{6,12})(?![\w\-]|[./]\w)"
)
# The label after the value, as legal Hungarian has it: "a 123456AB számú személyi igazolvány",
# "BA1234567 sz. útlevéllel".
_ID_LABEL_AFTER_RE = re.compile(
    rf"[ \t]*(?:\([^)\n]{{0,20}}\)[ \t]*)?(?:számú|sz\.)[ \t]+{_ID_LABEL}", re.IGNORECASE
)
_ID_CONTEXT_WINDOW = 40


def _find_id_document(text: str) -> Iterator[_Hit]:
    """ID card, passport, driving licence and residence permit numbers next to their label."""
    for m in _ID_AFTER_LABEL_RE.finditer(text):
        known = _ID_FORMAT_RE.fullmatch(m.group("id")) is not None
        yield _Hit(
            m.start("id"),
            m.end("id"),
            EntityType.ID_DOCUMENT,
            0.95 if known else 0.85,
            VALIDATED_ID_DOCUMENT,
        )
    for m in _ID_FORMAT_RE.finditer(text):
        before = text[max(0, m.start() - _ID_CONTEXT_WINDOW) : m.start()]
        if _ID_LABEL_RE.search(before) or _ID_LABEL_AFTER_RE.match(text, m.end()):
            yield _Hit(m.start(), m.end(), EntityType.ID_DOCUMENT, 0.95, VALIDATED_ID_DOCUMENT)


_BARE_ID_CARD_RE = re.compile(rf"(?<![\w\-./]){_ID_CARD}(?![\w\-]|[./]\w)")


def _find_bare_id_card(text: str) -> Iterator[_Hit]:
    """``123456AB`` without its label: distinctive in Hungarian text, but no checksum."""
    for m in _BARE_ID_CARD_RE.finditer(text):
        yield _Hit(m.start(), m.end(), EntityType.ID_DOCUMENT, 0.7)


# --- Machine-readable zones (ICAO 9303) -------------------------------------

# OCR'd ID cards (TD1: 3 lines of 30) and passports (TD3: 2 lines of 44). Every check digit
# must agree; a zone of the right shape whose digits don't (OCR errors) still scores, lower.
# The whole zone is the span: it holds the name, document number and date of birth.
_MRZ_LINE = "[A-Z0-9<]"
_MRZ_TD3_RE = re.compile(
    rf"(?m)^[ \t]*(?P<l1>P{_MRZ_LINE}{{43}})[ \t]*\r?\n[ \t]*(?P<l2>{_MRZ_LINE}{{44}})[ \t]*$"
)
_MRZ_TD1_RE = re.compile(
    rf"(?m)^[ \t]*(?P<l1>[ACI]{_MRZ_LINE}{{29}})[ \t]*\r?\n"
    rf"[ \t]*(?P<l2>{_MRZ_LINE}{{30}})[ \t]*\r?\n[ \t]*(?P<l3>{_MRZ_LINE}{{30}})[ \t]*$"
)


def _find_mrz(text: str) -> Iterator[_Hit]:
    for m in _MRZ_TD3_RE.finditer(text):
        if "<<" not in m.group("l1"):
            continue  # the name field always has a "<<" separator
        valid = is_valid_mrz_td3(m.group("l1"), m.group("l2"))
        yield _Hit(
            m.start("l1"),
            m.end("l2"),
            EntityType.ID_DOCUMENT,
            0.99 if valid else 0.8,
            VALIDATED_ID_DOCUMENT,
        )
    for m in _MRZ_TD1_RE.finditer(text):
        if "<<" not in m.group("l3"):
            continue
        valid = is_valid_mrz_td1(m.group("l1"), m.group("l2"), m.group("l3"))
        yield _Hit(
            m.start("l1"),
            m.end("l3"),
            EntityType.ID_DOCUMENT,
            0.99 if valid else 0.8,
            VALIDATED_ID_DOCUMENT,
        )


# --- Bank accounts ----------------------------------------------------------

# Two or three blocks of 8 digits separated by a hyphen, a space or a dot, or nothing.
_GIRO_RE = re.compile(NUM_START + r"(\d{8})([- .]?)(\d{8})(?:\2(\d{8}))?" + NUM_END)
# The same account printed in four-character groups, using one consistent space or hyphen,
# and not as part of a longer grouped number (LAB-1095).
_GIRO_QUAD_RE = re.compile(
    NUM_START
    + NO_GROUP_BEFORE
    + r"(\d{4}([ -])\d{4}(?:\2\d{4}){2}(?:(?:\2\d{4}){2})?)"
    + NUM_END
    + r"(?![ -]\d)"
)


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
    for m in _GIRO_QUAD_RE.finditer(text):
        if is_valid_giro(m.group(1).replace(m.group(2), "")):
            yield _Hit(m.start(1), m.end(1), EntityType.BANK_ACCOUNT, 0.95)


# --- Contact details --------------------------------------------------------

# Hungarian numbers: prefix +36 / 0036 / 06, then the national significant number with
# optional separators and parentheses. Its length is checked against the area code below.
_HU_PHONE_RE = re.compile(
    r"(?<![\w+])(?<!\d[-./])"
    r"(?P<open>\()?"
    r"(?P<prefix>\+36|0036|06)"
    r"(?P<nsn>[ \-/]?\(?\d(?:(?:[ \-/.]|\)[ \-/]?)?\d){5,9})"
    r"(?!\d)" + NOT_IN_WORD_AFTER
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
    # English month names and abbreviations: `ls -la` and other tool output puts one
    # after a bare size or count ("1203 Oct 28"), which is not a settlement (LAB-1476).
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October",
    "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct",
    "Nov", "Dec",
    # Hungarian month abbreviations, as typed with a capital ("Okt", not "okt.").
    "Febr", "Márc", "Ápr", "Máj", "Jún", "Júl", "Szept", "Okt",
})  # fmt: skip


def _find_postcode(text: str) -> Iterator[_Hit]:
    """A postcode on its own (``3300 Eger``, ``irányítószám: 8200``): the code is the span.

    A full address around it is found by :func:`_find_address`, whose span contains this one.
    """
    for m in _POSTCODE_RE.finditer(text):
        place = _PLACE_AFTER_RE.match(text, m.end())
        if m.group("prefix"):
            score = 0.9
        elif context_before(text, m.start(), _POSTCODE_CONTEXT, window=25):
            score = 0.85
        elif place and place.group(1) not in _NOT_PLACES:
            # "1999 Budapest Kft.": a company name, and "Order 1051 Budapest": a reference;
            # neither number is a postcode (LAB-1227). A cued postcode always counts.
            if legal_form_after(text, place.end()) or reference_or_amount_before(text, m.start()):
                continue
            # A bare pair needs a gazetteer-known settlement: a month abbreviation from
            # tool output ("1203 Oct 28") or any other unknown word is not one (LAB-1476).
            settlement = _settlement(place.group(1))
            if settlement is None:
                continue
            # The postcode check works like a checksum: only a consistent pair is boosted.
            consistent = _postcodes_agree(m.group("code"), settlement)
            score = 0.85 if consistent else 0.75
        else:
            continue
        yield _Hit(m.start("code"), m.end("code"), EntityType.ADDRESS, score)


# A full address: ``[<postcode>] <settlement>[ <district>], <street name> <street type>
# <house number>[ <floor/door>]``, e.g. ``1051 Budapest, Minta utca 12. 3/5.``,
# ``9021 Győr, Gyöngyvirág utca 7. fszt. 2.`` or, without a postcode, ``Debrecen, Kitalált
# utca 5.`` (then the settlement must be in the gazetteer, possibly inflected: ``Szegeden``).
#
# Validation, like a checksum for a structured ID: the postcode must belong to the settlement
# (``pii_guard.lang.postcode_index``). Consistent pairs score highest; a settlement the
# gazetteer doesn't know scores lower; a known settlement with a postcode of another place is
# not boosted above a bare postcode.
_STREET_ABBREVIATIONS = ("u.", "krt.", "ltp.", "rkp.", "stny.", "sgt.")
_DOOR = r"\d{1,3}\.?(?:[ \t]*ajtó)?"
_UNIT = (
    r"(?:"
    rf"(?:fszt|mfszt|földszint)\.?(?:[ \t]+{_DOOR})?"
    rf"|\d{{1,2}}\.[ \t]*em(?:elet|\.)(?:[ \t]+{_DOOR})?"
    r"|\d{1,2}/\d{1,3}\.?"
    r")"
)
_HOUSE_NUMBER = r"\d{1,4}(?:/[A-Za-z](?!\w)|[/-]\d{1,4}|[A-Za-z](?!\w))?\.?"

SCORE_CONSISTENT = 0.97
SCORE_UNVALIDATED = 0.85
SCORE_MISMATCH = 0.75


@cache
def _address_re() -> re.Pattern[str]:
    try:
        types = list(lexicon("street_types", "hu"))
    except LexiconUnavailable:  # pragma: no cover - the lists ship with the package
        types = ["utca", "út", "tér", "köz", "sor", "körút", "sétány", "rakpart"]
    alternatives = sorted({*types, *_STREET_ABBREVIATIONS}, key=len, reverse=True)
    street_type = "|".join(re.escape(t) for t in alternatives)
    return re.compile(
        r"(?<![\w\-./,])"
        r"(?:(?:HU?-)?(?P<code>[1-9]\d{3})[ \t]+)?"
        rf"(?P<place>[{_UPPER}][{_LOWER}]{{2,}})"
        r"(?:[ \t]+(?P<district>[IVX]{1,5})\.(?:[ \t]*ker(?:ület|\.))?)?"
        r",[ \t]*(?:\n[ \t]*)?"
        rf"(?P<street>[{_UPPER}\d][\w.\-]*(?:[ \t]+[\w.\-]+){{0,3}}?)"
        rf"[ \t]+(?:{street_type})(?!\w)"
        rf"[ \t]+{_HOUSE_NUMBER}"
        rf"(?:[ \t]+{_UNIT})*",
    )


@cache
def _settlement(word: str) -> str | None:
    """The gazetteer settlement ``word`` names, also in an inflected form (``Szegeden``)."""
    try:
        settlements = lexicon("settlements", "hu")
    except LexiconUnavailable:  # pragma: no cover
        return None
    if word in settlements:
        return word
    matcher = inflection_for("hu")
    for cut in range(len(word) - 1, 2, -1):
        stem = word[:cut]
        if stem in settlements:
            suffix = matcher.suffix_pattern(stem, EntityType.ADDRESS)
            if suffix and re.fullmatch(suffix, word[cut:], re.IGNORECASE):
                return stem
    return None


def _postcodes_agree(code: str, settlement: str) -> bool:
    try:
        return postcode_index("hu").consistent(code, settlement)
    except LexiconUnavailable:  # pragma: no cover
        return False


_ROMAN = {"I": 1, "V": 5, "X": 10}


def _roman(numeral: str) -> int:
    total = 0
    for current, following in zip(numeral, [*numeral[1:], ""], strict=True):
        value = _ROMAN[current]
        total += -value if following and _ROMAN[following] > value else value
    return total


def _district_agrees(code: str, district: str | None) -> bool:
    """A Budapest district (``XIII.``) must match the postcode's 2nd-3rd digits (``1134``)."""
    return district is None or not code.startswith("1") or int(code[1:3]) == _roman(district)


def _find_address(text: str) -> Iterator[_Hit]:
    for m in _address_re().finditer(text):
        word = m.group("place")
        if word in _NOT_PLACES:
            continue
        settlement = _settlement(word)
        code = m.group("code")
        if code is None:
            if settlement is None:
                continue  # "Kedves Anna, Minta utca 1." is not an address without a town
            score = SCORE_UNVALIDATED
        elif settlement is None:
            score = SCORE_UNVALIDATED
        elif _postcodes_agree(code, settlement) and _district_agrees(code, m.group("district")):
            score = SCORE_CONSISTENT
        else:
            score = SCORE_MISMATCH
        start = m.start("code") if code is not None else m.start("place")
        yield _Hit(start, m.end(), EntityType.ADDRESS, score)


# --- Land registry parcel numbers (helyrajzi szám) --------------------------

# ``1234``, ``1234/5``, ``0123/4`` (outskirts), ``0123/4/A/12`` (a unit in a condominium).
# Without a checksum and easily confused with fractions, dates and case numbers, so a parcel
# number needs its label right before or after it; a settlement name or "belterület" /
# "külterület" nearby raises the score.
_PARCEL = r"\d{1,6}(?:/\d{1,5})?(?:/[A-Z](?:/\d{1,4})?)?"
# Not followed by more digits, or by a full stop and a lowercase word: "3. emelet" is an ordinal.
_PARCEL_END = rf"(?![\w/]|[.\-]\d|\.[ \t]*[{_LOWER}])"
_PARCEL_LABEL = r"(?:hrsz\.?|helyrajzi[ \t]+sz(?:ám|\.)\w*)"
_PARCEL_AFTER_LABEL_RE = re.compile(
    rf"(?i:(?<!\w){_PARCEL_LABEL})[ \t]*(?::|-?(?:on|ön|en|ú|ű)\b)?[ \t]*\r?\n?[ \t]*"
    rf"(?P<n>{_PARCEL}){_PARCEL_END}"
)
# More parcels listed after the first: "hrsz.: 1234/5, 1234/6 és 1234/7".
_PARCEL_LIST_RE = re.compile(
    rf"(?:[ \t]*,[ \t]*|[ \t]+(?:és|valamint|and)[ \t]+)(?P<n>{_PARCEL}){_PARCEL_END}"
)
_PARCEL_BEFORE_LABEL_RE = re.compile(
    rf"(?<![\w\-./,])(?P<n>{_PARCEL})(?:[ \t]*\([^)\n]{{0,20}}\))?[ \t]+-?"
    rf"(?i:{_PARCEL_LABEL})"
)
_PARCEL_AREA = ("belterület", "külterület", "zártkert", "település", "ingatlan")
_PARCEL_PLACE_RE = re.compile(rf"[{_UPPER}][{_LOWER}]{{2,}}")


def _parcel_score(text: str, start: int) -> float:
    before = text[max(0, start - 60) : start]
    if any(word in before.casefold() for word in _PARCEL_AREA):
        return 0.95
    if any(_settlement(w.group()) for w in _PARCEL_PLACE_RE.finditer(before)):
        return 0.95
    return 0.9


def _find_parcel_number(text: str) -> Iterator[_Hit]:
    for m in _PARCEL_AFTER_LABEL_RE.finditer(text):
        score = _parcel_score(text, m.start())
        yield _Hit(m.start("n"), m.end("n"), EntityType.PARCEL_NUMBER_HU, score)
        end = m.end()
        while (more := _PARCEL_LIST_RE.match(text, end)) is not None:
            yield _Hit(more.start("n"), more.end("n"), EntityType.PARCEL_NUMBER_HU, score)
            end = more.end()
    for m in _PARCEL_BEFORE_LABEL_RE.finditer(text):
        score = _parcel_score(text, m.start())
        yield _Hit(m.start("n"), m.end("n"), EntityType.PARCEL_NUMBER_HU, score)


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
    _find_hu_personal_id,
    _find_id_document,
    _find_mrz,
    _find_parcel_number,
)
RULES: tuple[Rule, ...] = (
    _find_bare_taj,
    _find_vehicle_plate,
    _find_address,
    _find_postcode,
    _find_bare_id_card,
    find_company_person,
)
