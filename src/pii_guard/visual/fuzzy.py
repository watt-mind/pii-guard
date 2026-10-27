"""Fuzzy matching of OCR'd values against the values a vault session already holds.

A name on an ID card is rarely written the way the same person is written in a contract:
``FIKTÍV MÁRIA`` (capitals) or ``FIKTIV<<MARIA`` (the MRZ: no accents, surname first) on the
card, ``Fiktív Mária`` in the text, ``Mária Fiktív`` in an English letter. OCR adds its own
noise on top (``0``/``O``, ``1``/``l``/``I``, dropped accents). The vault's own matching is
exact up to case and whitespace (:func:`pii_guard.vault.normalize_value`), so on its own the
card value would get a second placeholder, and the upstream model could not tell that the
card belongs to the person in the contract.

:func:`match_value` compares a value with every candidate of a compatible type and returns
the best one with a **confidence** in ``[0, 1]``:

- **names** (``PERSON``) are compared token by token in any order (``SURNAME GIVEN`` vs
  ``Given Surname``), accent- and case-insensitively, with a weighted edit distance in which
  OCR confusions (``0``/``o``, ``1``/``l``/``i``, ``5``/``s``, ...) cost a fifth of a real
  edit. The confidence is the **worst** token's similarity, so one wrong given name sinks the
  match however long the surname is (``Kovács Anna`` vs ``Kovács Hanna`` is not a match), and
  a token with even one real edit (not an OCR confusion) is capped at :data:`EDIT_CAP`, below
  :data:`ACCEPT` (``Mustermann`` vs ``Mustermonn``).
  A value with fewer tokens than the candidate (the surname field alone) is a partial match,
  accepted only when no other candidate matches it too;
- **numbers and codes** (document numbers, personal ids) are compared on their letters and
  digits only, with the same OCR confusion costs; e-mail addresses and phone numbers without
  whitespace;
- **dates** are compared as dates, whatever their format (``1959.01.02.``, ``02 JAN 1959``,
  ``590102`` in an MRZ).

A match at or above :data:`ACCEPT` is used (the card value gets the session's placeholder).
Between :data:`UNCERTAIN` and :data:`ACCEPT`, or when two candidates are within
:data:`AMBIGUITY_MARGIN` of each other, the match is **uncertain**: the caller gives the value
a new placeholder and flags it, rather than guessing. Two different people are never merged
silently: near-namesakes (``Teszt Elek`` / ``Teszt Elemér``, ``Minta Péter`` / ``Minta
Petra``) fall below :data:`ACCEPT` by construction, and the tests keep it that way.

Nothing here logs, and no value is ever put into an exception or a ``repr``.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pii_guard.types import EntityType

__all__ = [
    "ACCEPT",
    "AMBIGUITY_MARGIN",
    "UNCERTAIN",
    "Candidate",
    "Match",
    "fold",
    "match_value",
    "name_tokens",
    "parse_date",
    "similarity",
]

#: A match at or above this confidence reuses the candidate's placeholder.
ACCEPT = 0.85
#: Below :data:`ACCEPT` and at or above this, the match is reported as uncertain.
UNCERTAIN = 0.6
#: Two candidates closer than this are ambiguous: the match is uncertain.
AMBIGUITY_MARGIN = 0.08
#: A partial name match (fewer tokens than the candidate) is worth this much of a full one.
PARTIAL_FACTOR = 0.95
#: Cost of substituting one character of an OCR confusion group for another.
CONFUSION_COST = 0.2
#: Cost of a dropped or added punctuation mark (``.``, ``-``, ``'``).
PUNCTUATION_COST = 0.2
#: The highest confidence a token or identifier with a real (non-confusion) edit can reach.
EDIT_CAP = 0.8
#: A name token shorter than this never matches on its own.
MIN_TOKEN_LENGTH = 2

#: Characters OCR reads for one another, after accents are dropped and case is folded.
CONFUSION_GROUPS: tuple[str, ...] = ("o0", "l1i|!", "s5", "b8", "z2", "g9", "uv", "ec")
_CONFUSABLE = {(a, b) for group in CONFUSION_GROUPS for a in group for b in group if a != b}
_PUNCTUATION = frozenset(".-'\u2019,")

#: Types whose values are compared as names, as identifiers, or as dates.
NAME_TYPES = frozenset({EntityType.PERSON})
#: Types compared with all whitespace removed (OCR splits ``a .b@example.org``).
COMPACT_TYPES = frozenset({EntityType.EMAIL, EntityType.PHONE})
DATE_TYPES = frozenset({EntityType.DATE_OF_BIRTH})
IDENTIFIER_TYPES = frozenset(
    {
        EntityType.ID_DOCUMENT,
        EntityType.NATIONAL_ID_HU_TAX,
        EntityType.NATIONAL_ID_HU_TAJ,
        EntityType.BANK_ACCOUNT,
        EntityType.COMPANY_ID_HU,
        EntityType.VEHICLE_PLATE,
        EntityType.PARCEL_NUMBER_HU,
    }
)


def _family(entity_type: EntityType) -> str:
    if entity_type in COMPACT_TYPES:
        return "compact"
    if entity_type in NAME_TYPES:
        return "name"
    if entity_type in DATE_TYPES:
        return "date"
    if entity_type in IDENTIFIER_TYPES:
        return "identifier"
    return entity_type.value


@dataclass(frozen=True, slots=True)
class Candidate:
    """A value the session already holds: its placeholder, type and value (never repr'd)."""

    placeholder: str
    entity_type: EntityType
    value: str

    def __repr__(self) -> str:
        return f"Candidate(placeholder={self.placeholder!r}, value=<redacted>)"


@dataclass(frozen=True, slots=True)
class Match:
    """The best candidate for a value and how sure the match is.

    ``status``: ``"exact"`` (equal once folded), ``"fuzzy"`` (accepted), ``"uncertain"``
    (do not reuse ``candidate``; flag it) or ``"none"`` (no candidate came close;
    ``candidate`` is ``None``).
    """

    candidate: Candidate | None
    confidence: float
    status: str

    @property
    def accepted(self) -> bool:
        return self.status in ("exact", "fuzzy")


def fold(text: str) -> str:
    """Accents dropped, case folded, whitespace collapsed (``FIKTÍV Mária`` -> ``fiktiv maria``)."""
    decomposed = unicodedata.normalize("NFKD", text.replace("ß", "ss"))
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(plain.casefold().split())


_TOKEN_SPLIT_RE = re.compile(r"[\s<,;/]+")
_STRIP = ".-'\u2019"


def name_tokens(text: str) -> list[str]:
    """The folded tokens of a name, in any notation (``FIKTIV<<MARIA``, ``Fiktív, Mária``)."""
    stripped = (t.strip(_STRIP) for t in _TOKEN_SPLIT_RE.split(fold(text)))
    return [t for t in stripped if t]


def _sub_cost(a: str, b: str) -> float:
    if a == b:
        return 0.0
    return CONFUSION_COST if (a, b) in _CONFUSABLE else 1.0


def _indel_cost(c: str) -> float:
    return PUNCTUATION_COST if c in _PUNCTUATION else 1.0


def _distance(a: str, b: str) -> float:
    """Weighted Levenshtein distance (OCR confusions and punctuation are cheap)."""
    previous = [0.0]
    for c in b:
        previous.append(previous[-1] + _indel_cost(c))
    for ca in a:
        current = [previous[0] + _indel_cost(ca)]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + _indel_cost(ca),
                    current[j - 1] + _indel_cost(cb),
                    previous[j - 1] + _sub_cost(ca, cb),
                )
            )
        previous = current
    return previous[-1]


