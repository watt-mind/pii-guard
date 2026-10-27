"""Field captions on documents, and the values printed next to them.

ID cards, passports, licences and forms print each value next to a small caption:
``Családi név / Surname`` above ``FIKTÍV``, ``Date of birth`` above ``19 AUG 1995``,
``Telefon: +36 30 ...`` on one line. A text detector sees the value alone, out of context (a
surname on its own line, a foreign date format, a document number with no checksum), and
often misses it. The caption says what the value is, so this module finds captions in the
OCR words and pairs each with its value:

- **same line**: the words right of the caption, up to the next caption on that line;
- **below**: the nearest line under the caption within its column (from the caption's left
  edge to the next caption to its right), plus lines directly under that one (a value on two
  lines, a name in two scripts), up to the next caption.

Captions come from the language packs (``captions.tsv`` per language, see
:func:`load_captions`), plus a few EU languages that have no pack yet
(:data:`EXTRA_CAPTIONS`). Every caption of every language is searched for, since an image
does not say its language and ID documents are bilingual (``Name / Surname``). Matching
tolerates the OCR errors small caption print causes (``Date of bith``, ``Sumame``): the
caption and the words are compared without accents, case, spaces and punctuation, within an
edit distance that grows with the caption's length; a caption of five characters or fewer
must match exactly.

A caption whose value is not personal data (``Sex``, ``Nationality``, ``Expiry``) is still
recognised, with no entity type: it bounds the columns and stops a neighbouring caption from
claiming its value, but its value is never masked. This is not a layout rule that masks
every word on a card: a word is masked only as the value of a recognised personal-data
caption.

:func:`caption_values` returns the pairs (caption, entity type, value box, value words);
:func:`caption_value_regions` turns them into masking regions for
:func:`~pii_guard.visual.ocr.text_regions`. Neither logs or puts text into a ``repr``.
"""

from __future__ import annotations

import logging
import re
import statistics
import threading
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from importlib.resources.abc import Traversable
from typing import TYPE_CHECKING

from pii_guard.types import EntityType
from pii_guard.visual.regions import Box, Region

if TYPE_CHECKING:  # ocr.py imports this module
    from pii_guard.visual.ocr import OcrWord

__all__ = [
    "EXTRA_CAPTIONS",
    "SCORE",
    "SOURCE",
    "Caption",
    "CaptionLexicon",
    "CaptionValue",
    "caption_value_regions",
    "caption_values",
    "default_lexicon",
    "load_captions",
    "parse_captions",
]

logger = logging.getLogger(__name__)

#: ``Region.source`` of a caption-paired value (the API reports it as the region's detector).
SOURCE = "captions"
#: Score of a caption-paired value.
SCORE = 0.8

#: Two captions on one line further apart than this many line heights are separate columns
#: (``Nationality    Document no.``); closer ones are one bilingual caption (``Név Name``).
COLUMN_GAP = 1.2
#: With a separator between them (``Lakcím / Address``), two captions this many line heights
#: apart are still one caption.
SEPARATED_CAPTION_GAP = 4.0
#: A value line may start this many caption heights below the caption (or one value height,
#: whichever is larger).
MAX_VALUE_GAP = 2.5
#: A value word may start this many caption heights left of the caption.
LEFT_TOLERANCE = 1.5
#: A further line joins the value when it starts at most this many value heights below it.
CONTINUATION_GAP = 0.6
#: ... and its text height differs from the line above by at most this share (a heading or
#: footer printed under the value is a different size).
CONTINUATION_HEIGHT = 0.3
#: Lines a value may continue onto (an address, a name in two scripts).
MAX_CONTINUATION_LINES = 2
#: Words of one value line further apart than this many line heights are separate values.
VALUE_SPLIT_GAP = 1.5
#: A value box grows by this share of its height on every side (see :func:`_pad`).
VALUE_PADDING = 0.08
#: Captions of more than this many words are not looked for.
MAX_CAPTION_TOKENS = 6


