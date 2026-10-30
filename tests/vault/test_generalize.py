"""Context generalization (LAB-1152): gender, age and inflection clues around placeholders."""

from __future__ import annotations

import pytest

from pii_guard.types import EntityType, Span
from pii_guard.vault import Vault
from pii_guard.vault.generalize import RULES, generalize_context

P = "[[PERSON_7f3a9c]]"
E = "[[EMAIL_0b1c2d]]"


@pytest.mark.parametrize(
    ("text", "language", "expected"),
    [
        (f"Dear Ms {P},", "en", f"Dear {P},"),
        (f"Hi Mr. {P}, thanks", "en", f"Hi {P}, thanks"),
        (f"Seller: Mrs {P}", "en", f"Seller: {P}"),
        (f"I miss {P}", "en", f"I miss {P}"),  # lower-case "miss" is a verb
        (f"Sehr geehrte Frau {P},", "de", f"Guten Tag {P},"),
        (f"Sehr geehrter Herr {P},", "de", f"Guten Tag {P},"),
        (f"Lieber {P},", "de", f"Hallo {P},"),
        (f"an Herrn {P} senden", "de", f"an {P} senden"),
        (f"Tisztelt {P} úr!", "hu", f"Tisztelt {P}!"),
        (f"Átadtam {P} úrnak.", "hu", f"Átadtam {P}nak."),
        (f"Kedves {P} hölgy, köszönjük", "hu", f"Kedves {P}, köszönjük"),
        (f"{P} asszony aláírta", "hu", f"{P} aláírta"),
        (f"Vevő: {P}né", "hu", f"Vevő: {P}"),
    ],
)
def test_gender_titles(text: str, language: str, expected: str) -> None:
    result = generalize_context(text, language)
    assert result.text == expected
    assert result.rewrites["gender_title"] == (text != expected)


def test_titles_only_next_to_person_placeholders() -> None:
    text = "Ms Smith wrote to Frau Müller and [[ORGANIZATION_1a2b]] Mr"
    assert generalize_context(text, "en").text == text


@pytest.mark.parametrize(
    ("text", "language", "expected"),
    [
        ("she is 42 years old", "en", "she is 40-49 years old"),
        ("a 37-year-old tenant", "en", "a 30-39-year-old tenant"),
        ("a 7 éves fia", "hu", "a 0-9 éves fia"),
        ("ist 65 Jahre alt", "de", "ist 60-69 Jahre alt"),
        ("born in 1984, 2026 years old", "en", "born in 1984, 2026 years old"),
        ("room 42 is free", "en", "room 42 is free"),
    ],
)
def test_age_coarsened_to_decade(text: str, language: str, expected: str) -> None:
    result = generalize_context(text, language)
    assert result.text == expected
    assert result.rewrites["age"] == (text != expected)


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [
        ("nek", "nak"),
        ("nak", "nak"),
        ("ről", "ról"),
        ("nél", "nál"),
        ("höz", "hoz"),
        ("et", "ot"),
        ("öt", "ot"),
        ("ot", "ot"),
        ("t", "t"),
        ("csal", "val"),
        ("sel", "val"),
        ("val", "val"),
        ("vel", "val"),
        ("ért", "ért"),
        ("ig", "ig"),
    ],
)
def test_hungarian_suffix_harmony_hidden(suffix: str, expected: str) -> None:
    result = generalize_context(f"Átadtam {P}{suffix} a kulcsot.", "hu")
    assert result.text == f"Átadtam {P}{expected} a kulcsot."
    assert result.rewrites["hu_harmony"] == (suffix != expected)


def test_harmony_only_for_hungarian_person_placeholders() -> None:
    assert generalize_context(f"thanks {P}et", "en").text == f"thanks {P}et"
    assert generalize_context(f"írj {P}nek", "hu-HU").text == f"írj {P}nak"
    assert generalize_context(f"írj a {E}re", "hu").text == f"írj a {E}re"


@pytest.mark.parametrize(
    ("lemma", "suffix", "expected"),
    [
        ("Teszt Elek", "nak", "Teszt Eleknek"),
        ("Teszt Elek", "nek", "Teszt Eleknek"),
        ("Minta Ödön", "hoz", "Minta Ödönhöz"),
        ("Minta Ödön", "ot", "Minta Ödönöt"),
        ("Próba Zsófi", "nak", "Próba Zsófinak"),
        ("Próba Zsófi", "nek", "Próba Zsófinek"),  # neutral i after a back vowel: as written
        ("Próba Zsuzsanna", "nek", "Próba Zsuzsannának"),
        ("Teszt Elek", "val", "Teszt Elekkel"),
        ("Minta Kovács", "vel", "Minta Kováccsal"),
        ("Minta Kitti", "nak", "Minta Kittinek"),
        ("Minta Emil", "ért", "Minta Emilért"),
        ("Kiss Béláné", "nek", "Kiss Bélánénak"),
        ("Minta Kovácsné", "nek", "Minta Kovácsnénak"),
        ("Teszt Péterné", "nak", "Teszt Péternének"),
    ],
)
def test_hungarian_restore_reharmonizes(lemma: str, suffix: str, expected: str) -> None:
    from pii_guard.vault.inflection import inflection_for, restore

    assert restore(inflection_for("hu"), lemma, suffix, EntityType.PERSON) == expected


def test_placeholders_never_change_and_report_has_counts_only() -> None:
    text = f"Dear Ms {P}, mail {E}. She is 42 years old."
    result = generalize_context(text, "en")
    assert set(result.rewrites) == set(RULES)
    assert result.rewrites == {"gender_title": 1, "age": 1, "hu_harmony": 0}
    assert result.changed
    assert not generalize_context("plain text", "en").changed


def test_answers_still_unmask_after_generalization() -> None:
    vault = Vault(b"k" * 32)
    session = vault.session()
    text = "Átadtam Teszt Eleknek a kulcsot."
    span = Span(8, 18, EntityType.PERSON, "Teszt Elek", 1.0, "test")
    masked = session.mask(text, [span], language="hu")
    assert masked.endswith("nek a kulcsot.")
    generalized = generalize_context(masked, "hu").text
    assert "nak a kulcsot." in generalized
    # The upstream model answers with the generalized form; the vault re-inflects it.
    assert session.unmask(generalized) == text
