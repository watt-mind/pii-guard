"""Occurrences in another form: Unicode form, ß/SS, layout, aliases, suffix casing (LAB-1208).

Every case was a reproduced review finding (``review-evidence/vault/probe1.py``, ``probe3.py``,
``probe4.py``). All values are fictional (ADR 0005).
"""

from __future__ import annotations

import re
import unicodedata

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from vault_helpers import TEST_KEY, span_of

from pii_guard.detect.known import merge_known
from pii_guard.languages.hu.inflection import HungarianSuffixMatcher
from pii_guard.types import EntityType
from pii_guard.vault import PLACEHOLDER_RE, Vault, VaultSession
from pii_guard.vault.fold import fold_text
from pii_guard.vault.known import known_values_from

P = EntityType.PERSON


def session(*, case_sensitive: bool = False) -> VaultSession:
    return Vault(TEST_KEY, case_sensitive_placeholders=case_sensitive).session()


def nfd(value: str) -> str:
    return unicodedata.normalize("NFD", value)


def placeholders(masked: str) -> list[str]:
    return [m.group(0) for m in PLACEHOLDER_RE.finditer(masked)]


def round_trip(
    text: str, value: str, *, language: str = "hu", case_sensitive: bool = False
) -> tuple[str, str]:
    s = session(case_sensitive=case_sensitive)
    masked = s.mask(text, [span_of(text, value, P)], language=language)
    return masked, s.unmask(masked)


# --- the folded view ----------------------------------------------------------------------


def test_fold_maps_back_to_the_original() -> None:
    text = f"Herr Weiß und {nfd('Kovács')}."
    folded = fold_text(text)
    assert folded.text == "herr weiss und kovács."
    start = folded.text.index("weiss")
    assert text[slice(*folded.to_original(start, start + 5))] == "Weiß"
    start = folded.text.index("kovács")
    assert text[slice(*folded.to_original(start, start + 6))] == nfd("Kovács")


def test_fold_of_ascii_text_keeps_offsets() -> None:
    folded = fold_text("TESZT Elek")
    assert folded.text == "teszt elek"
    assert folded.to_original(0, 5) == (0, 5)
    assert "TESZT" not in repr(folded)


# --- finding 1: Unicode form and ß/SS ---------------------------------------------------------


@pytest.mark.parametrize("case_sensitive", [False, True])
def test_nfd_occurrence_of_an_nfc_span_is_masked_and_round_trips(case_sensitive: bool) -> None:
    text = f"Kovács Béla írt. Később {nfd('Kovács Béla')} is írt."
    masked, back = round_trip(text, "Kovács Béla", case_sensitive=case_sensitive)
    assert "Kov" not in masked
    assert "Béla" not in masked and nfd("Béla") not in masked
    assert len(placeholders(masked)) == 2
    assert back == text


def test_an_all_nfd_text_keeps_one_placeholder() -> None:
    text = nfd("Kovács Béla írt. Később Kovács Béla is írt, Kovács Bélának.")
    masked, back = round_trip(text, nfd("Kovács Béla"))
    assert "Kov" not in masked
    assert len(set(placeholders(masked))) == 1
    assert back == text


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Herr Weiß kommt. HERR WEISS unterschreibt.", "Weiß"),
        ("Frau Strauß ruft an. Brief an FRAU STRAUSS.", "Strauß"),
        ("Herr WEISS kommt. Herr Weiß unterschreibt.", "WEISS"),
    ],
)
def test_sharp_s_and_ss_are_one_value(text: str, value: str) -> None:
    masked, back = round_trip(text, value, language="de")
    assert "WEISS" not in masked and "Weiß" not in masked
    assert "STRAUSS" not in masked and "Strauß" not in masked
    assert len(set(placeholders(masked))) == 1
    # Default mode restores the first-written form (the documented casing limitation) ...
    assert back.casefold() == text.casefold()
    # ... and case-sensitive placeholders round-trip exactly.
    _, exact = round_trip(text, value, language="de", case_sensitive=True)
    assert exact == text


