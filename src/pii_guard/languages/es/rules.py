"""Spanish language pack: rules for Spanish identifiers and formats (LAB-1775).

Spanish IBANs (``ES`` + 22 digits) and ``+34`` phone numbers need nothing here: the
language-independent rules (:mod:`pii_guard.detect.rules.common`) already find them.

Run for every language (``EVERYWHERE``), because the value validates and its letters make
it distinctive:

- a DNI / NIF (``12345678Z``, ``12.345.678-Z``): eight digits and the mod-23 check letter;
- a NIE (``X1234567L``, ``X-1234567-L``): ``X``/``Y``/``Z``, seven digits and the check letter;
- a company CIF (``J99216582``) **next to its label** (``CIF``, ``NIF``) only: a letter and
  eight characters is a common shape for codes, so the label says what it is.

Run only for Spanish text (``RULES``), because the format alone is ambiguous elsewhere:

- national phone numbers: nine digits starting 6-9, grouped ``612 345 678``,
  ``612 34 56 78`` or ``91 234 56 78``, and a compact mobile (``612345678``);
- addresses: ``Calle del Olmo 14, 3.º B, 28012 Madrid`` (also ``C/``, ``Avda.``, ``Plaza``,
  ``Paseo`` ...), and a postcode before a place name where an address line starts
  (``28012 Madrid`` at the start of a line, after a comma or after ``C.P.``).

Every identifier is ``ID_DOCUMENT`` (the taxonomy has no Spanish type, as for German and
Polish identifiers). Bad check letters, passports, social security and driving-licence
numbers are found by the cues (``cues.tsv``).
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from pii_guard.detect.rules._base import (
    NO_GROUP_BEFORE,
    NOT_IN_WORD_AFTER,
    NUM_START,
    VALIDATED_ID_DOCUMENT,
    Rule,
    _Hit,
    legal_form_after,
    reference_or_amount_before,
)
from pii_guard.languages.es.checksums import is_valid_cif, is_valid_dni, is_valid_nie
from pii_guard.types import EntityType

__all__ = ["EVERYWHERE", "RULES"]

_UPPER = "A-ZÁÉÍÓÚÑÜ"
_LOWER = "a-záéíóúñüç"
# A Spanish amount: a currency word or sign right after the number.
_NOT_AMOUNT_ES = r"(?!\s?(?:€|EUR|euros?)(?!\w))"

# Labels, as whole words: ``context_before`` matches substrings, and ``nieto`` holds ``nie``.
_DNI_LABEL_RE = re.compile(
    r"(?i:(?<!\w)(?:d\.?n\.?i|n\.?i\.?f|documento nacional de identidad)(?!\w))"
)
_NIE_LABEL_RE = re.compile(
    r"(?i:(?<!\w)(?:n\.?i\.?e|t\.?i\.?e|tarjeta de residencia|extranjer[oa]s?)(?!\w))"
)
_CIF_LABEL_RE = re.compile(r"(?i:(?<!\w)(?:c\.?i\.?f|n\.?i\.?f)(?!\w))")
_LABEL_WINDOW = 40


def _labelled(label: re.Pattern[str], text: str, start: int) -> bool:
    """True if ``label`` appears in the ``_LABEL_WINDOW`` characters before ``start``."""
    return label.search(text, max(0, start - _LABEL_WINDOW), start) is not None


def _compact(value: str) -> str:
    return value.replace(" ", "").replace("-", "").replace(".", "")


# --- DNI / NIF, NIE, CIF ----------------------------------------------------------------

# Eight digits (compact or dotted in thousands) and the letter, glued or after a hyphen. A
# space before the letter counts only next to a label: in "unos 12345678 A las ..." the
# letter is a word, and one number in 23 would give it.
_DNI_RE = re.compile(
    NUM_START
    + NO_GROUP_BEFORE
    + r"(?P<value>(?:\d{8}|\d{2}\.\d{3}\.\d{3})(?P<sep>[- ])?[A-Z])(?![\w-])"
)
_NIE_RE = re.compile(r"(?<![\w-])(?P<value>[XYZ](?P<sep>-?)\d{7}(?P=sep)[A-Z])(?![\w-])")
_CIF_RE = re.compile(r"(?<![\w-])(?P<value>[A-HJNP-SUVW]-?\d{7}-?[0-9A-J])(?![\w-])")


def _find_dni(text: str) -> Iterator[_Hit]:
    for m in _DNI_RE.finditer(text):
        if not is_valid_dni(_compact(m.group("value"))):
            continue
        start = m.start("value")
        labelled = _labelled(_DNI_LABEL_RE, text, start)
        if not labelled and (m.group("sep") == " " or reference_or_amount_before(text, start)):
            continue
        score = 0.97 if labelled else 0.9
        yield _Hit(start, m.end("value"), EntityType.ID_DOCUMENT, score, VALIDATED_ID_DOCUMENT)


def _find_nie(text: str) -> Iterator[_Hit]:
    for m in _NIE_RE.finditer(text):
        if not is_valid_nie(_compact(m.group("value"))):
            continue
        start = m.start("value")
        labelled = _labelled(_NIE_LABEL_RE, text, start)
        if not labelled and reference_or_amount_before(text, start):
            continue
        score = 0.97 if labelled else 0.9
        yield _Hit(start, m.end("value"), EntityType.ID_DOCUMENT, score, VALIDATED_ID_DOCUMENT)


def _find_labelled_cif(text: str) -> Iterator[_Hit]:
    for m in _CIF_RE.finditer(text):
        start = m.start("value")
        if is_valid_cif(_compact(m.group("value"))) and _labelled(_CIF_LABEL_RE, text, start):
            yield _Hit(start, m.end("value"), EntityType.ID_DOCUMENT, 0.95, VALIDATED_ID_DOCUMENT)


# --- Phone numbers ----------------------------------------------------------------------

# Nine digits, the first 6-9 (6 and 7: mobile; 8 and 9: fixed line), as Spanish text groups
# them: 3-3-3, 3-2-2-2, or a two-digit area code then 3-2-2 ("91 234 56 78"). Dots only
# where the grouping is no thousands grouping ("612.345.678" can be a count). A compact run
# needs a mobile prefix: a bare nine-digit 8xx/9xx run is as often a file or order number,
# and a cue (``teléfono``, ``cues.tsv``) finds those.
_PHONE_RE = re.compile(
    r"(?<![\w+(])(?<!\d[-./ ])"
    r"(?:[6-9]\d{2}(?P<s1>[ -])\d{3}(?P=s1)\d{3}"
    r"|[6-9]\d{2}(?P<s2>[ .-])\d{2}(?P=s2)\d{2}(?P=s2)\d{2}"
    r"|[89]\d(?P<s3>[ .-])\d{3}(?P=s3)\d{2}(?P=s3)\d{2}"
    r"|[67]\d{8})"
    r"(?!\d)(?![-./ ]\d)" + _NOT_AMOUNT_ES + NOT_IN_WORD_AFTER
)


def _find_phone(text: str) -> Iterator[_Hit]:
    for m in _PHONE_RE.finditer(text):
        if not reference_or_amount_before(text, m.start()):
            yield _Hit(m.start(), m.end(), EntityType.PHONE, 0.8)


# --- Addresses --------------------------------------------------------------------------

_STREET_TYPE = (
    r"(?:calle|c/|avenida|avda\.|av\.|plaza|pza\.|paseo|p\.º|camino|carretera|ctra\.|ronda"
    r"|traves[íi]a|glorieta|urbanizaci[óo]n|urb\.|pasaje|rambla|v[íi]a)"
)
_CONNECTOR = r"(?:de|del|la|las|los|el|y)"
# Words of a street name: capitalised words and abbreviations ("Gran Vía", "Dr. Fleming"),
# Roman numerals ("Alfonso XII"), joined by lowercase connectors ("del Olmo", "de la Paz").
_NAME_WORD = rf"(?:[{_UPPER}][{_LOWER}]*\.?(?:-[{_UPPER}][{_LOWER}]+)?|[IVXL]{{1,5}})"
_STREET_NAME = (
    rf"(?:{_CONNECTOR}[ \t]+)*{_NAME_WORD}(?:[ \t]+(?:{_CONNECTOR}[ \t]+)*{_NAME_WORD}){{0,4}}"
)
_HOUSE_NUMBER = (
    r"(?:(?:n\.?[ \t]?[ºo°]\.?|n[úu]m\.)[ \t]*)?"
    r"(?:\d{1,4}(?:[ \t]?[A-Za-z](?![\w]))?(?:-\d{1,4})?|s/n)"
)
# Floor and door: "3.º B", "2º izda.", "4.º 2.ª", "bajo", "ático".
_ORDINAL = r"\d{1,2}\.?[ºª°]"
_FLOOR = (
    rf"(?:{_ORDINAL}|bajo|entlo\.|entresuelo|[áa]tico|pral\.)"
    rf"(?:[ \t]*(?:{_ORDINAL}|[A-H](?![\w])|izda\.|izq\.|dcha\.|der\.|izda|dcha))?"
)
# A postcode (provinces 01-52) before a place name: "28012 Madrid", "28801 Alcalá de Henares".
_PLACE = rf"[{_UPPER}][{_LOWER}]+(?:[- ](?:{_CONNECTOR}[ \t]+)*[{_UPPER}][{_LOWER}]+){{0,3}}"
_POSTCODE_PLACE = rf"(?P<code>(?:0[1-9]|[1-4]\d|5[0-2])\d{{3}})[ \t]+{_PLACE}"
_ADDRESS_RE = re.compile(
    rf"(?<![\w.])(?i:{_STREET_TYPE})[ \t]*{_STREET_NAME}(?:,[ \t]*|[ \t]+){_HOUSE_NUMBER}"
    r"(?![\w/])"
    rf"(?:(?:,[ \t]*|[ \t]+){_FLOOR})?"
    rf"(?:(?:,[ \t]*|[ \t]+|[ \t]*\n[ \t]*)(?:C\.P\.[ \t]*)?{_POSTCODE_PLACE}(?![\w-]))?"
)
# Spanish nouns are lower case, so a capitalised word after five digits is mostly a place;
# still, a bare postcode counts only where an address line starts: the start of a line,
# after a comma, or after "C.P.".
_POSTCODE_RE = re.compile(
    r"(?:(?<=^)|(?<=\n)|(?<=,)|(?<=, )|(?<=C\.P\.)|(?<=C\.P\. ))[ \t]*"
    rf"(?P<line>{_POSTCODE_PLACE})(?![\w-])",
    re.MULTILINE,
)
# Capitalised words after five digits that are not a place: amounts, counts (table rows).
_NOT_PLACES = frozenset(
    {"euros", "eur", "unidades", "personas", "habitantes", "empleados", "páginas", "km"}
)


def _find_address(text: str) -> Iterator[_Hit]:
    for m in _ADDRESS_RE.finditer(text):
        yield _Hit(m.start(), m.end(), EntityType.ADDRESS, 0.85 if m.group("code") else 0.75)


def _find_postcode(text: str) -> Iterator[_Hit]:
    for m in _POSTCODE_RE.finditer(text):
        if m.group("line").split()[1].casefold() in _NOT_PLACES:
            continue
        if legal_form_after(text, m.end("line")):
            continue  # "28012 Madrid GmbH": a company name, not an address line
        yield _Hit(m.start("line"), m.end("line"), EntityType.ADDRESS, 0.7)


EVERYWHERE: tuple[Rule, ...] = (_find_dni, _find_nie, _find_labelled_cif)
RULES: tuple[Rule, ...] = (_find_phone, _find_address, _find_postcode)
