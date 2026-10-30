"""Context-cued numbers: a number right after a strong cue word is masked without a checksum.

The rules validate identifiers on purpose (checksums, numbering plans), so order numbers and
amounts are never masked. The price is that a number that fails its checksum, or a phone
number in a plan the rules don't know, is missed even when the text says what it is:
``kártyaszám: 4111 1111 1111 1112``, ``Steuer-ID 12 345 678 901``, ``Tel. +9-559-028.9863``.
This rule closes that gap: a digit or alphanumeric run right after a cue word (``TAJ``,
``adóazonosító``, ``passport``, ``IBAN``, ``telefon`` ...) is masked as the cue's type when it
has that type's shape (:data:`SHAPES`: characters, separators, length).

Cues are language-pack data, a ``cues.tsv`` next to ``captions.tsv``::

    # cue <TAB> entity type, or "-" for a cue that names something else (an order number)
    kártyaszám*	BANK_ACCOUNT
    TAJ	NATIONAL_ID_HU_TAJ
    rendelésszám*	-

- matching ignores case and accents (``kartyaszam`` is ``kártyaszám``), a space in a cue also
  matches a hyphen or nothing (``TAJ szám``, ``TAJ-szám``, ``TAJszám``), and a trailing ``*``
  lets the word take suffixes (``kártyaszám*``: ``kártyaszámát``, ``kártyaszámom``);
- between the cue and the value at most three short words or labels may stand
  (``credit card ending in``, ``Kreditkarte mit der Nummer``, ``száma (ha van):``), but no
  digit, no sentence end and no other cue: a ``-`` cue (``rendelésszám``, ``order number``)
  ends the window, so ``telefonos rendelésszám: 123456789`` stays unmasked;
- dates, amounts (a currency right after the value) and numbers that continue into a longer
  run are rejected, like everywhere else in the rules.

A third column ``after`` marks a cue that follows its value, as Hungarian puts it
(LAB-1199)::

    számon	PHONE	after
    számú útlevél*	ID_DOCUMENT	after

The value must stand right before the cue, separated by spaces only (``a +36 30 123 4567
számon``, ``a KA652524 számú útlevelére``), with the same shapes, score and rejections. A
phone before a post-value cue must also start with ``+`` or ``0`` (an international or trunk
prefix): ``a 2026/4471 számon iktatott`` is a file number. A bare ``számú`` is never a cue
(``a 4500123456 számú szerződés``); it names a type only together with its noun.

Hits score :data:`CUED_SCORE` (0.6), below every validated rule (0.7-0.99), and the rule
detector drops a cued hit that overlaps a validated one, so a checksum-valid identifier keeps
its validated span. Every pack's cues run for every text, like a pack's ``everywhere`` rules
(a Hungarian form with English labels is common); when two packs map the same cue to
different types, the text's own language wins. ``PII_GUARD_RULES_CUED_NUMBERS=false`` turns
the rule off (``docs/entities.md``).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from importlib.resources.abc import Traversable

from pii_guard.detect.rules._base import _Hit
from pii_guard.types import EntityType

__all__ = [
    "CUED_SCORE",
    "SHAPES",
    "Cue",
    "CueMatcher",
    "Shape",
    "fold",
    "load_cues",
    "matcher_for",
    "parse_cues",
]

#: Score of a cued, unvalidated hit: below every validated rule, so they win conflicts.
CUED_SCORE = 0.6


@dataclass(frozen=True, slots=True)
class Shape:
    """What a value of one type looks like, as characters between the separators.

    - ``letters``: uppercase ASCII letters allowed (alphanumeric identifiers);
    - ``digits``: bounds on the digit count; ``chars``: bounds on letters + digits;
    - ``separators``: single characters allowed between two value characters;
    - ``plus``: a leading ``+`` (international prefix) and parentheses (``(06 1)``) allowed.
    """

    digits: tuple[int, int]
    chars: tuple[int, int]
    letters: bool = False
    separators: str = " -"
    plus: bool = False


#: The value shape of every type a cue may name. A cue file naming another type is invalid.
SHAPES: dict[EntityType, Shape] = {
    # 7-15 digits (E.164), any grouping: unknown numbering plans are accepted after a cue.
    EntityType.PHONE: Shape(digits=(7, 15), chars=(7, 15), separators=" -./", plus=True),
    # Payment cards (12-19 digits) and account numbers up to IBAN length; shorter national
    # account numbers are left to the validated rules (an 8-digit run is too often a reference).
    EntityType.BANK_ACCOUNT: Shape(digits=(12, 34), chars=(12, 34), letters=True),
    # Hungarian tax ID (10 digits) and tax number (8-1-2).
    EntityType.NATIONAL_ID_HU_TAX: Shape(digits=(10, 11), chars=(10, 11)),
    # TAJ: 9 digits, usually in groups of three.
    EntityType.NATIONAL_ID_HU_TAJ: Shape(digits=(9, 9), chars=(9, 9)),
    # Passports, ID cards, licences, social security and tax IDs: 6-20 letters and digits,
    # at least two digits (so a word in capitals is never one).
    EntityType.ID_DOCUMENT: Shape(digits=(2, 20), chars=(6, 20), letters=True, separators=" -./"),
}

_HYPHENS = "\u2010\u2011\u2012\u2013\u2014\u2212"
_APOSTROPHES = "\u2018\u2019\u02bc"


def _fold_char(ch: str) -> str:
    if ch in _HYPHENS:
        return "-"
    if ch in _APOSTROPHES:
        return "'"
    lower = ch.lower()
    if len(lower) != 1:
        return ch
    base = unicodedata.normalize("NFD", lower)[0]
    return base if base.isascii() else lower


class _FoldTable(dict[int, str]):
    """``str.translate`` table that folds each character the first time it is seen."""

    def __missing__(self, code: int) -> str:
        folded = self[code] = _fold_char(chr(code))
        return folded


_FOLD = _FoldTable()


def fold(text: str) -> str:
    """Lower case without accents, hyphens as ``-``, apostrophes as ``'``; same length."""
    return text.translate(_FOLD)


