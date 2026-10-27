"""Language-pack lexicons: name and place lists for the generator and the rules (ADR 0009).

A lexicon is a weighted list of names or places that a language pack contributes, looked up
by kind::

    from pii_guard.lang import lexicon, postcode_index

    surnames = lexicon("surnames", "hu")        # Lexicon: entries + weights
    surnames.sample(rng)                          # frequency-weighted draw
    "Szeged" in lexicon("settlements", "hu")      # membership
    postcode_index("hu").consistent("6720", "Szeged")  # True

Kinds (:data:`LEXICON_KINDS`): ``given_names_m``, ``given_names_f``, ``surnames``,
``settlements``, ``postcodes``, ``street_types``, ``street_names``, plus pack-specific extras
(Hungarian: ``recent_given_names_m/f``, ``common_word_surnames``). A pack that doesn't provide
a kind raises :class:`LexiconUnavailable`; English is minimal on purpose (street types only).

The lists ship with the package (``pii_guard/lang/data/<code>/<kind>.tsv``) and are built by
``data/lexicons/fetch.py`` from public sources whose terms allow redistribution
(``data/lexicons/MANIFEST.md``). ``PII_GUARD_LEXICON_DIR`` points at a directory of local
overrides with the same layout (``<dir>/<code>/<kind>.tsv`` or ``<dir>/<kind>.tsv``), such as
the fetch-only lists the fetcher writes to ``data/lexicons/raw/derived/``: a file there
replaces the packaged one for that kind.

They are names and places, never person records.
"""

from __future__ import annotations

import bisect
import hashlib
import itertools
import os
import random
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from pathlib import Path

__all__ = [
    "LEXICON_KINDS",
    "Lexicon",
    "LexiconUnavailable",
    "PostcodeIndex",
    "available_kinds",
    "clear_cache",
    "lexicon",
    "lexicon_digest",
    "postcode_index",
]

#: The kinds every pack may provide (others are pack-specific extras).
LEXICON_KINDS: tuple[str, ...] = (
    "given_names_m",
    "given_names_f",
    "surnames",
    "settlements",
    "postcodes",
    "street_types",
    "street_names",
)

OVERRIDE_ENV = "PII_GUARD_LEXICON_DIR"


class LexiconUnavailable(LookupError):
    """The language pack doesn't provide this kind of lexicon."""