#: EU driving licence field numbers (Directive 2006/126/EC, Annex I): the number printed
#: before each value is its caption, in every language.
LICENCE_FIELDS: dict[str, EntityType | None] = {
    "1": EntityType.PERSON,  # surname
    "2": EntityType.PERSON,  # given names
    "3": EntityType.DATE_OF_BIRTH,  # date and place of birth
    "4a": None,  # date of issue
    "4b": None,  # date of expiry
    "4c": None,  # issuing authority
    "4d": EntityType.ID_DOCUMENT,  # personal number (optional)
    "5": EntityType.ID_DOCUMENT,  # licence number
    "8": EntityType.ADDRESS,  # residence (optional)
    "9": None,  # categories
}
#: Field numbers are captions only on a page where this many different ones start a line.
MIN_NUMBERED_FIELDS = 3
#: What separates the languages of a bilingual caption, as printed or as OCR reads it.
_SEPARATORS = ("/", "|", "!", "\\")
_FIELD_NUMBER_RE = re.compile(r"^(\d[a-d]?)[.,]$")


# --- the lexicon ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Caption:
    """One field caption: its text, its language and the type of its value.

    ``entity_type`` is ``None`` for a caption whose value is not personal data (``Sex``,
    ``Expiry``): it is recognised so it can bound its neighbours, and never masked.
    """

    text: str
    entity_type: EntityType | None
    language: str

    @property
    def key(self) -> str:
        return "".join(_tokens(self.text))


#: Captions of EU languages without a language pack, as printed on their ID documents.
#: When a pack for one of them is added, its captions move into the pack's ``captions.tsv``.
EXTRA_CAPTIONS: tuple[Caption, ...] = tuple(
    Caption(text, EntityType(kind) if kind != "-" else None, language)
    for language, rows in {
        "fr": (
            ("Nom", "PERSON"),
            ("Nom d'usage", "PERSON"),
            ("Prénom", "PERSON"),
            ("Prénoms", "PERSON"),
            ("Date de naissance", "DATE_OF_BIRTH"),
            ("Lieu de naissance", "ADDRESS"),
            ("Adresse", "ADDRESS"),
            ("N° du document", "ID_DOCUMENT"),
            ("N° de la carte", "ID_DOCUMENT"),
            ("Sexe", "-"),
            ("Nationalité", "-"),
            ("Date d'expiration", "-"),
            ("Date de délivrance", "-"),
            ("Valable jusqu'au", "-"),
            ("Signature du titulaire", "-"),
        ),
        "it": (
            ("Cognome", "PERSON"),
            ("Nome", "PERSON"),
            ("Luogo e data di nascita", "DATE_OF_BIRTH"),
            ("Data di nascita", "DATE_OF_BIRTH"),
            ("Luogo di nascita", "ADDRESS"),
            ("Indirizzo di residenza", "ADDRESS"),
            ("Codice fiscale", "ID_DOCUMENT"),
            ("Cittadinanza", "-"),
            ("Sesso", "-"),
            ("Scadenza", "-"),
            ("Emissione", "-"),
        ),
        "es": (
            ("Apellidos", "PERSON"),
            ("Nombre", "PERSON"),
            ("Fecha de nacimiento", "DATE_OF_BIRTH"),
            ("Lugar de nacimiento", "ADDRESS"),
            ("Domicilio", "ADDRESS"),
            ("Num soporte", "ID_DOCUMENT"),
            ("DNI", "ID_DOCUMENT"),
            ("Sexo", "-"),
            ("Nacionalidad", "-"),
            ("Validez", "-"),
        ),
        "pl": (
            ("Nazwisko", "PERSON"),
            ("Imiona", "PERSON"),
            ("Nazwisko rodowe", "PERSON"),
            ("Data urodzenia", "DATE_OF_BIRTH"),
            ("Miejsce urodzenia", "ADDRESS"),
            ("Numer PESEL", "ID_DOCUMENT"),
            ("Numer dowodu osobistego", "ID_DOCUMENT"),
            ("Płeć", "-"),
            ("Obywatelstwo", "-"),
            ("Data ważności", "-"),
        ),
        "nl": (
            ("Naam", "PERSON"),
            ("Voornamen", "PERSON"),
            ("Geboortedatum", "DATE_OF_BIRTH"),
            ("Geboorteplaats", "ADDRESS"),
            ("Persoonsnummer", "ID_DOCUMENT"),
            ("Documentnummer", "ID_DOCUMENT"),
            ("Geslacht", "-"),
            ("Nationaliteit", "-"),
            ("Geldig tot", "-"),
            ("Datum van afgifte", "-"),
        ),
    }.items()
    for text, kind in rows
)


