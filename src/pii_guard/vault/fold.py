"""The folded view occurrences are searched in, with an offset map back to the original.

A value the vault has confirmed must be found again however it is written: in another casing
(``TESZT ELEK``), in another Unicode form (macOS copy-paste is NFD: ``Kova\\u0301cs``), with the
German sharp s spelled out (``WEISS`` for ``Weiß``) or with an invisible character inside.
``re.IGNORECASE`` covers none of these but the first, so occurrence patterns are compiled from
the folded value and run over the folded text.

The fold is :func:`~pii_guard.detect.normalize.normalize_for_detection` (invisible characters
dropped, combining marks composed, Unicode spaces and dashes folded; the view every detector
sees) followed by a full case fold per character (``ß`` -> ``ss``). A match over the folded
text maps back to the smallest original span covering it (:meth:`FoldedText.to_original`), so
the placeholder replaces the occurrence exactly as it was written.

A zero-width separator between two letters of the same case is ambiguous: ``teszt\\u200belek``
may be two words run together or one word with an invisible character put in to break
matching (``Te\\u200bszt``). The detection fold drops it; :func:`fold_views` also gives the
reading with every such separator as a space, and the vault searches both, so neither way of
writing a value hides an occurrence.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from pii_guard.detect.normalize import (
    INVISIBLE_CHARS,
    ZERO_WIDTH_SEPARATORS,
    normalize_for_detection,
)

__all__ = ["FoldedText", "fold_text", "fold_value", "fold_views"]


@dataclass(frozen=True, slots=True)
class FoldedText:
    """``text`` folded, with ``starts[i]``/``ends[i]`` the original span of ``text[i]``.

    Both maps are empty when the fold kept every character in place (ASCII text: lower case
    only). ``repr()`` omits both texts: they hold personal data.
    """

    original: str
    text: str
    starts: tuple[int, ...] = ()
    ends: tuple[int, ...] = ()

    def __repr__(self) -> str:
        return f"FoldedText(length={len(self.original)}, folded={len(self.text)})"

    __str__ = __repr__

    def to_original(self, start: int, end: int) -> tuple[int, int]:
        """The original span covering ``text[start:end]`` (``start < end``)."""
        if not self.starts:
            return start, end
        return self.starts[start], self.ends[end - 1]


def fold_text(text: str) -> FoldedText:
    """``text`` normalised as for detection, then case-folded, with the offset map."""
    return _fold(text, text)


def fold_views(text: str) -> tuple[FoldedText, ...]:
    """The folded views occurrences are searched in: :func:`fold_text`'s, and one more if needed.

    The second view reads every zero-width separator between two letters (invisible
    characters and combining marks aside) as a space: ``teszt\\u200belek`` as ``teszt elek``.
    It is given only when ``text`` has such a separator; both views map back to ``text``.
    """
    primary = fold_text(text)
    if text.isascii() or not any(c in ZERO_WIDTH_SEPARATORS for c in text):
        return (primary,)
    spaced = _spaced(text)
    if spaced == text:
        return (primary,)
    alternative = _fold(text, spaced)
    if alternative.text == primary.text:
        return (primary,)
    return primary, alternative


def _spaced(text: str) -> str:
    """``text`` with each zero-width separator between two letters replaced by a space.

    One for one, so offsets into the result are offsets into ``text``.
    """
    chars = list(text)
    n = len(text)
    for k, char in enumerate(text):
        if char not in ZERO_WIDTH_SEPARATORS:
            continue
        before = k - 1
        while before >= 0 and (text[before] in INVISIBLE_CHARS or _is_mark(text[before])):
            before -= 1
        after = k + 1
        while after < n and text[after] in INVISIBLE_CHARS:
            after += 1
        if before >= 0 and after < n and text[before].isalpha() and text[after].isalpha():
            chars[k] = " "
    return "".join(chars)


def _is_mark(char: str) -> bool:
    return unicodedata.category(char) in ("Mn", "Mc", "Me")


def _fold(original: str, text: str) -> FoldedText:
    """Fold ``text``, a one-for-one rewrite of ``original``, as the view of ``original``."""
    if text.isascii():
        return FoldedText(original, text.lower())
    norm = normalize_for_detection(text)
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for index, char in enumerate(norm.text):
        start = norm.origin[index]
        end = norm.ends[index] if norm.ends else start + 1
        for folded in char.casefold():
            chars.append(folded)
            starts.append(start)
            ends.append(end)
    folded_text = "".join(chars)
    if len(folded_text) == len(text) and all(
        s == i and e == i + 1 for i, (s, e) in enumerate(zip(starts, ends, strict=True))
    ):
        return FoldedText(original, folded_text)
    return FoldedText(original, folded_text, tuple(starts), tuple(ends))


def fold_value(value: str) -> str:
    """The folded form of ``value`` that occurrence patterns are compiled from."""
    return fold_text(value).text