@dataclass(frozen=True, slots=True)
class Lexicon:
    """A weighted list: ``entries[i]`` with weight ``weights[i]``; ``rows`` keeps every
    column of the source file (settlements: county, KSH code, population)."""

    language: str
    kind: str
    entries: tuple[str, ...]
    weights: tuple[float, ...]
    rows: tuple[tuple[str, ...], ...] = ()
    source: str = "package"
    _folded: frozenset[str] = field(default=frozenset(), repr=False, compare=False)
    _cumulative: dict[float, tuple[float, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[str]:
        return iter(self.entries)

    def __contains__(self, value: object) -> bool:
        return isinstance(value, str) and value.casefold() in self._folded

    def __repr__(self) -> str:
        return f"Lexicon({self.language}/{self.kind}, {len(self.entries)} entries, {self.source})"

    def sample(self, rng: random.Random, temperature: float = 1.0) -> str:
        """One entry, drawn with probability proportional to ``weight ** temperature``.

        ``temperature=1`` follows the source frequencies, ``0`` is uniform; values in between
        flatten a long-tailed list (more distinct values in a small sample).
        """
        if not self.entries:
            raise LexiconUnavailable(f"{self.language}/{self.kind} is empty")
        cumulative = self._cumulative.get(temperature)
        if cumulative is None:
            cumulative = tuple(itertools.accumulate(w**temperature for w in self.weights))
            self._cumulative[temperature] = cumulative
        point = rng.random() * cumulative[-1]
        return self.entries[min(bisect.bisect_right(cumulative, point), len(self.entries) - 1)]


@dataclass(frozen=True, slots=True)
class PostcodeIndex:
    """Postcode -> settlements, and the reverse, for one language's postal system."""

    by_code: Mapping[str, frozenset[str]]
    by_settlement: Mapping[str, frozenset[str]]
    #: Settlements whose street-level postcodes are validated by structure rather than listed
    #: one by one (the gazetteer lists only their main code): folded name -> prefix. Budapest
    #: is ``1`` + district ``01``-``23`` + one digit; the other large cities share the first
    #: two digits of their main code (Debrecen ``40xx``).
    structural: Mapping[str, str] = field(default_factory=dict)

    def settlements(self, code: str) -> frozenset[str]:
        return self.by_code.get(code, frozenset())

    def consistent(self, code: str, settlement: str) -> bool:
        """True if ``code`` is a postcode of ``settlement`` (case-insensitive).

        A structural match doesn't count when the gazetteer assigns the code to another
        settlement (``6750`` is Algyő, not Szeged).
        """
        folded = settlement.casefold()
        listed = self.by_code.get(code, frozenset())
        if any(s.casefold() == folded for s in listed):
            return True
        prefix = self.structural.get(folded)
        if prefix is None or listed:
            return False
        return _structural_match(prefix, code)

    def known_settlement(self, settlement: str) -> bool:
        folded = settlement.casefold()
        return folded in self.by_settlement or folded in self.structural


def _structural_match(prefix: str, code: str) -> bool:
    if not (len(code) == 4 and code.isdigit() and code.startswith(prefix)):
        return False
    if prefix == "1":  # Budapest: the 2nd-3rd digits are the district
        return 1 <= int(code[1:3]) <= 23
    return True


# --- Loading ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _PackSpec:
    kinds: tuple[str, ...]
    #: kind -> files merged into it (later files add weight to earlier entries)
    merges: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    structural: Mapping[str, str] = field(default_factory=dict)


_PACKS: dict[str, _PackSpec] = {
    "hu": _PackSpec(
        kinds=(
            *LEXICON_KINDS,
            "recent_given_names_m",
            "recent_given_names_f",
            "common_word_surnames",
        ),
        merges={
            "given_names_m": ("given_names_m", "recent_given_names_m"),
            "given_names_f": ("given_names_f", "recent_given_names_f"),
        },
        structural={
            "budapest": "1",
            "debrecen": "40",
            "szeged": "67",
            "pécs": "76",
            "győr": "90",
            "miskolc": "35",
        },
    ),
    "en": _PackSpec(kinds=("street_types",)),
}


def _primary(language: str) -> str:
    return (language or "").strip().lower().replace("_", "-").split("-")[0]


def available_kinds(language: str) -> tuple[str, ...]:
    """The kinds ``language``'s pack provides (empty for a language without a pack)."""
    spec = _PACKS.get(_primary(language))
    return spec.kinds if spec else ()


def _override_dir() -> str:
    return os.environ.get(OVERRIDE_ENV, "")


def _read_lines(
    language: str, name: str, override: str, *, package: bool = True
) -> tuple[list[str], str]:
    if override:
        base = Path(override)
        for candidate in (base / language / f"{name}.tsv", base / f"{name}.tsv"):
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8").splitlines(), str(candidate)
    if not package:
        return [], "missing"
    resource = files("pii_guard.lang").joinpath("data", language, f"{name}.tsv")
    try:
        return resource.read_text(encoding="utf-8").splitlines(), "package"
    except FileNotFoundError:
        return [], "missing"


def _parse(lines: Sequence[str]) -> list[tuple[str, ...]]:
    return [tuple(line.split("\t")) for line in lines if line.strip() and not line.startswith("#")]


def _weight(row: tuple[str, ...], kind: str) -> float:
    if kind == "settlements":  # settlement, county, code, population
        return float(row[3]) if len(row) > 3 and row[3].isdigit() else 1.0
    if kind in {"postcodes", "common_word_surnames"}:
        return 1.0
    try:
        return float(row[1]) if len(row) > 1 else 1.0
    except ValueError:
        return 1.0


@cache
def _load(language: str, kind: str, override: str) -> Lexicon:
    spec = _PACKS.get(language)
    if spec is None or kind not in spec.kinds:
        raise LexiconUnavailable(f"no {kind!r} lexicon for language {language!r}")
    weights: dict[str, float] = {}
    rows: dict[str, tuple[str, ...]] = {}
    lines, source = _read_lines(language, kind, override, package=False)
    if source != "missing":
        parts = [(lines, source)]  # an override replaces the whole (merged) kind
    else:
        parts = [_read_lines(language, name, "") for name in spec.merges.get(kind, (kind,))]
    sources = sorted({src for _, src in parts if src != "missing"})
    for lines, _ in parts:
        for row in _parse(lines):
            key = row[0] if kind != "postcodes" else f"{row[0]}\t{row[1]}"
            weights[key] = weights.get(key, 0.0) + _weight(row, kind)
            rows.setdefault(key, row)
    if not weights:
        raise LexiconUnavailable(f"the {kind!r} lexicon for {language!r} is missing or empty")
    keys = sorted(weights)
    entries = tuple(keys)
    return Lexicon(
        language=language,
        kind=kind,
        entries=entries,
        weights=tuple(weights[k] for k in keys),
        rows=tuple(rows[k] for k in keys),
        source="+".join(sources),
        _folded=frozenset(e.casefold() for e in entries),
    )


def lexicon(kind: str, language: str = "hu") -> Lexicon:
    """The ``kind`` lexicon of ``language``'s pack (``"hu-HU"`` -> ``hu``).

    Raises :class:`LexiconUnavailable` when the pack doesn't provide it.
    """
    return _load(_primary(language), kind, _override_dir())


@cache
def _index(language: str, override: str) -> PostcodeIndex:
    table = _load(language, "postcodes", override)
    by_code: dict[str, set[str]] = {}
    by_settlement: dict[str, set[str]] = {}
    for row in table.rows:
        code, settlement = row[0], row[1]
        by_code.setdefault(code, set()).add(settlement)
        by_settlement.setdefault(settlement.casefold(), set()).add(code)
    spec = _PACKS[language]
    return PostcodeIndex(
        by_code={k: frozenset(v) for k, v in by_code.items()},
        by_settlement={k: frozenset(v) for k, v in by_settlement.items()},
        structural=dict(spec.structural),
    )


def postcode_index(language: str = "hu") -> PostcodeIndex:
    """Postcode <-> settlement lookups for ``language`` (from the ``postcodes`` lexicon)."""
    return _index(_primary(language), _override_dir())


def lexicon_digest(language: str, kinds: Sequence[str] | None = None) -> str:
    """A short SHA-256 over the lexicons in use (recorded with a generated corpus)."""
    digest = hashlib.sha256()
    for kind in kinds or available_kinds(language):
        lex = lexicon(kind, language)
        digest.update(f"{kind}:{lex.source}\n".encode())
        for entry, weight in zip(lex.entries, lex.weights, strict=True):
            digest.update(f"{entry}\t{weight}\n".encode())
    return digest.hexdigest()[:16]


def clear_cache() -> None:
    """Forget loaded lexicons (after changing ``PII_GUARD_LEXICON_DIR``)."""
    _load.cache_clear()
    _index.cache_clear()
