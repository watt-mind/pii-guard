"""Brand names the NER model calls a person: relabelled ``ORGANIZATION`` (LAB-1336).

The NER model sometimes tags a bare, capitalised company or product name as ``PERSON``:
``"Write a haiku about Meta"`` came out as ``"... about [[PERSON_3b9926]]"`` (score 0.97, so no
threshold helps). The upstream model then loses the topic of the prompt. Policy keeps
``ORGANIZATION`` by default (``policy.py``), so :func:`relabel_brands` turns such a span into an
``ORGANIZATION`` span rather than dropping it: the text stays readable upstream, and a policy
that masks organisations (``ORGANIZATION=mask``) still masks it.

The names are language-pack data, a ``brands.tsv`` next to ``cues.tsv``, one name per line
(``#`` starts a comment). The cross-language list (Meta, Llama, Google, OpenAI ...) is
``languages/brands.tsv``; each pack adds its own (``OTP Bank``, ``Deutsche Bahn``). Every pack's
names count for every text, as with cues: an English prompt about a Hungarian bank is common.

A ``PERSON`` span is relabelled only when **all** of these hold:

1. its text is exactly a listed name, ignoring case, optionally followed by a suffix the text
   language's inflection matcher allows for an organisation (``Meta's``, ``Google-nek``,
   ``Metas``). A longer span (``Meta Kovács``, ``Anna Apple``) is a person and stays one;
2. the name is not a given name or surname in any pack's name lexicons (a pack that ships the
   name as a surname protects it automatically);
3. no honorific stands right before or after it (``Ms. Apple``, ``Herr Meta``, ``Meta úr``);
4. no other ``PERSON`` span, and no capitalised word that a name lexicon knows, touches it
   (``Anna`` + ``Meta`` tagged as two spans, ``Kovács Meta``): it is part of a longer name.

Anything else passes untouched (fail closed). ``PII_GUARD_NER_BRANDS=false`` turns the
relabelling off. The list leaves out brands that are also common
personal names or surnames (Ford, Dell, Tesla, Siemens, Porsche, Disney, Claude, Alexa ...):
for those a missed brand costs readability, a missed person would cost a leak.

Only NER spans are checked. The rules never emit a person from these words, and the
known-values detector (a value the user registered) is a separate detector, so a user who
registers ``Meta`` as their own name still has it masked.
"""

from __future__ import annotations

import dataclasses
import os
import re
from collections.abc import Iterable, Sequence
from functools import cache
from importlib.resources import files
from importlib.resources.abc import Traversable

from pii_guard.types import EntityType, Span

__all__ = ["ENV_VAR", "HONORIFICS", "brand_names", "load_brands", "parse_brands", "relabel_brands"]

#: ``false`` / ``0`` / ``off`` turns the relabelling off (for comparison runs).
ENV_VAR = "PII_GUARD_NER_BRANDS"

#: Forms of address that make the next (or, Hungarian, previous) word a person's name.
#: Folded: lower case, no trailing full stop.
HONORIFICS: frozenset[str] = frozenset(
    {
        "mr", "mrs", "ms", "miss", "mx", "dr", "prof", "sir", "dame", "lord", "lady", "dear",
        "herr", "frau", "fräulein", "liebe", "lieber", "hr", "fr",
        "úr", "ur", "úrnak", "asszony", "asszonynak", "kisasszony", "néni", "bácsi", "né",
        "kedves", "tisztelt",
    }
)  # fmt: skip

_NAME_KINDS = (
    "surnames",
    "given_names_f",
    "given_names_m",
    "recent_given_names_f",
    "recent_given_names_m",
)
_WORD_BEFORE = re.compile(r"([^\W\d_][\w'\u2019-]*)\.?[ \t\u00a0]+$")
_WORD_AFTER = re.compile(r"^[ \t\u00a0]+([^\W\d_][\w'\u2019-]*)")
_GAP = re.compile(r"^[ \t\u00a0-]*$")


def parse_brands(text: str) -> tuple[str, ...]:
    """The names in a ``brands.tsv``: one per line, ``#`` comments, blank lines skipped.

    Raises :class:`ValueError` for a line with a tab (the file has one column) or a name
    without a letter.
    """
    names: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "\t" in line:
            raise ValueError(f"line {number}: one name per line, no tab")
        if not any(ch.isalpha() for ch in line):
            raise ValueError(f"line {number}: a name needs a letter")
        names.append(" ".join(line.split()))
    return tuple(names)


def load_brands(resource: Traversable) -> tuple[str, ...]:
    """Read a ``brands.tsv`` resource (see :func:`parse_brands`)."""
    return parse_brands(resource.read_text(encoding="utf-8"))


@cache
def brand_names() -> frozenset[str]:
    """Every listed name, case-folded: the shared list plus every pack's ``brands.tsv``."""
    from pii_guard.languages import packs

    names = set(load_brands(files("pii_guard.languages").joinpath("brands.tsv")))
    for pack in packs().values():
        if pack.brands is not None:
            names.update(load_brands(pack.brands))
    return frozenset(n.casefold() for n in names)


