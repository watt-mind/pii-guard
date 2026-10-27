"""Machine-readable zones (ICAO 9303) found by their layout in OCR words.

The MRZ on an ID card back (TD1: 3 lines of 30), a TD2 document (2 lines of 36) or a
passport data page (TD3: 2 lines of 44) repeats the holder's name, date of birth and
document and personal numbers. Tesseract reads the OCR-B zone badly enough (split words,
the ``<`` filler read as ``«``, ``K`` or ``c``, a wrong character per line) that the
text-level rule, which needs exact lines with valid check digits, rarely fires. This finder
needs neither: it looks for consecutive lines of about the right length made almost only of
MRZ characters, and returns **one** region per zone, the union of all its word boxes, so a
single box covers the whole zone.

The finder itself parses nothing, and a region never carries the text it covers.
:func:`mrz_zones` also returns each zone's lines as read, and :func:`parse_mrz` reads them
(ICAO 9303 TD1 / TD2 / TD3 field positions, check digits) for the document summary
(:mod:`pii_guard.visual.summary`); OCR errors usually leave ``valid`` false.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pii_guard.types import EntityType
from pii_guard.visual.regions import Box, Region

if TYPE_CHECKING:  # ocr.py imports this module
    from pii_guard.visual.ocr import OcrWord

__all__ = ["MrzData", "MrzZone", "check_digit", "mrz_regions", "mrz_zones", "parse_mrz"]

#: Line lengths of the ICAO formats: TD1, TD2 and TD3.
MRZ_LENGTHS: tuple[int, ...] = (30, 36, 44)
#: How far each line of a zone may be from its format's length (dropped or extra characters).
LENGTH_TOLERANCE = 5
#: An MRZ-like line has this many characters (words joined without spaces, junk trimmed).
MIN_LINE_LENGTH = min(MRZ_LENGTHS) - LENGTH_TOLERANCE
MAX_LINE_LENGTH = max(MRZ_LENGTHS) + LENGTH_TOLERANCE
#: How far the lines of one zone may differ in length from each other.
LINE_SPREAD = 5
#: Share of a line's characters that must be MRZ characters or OCR renderings of the filler.
MIN_MRZ_CHAR_RATIO = 0.85
#: Filler characters a line needs to anchor a zone (one is enough after a document code).
MIN_FILLERS = 3
#: A line with fewer fillers (TD1 line 2, TD3 line 2 with optional data) joins a zone next to
#: an anchoring line if it has a filler or this share of digits; it never starts a zone alone.
MIN_DIGIT_RATIO = 0.5
#: A zone of one line (OCR lost the others) needs this many fillers.
MIN_FILLERS_SINGLE_LINE = 5
#: Largest vertical gap between two lines of one zone, in line heights.
MAX_LINE_GAP = 2.0
#: Most lines in a zone (TD1).
MAX_LINES = 3
#: Score of a layout-found zone.
SCORE = 0.9
#: ``Region.source``: the rules detector's name, so the API and UI contract is unchanged.
SOURCE = "rules"

#: The ``<`` filler as OCR reads it, and characters it commonly turns the filler into.
_FILLERS = frozenset("<«\u2039")
_FILLER_LOOKALIKES = frozenset("(cekx£€¢")
_MRZ_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") | _FILLERS | _FILLER_LOOKALIKES
#: Document codes the first MRZ line starts with (passport, ID card, other documents).
_DOC_CODE_RE = re.compile(r"^(?:[PIAC][<«\u2039A-Z]|ID)")


@dataclass(frozen=True, slots=True)
class _Line:
    box: Box
    length: int
    fillers: int
    anchor: bool
    text: str = ""


@dataclass(frozen=True, slots=True)
class MrzZone:
    """One machine-readable zone: its ``ID_DOCUMENT`` region and its lines as OCR read them
    (words joined without spaces, junk trimmed). ``repr()`` omits the lines."""

    region: Region
    lines: tuple[str, ...]

    def __repr__(self) -> str:
        return f"MrzZone(region={self.region!r}, lines={len(self.lines)}, text=<redacted>)"


def mrz_regions(words: Sequence[OcrWord]) -> list[Region]:
    """One ``ID_DOCUMENT`` region per machine-readable zone found in ``words``."""
    return [zone.region for zone in mrz_zones(words)]


def mrz_zones(words: Sequence[OcrWord]) -> list[MrzZone]:
    """Every machine-readable zone found in ``words``, with its lines."""
    lines = sorted(_mrz_lines(words), key=lambda line: (line.box.y1, line.box.x1))
    zones: list[MrzZone] = []
    block: list[_Line] = []
    for line in lines:
        if block and not _continues(block, line):
            zones.extend(_close(block))
            block = []
        block.append(line)
    if block:
        zones.extend(_close(block))
    return zones


def _mrz_lines(words: Sequence[OcrWord]) -> list[_Line]:
    by_line: dict[tuple[int, ...], list[OcrWord]] = {}
    for word in words:
        by_line.setdefault(word.line, []).append(word)
    lines: list[_Line] = []
    for line_words in by_line.values():
        line = _mrz_line(line_words)
        if line is not None:
            lines.append(line)
    return lines


def _mrz_line(words: list[OcrWord]) -> _Line | None:
    # Drop junk words at the ends (a border or a stray mark read as "~—" or "|").
    while words and _ratio(words[0].text) < 0.5:
        words = words[1:]
    while words and _ratio(words[-1].text) < 0.5:
        words = words[:-1]
    if not words:
        return None
    compact = _trim("".join(word.text for word in words))
    if not MIN_LINE_LENGTH <= len(compact) <= MAX_LINE_LENGTH:
        return None
    if _ratio(compact) < MIN_MRZ_CHAR_RATIO:
        return None
    fillers = sum(char in _FILLERS for char in compact)
    # A heading in capitals ("IDENTITY CARD", "PERSONALAUSWEIS") has a document code too,
    # but no filler: a first MRZ line always has some.
    anchor = fillers >= MIN_FILLERS or (fillers > 0 and _DOC_CODE_RE.match(compact) is not None)
    digits = sum(char.isdigit() for char in compact) / len(compact)
    if not anchor and not fillers and digits < MIN_DIGIT_RATIO:
        return None
    box = words[0].box
    for word in words[1:]:
        box = box.union(word.box)
    return _Line(box, len(compact), fillers, anchor, compact)


def _ratio(text: str) -> float:
    return sum(char in _MRZ_CHARS for char in text) / len(text) if text else 0.0


def _trim(text: str) -> str:
    start, end = 0, len(text)
    while start < end and text[start] not in _MRZ_CHARS:
        start += 1
    while end > start and text[end - 1] not in _MRZ_CHARS:
        end -= 1
    return text[start:end]


def _continues(block: list[_Line], line: _Line) -> bool:
    """Whether ``line`` is the next line of the zone in ``block``."""
    if len(block) >= MAX_LINES:
        return False
    last = block[-1]
    gap = line.box.y1 - last.box.y2
    if gap > MAX_LINE_GAP * max(last.box.height, line.box.height):
        return False
    if line.box.x1 > last.box.x2 or last.box.x1 > line.box.x2:
        return False  # side by side, not stacked
    lengths = [*(member.length for member in block), line.length]
    return max(lengths) - min(lengths) <= LINE_SPREAD


def _format_fits(lengths: Sequence[int]) -> bool:
    return any(all(abs(n - size) <= LENGTH_TOLERANCE for n in lengths) for size in MRZ_LENGTHS)


def _close(block: list[_Line]) -> list[MrzZone]:
    if not any(line.anchor for line in block):
        return []
    if len(block) >= 2 and _format_fits([line.length for line in block]):
        members = block
    else:
        # Not a zone of several lines: each line can still be a zone whose other lines OCR lost.
        return [
            _close_single(line)
            for line in block
            if line.fillers >= MIN_FILLERS_SINGLE_LINE and _format_fits([line.length])
        ]
    box = members[0].box
    for line in members[1:]:
        box = box.union(line.box)
    region = Region(EntityType.ID_DOCUMENT, box, SCORE, SOURCE)
    return [MrzZone(region, tuple(line.text for line in members))]


def _close_single(line: _Line) -> MrzZone:
    return MrzZone(Region(EntityType.ID_DOCUMENT, line.box, SCORE, SOURCE), (line.text,))


# --- reading a zone ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MrzData:
    """The fields of a machine-readable zone. ``repr()`` shows the format and validity only.

    Dates are ``YYMMDD`` as printed. ``valid`` is true when the line lengths are exact and
    the document-number, birth-date and expiry check digits all match.
    """

    format: str
    document_code: str
    issuing_state: str
    document_number: str
    nationality: str
    birth: str
    expiry: str
    surname: str
    given: str
    valid: bool

    @property
    def name(self) -> str:
        """``SURNAME GIVEN`` with fillers as spaces (the MRZ's own order)."""
        return " ".join(part for part in (self.surname, self.given) if part)

    def __repr__(self) -> str:
        return f"MrzData(format={self.format!r}, valid={self.valid}, fields=<redacted>)"


_WEIGHTS = (7, 3, 1)
_LOOKALIKE_FILLERS = frozenset("«\u2039(£€¢") | frozenset("cekx")


def _value(char: str) -> int:
    if char.isdigit():
        return int(char)
    if "A" <= char <= "Z":
        return ord(char) - 55
    return 0  # the filler


def check_digit(field_: str) -> str:
    """The ICAO 9303 check digit of ``field_`` (weights 7, 3, 1; ``<`` counts 0)."""
    return str(sum(_value(c) * _WEIGHTS[i % 3] for i, c in enumerate(field_)) % 10)


def _clean(line: str) -> str:
    return "".join("<" if c in _LOOKALIKE_FILLERS else c for c in line if not c.isspace())


def _name(field_: str) -> tuple[str, str]:
    surname, _, given = field_.strip("<").partition("<<")
    return surname.replace("<", " ").strip(), given.replace("<", " ").strip()


def _checked(field_: str, digit: str) -> bool:
    return len(digit) == 1 and digit.isdigit() and check_digit(field_) == digit


def parse_mrz(lines: Sequence[str]) -> MrzData | None:
    """Read a zone's lines (TD1: 3 x 30, TD2: 2 x 36, TD3: 2 x 44); ``None`` if no format fits.

    Lines a character or two short or long (OCR) are padded or cut to the format's length;
    the zone is then read but not ``valid``.
    """
    clean = [_clean(line) for line in lines if line.strip()]
    if len(clean) == 3:
        size, fmt = 30, "TD1"
    elif len(clean) == 2:
        size = min((36, 44), key=lambda n: abs(n - len(clean[0])))
        fmt = "TD2" if size == 36 else "TD3"
    else:
        return None
    exact = all(len(line) == size for line in clean)
    fixed = [line[:size].ljust(size, "<") for line in clean]
    if fmt == "TD1":
        l1, l2, l3 = fixed
        number, number_check = l1[5:14], l1[14]
        birth, birth_check = l2[0:6], l2[6]
        expiry, expiry_check = l2[8:14], l2[14]
        code, state, nationality = l1[0:2], l1[2:5], l2[15:18]
        surname, given = _name(l3)
    else:
        l1, l2 = fixed
        number, number_check = l2[0:9], l2[9]
        nationality = l2[10:13]
        birth, birth_check = l2[13:19], l2[19]
        expiry, expiry_check = l2[21:27], l2[27]
        code, state = l1[0:2], l1[2:5]
        surname, given = _name(l1[5:])
    valid = (
        exact
        and _checked(number, number_check)
        and _checked(birth, birth_check)
        and _checked(expiry, expiry_check)
    )
    return MrzData(
        fmt,
        code.strip("<"),
        state.strip("<"),
        number.strip("<"),
        nationality.strip("<"),
        birth,
        expiry,
        surname,
        given,
        valid,
    )
