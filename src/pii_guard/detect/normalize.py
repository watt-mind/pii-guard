"""Normalise obfuscated text before detection, with an offset map back to the original.

Personal data can be hidden from a detector without hiding it from a reader: zero-width and
other invisible characters inside a name (``Te\\u200bszt``), Cyrillic or Greek lookalike
letters mixed into a Latin word (``T\\u0435szt``), or fullwidth / mathematical letters. A
downstream LLM reads all of these as the plain value, so detection must too.

:func:`normalize_for_detection` returns a :class:`NormalizedText`: the cleaned text and, for
every character of it, the original span it stands for. Characters are only **dropped**,
**replaced one for one** or **composed** with the combining marks after them, never inserted,
so a span over the cleaned text maps back to the smallest original span covering the same
characters, including any invisible characters or marks inside it
(:meth:`NormalizedText.to_original`). Masking that original span removes the value whole.

The rules:

- **Invisible characters** are dropped: zero-width space / non-joiner / joiner, word joiner,
  BOM, soft hyphen, combining grapheme joiner, Mongolian vowel separator, invisible math
  operators and the bidirectional controls (embeddings, overrides, isolates).
- **Zero-width separators** (zero-width space, word joiner, a BOM inside the text) are read
  as a space where they stand for one: between a lower-case letter and an upper-case one
  (``Teszt\\u200bElek`` reads ``Teszt Elek``). Anywhere else they are dropped like the other
  invisible characters, so one inside a word (``Te\\u200bszt``) still reads ``Teszt``. A
  separator between two words of the same case (``teszt\\u200belek``) cannot be told from one
  inside a word and is dropped; the vault searches both readings
  (:func:`~pii_guard.vault.fold.fold_views`). The non-joiner and joiner are never read as a
  space: they shape text in Arabic, Persian and Indic scripts.
- **Combining marks** are composed (NFC) with the character before them, so a decomposed
  ``e\\u0301`` reads as ``\\u00e9`` and the composed character's span ends after its marks. Marks
  NFC cannot compose onto an ASCII letter or digit (``5\\u0333``, keycap ``8\\u20e3``) are
  dropped the same way; marks on other scripts' letters are kept as they are.
- **Separators** that read like ASCII ones are folded one for one: every Unicode space (no-break,
  narrow no-break, thin, figure, ideographic ...) to a space, the hyphens and dashes U+2010-2015,
  the minus sign and the small hyphen-minus to ``-``, and the ideographic, halfwidth and one-dot
  leader full stops to ``.``. Word and Office text puts no-break spaces and en dashes inside
  numbers routinely.
- **Digits** of every script (Arabic-Indic, Devanagari ...) are folded to ASCII digits.
- **A number wrapped over a line break** (``+36 30 123`` / ``4567``) has the break read as a
  space when the next line holds nothing but the rest of the number and the line before is
  not a bare number (a list or a column of numbers stays apart). A CR LF counts as one break.
- **Lookalikes** are folded to Latin inside a word that also contains Latin letters, and in a
  word of nothing but lookalike letters with digits in it or joined to digits by a hyphen (the
  shape of a plate, document number or IBAN), so genuine Cyrillic or Greek text is left alone.
- **Fullwidth and mathematical alphanumerics** (``\\uff21``, ``\\U0001d400``) are folded with NFKC
  when that gives a single character.
- **Spoofed placeholders**: a value wrapped to look like a pii-guard placeholder
  (``[[PERSON_Teszt Elek]]``) has the wrapper blanked to spaces, so the model sees the value
  and not a placeholder it was told to skip. Real placeholders (``[[PERSON_3fa2c1]]``: an
  upper-case type and a lower-case hex id) are left alone.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = [
    "DASHES",
    "DOTS",
    "INVISIBLE_CHARS",
    "LOOKALIKES",
    "ZERO_WIDTH_SEPARATORS",
    "NormalizedText",
    "normalize_for_detection",
]

#: Characters with no visible glyph that can be put inside a value to break matching.
INVISIBLE_CHARS: frozenset[str] = frozenset(
    "­"  # soft hyphen
    "͏"  # combining grapheme joiner
    "᠎"  # Mongolian vowel separator
    "​‌‍"  # zero-width space, non-joiner, joiner
    "‎‏"  # left-to-right / right-to-left mark
    "‪‫‬‭‮"  # bidi embeddings and overrides
    "⁠⁡⁢⁣⁤"  # word joiner, invisible operators
    "⁦⁧⁨⁩"  # bidi isolates
    "﻿"  # zero-width no-break space (BOM)
)

#: Invisible characters that can stand for a space between two words: zero-width space, word
#: joiner and zero-width no-break space (BOM). Not the non-joiner or joiner, which shape text.
ZERO_WIDTH_SEPARATORS: frozenset[str] = frozenset("\u200b\u2060\ufeff")

#: Cyrillic and Greek letters that look like a Latin letter, mapped to it.
LOOKALIKES: dict[str, str] = {
    # Cyrillic lower case
    "\u0430": "a",  # CYRILLIC SMALL LETTER A
    "\u0441": "c",  # CYRILLIC SMALL LETTER ES
    "\u0435": "e",  # CYRILLIC SMALL LETTER IE
    "\u04bb": "h",  # CYRILLIC SMALL LETTER SHHA
    "\u0456": "i",  # CYRILLIC SMALL LETTER BYELORUSSIAN-UKRAINIAN I
    "\u0458": "j",  # CYRILLIC SMALL LETTER JE
    "\u043e": "o",  # CYRILLIC SMALL LETTER O
    "\u0440": "p",  # CYRILLIC SMALL LETTER ER
    "\u0455": "s",  # CYRILLIC SMALL LETTER DZE
    "\u0445": "x",  # CYRILLIC SMALL LETTER HA
    "\u0443": "y",  # CYRILLIC SMALL LETTER U
    "\u0501": "d",  # CYRILLIC SMALL LETTER KOMI DE
    # Cyrillic upper case
    "\u0410": "A",  # CYRILLIC CAPITAL LETTER A
    "\u0412": "B",  # CYRILLIC CAPITAL LETTER VE
    "\u0421": "C",  # CYRILLIC CAPITAL LETTER ES
    "\u0415": "E",  # CYRILLIC CAPITAL LETTER IE
    "\u041d": "H",  # CYRILLIC CAPITAL LETTER EN
    "\u0406": "I",  # CYRILLIC CAPITAL LETTER BYELORUSSIAN-UKRAINIAN I
    "\u0408": "J",  # CYRILLIC CAPITAL LETTER JE
    "\u041a": "K",  # CYRILLIC CAPITAL LETTER KA
    "\u041c": "M",  # CYRILLIC CAPITAL LETTER EM
    "\u041e": "O",  # CYRILLIC CAPITAL LETTER O
    "\u0420": "P",  # CYRILLIC CAPITAL LETTER ER
    "\u0405": "S",  # CYRILLIC CAPITAL LETTER DZE
    "\u0422": "T",  # CYRILLIC CAPITAL LETTER TE
    "\u0425": "X",  # CYRILLIC CAPITAL LETTER HA
    "\u0423": "Y",  # CYRILLIC CAPITAL LETTER U
    # Greek
    "\u0391": "A",  # GREEK CAPITAL LETTER ALPHA
    "\u0392": "B",  # GREEK CAPITAL LETTER BETA
    "\u0395": "E",  # GREEK CAPITAL LETTER EPSILON
    "\u0396": "Z",  # GREEK CAPITAL LETTER ZETA
    "\u0397": "H",  # GREEK CAPITAL LETTER ETA
    "\u0399": "I",  # GREEK CAPITAL LETTER IOTA
    "\u039a": "K",  # GREEK CAPITAL LETTER KAPPA
    "\u039c": "M",  # GREEK CAPITAL LETTER MU
    "\u039d": "N",  # GREEK CAPITAL LETTER NU
    "\u039f": "O",  # GREEK CAPITAL LETTER OMICRON
    "\u03a1": "P",  # GREEK CAPITAL LETTER RHO
    "\u03a4": "T",  # GREEK CAPITAL LETTER TAU
    "\u03a5": "Y",  # GREEK CAPITAL LETTER UPSILON
    "\u03a7": "X",  # GREEK CAPITAL LETTER CHI
    "\u03bf": "o",  # GREEK SMALL LETTER OMICRON
    "\u03b1": "a",  # GREEK SMALL LETTER ALPHA
    "\u03b9": "i",  # GREEK SMALL LETTER IOTA
    "\u03ba": "k",  # GREEK SMALL LETTER KAPPA
    "\u03bd": "v",  # GREEK SMALL LETTER NU
    "\u03c1": "p",  # GREEK SMALL LETTER RHO
    "\u03c5": "u",  # GREEK SMALL LETTER UPSILON
}

#: Dashes that read as a hyphen inside a number (U+2010-2015, minus sign, small hyphen-minus).
DASHES: frozenset[str] = frozenset("\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe63")
#: Dots that read as a full stop inside an e-mail address (ideographic, halfwidth, leader).
DOTS: frozenset[str] = frozenset("\u3002\uff61\u2024")
#: Line breaks that may wrap a number in the middle (CR LF counts as one).
_LINE_BREAKS = "\n\r\x0b\x0c\x85\u2028\u2029"

_WORD_RE = re.compile(r"[^\W_]+")
# ``[[TYPE_<anything but a hex id>]]`` on one line (cf. ``pii_guard.vault.placeholders``).
_SPOOFED_PLACEHOLDER_RE = re.compile(r"(\[\[[A-Z][A-Z0-9_]*_)([^\[\]\n]{1,200}?)(\]\])")
_HEX_ID_RE = re.compile(r"[0-9a-f]{4,}")
# A line break directly between two digits: ``+36 30 123\n4567``, ``DE89\r\n3704 ...``.
_WRAPPED_NUMBER_RE = re.compile(r"(?<=[0-9])(\r\n|[\n\r\x0b\x0c\x85\u2028\u2029])(?=[0-9])")
_LINE_BREAK_RE = re.compile(f"[{_LINE_BREAKS}]")
# A line of nothing but a number (a list or a table column): never joined to the next one.
_NUMBER_LINE_RE = re.compile(r"[ \t]*[+(]?[0-9][0-9 ()+\-./]*[ \t]*")
# The rest of a wrapped number: digit groups and nothing else on the line but a closing mark.
_CONTINUATION_RE = re.compile(r"[0-9]+(?:[ -][0-9]+)*[ \t]*[.,;:!?)]?[ \t]*")


def _is_latin(char: str) -> bool:
    if not char.isalpha():
        return False
    return char.isascii() or "LATIN" in unicodedata.name(char, "")


def _is_mark(char: str) -> bool:
    """A combining or enclosing mark (``\\u0301``, ``\\u0333``, keycap ``\\u20e3``)."""
    return unicodedata.combining(char) != 0 or unicodedata.category(char) in ("Mn", "Me")


def _next_visible(text: str, k: int) -> str:
    """The first character at or after ``k`` that is not invisible (``""`` at the end)."""
    n = len(text)
    while k < n and text[k] in INVISIBLE_CHARS:
        k += 1
    return text[k] if k < n else ""


def _reads_as_space(text: str, k: int, before: str) -> bool:
    """Whether the zero-width separator ``text[k]``, after the letter ``before``, is a space.

    It is between a lower-case and an upper-case letter (``Teszt\\u200bElek``): a word
    boundary. Between letters of one case it cannot be told from a separator put inside a word
    to break matching (``Te\\u200bszt``), so it is dropped like the other invisible characters.
    """
    if text[k] not in ZERO_WIDTH_SEPARATORS or not before.islower():
        return False
    return _next_visible(text, k + 1).isupper()


def _fold_char(char: str) -> str:
    """The one-for-one fold of a non-ASCII character (itself if nothing applies)."""
    code = ord(char)
    if 0xFF01 <= code <= 0xFF5E or 0x1D400 <= code <= 0x1D7FF:
        folded = unicodedata.normalize("NFKC", char)
        if len(folded) == 1:
            return folded
    if char in DASHES:
        return "-"
    if char in DOTS:
        return "."
    category = unicodedata.category(char)
    if category == "Zs":
        return " "
    if category == "Nd":
        return str(unicodedata.decimal(char))
    return char


@dataclass(frozen=True, slots=True)
class NormalizedText:
    """``text`` with ``origin[i]`` = index in ``original`` of ``text[i]``.

    ``ends[i]`` is the index just after the original characters ``text[i]`` stands for: more
    than ``origin[i] + 1`` when it was composed from a base character and combining marks.
    Empty when every character stands for exactly one.
    """

    original: str
    text: str
    origin: tuple[int, ...]
    ends: tuple[int, ...] = ()

    @property
    def changed(self) -> bool:
        return self.text != self.original

    def to_original(self, start: int, end: int) -> tuple[int, int]:
        """The original span covering ``text[start:end]`` (``end`` exclusive, ``start < end``)."""
        if not 0 <= start < end <= len(self.text):
            raise ValueError("span out of range")
        last = self.ends[end - 1] if self.ends else self.origin[end - 1] + 1
        return self.origin[start], last


def _compose(text: str) -> tuple[list[str], list[int], list[int]]:
    """Drop invisible characters, compose combining marks (NFC) and fold one for one.

    Returns the characters with the original start and end of each. A base character and
    the marks after it are composed when NFC makes them one character; marks left on an
    ASCII letter or digit (``5\\u0333``, keycap ``8\\u20e3``) are dropped, the base standing
    for all of them. Anything else is kept as it is, character for character.
    """
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        if c < "\x80" and (i + 1 == n or text[i + 1] < "\x80"):
            chars.append(c)
            starts.append(i)
            ends.append(i + 1)
            i += 1
            continue
        if c in INVISIBLE_CHARS:
            if chars and _reads_as_space(text, i, chars[-1]):
                chars.append(" ")
                starts.append(i)
                ends.append(i + 1)
            i += 1
            continue
        c_fold = c if c < "\x80" else _fold_char(c)
        # The marks after a base character (invisible characters between them are dropped,
        # up to a zero-width separator that reads as a space after it).
        j = i + 1
        while j < n and (text[j] in INVISIBLE_CHARS or (text[j] >= "\x80" and _is_mark(text[j]))):
            if _reads_as_space(text, j, c_fold):
                break
            j += 1
        if j == i + 1:
            chars.append(c_fold)
            starts.append(i)
            ends.append(i + 1)
            i += 1
            continue
        _cluster(text, i, j, chars, starts, ends)
        i = j
    return chars, starts, ends


def _cluster(
    text: str, i: int, j: int, chars: list[str], starts: list[int], ends: list[int]
) -> None:
    """Append ``text[i:j]``: a character followed by marks (and maybe invisible characters)."""
    kept = [k for k in range(i, j) if text[k] not in INVISIBLE_CHARS]
    if not kept:
        return
    if _is_mark(text[kept[0]]):  # marks with no base: keep each one as it is
        for k in kept:
            chars.append(text[k])
            starts.append(k)
            ends.append(k + 1)
        return
    cluster = "".join(text[k] for k in kept)
    composed = unicodedata.normalize("NFC", cluster)
    base = _fold_char(composed[0]) if composed[0] >= "\x80" else composed[0]
    if len(composed) == 1 or (base.isascii() and base.isalnum()):
        chars.append(base)
        starts.append(i)
        ends.append(kept[-1] + 1)
        return
    for k in kept:
        chars.append(_fold_char(text[k]))
        starts.append(k)
        ends.append(k + 1)


def _fold_lookalikes(chars: list[str]) -> None:
    """Fold lookalike letters in a word that has Latin letters or is shaped like an identifier.

    Genuine Cyrillic or Greek words are left alone. A word of nothing but lookalike letters is
    folded when it has digits in it or is joined to digits by a hyphen, the shape of a plate,
    a document number or an IBAN: ``\\u0410\\u0412\\u0421-123``, ``123456\\u0410\\u0412``,
    ``\\u0392\\u039568 5390 ...``.
    """
    joined = "".join(chars)
    for match in _WORD_RE.finditer(joined):
        start, end = match.span()
        word = joined[start:end]
        if word.isascii() or not any(c in LOOKALIKES for c in word):
            continue
        if not any(_is_latin(c) for c in word):
            letters = [c for c in word if c.isalpha()]
            if not all(c in LOOKALIKES for c in letters):
                continue
            has_digit = any(c.isdigit() for c in word)
            hyphen_digit = (
                end + 1 < len(joined) and joined[end] == "-" and joined[end + 1].isdigit()
            ) or (start >= 2 and joined[start - 1] == "-" and joined[start - 2].isdigit())
            if not (has_digit or hyphen_digit):
                continue
        for k in range(start, end):
            chars[k] = LOOKALIKES.get(chars[k], chars[k])


def _blank_spoofed_placeholders(chars: list[str]) -> None:
    """Blank the wrapper of spoofed placeholders (one for one, offsets unchanged)."""
    joined = "".join(chars)
    if "[[" not in joined:
        return
    for match in _SPOOFED_PLACEHOLDER_RE.finditer(joined):
        if _HEX_ID_RE.fullmatch(match.group(2)):
            continue
        for k in (*range(*match.span(1)), *range(*match.span(3))):
            chars[k] = " "


def _join_wrapped_numbers(chars: list[str]) -> list[int]:
    """Turn a line break inside a number into a space; the indices to drop (CR of a CR LF).

    A break is joined only when the next line holds nothing but the rest of the number
    (``+36 30 123`` / ``4567``) and the line before has more than a number on it, so a list or
    a column of numbers, one per line, and chat lines starting with a time stay apart.
    """
    joined = "".join(chars)
    if not any(b in joined for b in _LINE_BREAKS):
        return []
    drop: list[int] = []
    for match in _WRAPPED_NUMBER_RE.finditer(joined):
        start, end = match.span()
        line_start = max(joined.rfind(b, 0, start) for b in _LINE_BREAKS) + 1
        following = _LINE_BREAK_RE.search(joined, end)
        before = joined[line_start:start]
        after = joined[end : following.start() if following else len(joined)]
        if _NUMBER_LINE_RE.fullmatch(before) or not _CONTINUATION_RE.fullmatch(after):
            continue
        chars[end - 1] = " "
        drop.extend(range(start, end - 1))
    return drop


def normalize_for_detection(text: str) -> NormalizedText:
    """Clean ``text`` for detection with an exact offset map back; see the module docstring."""
    if not text:
        return NormalizedText(text, text, ())
    if text.isascii():
        chars = list(text)
        starts: list[int] | range = range(len(text))
        ends: list[int] | None = None
    else:
        chars, starts, ends = _compose(text)
        _fold_lookalikes(chars)
    _blank_spoofed_placeholders(chars)
    drop = _join_wrapped_numbers(chars)
    if drop:
        dropped = set(drop)
        keep = [k for k in range(len(chars)) if k not in dropped]
        chars = [chars[k] for k in keep]
        starts = [starts[k] for k in keep]
        ends = [ends[k] for k in keep] if ends is not None else None
    out = "".join(chars)
    if out == text:
        return NormalizedText(text, text, tuple(range(len(text))))
    origin = tuple(starts)
    end_map: tuple[int, ...] = ()
    if ends is not None and any(e != s + 1 for s, e in zip(starts, ends, strict=True)):
        end_map = tuple(ends)
    return NormalizedText(text, out, origin, end_map)