def parse_captions(text: str, language: str) -> tuple[Caption, ...]:
    """Parse a ``captions.tsv``: ``caption<TAB>ENTITY_TYPE`` (``-`` for a caption whose value
    is not personal data) per line; ``#`` starts a comment line. Raises ``ValueError`` on a
    malformed line or an unknown entity type.
    """
    captions: list[Caption] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in raw.split("\t")]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(f"line {number}: expected 'caption<TAB>ENTITY_TYPE'")
        caption, kind = parts
        if not _tokens(caption):
            raise ValueError(f"line {number}: caption has no letters or digits")
        if kind == "-":
            entity_type = None
        else:
            try:
                entity_type = EntityType(kind)
            except ValueError:
                raise ValueError(f"line {number}: unknown entity type {kind!r}") from None
        captions.append(Caption(caption, entity_type, language))
    return tuple(captions)


def load_captions(resource: Traversable, language: str) -> tuple[Caption, ...]:
    """Read a language pack's ``captions.tsv`` (see :func:`parse_captions`)."""
    return parse_captions(resource.read_text(encoding="utf-8"), language)


class CaptionLexicon:
    """A set of captions, indexed for fuzzy matching against OCR tokens."""

    def __init__(self, captions: Iterable[Caption]) -> None:
        by_key: dict[str, Caption] = {}
        for caption in captions:
            key = caption.key
            if not key or len(_tokens(caption.text)) > MAX_CAPTION_TOKENS:
                continue
            key = _confusable(key)
            current = by_key.get(key)
            # The same caption in two languages: a personal-data type wins over "not personal".
            if current is None or (current.entity_type is None and caption.entity_type):
                by_key[key] = caption
        self.captions: tuple[Caption, ...] = tuple(by_key.values())
        self._by_key = by_key
        self._exact = {k: c for k, c in by_key.items() if _tolerance(k) == 0}
        self._fuzzy = [
            (_confusable(k), c, tuple(_confusable(t) for t in _tokens(c.text)))
            for k, c in sorted(by_key.items(), key=lambda kc: -len(kc[0]))
            if _tolerance(k) > 0
        ]
        self._max_tokens = max((len(_tokens(c.text)) for c in self.captions), default=0)

    def __len__(self) -> int:
        return len(self.captions)

    def __repr__(self) -> str:
        return f"CaptionLexicon({len(self.captions)} captions)"

    def match(self, tokens: Sequence[str], start: int) -> tuple[Caption, int] | None:
        """The caption that best matches ``tokens[start:start + n]``, and ``n``; or ``None``.

        Prefers the match that covers more tokens, then the smaller edit distance. A fuzzy
        match compares token by token when the counts agree (no token may be replaced
        entirely: ``personal`` is not ``Personal no``), or the joined text when OCR merged
        or split one word (then the lengths may differ by one character at most).
        """
        best: tuple[int, int, Caption] | None = None  # (-n, distance, caption)
        limit = min(len(tokens) - start, self._max_tokens + 1)
        for n in range(1, limit + 1):
            window = [_confusable(t) for t in tokens[start : start + n]]
            joined = "".join(window)
            exact = self._exact.get(joined) or self._by_key.get(joined)
            if exact is not None:
                candidate = (-n, 0, exact)
                best = candidate if best is None or candidate[:2] < best[:2] else best
                continue
            for key, caption, parts in self._fuzzy:
                distance = _fuzzy_distance(key, parts, window, joined)
                if distance is not None:
                    candidate = (-n, distance, caption)
                    if best is None or candidate[:2] < best[:2]:
                        best = candidate
        if best is None:
            return None
        return best[2], -best[0]


