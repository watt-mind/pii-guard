"""Casing of value occurrences: one placeholder by default, one per casing class on request.

All values are fictional (ADR 0005).
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from vault_helpers import TEST_KEY, span_of

from pii_guard.config import Settings
from pii_guard.types import EntityType
from pii_guard.vault import PLACEHOLDER_RE, StreamUnmasker, Vault, VaultSession
from pii_guard.vault.placeholders import casing_class, derive_id, format_placeholder

NAME = "Teszt Elek"
SELLER_TEXT = "Az Eladó fizet. Az eladó átveszi."
CAPS_TEXT = "TESZT ELEK és Teszt Elek."


def session(*, case_sensitive: bool = False) -> VaultSession:
    return Vault(TEST_KEY, case_sensitive_placeholders=case_sensitive).session()


def placeholders(masked: str) -> list[str]:
    return [m.group(0) for m in PLACEHOLDER_RE.finditer(masked)]


# --- casing_class --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("TESZT ELEK", "upper"),
        ("teszt elek", "lower"),
        ("Teszt Elek", "mixed"),
        ("Teszt ELEK", "mixed"),
        ("HU12 ABCD", "upper"),
        ("1234 5678", "mixed"),
    ],
)
def test_casing_class(value: str, expected: str) -> None:
    assert casing_class(value) == expected


def test_casing_variant_id_differs_and_default_id_is_unchanged() -> None:
    args = (TEST_KEY, "s_1", EntityType.PERSON, "teszt elek")
    assert derive_id(*args) == derive_id(*args, casing="")
    assert derive_id(*args, casing="upper") != derive_id(*args)
    assert derive_id(*args, casing="upper") != derive_id(*args, casing="lower")


# --- default: one placeholder per value -------------------------------------------------------


def test_default_lowercase_occurrence_shares_placeholder_and_restores_canonical() -> None:
    s = session()
    masked = s.mask(SELLER_TEXT, [span_of(SELLER_TEXT, "Eladó", "PERSON")])
    found = placeholders(masked)
    assert len(found) == 2 and len(set(found)) == 1
    assert "eladó" not in masked.casefold()
    # Documented limitation: the lowercase occurrence comes back as first written.
    assert s.unmask(masked) == "Az Eladó fizet. Az Eladó átveszi."


def test_default_all_caps_occurrence_shares_placeholder_and_restores_canonical() -> None:
    s = session()
    masked = s.mask(CAPS_TEXT, [span_of(CAPS_TEXT, NAME, "PERSON")])
    assert len(set(placeholders(masked))) == 1
    assert masked.count("[[PERSON_") == 2
    assert s.unmask(masked) == "Teszt Elek és Teszt Elek."


def test_default_id_card_caps_name_matches_prose_name_across_requests() -> None:
    # An ID card read gives "TESZT ELEK"; later prose writes "Teszt Elek" (and inflects it).
    s = session()
    card = "Név: TESZT ELEK"
    card_masked = s.mask(card, [span_of(card, "TESZT ELEK", "PERSON")])
    (card_placeholder,) = placeholders(card_masked)
    prose = "Teszt Elek aláírta. Teszt Eleknek küldjük."
    prose_masked = s.mask(prose, [])
    assert placeholders(prose_masked) == [card_placeholder, card_placeholder]
    assert prose_masked.endswith(f"{card_placeholder}nek küldjük.")
    # One entity, counted once per occurrence.
    assert s.entities() == [(card_placeholder, EntityType.PERSON, 3)]


def test_default_inflected_caps_form_keeps_one_placeholder() -> None:
    s = session()
    text = "Teszt Elek írt. TESZT ELEKNEK válaszolunk, teszt eleket hívjuk."
    masked = s.mask(text, [span_of(text, NAME, "PERSON")])
    found = placeholders(masked)
    assert len(found) == 3 and len(set(found)) == 1
    assert f"{found[0]}NEK" in masked and f"{found[0]}et" in masked


def test_default_from_settings_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PII_GUARD_VAULT_CASE_SENSITIVE_PLACEHOLDERS", raising=False)
    settings_ = Settings(_env_file=None, tenant_key="0f" * 32)
    assert settings_.vault_case_sensitive_placeholders is False
    s = Vault.from_settings(settings_).session()
    masked = s.mask(CAPS_TEXT, [span_of(CAPS_TEXT, NAME, "PERSON")])
    assert len(set(placeholders(masked))) == 1


# --- case-sensitive placeholders ------------------------------------------------------------


def test_case_sensitive_lowercase_occurrence_round_trips() -> None:
    s = session(case_sensitive=True)
    masked = s.mask(SELLER_TEXT, [span_of(SELLER_TEXT, "Eladó", "PERSON")])
    found = placeholders(masked)
    assert len(found) == 2 and found[0] != found[1]
    assert "eladó" not in masked.casefold()
    assert s.unmask(masked) == SELLER_TEXT


def test_case_sensitive_all_caps_occurrence_round_trips() -> None:
    s = session(case_sensitive=True)
    masked = s.mask(CAPS_TEXT, [span_of(CAPS_TEXT, NAME, "PERSON")])
    upper, mixed = placeholders(masked)
    assert upper != mixed
    assert s.unmask(masked) == CAPS_TEXT


def test_case_sensitive_same_casing_shares_placeholder() -> None:
    s = session(case_sensitive=True)
    text = "Teszt Elek, TESZT ELEK, Teszt Elek, TESZT ELEK, teszt elek."
    masked = s.mask(text, [span_of(text, NAME, "PERSON")])
    found = placeholders(masked)
    assert len(set(found)) == 3
    assert found[0] == found[2] and found[1] == found[3]
    assert s.unmask(masked) == text
    counts = {placeholder: count for placeholder, _, count in s.entities()}
    assert counts == {found[0]: 2, found[1]: 2, found[4]: 1}


def test_case_sensitive_canonical_id_matches_default_mode() -> None:
    vault = Vault(TEST_KEY, case_sensitive_placeholders=True)
    s = vault.session()
    masked = s.mask(CAPS_TEXT, [span_of(CAPS_TEXT, NAME, "PERSON")])
    canonical = format_placeholder(
        EntityType.PERSON, derive_id(TEST_KEY, s.session_id, EntityType.PERSON, "teszt elek")
    )
    assert placeholders(masked)[1] == canonical


def test_case_sensitive_variant_persists_across_requests() -> None:
    s = session(case_sensitive=True)
    first = s.mask(CAPS_TEXT, [span_of(CAPS_TEXT, NAME, "PERSON")])
    upper, _ = placeholders(first)
    second = s.mask("Aláíró: TESZT ELEK", [])
    assert placeholders(second) == [upper]
    assert s.unmask(second) == "Aláíró: TESZT ELEK"


def test_case_sensitive_inflected_forms_round_trip() -> None:
    s = session(case_sensitive=True)
    text = "Teszt Eleknek írtunk. TESZT ELEKNEK válaszolunk, teszt eleket hívjuk."
    masked = s.mask(text, [span_of(text, "Teszt Eleknek", "PERSON")])
    found = placeholders(masked)
    assert len(set(found)) == 3
    assert "elek" not in masked.casefold()
    assert s.unmask(masked) == text


def test_case_sensitive_stem_changed_caps_form_round_trips() -> None:
    s = session(case_sensitive=True)
    text = "Próba Zsuzsanna aláírta. PRÓBA ZSUZSANNÁNAK küldjük."
    masked = s.mask(text, [span_of(text, "Próba Zsuzsanna", "PERSON")])
    first, second = placeholders(masked)
    assert first != second
    assert f"{second}NAK" in masked
    assert s.unmask(masked) == text
    # Without a suffix the caps variant restores the value in caps.
    assert s.unmask(f"{second}.") == "PRÓBA ZSUZSANNA."


def test_case_sensitive_stem_changed_mixed_form_of_caps_value_round_trips() -> None:
    s = session(case_sensitive=True)
    text = "Név: PRÓBA ZSUZSANNA. Próba Zsuzsannának küldjük."
    masked = s.mask(text, [span_of(text, "PRÓBA ZSUZSANNA", "PERSON")])
    _, mixed = placeholders(masked)
    assert s.unmask(masked) == text
    assert s.unmask(f"{mixed}.") == "Próba Zsuzsanna."


def test_case_sensitive_span_in_other_casing_gets_variant() -> None:
    # Two spans of one value in different casings: the second one is a variant, too.
    s = session(case_sensitive=True)
    text = "Név: TESZT ELEK. Teszt Elek aláírta."
    spans = [span_of(text, "TESZT ELEK", "PERSON"), span_of(text, NAME, "PERSON")]
    masked = s.mask(text, spans)
    first, second = placeholders(masked)
    assert first != second
    assert s.unmask(masked) == text


def test_case_sensitive_stream_unmask_equals_whole_text() -> None:
    s = session(case_sensitive=True)
    masked = s.mask(CAPS_TEXT, [span_of(CAPS_TEXT, NAME, "PERSON")])
    unmasker = StreamUnmasker(s)
    streamed = "".join(unmasker.feed(masked[i : i + 3]) for i in range(0, len(masked), 3))
    assert streamed + unmasker.flush() == s.unmask(masked) == CAPS_TEXT


def test_case_sensitive_remask_keeps_variant_placeholders() -> None:
    s = session(case_sensitive=True)
    masked = s.mask(CAPS_TEXT, [span_of(CAPS_TEXT, NAME, "PERSON")])
    assert s.mask(masked, [], remask=True) == masked


def test_case_sensitive_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_VAULT_CASE_SENSITIVE_PLACEHOLDERS", "true")
    settings_ = Settings(_env_file=None, tenant_key="0f" * 32)
    assert settings_.vault_case_sensitive_placeholders is True
    s = Vault.from_settings(settings_).session()
    masked = s.mask(CAPS_TEXT, [span_of(CAPS_TEXT, NAME, "PERSON")])
    assert len(set(placeholders(masked))) == 2
    assert s.unmask(masked) == CAPS_TEXT
    # An explicit argument wins over the setting.
    plain = Vault.from_settings(settings_, case_sensitive_placeholders=False).session()
    assert len(set(placeholders(plain.mask(CAPS_TEXT, [span_of(CAPS_TEXT, NAME, "PERSON")])))) == 1


# --- properties ------------------------------------------------------------------------------

_CLASS_FORMS = st.sampled_from(["Teszt Elek", "TESZT ELEK", "teszt elek"])
_ANY_CASING = st.lists(st.booleans(), min_size=len(NAME), max_size=len(NAME)).map(
    lambda flags: "".join(c.upper() if up else c.lower() for c, up in zip(NAME, flags, strict=True))
)


def _text_of(forms: list[str]) -> str:
    return "Ügyfél: " + ". Aláíró: ".join(forms) + "."


@settings(max_examples=60, deadline=None)
@given(forms=st.lists(_CLASS_FORMS, min_size=1, max_size=5))
def test_property_case_sensitive_class_forms_round_trip(forms: list[str]) -> None:
    text = _text_of(forms)
    s = session(case_sensitive=True)
    masked = s.mask(text, [span_of(text, forms[0], "PERSON")])
    assert "teszt" not in masked.casefold() and "elek" not in masked.casefold()
    assert len(placeholders(masked)) == len(forms)
    assert len(set(placeholders(masked))) == len(set(forms))
    assert s.unmask(masked) == text


@settings(max_examples=60, deadline=None)
@pytest.mark.parametrize("case_sensitive", [False, True])
@given(forms=st.lists(_ANY_CASING, min_size=1, max_size=5))
def test_property_any_casing_never_leaks(case_sensitive: bool, forms: list[str]) -> None:
    text = _text_of(forms)
    s = session(case_sensitive=case_sensitive)
    masked = s.mask(text, [span_of(text, forms[0], "PERSON")])
    assert "teszt" not in masked.casefold() and "elek" not in masked.casefold()
    assert len(placeholders(masked)) == len(forms)
    restored = s.unmask(masked)
    # Exact up to casing in both modes; exact when every form is in its own casing class.
    assert restored.casefold() == text.casefold()
    if not case_sensitive:
        assert len(set(placeholders(masked))) == 1