@cache
def _person_names() -> frozenset[str]:
    """Given names and surnames from every pack's lexicons, case-folded."""
    from pii_guard.lang import LexiconUnavailable, lexicon
    from pii_guard.languages import packs

    found: set[str] = set()
    for code, pack in packs().items():
        if pack.lexicons is None:
            continue
        for kind in _NAME_KINDS:
            if kind not in pack.lexicons.kinds:
                continue
            try:
                found.update(e.casefold() for e in lexicon(kind, code))
            except LexiconUnavailable:  # pragma: no cover - declared kinds ship with the pack
                continue
    return frozenset(found)


#: Endings every language allows after a brand: the English possessive, a hyphenated suffix.
_ALWAYS = r"['\u2019]s?|-[^\W\d_]{1,8}"


@cache
def _suffix_re(language: str, stem: str) -> re.Pattern[str]:
    """What may follow ``stem`` (folded) in ``language``: its inflection for an organisation."""
    from pii_guard.languages import get_pack

    pack = get_pack(language)
    inflection = pack.inflection if pack is not None else None
    extra = inflection.suffix_pattern(stem, EntityType.ORGANIZATION) if inflection else ""
    alternatives = _ALWAYS + (f"|{extra}" if extra else "")
    return re.compile(f"(?:{alternatives})", re.IGNORECASE)


@cache
def _changed_stems(language: str) -> dict[str, tuple[re.Pattern[str], ...]]:
    """Changed stems of the listed names (Hungarian ``meta`` -> ``metá`` before ``-ról``).

    ``changed stem (folded) -> the suffixes that must follow it``, from the language's
    inflection matcher (``variant_stems``); empty for a language whose stems don't change.
    """
    from pii_guard.languages import get_pack
    from pii_guard.vault.inflection import variant_stems

    pack = get_pack(language)
    if pack is None or pack.inflection is None:
        return {}
    persons = _person_names()
    found: dict[str, list[re.Pattern[str]]] = {}
    for name in brand_names():
        if name in persons:
            continue
        for stem, suffixes in variant_stems(pack.inflection, name, EntityType.ORGANIZATION):
            pattern = re.compile(f"(?:{suffixes})", re.IGNORECASE)
            found.setdefault(stem.casefold(), []).append(pattern)
    return {stem: tuple(patterns) for stem, patterns in found.items()}


def _clear() -> None:
    brand_names.cache_clear()
    _person_names.cache_clear()
    _suffix_re.cache_clear()
    _changed_stems.cache_clear()


def _is_brand(value: str, language: str) -> bool:
    """``value`` is a listed name, or a listed name plus an allowed suffix (``Meta's``,
    ``Metáról``)."""
    folded = " ".join(value.split()).casefold()
    names = brand_names()
    persons = _person_names()
    if folded in names:
        return folded not in persons
    changed = _changed_stems(language)
    for end in range(len(folded) - 1, 0, -1):
        stem, rest = folded[:end], folded[end:]
        if stem in names and stem not in persons and _suffix_re(language, stem).fullmatch(rest):
            return True
        if any(p.fullmatch(rest) for p in changed.get(stem, ())):
            return True
    return False


def _fold_word(word: str) -> str:
    return word.casefold().rstrip(".")


def _is_name_word(word: str) -> bool:
    return word[:1].isupper() and word.casefold().split("-")[0] in _person_names()


def _part_of_name(text: str, span: Span, persons: Sequence[Span]) -> bool:
    before = _WORD_BEFORE.search(text[max(0, span.start - 40) : span.start])
    after = _WORD_AFTER.match(text[span.end : span.end + 40])
    for match in (before, after):
        if match is None:
            continue
        word = match.group(1)
        if _fold_word(word) in HONORIFICS or _is_name_word(word):
            return True
    for other in persons:
        if other is span:
            continue
        gap = (
            text[other.end : span.start]
            if other.end <= span.start
            else text[span.end : other.start]
            if span.end <= other.start
            else None
        )
        if gap is None or _GAP.match(gap):
            return True  # overlapping or touching: one longer name
    return False


def relabel_brands(text: str, spans: Iterable[Span], language: str = "hu") -> list[Span]:
    """``spans`` with every NER ``PERSON`` span that is only a brand name made ``ORGANIZATION``.

    The span's offsets, text, score and detector are kept; only the type changes. Spans of
    other types pass untouched. The result is sorted like the detector's output, without
    duplicates (the model may also have proposed the same ``ORGANIZATION`` span).
    """
    found = list(spans)
    if os.environ.get(ENV_VAR, "").strip().lower() in {"0", "false", "off", "no"}:
        return found
    persons = [s for s in found if s.entity_type is EntityType.PERSON]
    if not persons:
        return found
    out: list[Span] = []
    for span in found:
        if (
            span.entity_type is EntityType.PERSON
            and _is_brand(span.text, language)
            and not _part_of_name(text, span, persons)
        ):
            span = dataclasses.replace(span, entity_type=EntityType.ORGANIZATION)
        out.append(span)
    return sorted(set(out), key=lambda s: (s.start, s.end, s.entity_type.value))


def _register() -> None:
    from pii_guard.languages import on_change

    on_change(_clear)


_register()