@dataclass(frozen=True, slots=True)
class Cue:
    """One line of ``cues.tsv``: the cue text, its type (``None`` for ``-``), suffixes."""

    text: str
    entity_type: EntityType | None
    language: str
    suffix: bool = False
    #: The cue follows its value (``a +36 30 123 4567 számon``) instead of preceding it.
    after: bool = False

    @property
    def key(self) -> str:
        return " ".join(fold(self.text).split())


_CUE_TEXT_RE = re.compile(r"^[^\W\d_](?:(?:[^\W\d]|[ .'\u2019/#-])*(?:[^\W\d_]|[.#]))?$")


def parse_cues(text: str, language: str) -> tuple[Cue, ...]:
    """Parse a ``cues.tsv``: ``cue<TAB>ENTITY_TYPE`` or ``cue<TAB>-``; ``#`` comments.

    A third column ``after`` marks a cue that follows its value (it must name a type).

    Raises :class:`ValueError` (with the line number) on a malformed line, an entity type
    without a value shape in :data:`SHAPES`, or a cue listed twice.
    """
    cues: list[Cue] = []
    seen: dict[str, int] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in raw.split("\t")]
        if len(parts) not in (2, 3) or not all(parts):
            raise ValueError(f"line {number}: expected 'cue<TAB>ENTITY_TYPE' or 'cue<TAB>-'")
        cue_text, type_name = parts[:2]
        after = len(parts) == 3
        if after and parts[2] != "after":
            raise ValueError(f"line {number}: expected 'after' or nothing in the third column")
        if after and type_name == "-":
            raise ValueError(f"line {number}: an 'after' cue must name an entity type")
        suffix = cue_text.endswith("*")
        cue_text = cue_text.removesuffix("*").strip()
        if not _CUE_TEXT_RE.match(cue_text):
            raise ValueError(f"line {number}: cue must start with a letter and hold no digits")
        entity_type: EntityType | None = None
        if type_name != "-":
            try:
                entity_type = EntityType(type_name)
            except ValueError:
                raise ValueError(f"line {number}: unknown entity type {type_name!r}") from None
            if entity_type not in SHAPES:
                known = ", ".join(sorted(t.value for t in SHAPES))
                raise ValueError(
                    f"line {number}: {type_name} has no value shape (cues may name {known})"
                )
        cue = Cue(cue_text, entity_type, language, suffix, after)
        if cue.key in seen:
            raise ValueError(f"line {number}: cue already listed on line {seen[cue.key]}")
        seen[cue.key] = number
        cues.append(cue)
    return tuple(cues)


