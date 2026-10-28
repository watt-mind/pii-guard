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
- **Obfuscated e-mail addresses** (``name [at] example [dot] com``, ``name(at)example.com``)
  read as ``name@example.com``: a bracketed ``at`` (``[at]``, ``(at)``, ``{at}``, ``<at>``; also
  ``ät``, ``kukac``) and a bracketed ``dot`` (also ``punkt``, ``pont``), with the spaces
  around them, stand for ``@`` and ``.`` when the whole reads as an address: a local part,
  ``@`` and at least two domain labels, the last of letters, at least one separator
  bracketed. Bare ``at`` and ``dot`` words in prose are left alone.
- **A value spelled out one character at a time** (``D E 6 3 1 4 ...``, ``0 1 1 3 4 9 6 ...``):
  a run of at least six single letters or digits separated by single spaces, with at least six
  digits, has the spaces dropped.
- **A value regrouped in threes with dots** (``GB5.4PZ.JT7.994.613``, ``294.221.325``): at least
  three dot-separated groups of three letters or digits (the last may be shorter), with at least
  six digits, has the dots dropped. An amount (a decimal part after it, a currency next to it),
  an IPv4 address and anything inside a longer dotted name are left alone.
- **Spoofed placeholders**: a value wrapped to look like a pii-guard placeholder
  (``[[PERSON_Teszt Elek]]``) has the wrapper blanked to spaces, so the model sees the value
  and not a placeholder it was told to skip. Real placeholders (``[[PERSON_3fa2c1]]``: an
  upper-case type and a lower-case hex id) are left alone.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
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
_LINE_BREAK_RE = re.compile(rf"\r\n|[{_LINE_BREAKS}]")

