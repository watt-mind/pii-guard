"""English possessives in the vault (LAB-1096). All names are fictional (ADR 0005)."""

from __future__ import annotations

import pytest
from vault_helpers import span_of

from pii_guard.languages.en.inflection import EnglishPossessiveMatcher
from pii_guard.languages.hu.inflection import HungarianSuffixMatcher
from pii_guard.types import EntityType
from pii_guard.vault import PLACEHOLDER_RE, Vault, inflection_for
from pii_guard.vault.inflection import ExactMatcher

NAME = "Jane Example"


def _placeholder(masked: str) -> str:
    match = PLACEHOLDER_RE.search(masked)
    assert match is not None
    return match.group(0)


@pytest.mark.parametrize("language", ["en", "en-GB", "EN_us", "en-US"])
def test_english_matcher_by_primary_language(language: str) -> None:
    assert isinstance(inflection_for(language), EnglishPossessiveMatcher)


def test_region_fallback_for_other_languages() -> None:
    assert isinstance(inflection_for("hu-HU"), HungarianSuffixMatcher)
    assert isinstance(inflection_for("fi-FI"), ExactMatcher)  # no fi pack
    assert isinstance(inflection_for(""), ExactMatcher)


@pytest.mark.parametrize(
    ("value", "inflected", "suffix"),
    [
        ("Smith", "Smith's", "'s"),
        ("Smith", "Smith\u2019s", "\u2019s"),
        ("James", "James'", "'"),
    ],
)
def test_possessive_keeps_suffix_outside_placeholder(
    vault: Vault, value: str, inflected: str, suffix: str
) -> None:
    session = vault.session()
    text = f"{value} signed. Later {inflected} car was sold."
    masked = session.mask(text, [span_of(text, value, "PERSON")], language="en")
    placeholder = _placeholder(masked)
    assert masked == f"{placeholder} signed. Later {placeholder}{suffix} car was sold."
    assert value.casefold() not in masked.casefold().replace(placeholder.casefold(), "")
    assert session.unmask(masked) == text


def test_uppercase_possessive_is_masked(vault: Vault) -> None:
    # Matching is case-insensitive; unmasking restores the value as first detected.
    session = vault.session()
    text = "Smith signed. SMITH'S car was sold."
    masked = session.mask(text, [span_of(text, "Smith", "PERSON")], language="en")
    placeholder = _placeholder(masked)
    assert masked == f"{placeholder} signed. {placeholder}'S car was sold."


def test_possessive_on_first_occurrence_only(vault: Vault) -> None:
    # The detector reports "Smith" inside "Smith's"; later bare mentions are masked too.
    session = vault.session()
    text = "Smith's lease ends. Smith agreed."
    masked = session.mask(text, [span_of(text, "Smith", "PERSON")], language="en")
    placeholder = _placeholder(masked)
    assert masked == f"{placeholder}'s lease ends. {placeholder} agreed."
    assert session.unmask(masked) == text


@pytest.mark.parametrize("other", ["Smithson", "Smiths", "Smith_2", "XSmith", "Smithy's"])
def test_other_words_are_not_masked(vault: Vault, other: str) -> None:
    session = vault.session()
    text = f"Smith and {other}"
    masked = session.mask(text, [span_of(text, "Smith", "PERSON")], language="en")
    assert masked.endswith(f" and {other}")


def test_no_hungarian_suffixes_in_english(vault: Vault) -> None:
    session = vault.session()
    text = f"{NAME} wrote to {NAME}nek"
    masked = session.mask(text, [span_of(text, NAME, "PERSON")], language="en")
    assert masked.endswith(f"{NAME}nek")


def test_pattern_shape() -> None:
    pattern = EnglishPossessiveMatcher().suffix_pattern("Smith", EntityType.PERSON)
    assert pattern == "(?:['\u2019]s|['\u2019])"