def _fuzzy_distance(key: str, parts: tuple[str, ...], window: list[str], joined: str) -> int | None:
    """Edit distance between a caption and OCR tokens if within tolerance, else ``None``."""
    tolerance = _tolerance(key)
    if abs(len(key) - len(joined)) > tolerance:
        return None
    if len(window) == len(parts):
        total = 0
        for part, token in zip(parts, window, strict=True):
            distance = _distance(part, token, min(tolerance - total, len(part) - 1))
            if distance >= len(part) and part != token:
                return None
            total += distance
            if total > tolerance:
                return None
        return total
    if abs(len(window) - len(parts)) == 1 and abs(len(key) - len(joined)) <= 1:
        distance = _distance(key, joined, tolerance)
        return distance if distance <= tolerance else None
    return None


_lock = threading.Lock()
_default: CaptionLexicon | None = None


def default_lexicon() -> CaptionLexicon:
    """Every language pack's captions plus :data:`EXTRA_CAPTIONS` (cached; rebuilt when the
    set of language packs changes)."""
    global _default
    with _lock:
        if _default is None:
            from pii_guard.languages import packs

            captions: list[Caption] = []
            for code, pack in packs().items():
                if pack.captions is not None:
                    captions.extend(load_captions(pack.captions, code))
            have = {c.language for c in captions}
            captions.extend(c for c in EXTRA_CAPTIONS if c.language not in have)
            _default = CaptionLexicon(captions)
        return _default


def _clear_default() -> None:
    global _default
    with _lock:
        _default = None


def _register_listener() -> None:
    from pii_guard.languages import on_change

    on_change(_clear_default)


_register_listener()


# --- text normalisation ---------------------------------------------------------------------