def _token_similarity(a: str, b: str) -> float:
    """``1 - distance / length``, capped at :data:`EDIT_CAP` (below :data:`ACCEPT`) as soon as
    the tokens differ by one real edit, an edit that is not an OCR confusion: ``Mustermann``
    and ``Mustermonn`` are two names, however long."""
    if a == b:
        return 1.0
    longest = max(len(a), len(b))
    if longest == 0:
        return 0.0
    distance = _distance(a, b)
    score = max(0.0, 1.0 - distance / longest)
    return min(score, EDIT_CAP) if distance >= 1.0 else score


def _name_similarity(value: str, candidate: str) -> tuple[float, bool]:
    """``(confidence, partial)``: the worst token similarity of the best one-to-one token
    pairing, in any order. ``partial``: one side has tokens the other doesn't."""
    left, right = name_tokens(value), name_tokens(candidate)
    if not left or not right:
        return 0.0, False
    short, long_ = (left, right) if len(left) <= len(right) else (right, left)
    if any(len(t) < MIN_TOKEN_LENGTH for t in short):
        return 0.0, False
    # Greedy pairing on the best similarities (names have a handful of tokens).
    pairs = sorted(
        ((_token_similarity(s, t), i, j) for i, s in enumerate(short) for j, t in enumerate(long_)),
        reverse=True,
    )
    used_short: set[int] = set()
    used_long: set[int] = set()
    worst = 1.0
    for score, i, j in pairs:
        if i in used_short or j in used_long:
            continue
        used_short.add(i)
        used_long.add(j)
        worst = min(worst, score)
        if len(used_short) == len(short):
            break
    partial = len(short) != len(long_)
    return (worst * PARTIAL_FACTOR if partial else worst), partial


def _identifier_similarity(value: str, candidate: str) -> float:
    """Letters and digits only; two document numbers one real character apart are two
    documents (see :func:`_token_similarity`)."""
    a = "".join(c for c in fold(value) if c.isalnum())
    b = "".join(c for c in fold(candidate) if c.isalnum())
    if not a or not b:
        return 0.0
    if _distance(a, b) >= 2.0:
        return 0.0  # two real edits: another document, not even an uncertain one
    return _token_similarity(a, b)