# Obfuscated e-mail separators: ``[at]``, ``(dot)`` ... with the spaces around them (LAB-1297).
_OPEN, _CLOSE = r"[\[({<]", r"[\])}>]"
_AT_WORD = rf"[ \t]*{_OPEN}[ \t]*(?:at|ät|kukac)[ \t]*{_CLOSE}[ \t]*"
_DOT_WORD = rf"[ \t]*{_OPEN}[ \t]*(?:dot|punkt|pont)[ \t]*{_CLOSE}[ \t]*"
_LABEL = r"[^\W_](?:[\w-]*[^\W_])?"
_OBFUSCATED_EMAIL_RE = re.compile(
    rf"(?<![\w.+-])[^\W_][\w.+-]*(?:{_AT_WORD}|@){_LABEL}(?:(?:{_DOT_WORD}|\.){_LABEL})+"
    r"(?![\w-])",
    re.IGNORECASE,
)
_EMAIL_SEPARATOR_RE = re.compile(rf"(?P<at>{_AT_WORD})|(?P<dot>{_DOT_WORD})", re.IGNORECASE)
# Single letters or digits separated by single spaces: ``D E 6 3 1 4 ...``.
_SPELLED_OUT_RE = re.compile(r"(?<![^\W_])(?:[^\W_] ){5,}[^\W_](?![^\W_])")
# Groups of three separated by dots: ``GB5.4PZ.JT7.994``, ``294.221.325``.
_DOTTED_GROUPS_RE = re.compile(
    r"(?<![\w.])[^\W_]{3}(?:\.[^\W_]{3})+(?:\.[^\W_]{1,2})?(?!\w|\.[^\W_]|,[0-9])"
)
_CURRENCY_RE = re.compile(r"(?:[$€£¥₽]|\b(?:Ft|HUF|EUR|USD|GBP|CHF|Euro|Forint)\b)", re.IGNORECASE)
# A cheap test for the three folds above, so plain text keeps the fast path.
_REGROUPED_HINT_RE = re.compile(
    rf"{_OPEN}[ \t]*(?:at|ät|kukac|dot|punkt|pont)[ \t]*{_CLOSE}|(?:[^\W_] ){{5}}[^\W_]"
    r"|[^\W_]{3}\.[^\W_]{3}\.[^\W_]",
    re.IGNORECASE,
)
#: Fewest digits in a spelled-out or dot-regrouped value (a short code stays as it is).
_MIN_REGROUPED_DIGITS = 6


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

    ``origin`` is a tuple, or ``range(len(text))`` when nothing changed (no map is built).

    ``ends[i]`` is the index just after the original characters ``text[i]`` stands for: more
    than ``origin[i] + 1`` when it was composed from a base character and combining marks.
    Empty when every character stands for exactly one.
    """

    original: str
    text: str
    origin: Sequence[int]
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


def _is_number_line(text: str) -> bool:
    """Recognize a bare numeric line in linear time, including optional sign and padding."""
    line = text.strip(" \t")
    if not line:
        return False
    start = int(line[0] in "+(")
    if start == len(line) or not "0" <= line[start] <= "9":
        return False
    # Tabs are padding only; spaces and these marks may also occur inside the number.
    return all(char in "0123456789 ()+-./" for char in line[start + 1 :])


def _is_number_continuation(text: str) -> bool:
    """Recognize digit groups, optional closing punctuation and space/tab padding linearly."""
    line = text.rstrip(" \t")
    if line and line[-1] in ".,;:!?)":
        line = line[:-1].rstrip(" \t")
    # A separator must have digits on both sides. Each character has exactly one role;
    # trailing whitespace is removed above rather than backtracked between repetitions.
    needs_digit = True
    for char in line:
        if "0" <= char <= "9":
            needs_digit = False
        elif char in " -" and not needs_digit:
            needs_digit = True
        else:
            return False
    return not needs_digit


def _join_wrapped_numbers(chars: list[str]) -> list[int]:
    """Turn a line break inside a number into a space; the indices to drop (CR of a CR LF).

    A break is joined only when the next line holds nothing but the rest of the number
    (``+36 30 123`` / ``4567``) and the line before has more than a number on it, so a list or
    a column of numbers, one per line, and chat lines starting with a time stay apart.
    """
    joined = "".join(chars)
    breaks = iter(_LINE_BREAK_RE.finditer(joined))
    current = next(breaks, None)
    line_start = 0
    drop: list[int] = []
    while current is not None:
        following = next(breaks, None)
        start, end = current.span()
        if (
            start > 0
            and end < len(joined)
            and ("0" <= joined[start - 1] <= "9" and "0" <= joined[end] <= "9")
        ):
            before = joined[line_start:start]
            after = joined[end : following.start() if following else len(joined)]
            if not _is_number_line(before) and _is_number_continuation(after):
                chars[end - 1] = " "
                drop.extend(range(start, end - 1))
        # Every boundary advances once; each adjacent line is checked at most twice.
        line_start = end
        current = following
    return drop


def _fold_obfuscated_emails(chars: list[str]) -> list[int]:
    """Read ``[at]`` / ``[dot]`` in an e-mail address as ``@`` / ``.``; the indices to drop.

    Each bracketed separator, with the spaces around it, becomes its first character (set to
    ``@`` or ``.``) and the rest is dropped, so the address maps back over all of it.
    """
    joined = "".join(chars)
    drop: list[int] = []
    for match in _OBFUSCATED_EMAIL_RE.finditer(joined):
        value = match.group()
        tld = re.split(_DOT_WORD + r"|\.", value, flags=re.IGNORECASE)[-1]
        if len(tld) < 2 or not tld.isalpha():
            continue
        offset = match.start()
        for sep in _EMAIL_SEPARATOR_RE.finditer(value):
            start, end = offset + sep.start(), offset + sep.end()
            chars[start] = "@" if sep.group("at") else "."
            drop.extend(range(start + 1, end))
    return drop


def _digit_count(text: str) -> int:
    return sum(c.isdigit() for c in text)


def _join_spelled_out(chars: list[str]) -> list[int]:
    """Drop the spaces of a spelled-out value and the dots of a dot-regrouped one.

    ``D E 6 3 1 4 ...`` and ``GB5.4PZ.JT7.994`` read as one token. One lower-case letter before
    upper-case letters or digits (``a G B 2 5 ...``: an article) is not joined to them.
    """
    joined = "".join(chars)
    drop: list[int] = []
    for match in _SPELLED_OUT_RE.finditer(joined):
        start, end = match.span()
        if _digit_count(match.group()) < _MIN_REGROUPED_DIGITS:
            continue
        if joined[start].islower() and not joined[start + 2].islower():
            start += 2  # ``a G B 2 5 ...``: an article before the value
        drop.extend(range(start + 1, end, 2))
    for match in _DOTTED_GROUPS_RE.finditer(joined):
        start, end = match.span()
        groups = match.group().split(".")
        if len(groups) < 3 or _digit_count(match.group()) < _MIN_REGROUPED_DIGITS:
            continue
        if all(g.isdigit() for g in groups):
            if len(groups) == 4 and all(int(g) <= 255 for g in groups):
                continue  # an IPv4 address
            around = joined[max(0, start - 6) : start] + " " + joined[end : end + 8]
            if _CURRENCY_RE.search(around):
                continue  # an amount: 1.234.567 Ft, € 123.456.789
        drop.extend(k for k in range(start, end) if joined[k] == ".")
    return drop


def _one_for_one_fold(text: str) -> tuple[dict[int, str], bool] | None:
    """How ``text`` folds when every character folds one for one, else ``None``.

    That holds when ``text`` has no invisible character and no combining mark: :func:`_compose`
    then maps each character to :func:`_fold_char` of it, with the identity offset map. Returns
    the translation table and whether the folded text has a lookalike letter in it (when it has
    none, :func:`_fold_lookalikes` has nothing to do). Only the distinct characters are looked
    at, so this costs a fraction of :func:`_compose`.
    """
    table: dict[int, str] = {}
    lookalike = False
    for char in set(text):
        if char < "\x80":
            continue
        if char in INVISIBLE_CHARS or _is_mark(char):
            return None
        folded = _fold_char(char)
        if folded != char:
            table[ord(char)] = folded
        # A mathematical Greek letter folds (NFKC) to a Greek lookalike.
        lookalike = lookalike or folded in LOOKALIKES
    return table, lookalike


def normalize_for_detection(text: str) -> NormalizedText:
    """Clean ``text`` for detection with an exact offset map back; see the module docstring."""
    return _normalize(text, fast=True)


def _normalize_reference(text: str) -> NormalizedText:
    """:func:`normalize_for_detection` without the one-for-one fast path (tests compare them)."""
    return _normalize(text, fast=False)


def _translate(text: str, table: dict[int, str]) -> str:
    """``text.translate(table)``, by ``str.replace`` when that is the same and faster.

    A table is a handful of characters (a no-break space, an en dash); one ``replace`` per
    entry beats ``translate`` looking every character up. It is the same when no replacement
    is itself a key, which :func:`_fold_char` guarantees, but the check is cheap.
    """
    if len(table) > 8 or any(ord(v) in table for v in table.values()):
        return text.translate(table)
    for code, folded in table.items():
        text = text.replace(chr(code), folded)
    return text


def _normalize(text: str, *, fast: bool) -> NormalizedText:
    if not text:
        return NormalizedText(text, text, ())
    starts: list[int] | range = range(len(text))
    ends: list[int] | None = None
    folded: str | None = None  # the text so far, when every character was folded one for one
    if text.isascii():
        folded = text
    elif fast and (one_for_one := _one_for_one_fold(text)) is not None:
        table, lookalike = one_for_one
        folded = _translate(text, table) if table else text
        if lookalike:
            chars = list(folded)
            _fold_lookalikes(chars)
            folded = "".join(chars)
    else:
        chars, starts, ends = _compose(text)
        _fold_lookalikes(chars)
    if (
        fast
        and folded is not None
        and "[[" not in folded
        and not _WRAPPED_NUMBER_RE.search(folded)
        and not _REGROUPED_HINT_RE.search(folded)
    ):
        # No placeholder to blank, no wrapped number, address or regrouped value to join:
        # the fold is final.
        if folded == text:
            return NormalizedText(text, text, starts)
        return NormalizedText(text, folded, tuple(starts))
    if folded is not None:
        chars = list(folded)
    _blank_spoofed_placeholders(chars)
    drop = _fold_obfuscated_emails(chars) + _join_spelled_out(chars) + _join_wrapped_numbers(chars)
    if drop:
        dropped = set(drop)
        keep = [k for k in range(len(chars)) if k not in dropped]
        chars = [chars[k] for k in keep]
        starts = [starts[k] for k in keep]
        ends = [ends[k] for k in keep] if ends is not None else None
    out = "".join(chars)
    if out == text:
        return NormalizedText(text, text, range(len(text)) if fast else tuple(range(len(text))))
    origin = tuple(starts)
    end_map: tuple[int, ...] = ()
    if ends is not None and any(e != s + 1 for s, e in zip(starts, ends, strict=True)):
        end_map = tuple(ends)
    return NormalizedText(text, out, origin, end_map)