def load_cues(resource: Traversable, language: str) -> tuple[Cue, ...]:
    """Read a language pack's ``cues.tsv`` (see :func:`parse_cues`)."""
    return parse_cues(resource.read_text(encoding="utf-8"), language)


_SEPARATOR = r"[ \t\u00a0-]*"  # a space or hyphen in a cue: any of them, or nothing


def _squash(key: str) -> str:
    return key.replace(" ", "").replace("-", "")


def _trie_pattern(cues: Sequence[Cue]) -> str:
    """One regular expression for every cue, shaped as a trie (one branch per character).

    A plain alternation of a hundred cues is tried cue by cue at every word start, which made
    the rule detector ten times slower; the trie tries each character once.
    """
    trie: dict[str, dict] = {}
    for cue in cues:
        node = trie
        for ch in cue.key.replace("-", " "):
            node = node.setdefault(ch, {})
        ends = node.setdefault("", set())
        ends.add("suffix" if cue.suffix else ("word" if cue.key[-1].isalnum() else "any"))

    def build(node: dict) -> str:
        branches = []
        for ch in sorted(k for k in node if k):
            head = _SEPARATOR if ch == " " else re.escape(ch)
            branches.append(head + build(node[ch]))
        for end in sorted(node.get("", ())):
            branches.append({"suffix": r"\w*", "word": r"(?!\w)", "any": ""}[end])
        if len(branches) == 1:
            return branches[0]
        return "(?:" + "|".join(branches) + ")"

    return r"(?<![^\W_])" + build(trie)


# Between the cue and the value: up to three short words (``ending in``, ``no.``) and labels
# (``:``, ``#``, ``(``), on one line, with no digit.
_MAX_FILLER_WORDS = 3
_SPACE_RE = re.compile(r"[ \t\u00a0]*")
_PUNCT_RE = re.compile(r"[:#=()\[\]'\u2019-]+")
_WORD_RE = re.compile(r"[^\W\d_]{1,15}(\.?)")
#: A word ending in "." longer than this ends a sentence; shorter ones are "no.", "Nr.", "Tel.".
_MAX_ABBREVIATION = 4

# A date inside a cued value rejects it: a year, month and day in range, with digit boundaries
# on both sides. So neither the tail of a longer number (``12345/42/00`` holds ``2345/42/00``)
# nor a same-shape number with no such month (``5936/42/00``, a Polish driving licence) is a
# date (LAB-1433).
_MONTH = r"(?:0?[1-9]|1[0-2])"
_DAY = r"(?:0?[1-9]|[12]\d|3[01])"
_DATE_RE = re.compile(
    rf"(?<!\d)[12]\d{{3}}[-./ ]{{1,2}}{_MONTH}[-./ ]{{1,2}}{_DAY}(?!\d)"
    rf"|(?<!\d)(?:{_DAY}[./]{_MONTH}|{_MONTH}[./]{_DAY})[./](?:\d{{2}}|[12]\d{{3}})(?!\d)"
)
_CURRENCY_AFTER_RE = re.compile(r"[ \t\u00a0]?(?:Ft|HUF|forint|EUR|USD|GBP|CHF|€|\$|£)(?!\w)")
_CURRENCY_BEFORE = ("$", "€", "£")
#: How far back from a post-value cue a value may start (the longest shape plus separators).
_MAX_VALUE_LENGTH = 48