_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("jan", "januar", "january", "janner"),
            ("feb", "februar", "february"),
            ("mar", "marc", "marz", "march", "marcius"),
            ("apr", "aprilis", "april"),
            ("maj", "mai", "may", "majus"),
            ("jun", "juni", "june", "junius"),
            ("jul", "juli", "july", "julius"),
            ("aug", "augusztus", "august"),
            ("sep", "sept", "szept", "september", "szeptember"),
            ("okt", "oct", "oktober", "october"),
            ("nov", "november"),
            ("dec", "dez", "december", "dezember"),
        ),
        start=1,
    )
    for name in names
}
_DATE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})"), "ymd"),
    (re.compile(r"(\d{1,2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{4})"), "dmy"),
    (re.compile(r"(\d{1,2})\s*\.?\s*([a-z]{3,10})\.?\s*(\d{4})"), "dMy"),
    (re.compile(r"(\d{4})\s*\.?\s*([a-z]{3,10})\.?\s*(\d{1,2})"), "yMd"),
)


def parse_date(text: str, *, yymmdd: bool = False) -> dt.date | None:
    """A date in a common printed format (``1959.01.02.``, ``02.01.1959``, ``02 JAN 1959``,
    ``1959-01-02``), or ``YYMMDD`` when ``yymmdd`` (MRZ; a year above the current two-digit
    year + 20 is read as 19xx). ``None`` if nothing parses."""
    folded = fold(text)
    if yymmdd:
        digits = "".join(c for c in folded if c.isdigit())
        if len(digits) != 6:
            return None
        yy, mm, dd = int(digits[:2]), int(digits[2:4]), int(digits[4:])
        pivot = (dt.date.today().year + 20) % 100
        year = (2000 if yy <= pivot else 1900) + yy
        return _date(year, mm, dd)
    for pattern, order in _DATE_PATTERNS:
        match = pattern.search(folded)
        if match is None:
            continue
        a, b, c = match.groups()
        if order == "ymd":
            return _date(int(a), int(b), int(c))
        if order == "dmy":
            return _date(int(c), int(b), int(a))
        if order == "dMy":
            month = _MONTHS.get(b)
            return _date(int(c), month, int(a)) if month else None
        month = _MONTHS.get(b)
        return _date(int(a), month, int(c)) if month else None
    return None


def _date(year: int, month: int, day: int) -> dt.date | None:
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def similarity(value: str, entity_type: EntityType, candidate: Candidate) -> float:
    """How likely ``value`` (of ``entity_type``) is ``candidate``'s value, in ``[0, 1]``.

    ``0.0`` for incompatible types. Partial name matches are discounted by
    :data:`PARTIAL_FACTOR`.
    """
    family = _family(entity_type)
    if family != _family(candidate.entity_type):
        return 0.0
    if fold(value) == fold(candidate.value):
        return 1.0
    if family == "name":
        return _name_similarity(value, candidate.value)[0]
    if family == "date":
        a, b = parse_date(value), parse_date(candidate.value)
        return 1.0 if a is not None and a == b else 0.0
    if family == "identifier":
        if entity_type is not candidate.entity_type and EntityType.ID_DOCUMENT not in (
            entity_type,
            candidate.entity_type,
        ):
            return 0.0  # a TAJ number is never a tax number; ID_DOCUMENT is the generic one
        return _identifier_similarity(value, candidate.value)
    if family == "compact":
        return _token_similarity(
            "".join(fold(value).split()), "".join(fold(candidate.value).split())
        )
    return _token_similarity(fold(value), fold(candidate.value))


def match_value(
    value: str,
    entity_type: EntityType,
    candidates: Iterable[Candidate],
    *,
    accept: float = ACCEPT,
    uncertain: float = UNCERTAIN,
) -> Match:
    """The best candidate for ``value``, or an uncertain / no match (see the module doc)."""
    scored: list[tuple[float, Candidate]] = []
    for candidate in candidates:
        score = similarity(value, entity_type, candidate)
        if score >= uncertain:
            scored.append((score, candidate))
    if not scored:
        return Match(None, 0.0, "none")
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best = scored[0]
    # Ambiguity: a second, different value nearly as close (two people sharing a surname).
    rivals: Sequence[tuple[float, Candidate]] = [
        item
        for item in scored[1:]
        if item[1].placeholder != best.placeholder
        and fold(item[1].value) != fold(best.value)  # one value, two casings: not a rival
        and best_score - item[0] < AMBIGUITY_MARGIN
    ]
    confidence = round(best_score, 4)
    if rivals or best_score < accept:
        return Match(best, confidence, "uncertain")
    if fold(value) == fold(best.value):
        return Match(best, 1.0, "exact")
    return Match(best, confidence, "fuzzy")
