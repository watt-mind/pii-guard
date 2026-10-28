"""Hungarian pack: which detector name spans are trimmed to their stem (LAB-1174).

All names are fictional (ADR 0005).
"""

from __future__ import annotations

import pytest

from pii_guard.languages.hu.inflection import HungarianSuffixMatcher
from pii_guard.types import EntityType

E = EntityType
M = HungarianSuffixMatcher()
#: A stand-in for the pack's lexicons, so the cases don't depend on the lists' contents.
NAMES = frozenset(
    n.casefold()
    for n in (
        "Ottó", "Béla", "Zoltán", "Kornél", "Márton", "Simon", "Kelemen", "Gellért", "Klára",
        "Jakab", "Judit", "Kis", "Kiss", "Kovács", "Bálint", "Donát", "Máté",
    )
)  # fmt: skip


def is_name(word: str) -> bool:
    return word.casefold() in NAMES


@pytest.mark.parametrize(
    ("surface", "stem", "lemma", "suffix"),
    [
        # The ablative of the demo sample (LAB-1174), both vowel harmonies.
        ("Kerekes Ottótól", "Kerekes Ottó", "Kerekes Ottó", "tól"),
        ("KEREKES OTTÓTÓL", "KEREKES OTTÓ", "KEREKES OTTÓ", "TÓL"),
        ("Gyakorló Tihamértől", "Gyakorló Tihamér", "Gyakorló Tihamér", "től"),
        # A long case ending after an unknown name: no name ends in it.
        ("Gyakorló Tihamérnak", "Gyakorló Tihamér", "Gyakorló Tihamér", "nak"),
        ("Minta Ödönhöz", "Minta Ödön", "Minta Ödön", "höz"),
        ("Teszt Eleknek", "Teszt Elek", "Teszt Elek", "nek"),
        # A stem change: the vowel lengthens (strong) or the digraph doubles.
        ("Minta Hajnának", "Minta Hajná", "Minta Hajna", "nak"),
        ("Próba Szabolccsal", "Próba Szabolccs", "Próba Szabolcs", "al"),
        ("Minta Gergellyel", "Minta Gergelly", "Minta Gergely", "el"),
        # Short or ambiguous endings, applied because the lemma is a lexicon name.
        ("Minta Bélát", "Minta Bélá", "Minta Béla", "t"),
        ("Teszt Zoltánt", "Teszt Zoltán", "Teszt Zoltán", "t"),
        ("Próba Jakabbal", "Próba Jakab", "Próba Jakab", "bal"),
        ("Próba Kornélnak", "Próba Kornél", "Próba Kornél", "nak"),
        ("Kovácsnál", "Kovács", "Kovács", "nál"),
    ],
)
def test_inflected_names_split_at_the_stem(
    surface: str, stem: str, lemma: str, suffix: str
) -> None:
    split = M.confident_split(surface, E.PERSON, is_name)
    assert split is not None
    assert (split.stem, split.lemma, split.suffix) == (stem, lemma, suffix)
    assert split.stem + split.suffix == surface


@pytest.mark.parametrize(
    "surface",
    [
        # Names that only look inflected: the last word is a name itself.
        "Próba Márton",  # -on
        "Próba Kornél",  # -nél
        "Teszt Simon",  # -on
        "Minta Kelemen",  # -en
        "Teszt Gellért",  # -ért
        "Minta Klára",  # -ra
        "Teszt Bálint",  # -t
        "Minta Judit",  # -t
        "Teszt Máté",  # -é
        "Minta Donát",  # lengthened a + t
        # Unknown names with an ambiguous ending: left to the vault (a confirmed lemma).
        "Minta Petra",
        "Teszt Zsolt",
        "Teszt Tihamérért",
        "Minta Dórát",
        # Two lexicon readings (Kis + sel, Kiss + el): no guess.
        "Teszt Kissel",
        # Not a name ending: nothing to split.
        "Kerekes Ottó",
        "Gyakorló Tihamér",
    ],
)
def test_names_that_only_look_inflected_stay_whole(surface: str) -> None:
    assert M.confident_split(surface, E.PERSON, is_name) is None


@pytest.mark.parametrize(
    ("value", "entity_type"),
    [("anna.minta@example.com", E.EMAIL), ("Minta Kft-nek", E.ORGANIZATION)],
)
def test_only_person_values_are_trimmed(value: str, entity_type: EntityType) -> None:
    assert M.confident_split(value, entity_type, is_name) is None