def _scan_value(text: str, pos: int, shape: Shape) -> int | None:
    """End of the value starting at ``pos``, or ``None`` if none of ``shape`` starts there."""
    n = len(text)
    i = pos
    if shape.plus and i < n and text[i] in "+(":
        i += 1
    separators = shape.separators + ("()" if shape.plus else "")

    def value_char(ch: str) -> bool:
        return ch.isascii() and (ch.isdigit() or (shape.letters and ch.isupper()))

    def digitish(ch: str) -> bool:
        return ch.isdigit() or (shape.plus and ch in "()")

    if i >= n or not value_char(text[i]):
        return None
    end = i
    while i < n:
        ch = text[i]
        if value_char(ch):
            i += 1
            end = i
            continue
        if ch not in separators:
            break
        j = i + 1
        if ch == ")" and j < n and text[j] in shape.separators and text[j] != " ":  # "(95)-76"
            j += 1
        if ch != " " and j < n and text[j] == " ":  # "- 30", ") 234": one space after
            j += 1
        if j >= n or not (value_char(text[j]) or (shape.plus and text[j] == "(")):
            break
        # A space only separates digit groups, never a value from the next word.
        if " " in text[i:j] and not (digitish(text[i - 1]) and digitish(text[j])):
            break
        i = j
    if shape.plus and text[pos:end].count("(") > text[pos:end].count(")"):
        if text[end : end + 1] != ")":
            return None
        end += 1
    # The value must end here, not run on into a word or a longer number.
    if end < n and (text[end].isalnum() or text[end] == "_"):
        return None
    if end + 1 < n and text[end] in "-./," and text[end + 1].isdigit():
        return None
    return end


def _shape_ok(value: str, shape: Shape) -> bool:
    digits = sum(ch.isdigit() for ch in value)
    chars = sum(ch.isalnum() for ch in value)
    (min_digits, max_digits), (min_chars, max_chars) = shape.digits, shape.chars
    return min_digits <= digits <= max_digits and min_chars <= chars <= max_chars