def test_invisible_character_inside_an_occurrence_does_not_hide_it() -> None:
    zwsp = "\u200b"
    text = f"Teszt Elek írt. Később Te{zwsp}szt El{zwsp}ek is."
    masked, back = round_trip(text, "Teszt Elek")
    assert "El" not in masked
    assert back == text.replace(zwsp, "")  # restored as first written


# --- known values against another form -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value", "language"),
    [
        (nfd("Üdv, Gyakorló Tihamér!"), "Gyakorló Tihamér", "hu"),
        ("Brief an HERRN WEISS.", "Weiß", "de"),
        ("Beszéltem Varga Bernadettel tegnap.", "Varga Bernadett", "hu"),
        ("Kissel beszéltem, Kissé vált.", "Kiss", "hu"),
    ],
)
def test_known_values_are_found_in_another_form(text: str, value: str, language: str) -> None:
    s = session()
    s.known_values.add(known_values_from([{"value": value, "entity_type": "PERSON"}]))
    spans = merge_known(text, [], s.known_values, language)
    assert spans
    masked = s.mask(text, spans, language=language)
    assert value.split()[-1].casefold()[:4] not in fold_text(masked).text
    assert len(set(placeholders(masked))) == 1
    assert s.unmask(masked).casefold() == text.casefold()


# --- finding 2: Hungarian -val/-vel after a doubled consonant -----------------------------------


@pytest.mark.parametrize(
    ("text", "value", "expected_suffixes"),
    [
        ("Kiss úr írt. Kissel beszéltem.", "Kiss", ["", "el"]),
        ("Varga Bernadett írt. Varga Bernadettel beszéltem.", "Varga Bernadett", ["", "el"]),
        ("Szabó Mariann írt. Szabó Mariannal beszéltem.", "Szabó Mariann", ["", "al"]),
        ("Varga Bernadett írt. Varga Bernadetté vált.", "Varga Bernadett", ["", "é"]),
        ("Kovács úr írt. Kováccsal beszéltem.", "Kovács", ["", "al"]),
    ],
)
def test_doubled_final_consonant_takes_val_without_a_third_letter(
    text: str, value: str, expected_suffixes: list[str]
) -> None:
    s = session()
    masked = s.mask(text, [span_of(text, value, P)])
    (placeholder,) = set(placeholders(masked))
    found = [masked[m.end() :].split(" ")[0].rstrip(".") for m in PLACEHOLDER_RE.finditer(masked)]
    assert found == expected_suffixes
    assert masked.count(placeholder) == 2
    assert s.unmask(masked) == text


def test_suffix_pattern_and_splits_for_a_doubled_final_consonant() -> None:
    hu = HungarianSuffixMatcher()
    pattern = re.compile(hu.suffix_pattern("Kiss", P))
    assert pattern.fullmatch("el") and pattern.fullmatch("al") and pattern.fullmatch("é")
    assert not pattern.fullmatch("sel")
    readings = [(x.lemma, x.suffix) for x in hu.splits("Varga Bernadettel", P)]
    assert ("Varga Bernadett", "el") in readings
    assert ("Varga Bernadet", "tel") in readings  # still a reading: Bernadet is a lemma too
    assert ("Kiss", "el") in [(x.lemma, x.suffix) for x in hu.splits("Kissel", P)]
    # Single consonants still double (Elek -> Elekkel) and restore is unchanged.
    assert ("Elek", "kel") in [(x.lemma, x.suffix) for x in hu.splits("Elekkel", P)]
    assert hu.restore("Varga Bernadett", "vel", P) == "Varga Bernadettel"
    assert hu.restore("Kiss", "val", P) == "Kissal"


def test_a_confirmed_doubled_lemma_is_chosen_for_the_inflected_span() -> None:
    text = "Varga Bernadett írt. Varga Bernadettel beszéltem."
    s = session()
    spans = [span_of(text, "Varga Bernadett", P), span_of(text, "Varga Bernadettel", P)]
    masked = s.mask(text, spans)
    assert masked.endswith("]]el beszéltem.")
    assert len(set(placeholders(masked))) == 1
    assert s.unmask(masked) == text


# --- finding 3: alias forms are restored as written ---------------------------------------------