def _tokens(text: str) -> list[str]:
    """Lower-case ASCII letter/digit runs: ``"Születési idő/Date"`` -> ``szuletesi ido date``."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    out: list[str] = []
    current: list[str] = []
    for char in decomposed:
        if unicodedata.combining(char):
            continue
        if char.isalnum():
            current.append(char)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


def _confusable(key: str) -> str:
    """Fold glyph pairs OCR confuses in small print (``rn`` read as ``m``)."""
    return key.replace("rn", "m")


def _tolerance(key: str) -> int:
    """Edits allowed for a caption key: none up to 5 characters, then one per 4."""
    n = len(key)
    return 0 if n <= 5 else (n - 2) // 4


def _distance(a: str, b: str, limit: int) -> int:
    """Levenshtein distance, stopping early once it exceeds ``limit``."""
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        row_min = i
        for j, cb in enumerate(b, start=1):
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            current.append(value)
            row_min = min(row_min, value)
        if row_min > limit:
            return limit + 1
        previous = current
    return previous[-1]


# --- layout ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CaptionValue:
    """A value printed next to a recognised caption.

    - ``caption``: the caption as written in the lexicon (``"Date of birth"``), never the OCR
      text; ``language`` its language.
    - ``entity_type``: the type the caption gives the value.
    - ``box``: the value's pixel box (one line); ``caption_box``: where the caption is.
    - ``words``: the value's OCR words; ``text`` joins them. ``repr()`` omits both.
    """

    caption: str
    language: str
    entity_type: EntityType
    box: Box
    caption_box: Box
    words: tuple[OcrWord, ...] = field(default=())

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)

    def __repr__(self) -> str:
        return (
            f"CaptionValue(caption={self.caption!r}, entity_type={self.entity_type.value}, "
            f"box={self.box!r}, words={len(self.words)}, text=<redacted>)"
        )


@dataclass(slots=True)
class _Line:
    words: list[OcrWord]
    box: Box

    @property
    def height(self) -> int:
        return self.box.height


@dataclass(slots=True)
class _Group:
    """One caption on the page: one or more matched captions read as one (bilingual) label."""

    captions: list[Caption]
    words: list[OcrWord]
    line: int
    box: Box
    column_end: int = 1 << 30

    @property
    def entity_type(self) -> EntityType | None:
        return next((c.entity_type for c in self.captions if c.entity_type), None)


def caption_values(
    words: Sequence[OcrWord], lexicon: CaptionLexicon | None = None
) -> list[CaptionValue]:
    """Pair every personal-data caption found in ``words`` with the value next to it."""
    lexicon = lexicon if lexicon is not None else default_lexicon()
    if not words:
        return []
    lines = _lines(words)
    groups: list[_Group] = []
    caption_word_ids: set[int] = set()
    numbered = _numbered_fields(lines)
    for index, line in enumerate(lines):
        line_groups = _line_groups(line, index, lexicon) if len(lexicon) else []
        taken = {id(w) for group in line_groups for w in group.words}
        for word in line.words:
            caption = numbered.get(id(word))
            if caption is not None and id(word) not in taken:
                line_groups.append(_Group([caption], [word], index, word.box))
        for group in line_groups:
            groups.append(group)
            caption_word_ids.update(id(word) for word in group.words)
    if not groups:
        return []
    _set_columns(groups)
    values: list[CaptionValue] = []
    for group in groups:
        entity_type = group.entity_type
        if entity_type is None:
            continue
        found = _same_line_value(group, lines[group.line], groups, caption_word_ids)
        if not found:
            found = _value_below(group, lines, groups, caption_word_ids)
        caption = next(c for c in group.captions if c.entity_type is entity_type)
        for value_words in found:
            box = _pad(_union(word.box for word in value_words))
            values.append(
                CaptionValue(
                    caption.text, caption.language, entity_type, box, group.box, tuple(value_words)
                )
            )
    return values


def caption_value_regions(
    words: Sequence[OcrWord], lexicon: CaptionLexicon | None = None
) -> list[Region]:
    """One region per value found by :func:`caption_values` (source ``"captions"``)."""
    return [
        Region(value.entity_type, value.box, SCORE, SOURCE)
        for value in caption_values(words, lexicon)
    ]


def _pad(box: Box) -> Box:
    """Grow an OCR box to the printed line: Tesseract boxes hug the glyphs, so their edges
    (accents, descenders, anti-aliasing) would show around a tight cover."""
    dy = round(VALUE_PADDING * box.height)
    return Box(max(0, box.x1 - dy), max(0, box.y1 - dy), box.x2 + dy, box.y2 + dy)


def _union(boxes: Iterable[Box]) -> Box:
    iterator = iter(boxes)
    box = next(iterator)
    for other in iterator:
        box = box.union(other)
    return box


def _lines(words: Sequence[OcrWord]) -> list[_Line]:
    by_key: dict[tuple[int, ...], list[OcrWord]] = {}
    for word in words:
        by_key.setdefault(word.line, []).append(word)
    lines = []
    for line_words in by_key.values():
        line_words = sorted(line_words, key=lambda w: w.box.x1)
        lines.append(_Line(line_words, _union(w.box for w in line_words)))
    return lines


def _numbered_fields(lines: list[_Line]) -> dict[int, Caption]:
    """Field numbers used as captions (``1.`` surname, ``3.`` date of birth on an EU driving
    licence), keyed by word id; only on a page where at least
    :data:`MIN_NUMBERED_FIELDS` different field numbers start a line."""
    starts = {
        match.group(1)
        for line in lines
        if (match := _FIELD_NUMBER_RE.match(line.words[0].text))
        and match.group(1) in LICENCE_FIELDS
    }
    if len(starts) < MIN_NUMBERED_FIELDS:
        return {}
    found: dict[int, Caption] = {}
    for line in lines:
        for word in line.words:
            match = _FIELD_NUMBER_RE.match(word.text)
            if match and match.group(1) in LICENCE_FIELDS:
                found[id(word)] = Caption(
                    match.group(1) + ".", LICENCE_FIELDS[match.group(1)], "und"
                )
    return found


def _line_groups(line: _Line, index: int, lexicon: CaptionLexicon) -> list[_Group]:
    # Tokens of the line, each tied to the word it came from ("Vorname/Surname" gives two).
    tokens: list[str] = []
    owner: list[int] = []
    for position, word in enumerate(line.words):
        for token in _tokens(word.text):
            tokens.append(token)
            owner.append(position)
    groups: list[_Group] = []
    i = 0
    while i < len(tokens):
        found = lexicon.match(tokens, i)
        if found is None:
            i += 1
            continue
        caption, n = found
        first, last = owner[i], owner[i + n - 1]
        anchor = line.words.index(groups[-1].words[-1]) if groups else -1
        mid_word = i > 0 and owner[i - 1] == first
        if not _starts_field(line, anchor, first, last, mid_word):
            i += 1
            continue
        caption_words = line.words[first : last + 1]
        box = _union(w.box for w in caption_words)
        previous = groups[-1] if groups else None
        if previous is not None and _same_caption(line, previous, caption_words, box):
            previous.captions.append(caption)
            previous.words.extend(w for w in caption_words if w not in previous.words)
            previous.box = previous.box.union(box)
        else:
            groups.append(_Group([caption], list(caption_words), index, box))
        # Continue after the last word used, so a word is never part of two captions.
        i += n
        while i < len(tokens) and owner[i] == last:
            i += 1
    return groups


def _starts_field(line: _Line, anchor: int, first: int, last: int, mid_word: bool) -> bool:
    """Whether a caption found in ``line.words[first:last + 1]`` labels a field, rather than
    being a word in running text (``My name is ...``): it starts the line (after punctuation
    or another caption), starts a column (a wide gap before it) or ends with a colon."""
    words = line.words
    if words[last].text.endswith(":") or (
        last + 1 < len(words) and words[last + 1].text.strip() == ":"
    ):
        return True
    # The second half of a bilingual caption whose first half is not in the lexicon
    # ("Utónév/Given names", "Tópos / Place of birth").
    if mid_word:
        return "/" in words[first].text
    if first > anchor + 1 and words[first - 1].text.rstrip().endswith(_SEPARATORS):
        return True
    before = [w for w in words[anchor + 1 : first] if _tokens(w.text)]
    if not before:
        return True
    return words[first].box.x1 - before[-1].box.x2 > COLUMN_GAP * line.height


def _same_caption(line: _Line, previous: _Group, caption_words: list[OcrWord], box: Box) -> bool:
    """Whether a caption continues the previous one on its line (the other language of a
    bilingual caption) rather than starting the next column."""
    if not _only_separators(line.words, previous.words[-1], caption_words[0]):
        return False
    gap = box.x1 - previous.box.x2
    between = line.words.index(caption_words[0]) - line.words.index(previous.words[-1]) - 1
    limit = SEPARATED_CAPTION_GAP if between else COLUMN_GAP
    return gap <= limit * line.height


def _only_separators(words: list[OcrWord], left: OcrWord, right: OcrWord) -> bool:
    """True when only punctuation lies between two caption words on a line."""
    try:
        start, end = words.index(left), words.index(right)
    except ValueError:
        return False
    return all(not _tokens(word.text) for word in words[start + 1 : end])


def _overlaps_vertically(a: Box, b: Box) -> bool:
    return a.y1 <= b.y2 and b.y1 <= a.y2


def _set_columns(groups: list[_Group]) -> None:
    """A caption's column ends where the next caption to its right on the same row starts."""
    for group in groups:
        for other in groups:
            if other is group or other.box.x1 <= group.box.x2:
                continue
            if _overlaps_vertically(group.box, other.box):
                group.column_end = min(group.column_end, other.box.x1)


