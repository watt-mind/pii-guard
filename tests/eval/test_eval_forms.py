"""Surface-form matching per language. All values are fictional."""

from __future__ import annotations

import pytest

from pii_guard.eval import (
    LanguageForms,
    find_surface_forms,
    language_forms,
    register_language_forms,
    surface_pattern,
)
from pii_guard.eval.forms import _FORMS
from pii_guard.types import EntityType

P = EntityType.PERSON


def _found(text: str, value: str, entity_type: EntityType = P, language: str = "hu") -> list[str]:
    return [text[s:e] for s, e in find_surface_forms(text, value, entity_type, language)]


def test_case_and_whitespace_insensitive() -> None:
    assert _found("írt TESZT   elek ma", "Teszt Elek") == ["TESZT   elek"]
    assert _found("Teszt\nElek", "Teszt Elek") == ["Teszt\nElek"]


def test_word_boundaries() -> None:
    assert _found("Elekes Tesztelek", "Elek") == []


def test_hungarian_suffixes_stay_outside_the_match() -> None:
    assert _found("Teszt Eleknek írtam", "Teszt Elek") == ["Teszt Elek"]
    assert _found("Teszt Elekkel", "Teszt Elek") == ["Teszt Elek"]
    assert _found("a@example.com-ra", "a@example.com", EntityType.EMAIL) == ["a@example.com"]


def test_hungarian_stem_changes_match_the_whole_word() -> None:
    assert _found("Minta Annának adtam", "Minta Anna") == ["Minta Annának"]
    assert _found("Gipsz Kováccsal", "Gipsz Kovács") == ["Gipsz Kováccsal"]
    assert _found("Próba Petének", "Próba Pete") == ["Próba Petének"]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        # A lengthened stem + the family / possessive chain (LAB-1342): the whole word.
        ("Teszt Hajnáéknál laktunk", "Teszt Hajna"),
        ("Teszt Hajnáéktól kértük", "Teszt Hajna"),
        ("Teszt Hajnáékat hívtuk", "Teszt Hajna"),
        ("Teszt Hajnáékkal mentünk", "Teszt Hajna"),
        ("Minta Kendééknek írtam", "Minta Kende"),
        ("Minta Hubáé a kulcs", "Minta Huba"),
        ("Minta Hubáéval szemben", "Minta Huba"),
        ("Teszt Hajnáéit vittük", "Teszt Hajna"),
        ("Próba Bencééké a ház", "Próba Bence"),
    ],
)
def test_hungarian_stacked_chain_after_a_lengthened_stem(text: str, value: str) -> None:
    (found,) = _found(text, value)
    assert text.startswith(found)
    assert found == text.split(" ")[0] + " " + text.split(" ")[1]


def test_hungarian_stacked_chain_on_an_unchanged_stem_stays_outside() -> None:
    assert _found("Kerekes Ottóéknál laktunk", "Kerekes Ottó") == ["Kerekes Ottó"]
    assert _found("Gyakorló Tihaméréké a ház", "Gyakorló Tihamér") == ["Gyakorló Tihamér"]


@pytest.mark.parametrize("text", ["Teszt Hajnáékszám nem szó", "Teszt Hajnáénekes nem szó"])
def test_hungarian_stacked_chain_needs_a_word_end(text: str) -> None:
    assert _found(text, "Teszt Hajna") == []


def test_english_is_exact_without_hungarian_suffixes() -> None:
    assert _found("Jane Examplenek", "Jane Example", language="en") == []
    assert _found("Jane Example's", "Jane Example", language="en") == ["Jane Example"]
    assert _found("Anna Samplenak", "Anna Sample", language="en-GB") == []


def test_unknown_language_falls_back_to_exact() -> None:
    forms = language_forms("xx")
    assert isinstance(forms, LanguageForms)
    assert forms.stem_variants("Anna", P) == []
    assert _found("Elekke", "Elek", language="xx") == []
    assert _found("Elek.", "Elek", language="xx") == ["Elek"]


@pytest.mark.parametrize(
    ("text", "value", "entity_type"),
    [
        ("adószám: 8123456789", "8123456789", EntityType.NATIONAL_ID_HU_TAX),
        ("TAJ 123-456-789", "123 456 789", EntityType.NATIONAL_ID_HU_TAJ),
        ("számla 1199999211111111", "11999992-11111111", EntityType.BANK_ACCOUNT),
        ("hívj: 06 30 123 4567", "+36 30 123 4567", EntityType.PHONE),
        ("hívj: +36-30-1234567", "06 30 123 4567", EntityType.PHONE),
        ("hívj: 30 123 4567", "06301234567", EntityType.PHONE),
        ("rendszám abc 123", "ABC-123", EntityType.VEHICLE_PLATE),
        ("card 4000-0000-0000-0002", "4000000000000002", EntityType.PAYMENT_CARD),
        ("card 4000000000000002", "4000 0000 0000 0002", EntityType.PAYMENT_CARD),
    ],
)
def test_codes_match_with_any_separators(text: str, value: str, entity_type: EntityType) -> None:
    assert _found(text, value, entity_type)


def test_hu_iban_also_matches_the_giro_number_inside() -> None:
    iban = "HU42 1177 7779 0000 0000 1234 5678"
    giro = "11777779-00000000-12345678"
    assert _found(f"utald ide: {giro}", iban, EntityType.BANK_ACCOUNT) == [giro]


def test_codes_do_not_match_inside_longer_digit_runs() -> None:
    assert _found("181234567890", "8123456789", EntityType.NATIONAL_ID_HU_TAX) == []


def test_register_language_forms() -> None:
    class Plural(LanguageForms):
        def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
            return "s"

    original = _FORMS.get("zz")
    register_language_forms(Plural("zz"))
    try:
        assert _found("two Bobs", "Bob", language="zz") == ["Bob"]
    finally:
        if original is None:
            _FORMS.pop("zz", None)
        surface_pattern.cache_clear()


def test_blank_value_rejected() -> None:
    with pytest.raises(ValueError, match="blank"):
        surface_pattern("  ", P, "hu")
