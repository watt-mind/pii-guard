"""Language-pack lexicons (pii_guard.lang): lookup, sampling, overrides, postcode index."""

# Seeded, reproducible sampling: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest

from pii_guard import lang
from pii_guard.lang import (
    LEXICON_KINDS,
    LexiconUnavailable,
    available_kinds,
    lexicon,
    lexicon_digest,
    postcode_index,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(lang.OVERRIDE_ENV, raising=False)
    lang.clear_cache()
    yield
    lang.clear_cache()


@pytest.mark.parametrize("kind", LEXICON_KINDS)
def test_hungarian_pack_provides_every_kind(kind: str) -> None:
    lex = lexicon(kind, "hu")
    assert len(lex) > 0 and lex.source == "package"
    assert len(lex.entries) == len(lex.weights) == len(lex.rows)
    assert all(w > 0 for w in lex.weights)


def test_list_sizes_are_what_the_manifest_says() -> None:
    assert len(lexicon("settlements")) == 3155
    assert len(lexicon("postcodes")) == 3632
    assert len(lexicon("street_names")) == 100
    assert len(lexicon("surnames")) >= 200
    assert len(lexicon("given_names_m")) >= 100 and len(lexicon("given_names_f")) >= 100


def test_language_tags_and_membership_are_normalised() -> None:
    settlements = lexicon("settlements", "hu-HU")
    assert "Szeged" in settlements and "szeged" in settlements and "SZEGED" in settlements
    assert "Szegedke" not in settlements and 42 not in settlements
    assert "Budapest" in settlements
    assert "Szeged" in list(settlements)


def test_merged_given_names_add_the_recent_ones() -> None:
    merged = set(lexicon("given_names_f"))
    assert set(lexicon("recent_given_names_f")) <= merged
    assert "Zsófia" in merged and "Mária" in merged


def test_settlement_rows_keep_county_and_population() -> None:
    lex = lexicon("settlements")
    row = lex.rows[lex.entries.index("Szeged")]
    assert row[1] == "Csongrád-Csanád" and int(row[3]) > 100_000
    assert lex.weights[lex.entries.index("Budapest")] > lex.weights[lex.entries.index("Szeged")]


def test_english_is_minimal() -> None:
    assert available_kinds("en-GB") == ("street_types",)
    assert len(lexicon("street_types", "en")) > 0
    with pytest.raises(LexiconUnavailable):
        lexicon("surnames", "en")
    with pytest.raises(LexiconUnavailable):
        lexicon("surnames", "xx")
    assert available_kinds("xx") == ()


def test_sampling_is_seeded_and_frequency_weighted() -> None:
    lex = lexicon("settlements")
    a = [lex.sample(random.Random(7)) for _ in range(3)]
    b = [lex.sample(random.Random(7)) for _ in range(3)]
    assert a == b
    rng = random.Random(1)
    draws = Counter(lex.sample(rng) for _ in range(2000))
    assert draws.most_common(1)[0][0] == "Budapest"


def test_temperature_flattens_the_long_tail() -> None:
    lex = lexicon("settlements")
    rng = random.Random(3)
    weighted = {lex.sample(rng, 1.0) for _ in range(200)}
    rng = random.Random(3)
    flat = {lex.sample(rng, 0.0) for _ in range(200)}
    assert len(flat) > len(weighted)


def test_an_empty_lexicon_cannot_be_sampled() -> None:
    empty = lang.Lexicon("hu", "surnames", (), ())
    with pytest.raises(LexiconUnavailable):
        empty.sample(random.Random(0))
    assert "0 entries" in repr(empty)


def test_override_directory_replaces_a_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(lang.OVERRIDE_ENV, str(FIXTURES / "overrides"))
    lang.clear_cache()
    surnames = lexicon("surnames")
    assert list(surnames) == ["Próbanév", "Tesztnév"]
    assert surnames.source.endswith("surnames.tsv")
    # a file at the top of the directory applies to every language
    assert postcode_index().consistent("9999", "Próbafalva")
    # kinds without an override keep the packaged list
    assert lexicon("settlements").source == "package"


def test_digest_is_stable_and_tracks_the_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    first = lexicon_digest("hu")
    assert first == lexicon_digest("hu") and len(first) == 16
    monkeypatch.setenv(lang.OVERRIDE_ENV, str(FIXTURES / "overrides"))
    lang.clear_cache()
    assert lexicon_digest("hu") != first
    assert lexicon_digest("hu", ["street_types"]) != lexicon_digest("hu", ["settlements"])


# --- Postcode index ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "settlement"),
    [
        ("6720", "Szeged"),  # listed main code
        ("6724", "Szeged"),  # street-level code, by structure
        ("1051", "Budapest"),  # district 05
        ("1239", "budapest"),  # district 23, case-insensitive
        ("4026", "Debrecen"),
        ("7624", "Pécs"),
        ("9022", "Győr"),
        ("3530", "Miskolc"),
        ("6750", "Algyő"),
        ("3300", "Eger"),
    ],
)
def test_consistent_postcodes(code: str, settlement: str) -> None:
    assert postcode_index("hu").consistent(code, settlement)


@pytest.mark.parametrize(
    ("code", "settlement"),
    [
        ("6750", "Szeged"),  # Algyő's code, though it shares Szeged's prefix
        ("1241", "Budapest"),  # no 24th district
        ("1001", "Budapest"),  # no district 00
        ("3300", "Szeged"),  # Eger's code
        ("6720", "Eger"),
        ("12345", "Budapest"),
        ("1o51", "Budapest"),
        ("6720", "Nemlétező"),
    ],
)
def test_inconsistent_postcodes(code: str, settlement: str) -> None:
    assert not postcode_index("hu").consistent(code, settlement)


def test_index_lookups() -> None:
    index = postcode_index("hu")
    assert "Eger" in index.settlements("3300")
    assert index.settlements("0000") == frozenset()
    assert index.known_settlement("Eger") and index.known_settlement("budapest")
    assert not index.known_settlement("Nemlétező")