class CueMatcher:
    """Finds cued values in a text for a fixed set of cues (see the module docstring)."""

    def __init__(self, cues: Iterable[Cue]) -> None:
        by_key: dict[str, Cue] = {}
        for cue in cues:
            by_key.setdefault(_squash(cue.key), cue)  # the first pack listing a cue wins
        self.cues: tuple[Cue, ...] = tuple(by_key.values())
        self._exact = {key: cue for key, cue in by_key.items() if not cue.suffix}
        # Stems longest first, so "kártyaszám*" wins over "kártya*".
        self._stems = sorted(
            ((key, cue) for key, cue in by_key.items() if cue.suffix), key=lambda kc: -len(kc[0])
        )
        self._re = re.compile(_trie_pattern(self.cues)) if self.cues else None

    def _cue_for(self, matched: str) -> Cue | None:
        """The cue a match of the trie stands for: the longest that fits it."""
        squashed = re.sub(r"[ \t\u00a0-]", "", matched)
        exact = self._exact.get(squashed)
        if exact is not None:
            return exact
        return next((cue for key, cue in self._stems if squashed.startswith(key)), None)

    def __len__(self) -> int:
        return len(self.cues)

    def __repr__(self) -> str:
        return f"CueMatcher({len(self.cues)} cues)"

    def find(self, text: str) -> Iterator[_Hit]:
        """Every cued value in ``text`` (overlaps with validated hits are the caller's)."""
        if self._re is None:
            return
        matches = list(self._re.finditer(fold(text)))
        seen: set[tuple[int, int]] = set()
        for index, m in enumerate(matches):
            cue = self._cue_for(m.group())
            if cue is None or cue.entity_type is None:
                continue
            if cue.after:
                hit = self._value_before(text, m.start(), cue.entity_type)
            else:
                # The window ends where the next cue starts: that one names what follows.
                limit = matches[index + 1].start() if index + 1 < len(matches) else len(text)
                hit = self._value_after(text, m.end(), limit, cue.entity_type)
            if hit is not None and (hit.start, hit.end) not in seen:
                seen.add((hit.start, hit.end))
                yield hit

    def _value_before(self, text: str, cue_start: int, entity_type: EntityType) -> _Hit | None:
        """The value ending right before a post-value cue, spaces between (the longest one)."""
        shape = SHAPES[entity_type]
        end = cue_start
        while end > 0 and text[end - 1] in " \t\u00a0":
            end -= 1
        if end == cue_start or end == 0:
            return None
        # Walk back over the characters a value of this shape may hold, then take the
        # leftmost start whose value ends exactly at ``end``.
        allowed = shape.separators + ("+()" if shape.plus else "")
        lo = max(0, end - _MAX_VALUE_LENGTH)
        first = end
        while first > lo and (
            (text[first - 1].isascii() and text[first - 1].isalnum()) or text[first - 1] in allowed
        ):
            first -= 1
        for start in range(first, end):
            if start and (text[start - 1].isalnum() or text[start - 1] in "+("):
                continue
            if start >= 2 and text[start - 1] in "-./," and text[start - 2].isdigit():
                continue  # the tail of a longer number
            hit = self._value_at(text, start, shape, entity_type)
            if hit is None or hit.end != end:
                continue
            if entity_type is EntityType.PHONE and text[start] not in "+0(":
                return None
            if entity_type is EntityType.PHONE and text[start] == "(" and text[start + 1] != "0":
                return None
            return hit
        return None

    def _value_after(self, text: str, pos: int, limit: int, entity_type: EntityType) -> _Hit | None:
        shape = SHAPES[entity_type]
        words = 0
        while pos <= limit:
            pos = _SPACE_RE.match(text, pos).end()  # type: ignore[union-attr]  # matches ""
            if pos >= limit:
                return None
            hit = self._value_at(text, pos, shape, entity_type)
            if hit is not None:
                return hit
            punct = _PUNCT_RE.match(text, pos)
            if punct:
                pos = punct.end()
                continue
            word = _WORD_RE.match(text, pos)
            if word is None:
                return None  # a digit, a sentence mark or a line break: no value here
            words += 1
            if words > _MAX_FILLER_WORDS:
                return None
            if word.group(1) and len(word.group()) - 1 > _MAX_ABBREVIATION:
                return None  # "... telefon. Másnap": the sentence ended
            pos = word.end()
        return None

    @staticmethod
    def _value_at(text: str, start: int, shape: Shape, entity_type: EntityType) -> _Hit | None:
        if start and text[start - 1].isalnum():
            return None  # "Nr123": the value would start inside a word
        if text[max(0, start - 2) : start].strip().endswith(_CURRENCY_BEFORE):
            return None
        end = _scan_value(text, start, shape)
        if end is None:
            return None
        value = text[start:end]
        if not _shape_ok(value, shape) or _DATE_RE.search(value):
            return None
        if _CURRENCY_AFTER_RE.match(text, end):
            return None
        return _Hit(start, end, entity_type, CUED_SCORE)


def matcher_for(language: str, cue_sets: Sequence[tuple[str, Sequence[Cue]]]) -> CueMatcher:
    """A matcher over every pack's cues, the text language's own listed first (it wins)."""
    own = [cues for code, cues in cue_sets if code == language]
    others = [cues for code, cues in cue_sets if code != language]
    return CueMatcher(cue for cues in (*own, *others) for cue in cues)