def _text_height(words: list[OcrWord]) -> float:
    """The median word height: the size of the print, robust to one odd box."""
    return float(statistics.median(w.box.height for w in words))


def _split(words: list[OcrWord]) -> list[list[OcrWord]]:
    """Split one line's value words where they are far apart (two values side by side)."""
    parts: list[list[OcrWord]] = []
    for word in sorted(words, key=lambda w: w.box.x1):
        if parts:
            last = parts[-1][-1]
            gap = word.box.x1 - last.box.x2
            if gap <= VALUE_SPLIT_GAP * max(last.box.height, word.box.height):
                parts[-1].append(word)
                continue
        parts.append([word])
    return parts


def _same_line_value(
    group: _Group, line: _Line, groups: list[_Group], caption_ids: set[int]
) -> list[list[OcrWord]]:
    end = group.column_end
    words = [
        w
        for w in line.words
        if w.box.x1 > group.box.x2 and w.box.x1 < end and id(w) not in caption_ids
    ]
    words = [w for w in words if _tokens(w.text)]
    if not words:
        return []
    # Only the first run of words: a far-away word on the same line belongs to something else.
    first = _split(words)[0]
    if first[0].box.x1 - group.box.x2 > 2 * VALUE_SPLIT_GAP * line.height:
        return []
    return [first]