@pytest.mark.parametrize("case_sensitive", [False, True])
def test_alias_form_in_the_same_text_restores_as_written(case_sensitive: bool) -> None:
    text = "Láttam Teszt Zoltánt. TESZT ZOLTÁN is írt."
    masked, back = round_trip(text, "Teszt Zoltánt", case_sensitive=case_sensitive)
    assert "ZOLT" not in masked and "Zolt" not in masked
    assert back == text


@pytest.mark.parametrize("case_sensitive", [False, True])
def test_alias_form_in_a_later_call_restores_as_written(case_sensitive: bool) -> None:
    s = session(case_sensitive=case_sensitive)
    first = "Láttam Minta Kendét."
    m1 = s.mask(first, [span_of(first, "Minta Kendét", P)])
    second = "Minta Kende telefonált."
    m2 = s.mask(second, [])
    assert "Kend" not in m2
    assert s.unmask(m1) == first
    assert s.unmask(m2) == second
    # The alias got an entry of its own; a model-added suffix re-inflects it.
    (alias_placeholder,) = placeholders(m2)
    assert s.unmask(f"{alias_placeholder}nek") == "Minta Kendének"


# --- finding 4: whitespace variants and suffix casing -------------------------------------------


@pytest.mark.parametrize("case_sensitive", [False, True])
def test_line_break_inside_an_occurrence_is_restored(case_sensitive: bool) -> None:
    text = "Teszt Elek írt.\nAláírás: Teszt\nElek"
    masked, back = round_trip(text, "Teszt Elek", case_sensitive=case_sensitive)
    assert "Elek" not in masked
    assert back == text


def test_extra_spaces_share_the_placeholder() -> None:
    text = "Teszt Elek írt. Teszt  Elek is."
    masked, back = round_trip(text, "Teszt Elek")
    assert len(set(placeholders(masked))) == 1
    assert back == "Teszt Elek írt. Teszt Elek is."


def test_same_suffix_in_another_casing_round_trips_in_default_mode() -> None:
    text = "Teszt Eleknek írtam, és TESZT ELEKNEK is."
    masked, back = round_trip(text, "Teszt Elek")
    assert len(set(placeholders(masked))) == 1
    assert back == text


def test_model_suffix_in_an_unseen_casing_uses_the_folded_stem() -> None:
    s = session()
    text = "Teszt Eleknek írtam."
    masked = s.mask(text, [span_of(text, "Teszt Elek", P)])
    (placeholder,) = placeholders(masked)
    assert s.unmask(f"{placeholder}Nek") == "Teszt ElekNek"


# --- property: mask -> unmask over forms of one value --------------------------------------------

NAMES = ["Teszt Elek", "Próba Zsuzsanna", "Kovács Béla", "Varga Bernadett", "Gyakorló Tihamér"]
SUFFIXES = ["", "nak", "nek", "ról", "ért"]


def _form(value: str, how: str) -> str:
    if how == "nfd":
        return nfd(value)
    if how == "upper":
        return value.upper()
    if how == "lower":
        return value.lower()
    if how == "newline":
        return value.replace(" ", "\n", 1)
    return value


@settings(max_examples=150, deadline=None)
@given(
    name=st.sampled_from(NAMES),
    forms=st.lists(
        st.tuples(
            st.sampled_from(["same", "nfd", "upper", "lower", "newline"]),
            st.sampled_from(SUFFIXES),
        ),
        min_size=1,
        max_size=4,
    ),
    case_sensitive=st.booleans(),
)
def test_every_form_is_masked_and_round_trips(
    name: str, forms: list[tuple[str, str]], case_sensitive: bool
) -> None:
    parts = [f"{name} írt."]
    for how, suffix in forms:
        parts.append(f"Aztán {_form(name, how)}{suffix} is.")
    text = " ".join(parts)
    s = session(case_sensitive=case_sensitive)
    masked = s.mask(text, [span_of(text, name, P)])
    surname = fold_text(name.split()[0]).text
    assert surname not in fold_text(masked).text
    back = s.unmask(masked)
    if case_sensitive or all(how in ("same", "nfd", "newline") for how, _ in forms):
        assert back == text
    else:  # default mode: a casing variant restores the first-written casing
        assert fold_text(back).text == fold_text(text).text
