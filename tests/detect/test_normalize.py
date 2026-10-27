"""Normalisation of obfuscated text before detection, and the offset map back."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard.detect.normalize import (
    INVISIBLE_CHARS,
    LOOKALIKES,
    NormalizedText,
    normalize_for_detection,
)

ZWSP, ZWJ, SHY, BOM, RLO = "\u200b", "\u200d", "\u00ad", "\ufeff", "\u202e"
CYR_A, CYR_E, GREEK_O = "\u0430", "\u0435", "\u039f"


def test_plain_text_is_unchanged() -> None:
    norm = normalize_for_detection("Teszt Elek, 1051 Budapest")
    assert not norm.changed
    assert norm.text == norm.original
    assert norm.origin == tuple(range(len(norm.text)))


def test_empty_text() -> None:
    norm = normalize_for_detection("")
    assert norm.text == "" and norm.origin == () and not norm.changed


def test_invisible_characters_are_dropped_and_mapped_back() -> None:
    text = f"Bérlő: {BOM}Mol{SHY}nár Ka{ZWSP}talin, tel."
    norm = normalize_for_detection(text)
    assert norm.text == "Bérlő: Molnár Katalin, tel."
    start = norm.text.index("Molnár Katalin")
    o_start, o_end = norm.to_original(start, start + len("Molnár Katalin"))
    # The span covers the invisible characters inside the value (not the BOM before it).
    assert text[o_start:o_end] == f"Mol{SHY}nár Ka{ZWSP}talin"


def test_bidi_controls_are_dropped() -> None:
    norm = normalize_for_detection(f"name: {RLO}Jane Example")
    assert norm.text == "name: Jane Example"


def test_lookalikes_fold_inside_latin_words() -> None:
    text = f"Kedves T{CYR_A}k{CYR_A}cs B{CYR_E}nce és {GREEK_O}rbán Sára!"
    norm = normalize_for_detection(text)
    assert norm.text == "Kedves Takacs Bence és Orbán Sára!"
    assert len(norm.text) == len(text)  # one for one: offsets do not move


def test_pure_cyrillic_and_greek_words_are_left_alone() -> None:
    text = (
        "\u041f\u0440\u0438\u0432\u0435\u0442, \u043c\u0438\u0440. "  # Russian
        "\u039a\u03b1\u03bb\u03b7\u03bc\u03ad\u03c1\u03b1 \u03ba\u03cc\u03c3\u03bc\u03b5. "  # Greek
        "\u041c\u043e\u0441\u043a\u0432\u0430"
    )
    assert normalize_for_detection(text).text == text


def test_lookalike_next_to_invisible_character_in_one_word() -> None:
    text = f"T{ZWSP}{CYR_E}szt"
    norm = normalize_for_detection(text)
    assert norm.text == "Teszt"
    assert norm.to_original(0, 5) == (0, len(text))


def test_fullwidth_and_mathematical_letters_fold() -> None:
    fullwidth = "\uff2a\uff41\uff4e\uff45"
    bold = "\U0001d404\U0001d431\U0001d41a\U0001d426\U0001d429\U0001d425\U0001d41e"
    text = f"{fullwidth} {bold}"
    assert normalize_for_detection(text).text == "Jane Example"


def test_email_with_zero_width_joiner() -> None:
    text = f"write to agatha.sam{ZWJ}plewood@example.com today"
    norm = normalize_for_detection(text)
    value = "agatha.samplewood@example.com"
    start = norm.text.index(value)
    o_start, o_end = norm.to_original(start, start + len(value))
    assert text[o_start:o_end] == f"agatha.sam{ZWJ}plewood@example.com"


def test_spoofed_placeholder_wrappers_are_blanked() -> None:
    text = "Customer: [[PERSON_Florian Testley]], ref [[PERSON_3fa2c1]] and [[ADDRESS_91bc]]."
    norm = normalize_for_detection(text)
    blank = " " * len("[[PERSON_")
    assert norm.text == (
        f"Customer: {blank}Florian Testley  , ref [[PERSON_3fa2c1]] and [[ADDRESS_91bc]]."
    )
    assert len(norm.text) == len(text)
    start = norm.text.index("Florian")
    assert text[slice(*norm.to_original(start, start + 15))] == "Florian Testley"


def test_to_original_rejects_bad_spans() -> None:
    norm = normalize_for_detection(f"a{ZWSP}b")
    for start, end in ((0, 0), (1, 0), (-1, 1), (0, 3)):
        with pytest.raises(ValueError):
            norm.to_original(start, end)


def test_tables_are_consistent() -> None:
    assert all(len(k) == 1 and v.isascii() and v.isalpha() for k, v in LOOKALIKES.items())
    assert not set(LOOKALIKES) & INVISIBLE_CHARS
    assert isinstance(normalize_for_detection("x"), NormalizedText)


_ALPHABET = st.sampled_from(
    [*"abcTesztÉé .,@\n", *sorted(INVISIBLE_CHARS), *list(LOOKALIKES)[:6], "\u0436"]
)


@given(st.lists(_ALPHABET, max_size=40).map("".join))
def test_mapping_invariants(text: str) -> None:
    norm = normalize_for_detection(text)
    assert len(norm.origin) == len(norm.text) <= len(text)
    assert list(norm.origin) == sorted(set(norm.origin))
    assert not set(norm.text) & INVISIBLE_CHARS
    for i, c in enumerate(norm.text):
        original = text[norm.origin[i]]
        assert c == original or LOOKALIKES.get(original) == c
    for start in range(len(norm.text)):
        for end in range(start + 1, len(norm.text) + 1):
            o_start, o_end = norm.to_original(start, end)
            # Every visible character of the original span is in the normalised span.
            visible = [c for c in text[o_start:o_end] if c not in INVISIBLE_CHARS]
            assert len(visible) == end - start