def _value_below(
    group: _Group, lines: list[_Line], groups: list[_Group], caption_ids: set[int]
) -> list[list[OcrWord]]:
    caption = group.box
    left = caption.x1 - LEFT_TOLERANCE * caption.height
    # The next caption down the column ends the value, even where OCR boxes overlap it.
    stop = min(
        (
            other.box.y1
            for other in groups
            if other is not group
            and other.box.y1 > caption.y1 + caption.height // 2
            and other.box.x1 < group.column_end
            and other.box.x2 >= left
        ),
        default=1 << 30,
    )
    candidates: list[tuple[int, _Line, list[OcrWord]]] = []
    for line in lines:
        if line.box.y1 <= caption.y1 + caption.height // 2:
            continue
        in_column = [
            w
            for w in line.words
            if left <= (w.box.x1 + w.box.x2) / 2 < group.column_end
            and (w.box.y1 + w.box.y2) / 2 < stop
        ]
        if not in_column:
            continue
        candidates.append((min(w.box.y1 for w in in_column), line, in_column))
    if not candidates:
        return []
    candidates.sort(key=lambda c: c[0])
    found: list[list[OcrWord]] = []
    previous: Box | None = None
    previous_height = 0.0
    for top, _line, in_column in candidates:
        if any(id(w) in caption_ids for w in in_column):
            break  # the next caption: this one's value is missing (or OCR lost it)
        words = [w for w in in_column if _tokens(w.text)]
        if not words:
            continue
        box = _union(w.box for w in words)
        if previous is None and top - caption.y2 > max(MAX_VALUE_GAP * caption.height, box.height):
            break  # the nearest line under the caption is too far away to be its value
        if previous is not None and _overlaps_vertically(box, previous):
            # Two OCR lines of one printed line (Tesseract splits lines at large gaps).
            found[-1] = sorted([*found[-1], *words], key=lambda w: w.box.x1)
            previous = previous.union(box)
            continue
        if previous is not None and (
            len(found) > MAX_CONTINUATION_LINES
            or top - previous.y2 > CONTINUATION_GAP * previous.height
            or abs(box.x1 - previous.x1) > 2 * previous.height
            or abs(_text_height(words) - previous_height) > CONTINUATION_HEIGHT * previous_height
        ):
            break
        found.append(words)
        previous = box
        previous_height = _text_height(words)
    if len(found) <= 1:
        return _split(found[0]) if found else []
    # A value on several lines (an address, a name in two scripts) is one block.
    return [[word for words in found for word in words]]
