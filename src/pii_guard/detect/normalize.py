"""Normalise obfuscated text before detection, with an offset map back to the original.

Personal data can be hidden from a detector without hiding it from a reader: zero-width and
other invisible characters inside a name (``Te\\u200bszt``), Cyrillic or Greek lookalike
letters mixed into a Latin word (``T\\u0435szt``), or fullwidth / mathematical letters. A
downstream LLM reads all of these as the plain value, so detection must too.

:func:`normalize_for_detection` returns a :class:`NormalizedText`: the cleaned text and, for
every character of it, the index of the original character it came from. Characters are only
**dropped** (invisible ones) or **replaced one for one** (lookalikes), never inserted, so a span
over the cleaned text maps back to the smallest original span covering the same characters,
including any invisible characters inside it (:meth:`NormalizedText.to_original`). Masking that
original span removes the obfuscated value whole.

The rules:

- **Invisible characters** are dropped: zero-width space / non-joiner / joiner, word joiner,
  BOM, soft hyphen, combining grapheme joiner, Mongolian vowel separator, invisible math
  operators and the bidirectional controls (embeddings, overrides, isolates).
- **Lookalikes** are folded to Latin only inside a word that also contains Latin letters, so
  genuine Cyrillic or Greek text is left alone.
- **Fullwidth and mathematical alphanumerics** (``\\uff21``, ``\\U0001d400``) are folded with NFKC
  when that gives a single character.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = ["INVISIBLE_CHARS", "LOOKALIKES", "NormalizedText", "normalize_for_detection"]

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

# A "word" for the mixed-script test: letters, digits and invisible characters inside it.
_INVISIBLE_CLASS = "".join(re.escape(c) for c in sorted(INVISIBLE_CHARS))
_WORD_RE = re.compile(rf"(?:[^\W_]|[{_INVISIBLE_CLASS}])+")


def _is_latin(char: str) -> bool:
    if not char.isalpha():
        return False
    return char.isascii() or "LATIN" in unicodedata.name(char, "")


def _fold_wide(char: str) -> str:
    code = ord(char)
    if 0xFF01 <= code <= 0xFF5E or 0x1D400 <= code <= 0x1D7FF:
        folded = unicodedata.normalize("NFKC", char)
        if len(folded) == 1:
            return folded
    return char


@dataclass(frozen=True, slots=True)
class NormalizedText:
    """``text`` with ``origin[i]`` = index in ``original`` of ``text[i]``."""

    original: str
    text: str
    origin: tuple[int, ...]

    @property
    def changed(self) -> bool:
        return self.text != self.original

    def to_original(self, start: int, end: int) -> tuple[int, int]:
        """The original span covering ``text[start:end]`` (``end`` exclusive, ``start < end``)."""
        if not 0 <= start < end <= len(self.text):
            raise ValueError("span out of range")
        return self.origin[start], self.origin[end - 1] + 1


def normalize_for_detection(text: str) -> NormalizedText:
    """Drop invisible characters and fold lookalike letters; see the module docstring."""
    if not text:
        return NormalizedText(text, text, ())
    chars = [_fold_wide(c) for c in text]
    # Fold lookalikes inside words that also have Latin letters.
    for match in _WORD_RE.finditer(text):
        word = chars[match.start() : match.end()]
        if any(c in LOOKALIKES for c in word) and any(_is_latin(c) for c in word):
            for i in range(match.start(), match.end()):
                chars[i] = LOOKALIKES.get(chars[i], chars[i])
    out: list[str] = []
    origin: list[int] = []
    for i, c in enumerate(chars):
        if c in INVISIBLE_CHARS:
            continue
        out.append(c)
        origin.append(i)
    return NormalizedText(text, "".join(out), tuple(origin))
