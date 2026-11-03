"""French language pack: rules for French identifiers and formats (LAB-1774).

French IBANs (``FR`` + 25 characters) and ``+33`` phone numbers need nothing here: the
language-independent rules (:mod:`pii_guard.detect.rules.common`) already find them.

Run for every language (``EVERYWHERE``), because the value validates and its format or label
says what it is:

- the NIR (numéro de sécurité sociale) **next to its label** (``sécurité sociale``, ``NIR``,
  ``INSEE``, ``carte Vitale`` ...), with any field code the INSEE allows;
- an **unlabelled** NIR, compact or grouped as the card prints it (``1 85 05 78 006 084 36``),
  when its sex digit is 1 or 2, its month a calendar month and its key valid: about one random
  15-digit run in 4 000 passes, and the hu/en/de/pl scorecards don't move;
- the numéro fiscal (SPI) **next to its label** (``numéro fiscal``, ``SPI``): a bare 13-digit
  number is too common (EAN-13 barcodes, references), and one in 511 passes the check.

Run only for French text (``RULES``), because the format alone is ambiguous elsewhere:

- national phone numbers ``06 39 98 12 34`` (also with dots or hyphens, or compact);
- addresses: ``12 rue des Lilas``, optionally followed by ``, 69003 Lyon``, and a postcode
  where an address line starts (``75008 Paris``, ``13100 Aix-en-Provence Cedex 1``).

Both identifiers are ``ID_DOCUMENT`` (the taxonomy has no French type, as for German and
Polish identifiers). A NIR or numéro fiscal with a bad key is found by the cues
(``cues.tsv``), and so are passport, CNI and driving-licence numbers, which print no check
digit.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from pii_guard.detect.rules._base import (
    NO_GROUP_AFTER,
    NO_GROUP_BEFORE,
    NOT_IN_WORD_AFTER,
    VALIDATED_ID_DOCUMENT,
    Rule,
    _Hit,
    legal_form_after,
    reference_or_amount_before,
)
from pii_guard.languages.cues import CUED_SCORE
from pii_guard.languages.fr.checksums import is_valid_nir, is_valid_spi, nir_month_is_calendar
from pii_guard.types import EntityType

__all__ = ["EVERYWHERE", "RULES"]

# An apostrophe, straight or typographic.
_APOS = "['\u2019]"
_UPPER = "A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸŒÆ"
_LOWER = "a-zàâäçéèêëîïôöùûüÿœæ"
# A French amount: a currency word or sign right after the number.
_NOT_AMOUNT_FR = r"(?!\s?(?:€|EUR|euros?)(?!\w))"

# Labels, as whole words in the 40 characters before the value ("nir" is also inside
# "fournir", "avenir").
_NIR_LABEL_RE = re.compile(
    r"(?i:(?<!\w)(?:nir|insee|n°[ \t]?ss|num[ée]ro[ \t]ss|s[ée]curit[ée][ \t]sociale|s[ée]cu"
    r"|carte[ \t]vitale|social[ \t]security)(?!\w))"
)
_SPI_LABEL_RE = re.compile(r"(?i:(?<!\w)(?:fiscal\w*|spi)(?!\w))")


def _labelled(text: str, start: int, label: re.Pattern[str]) -> bool:
    return label.search(text, max(0, start - 40), start) is not None


# "Facture n° 123", "Commande no 123", "Réf. : 123": the shared check knows the label words
# (references.tsv) but not the French "n°" between them and the number (LAB-1785).
_REFERENCE_N_RE = re.compile(
    r"(?i:(?<!\w)(?:factur\w*|command\w*|r[ée]f[ée]rence\w*|r[ée]f\.?|dossier\w*|contrat\w*"
    r"|colis|suivi|devis|ticket\w*|re[çc]u|lot|article\w*)"
    r"[ \t]*(?:n[°º]|no\b|num\.?)?[ \t:#]*)$"
)


def _reference_before(text: str, start: int) -> bool:
    if reference_or_amount_before(text, start):
        return True
    return _REFERENCE_N_RE.search(text, max(0, start - 40), start) is not None


def _compact(value: str) -> str:
    return re.sub(r"[ .\-]", "", value)


def _id_hit(m: re.Match[str], score: float) -> _Hit:
    return _Hit(
        m.start("value"), m.end("value"), EntityType.ID_DOCUMENT, score, VALIDATED_ID_DOCUMENT
    )


# --- NIR ---------------------------------------------------------------------------------

# Compact (15, or 13 and the key after a space) or grouped 1-2-2-2-3-3-2, the layout of the
# carte Vitale. The department may be 2A/2B (Corsica).
_DEPT = r"(?:\d{2}|2[AB])"
_NIR_RE = re.compile(
    r"(?<![\w+-])" + NO_GROUP_BEFORE + r"(?P<value>"
    rf"[1-478]\d{{4}}{_DEPT}\d{{6}} ?\d{{2}}"
    rf"|[1-478] \d{{2}} \d{{2}} {_DEPT} \d{{3}} \d{{3}} \d{{2}}"
    r")(?![\w-])(?![.,]\d)" + NO_GROUP_AFTER + _NOT_AMOUNT_FR
)


def _find_nir(text: str) -> Iterator[_Hit]:
    for m in _NIR_RE.finditer(text):
        value = _compact(m.group("value"))
        if not is_valid_nir(value):
            continue
        if _labelled(text, m.start("value"), _NIR_LABEL_RE):
            yield _id_hit(m, 0.97)
        elif nir_month_is_calendar(value) and not _reference_before(text, m.start("value")):
            yield _id_hit(m, 0.9)


# --- Numéro fiscal (SPI) -----------------------------------------------------------------

# Compact, or grouped 2-2-3-3-3 as the tax notice prints it.
_SPI_RE = re.compile(
    r"(?<![\w+-])" + NO_GROUP_BEFORE + r"(?P<value>[0-3]\d{12}|[0-3]\d \d{2} \d{3} \d{3} \d{3})"
    r"(?![\w-])(?![.,]\d)" + NO_GROUP_AFTER + _NOT_AMOUNT_FR
)


def _find_labelled_spi(text: str) -> Iterator[_Hit]:
    for m in _SPI_RE.finditer(text):
        value = _compact(m.group("value"))
        if is_valid_spi(value) and _labelled(text, m.start("value"), _SPI_LABEL_RE):
            yield _id_hit(m, 0.97)


# --- Documents after "n°" --------------------------------------------------------------

# Passport, CNI, driving-licence and residence-permit numbers print no check digit, so the
# cues (cues.tsv) find them after their label. But French writes "passeport n° 19FA45821",
# and the shared cue window stops at "°" (LAB-1785; a cue may not hold it): this rule covers
# that form, at the cue score and with the cue's shape (6-20 letters and digits, at least two
# digits). It runs everywhere, like the cues.
_DOCUMENT_N_RE = re.compile(
    rf"(?i:(?<!\w)(?:passeport|carte[ \t]+(?:nationale[ \t]+)?d{_APOS}[ \t]?identit[ée]|cni"
    r"|permis(?:[ \t]+de[ \t]+conduire)?|titre[ \t]+de[ \t]+s[ée]jour"
    r"|s[ée]curit[ée][ \t]+sociale|num[ée]ro[ \t]+fiscal)"
    r"[ \t]*(?:n[°º]|no\.?)[ \t]*:?[ \t]*)"
    r"(?P<value>(?=(?:[A-Z]*\d){2})[A-Z0-9]{2,}(?:[ .-]?[A-Z0-9]+)*)(?![\w.,/-]?\w)"
)


def _find_document_after_n(text: str) -> Iterator[_Hit]:
    for m in _DOCUMENT_N_RE.finditer(text):
        compact = _compact(m.group("value"))
        if 6 <= len(compact) <= 20:
            yield _Hit(m.start("value"), m.end("value"), EntityType.ID_DOCUMENT, CUED_SCORE)


# --- Phone numbers -----------------------------------------------------------------------

# The trunk 0, a digit 1-9 and four pairs, with one kind of separator (space, dot, hyphen)
# or none. "+33 6 ..." is the language-independent rule's.
_PHONE_RE = re.compile(
    r"(?<![\w+(./-])(?<!\d )"
    r"0[1-9](?:(?P<sep>[ .-])\d{2}(?:(?P=sep)\d{2}){3}|\d{8})"
    r"(?!\d)(?![-./ ]\d)" + _NOT_AMOUNT_FR + NOT_IN_WORD_AFTER
)


def _find_phone(text: str) -> Iterator[_Hit]:
    for m in _PHONE_RE.finditer(text):
        if not _reference_before(text, m.start()):
            yield _Hit(m.start(), m.end(), EntityType.PHONE, 0.8)


# --- Addresses ---------------------------------------------------------------------------

_STREET_TYPE = (
    r"(?:rue|avenue|av\.|bd|boulevard|place|all[ée]e|chemin|impasse|quai|cours|route"
    r"|square|passage|faubourg|cit[ée]|r[ée]sidence|lotissement|hameau|esplanade|promenade"
    r"|sentier|villa|parvis|rond-point|chauss[ée]e)"
)
# Words of a street name: capitalised words joined by articles ("des Lilas", "de la
# République", "du Général de Gaulle", "d'Alsace") and the numbers of a date ("du 8 Mai 1945").
_CONNECTOR = rf"(?:de|du|des|la|le|les|aux|au|et|sur|sous|en|à|d{_APOS}|l{_APOS})"
# An abbreviation ("Gén.", "St.") keeps its dot only before the next word, so a sentence
# end stays outside the address.
_NAME_WORD = (
    rf"(?:[{_UPPER}][{_LOWER}]{{0,3}}\.(?=[ \t])|[{_UPPER}][{_LOWER}]*(?:-[{_UPPER}][{_LOWER}]+)*"
    r"|\d{1,4}|[IVX]{1,4})"
)
_NAME_PART = rf"(?:{_CONNECTOR}(?:[ \t]+|(?<={_APOS})))*{_NAME_WORD}"
_STREET_NAME = rf"{_NAME_PART}(?:[ \t]+{_NAME_PART}){{0,4}}"
_HOUSE_NUMBER = r"\d{1,4}(?:[ \t]?(?:bis|ter|quater|[A-D])(?!\w))?"
_CITY_WORD = rf"[{_UPPER}][{_LOWER}]+"
_CITY = (
    rf"(?:(?:Le|La|Les)[ \t]+)?{_CITY_WORD}"
    rf"(?:-(?:(?:sur|sous|en|lès|les|le|la|de|du|des|aux|au)-|[dl]{_APOS})?{_CITY_WORD}){{0,4}}"
    r"(?:[ \t]+(?i:cedex)(?:[ \t]+\d{1,2})?)?"
)
_POSTCODE = r"(?:0[1-9]|[1-8]\d|9[0-578])\d{3}"
_POSTCODE_CITY = rf"(?P<code>{_POSTCODE})[ \t]+{_CITY}"
_ADDRESS_RE = re.compile(
    rf"(?<![\w,.])(?<!\d )(?<!\d\.){_HOUSE_NUMBER},?[ \t]+(?i:{_STREET_TYPE})(?![\w-])"
    rf"[ \t]+{_STREET_NAME}(?![\w-])"
    rf"(?:(?:,[ \t]*|[ \t]+|[ \t]*\n[ \t]*){_POSTCODE_CITY}(?![\w-]))?"
)
# French nouns are lower case, but a sentence or a heading may start with a count ("20000
# Participants"): a bare postcode counts only where an address line starts (start of a line,
# or after a comma), as in German.
_POSTCODE_RE = re.compile(
    rf"(?:(?<=^)|(?<=\n)|(?<=,)|(?<=, ))[ \t]*(?P<line>{_POSTCODE_CITY})(?![\w-])",
    re.MULTILINE,
)
# Capitalised words after five digits that are not a place: amounts, counts.
_NOT_PLACES = frozenset(
    {
        "euros",
        "eur",
        "habitants",
        "personnes",
        "participants",
        "salariés",
        "exemplaires",
        "pages",
        "visiteurs",
        "clients",
        "utilisateurs",
    }
)
# French company forms after a place: "69003 Lyon SARL" is a company name.
_FR_LEGAL_FORM_RE = re.compile(r"[ \t]+(?:SA|SAS|SASU|SARL|EURL|SCI|SNC|SCP|SELARL)(?!\w)")


def _find_address(text: str) -> Iterator[_Hit]:
    for m in _ADDRESS_RE.finditer(text):
        yield _Hit(m.start(), m.end(), EntityType.ADDRESS, 0.85 if m.group("code") else 0.75)


def _find_postcode(text: str) -> Iterator[_Hit]:
    for m in _POSTCODE_RE.finditer(text):
        if m.group("line").split()[1].casefold() in _NOT_PLACES:
            continue
        end = m.end("line")
        if legal_form_after(text, end) or _FR_LEGAL_FORM_RE.match(text, end):
            continue  # a company name, not an address line
        yield _Hit(m.start("line"), m.end("line"), EntityType.ADDRESS, 0.7)


EVERYWHERE: tuple[Rule, ...] = (_find_nir, _find_labelled_spi, _find_document_after_n)
RULES: tuple[Rule, ...] = (_find_phone, _find_address, _find_postcode)
