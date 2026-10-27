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
"""

from __future__ import annotations

from dataclasses import dataclass

from pii_guard.detect.normalize import normalize_for_detection

__all__ = ["FoldedText", "fold_text", "fold_value"]


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
    if text.isascii():
        return FoldedText(text, text.lower())
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
        return FoldedText(text, folded_text)
    return FoldedText(text, folded_text, tuple(starts), tuple(ends))


def fold_value(value: str) -> str:
    """The folded form of ``value`` that occurrence patterns are compiled from."""
    return fold_text(value).text
