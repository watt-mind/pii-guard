"""VaultSession.mask / unmask, keyed placeholders, TTL and fail-closed errors."""

from __future__ import annotations

import hashlib
import logging

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from vault_helpers import OTHER_TEST_KEY, TEST_KEY, FakeClock, span_of

from pii_guard.config import Settings
from pii_guard.types import EntityType, MaskingError, Span
from pii_guard.vault import (
    PLACEHOLDER_RE,
    ExactMatcher,
    HungarianSuffixMatcher,
    SessionNotFoundError,
    UnmaskResult,
    Vault,
    VaultSession,
    inflection_for,
    normalize_value,
    register_inflection,
)
from pii_guard.vault import vault as vault_module
from pii_guard.vault.placeholders import derive_id, is_placeholder_prefix

NAME = "Teszt Elek"
OTHER_NAME = "Minta Béla"
EMAIL = "teszt.elek@example.com"


def mask_one(session: VaultSession, text: str, value: str, entity_type: str = "PERSON") -> str:
    return session.mask(text, [span_of(text, value, entity_type)])


# --- placeholders --------------------------------------------------------------------------


def test_placeholder_matches_contract_regex(vault: Vault) -> None:
    masked = mask_one(vault.session(), f"Kedves {NAME}!", NAME)
    match = PLACEHOLDER_RE.search(masked)
    assert match is not None
    assert match.group(1) == "PERSON"
    assert len(match.group(2)) == 6
    assert masked == f"Kedves {match.group(0)}!"


def test_same_value_same_placeholder_within_session(vault: Vault) -> None:
    session = vault.session()
    first = mask_one(session, NAME, NAME)
    second = mask_one(session, f"Ismét {NAME}", NAME)
    assert second == f"Ismét {first}"
    # Case and whitespace variants are the same value.
    third = mask_one(session, "teszt   ELEK", "teszt   ELEK")
    assert third == first


def test_type_is_part_of_the_key(vault: Vault) -> None:
    session = vault.session()
    text = "Minta Kft"
    as_org = mask_one(session, text, text, "ORGANIZATION")
    assert as_org.startswith("[[ORGANIZATION_")


def test_placeholders_unlinkable_across_tenants_and_sessions(clock: FakeClock) -> None:
    vault_a = Vault(TEST_KEY, clock=clock)
    vault_b = Vault(OTHER_TEST_KEY, clock=clock)
    a1, a2, b1 = vault_a.session(), vault_a.session(), vault_b.session()
    placeholders = {mask_one(s, NAME, NAME) for s in (a1, a2, b1)}
    assert len(placeholders) == 3
    # A placeholder from another tenant is not resolved here.
    foreign = mask_one(b1, NAME, NAME)
    result = a1.unmask_with_report(foreign)
    assert result.text == foreign
    assert result.unresolved == (foreign,)


def test_placeholder_is_deterministic_for_a_session_id(clock: FakeClock) -> None:
    session_id = "s_fixed"
    expected = derive_id(TEST_KEY, session_id, EntityType.PERSON, normalize_value(NAME))
    session = VaultSession(session_id, TEST_KEY, ttl_seconds=60, id_length=6, clock=clock)
    assert mask_one(session, NAME, NAME) == f"[[PERSON_{expected}]]"


def test_collision_extends_the_id(vault: Vault, monkeypatch: pytest.MonkeyPatch) -> None:
    def colliding(key: bytes, sid: str, et: EntityType, norm: str, length: int = 6) -> str:
        return ("abcd" + hashlib.sha256(norm.encode()).hexdigest())[:length]

    monkeypatch.setattr(vault_module, "derive_id", colliding)
    session = vault_module.Vault(TEST_KEY, id_length=4).session()
    text = f"{NAME} és {OTHER_NAME}"
    masked = session.mask(
        text, [span_of(text, NAME, "PERSON"), span_of(text, OTHER_NAME, "PERSON")]
    )
    first, second = PLACEHOLDER_RE.findall(masked)
    assert first == ("PERSON", "abcd")
    assert second[1].startswith("abcd")
    assert len(second[1]) == 6
    assert session.unmask(masked) == text


def test_entities_counts_occurrences(vault: Vault) -> None:
    session = vault.session()
    text = f"{NAME} írt {NAME}nek, cc {EMAIL}."
    masked = session.mask(text, [span_of(text, NAME, "PERSON"), span_of(text, EMAIL, "EMAIL")])
    entities = {placeholder: (et, count) for placeholder, et, count in session.entities()}
    person = PLACEHOLDER_RE.search(masked).group(0)  # type: ignore[union-attr]
    assert entities[person] == (EntityType.PERSON, 2)
    assert sorted(et for et, _ in entities.values()) == [EntityType.EMAIL, EntityType.PERSON]


# --- every occurrence, inflection ----------------------------------------------------------


def test_contract_example_suffix_kept_outside_placeholder(vault: Vault) -> None:
    session = vault.session()
    text = "Teszt Elek írt Teszt Eleknek."
    masked = session.mask(text, [span_of(text, NAME, "PERSON")])
    placeholder = PLACEHOLDER_RE.search(masked).group(0)  # type: ignore[union-attr]
    assert masked == f"{placeholder} írt {placeholder}nek."
    assert session.unmask(masked) == text


def test_undetected_occurrences_are_masked_case_and_whitespace_insensitively(
    vault: Vault,
) -> None:
    session = vault.session()
    text = f"{NAME}, TESZT ELEK és teszt\nelek"
    masked = session.mask(text, [span_of(text, NAME, "PERSON")])
    assert "teszt" not in masked.casefold()
    assert masked.count("[[PERSON_") == 3
    # Re-identification restores the confirmed surface form.
    assert session.unmask(masked) == f"{NAME}, {NAME} és {NAME}"


def test_values_confirmed_earlier_are_masked_in_later_calls(vault: Vault) -> None:
    session = vault.session()
    placeholder = mask_one(session, NAME, NAME)
    assert session.mask(f"Hol van {NAME}?", []) == f"Hol van {placeholder}?"


@pytest.mark.parametrize(
    ("value", "entity_type", "inflected", "suffix"),
    [
        ("Kovács", "PERSON", "Kovácsnál", "nál"),
        ("Elek", "PERSON", "Elekkel", "kel"),
        ("Elek", "PERSON", "Eleké", "é"),
        ("Anna", "PERSON", "Annaval", "val"),
        ("Minta Kft", "ORGANIZATION", "Minta Kft-vel", "-vel"),
        ("ABC-123", "VEHICLE_PLATE", "ABC-123-nak", "-nak"),
        (EMAIL, "EMAIL", f"{EMAIL}-ra", "-ra"),
        ("Szeged", "ADDRESS", "Szegeden", "en"),
    ],
)
def test_hungarian_suffix_variants(
    vault: Vault, value: str, entity_type: str, inflected: str, suffix: str
) -> None:
    session = vault.session()
    text = f"{value}. Később: {inflected} is."
    masked = session.mask(text, [span_of(text, value, entity_type)])
    placeholder = PLACEHOLDER_RE.search(masked).group(0)  # type: ignore[union-attr]
    assert masked == f"{placeholder}. Később: {placeholder}{suffix} is."
    assert session.unmask(masked) == text


@pytest.mark.parametrize("other", ["Elekes", "Elekfi", "Ele", "XElek", "Elek_1"])
def test_other_words_are_not_masked(vault: Vault, other: str) -> None:
    session = vault.session()
    text = f"Elek és {other}"
    masked = session.mask(text, [span_of(text, "Elek", "PERSON")])
    assert masked.endswith(f" és {other}")


def test_digraph_final_values_do_not_take_doubled_suffix(vault: Vault) -> None:
    # "Kovács" + "-val" is "Kováccsal": the stem changes, so it is not matched (documented).
    session = vault.session()
    text = "Kovács és Kovácscsal"
    masked = session.mask(text, [span_of(text, "Kovács", "PERSON")])
    assert masked.endswith(" és Kovácscsal")


def test_language_without_matcher_requires_exact_word(vault: Vault) -> None:
    session = vault.session()
    text = f"{NAME} wrote to {NAME}nek"
    masked = session.mask(text, [span_of(text, NAME, "PERSON")], language="fi")
    assert masked.endswith(f"{NAME}nek")
    assert isinstance(inflection_for("fi"), ExactMatcher)
    assert isinstance(inflection_for("hu"), HungarianSuffixMatcher)


def test_register_inflection_hook(vault: Vault) -> None:
    class PluralS:
        def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
            return "'s"

    register_inflection("xx", PluralS())
    try:
        session = vault.session()
        text = f"{NAME} and {NAME}'s car"
        masked = session.mask(text, [span_of(text, NAME, "PERSON")], language="xx")
        assert masked.count("[[PERSON_") == 2
        assert session.unmask(masked) == text
    finally:
        register_inflection("xx", ExactMatcher())


def test_longer_values_win_over_contained_ones(vault: Vault) -> None:
    session = vault.session()
    mask_one(session, "Elek", "Elek")
    text = f"Szia {NAME}! Elek?"
    masked = session.mask(text, [span_of(text, NAME, "PERSON")])
    assert masked.count("[[PERSON_") == 2
    assert session.unmask(masked) == text


def test_non_word_edges(vault: Vault) -> None:
    session = vault.session()
    phone = "+36 30 123 4567"
    text = f"Tel: {phone} (vagy {phone})"
    masked = session.mask(text, [span_of(text, phone, "PHONE")])
    assert masked.count("[[PHONE_") == 2
    assert session.unmask(masked) == text


# --- unmask --------------------------------------------------------------------------------


def test_unknown_and_mangled_placeholders_left_visible_and_reported(vault: Vault) -> None:
    session = vault.session()
    real = mask_one(session, NAME, NAME)
    invented = "[[PERSON_ffff]]"
    retyped = real.replace("PERSON", "EMAIL")
    broken = real[:-1]  # "[[PERSON_xxxxxx]" is not placeholder-shaped: left alone, not reported
    answer = f"{real} {invented} {retyped} {invented} {broken}"
    result = session.unmask_with_report(answer)
    assert result.text == f"{NAME} {invented} {retyped} {invented} {broken}"
    assert result.unresolved == (invented, retyped)
    assert session.unmask(answer) == result.text


def test_unmask_without_placeholders_is_identity(vault: Vault) -> None:
    assert vault.session().unmask("semmi [[ ]] _ff") == "semmi [[ ]] _ff"


# --- property: unmask(mask(x)) == x --------------------------------------------------------

VALUES: list[tuple[str, str]] = [
    (NAME, "PERSON"),
    (OTHER_NAME, "PERSON"),
    ("Próba Anna", "PERSON"),
    (EMAIL, "EMAIL"),
    ("+36 30 123 4567", "PHONE"),
    ("8312345678", "NATIONAL_ID_HU_TAX"),
    ("Minta Kft", "ORGANIZATION"),
]
# Filler that can't contain or extend a value into a different word.
FILLER = st.text(alphabet=" .,;:!?\n()-", min_size=1, max_size=8)


@st.composite
def documents(draw: st.DrawFn) -> tuple[str, list[Span]]:
    parts = draw(st.lists(st.tuples(FILLER, st.sampled_from(VALUES)), max_size=12))
    text = ""
    spans = []
    for filler, (value, entity_type) in parts:
        text += filler
        spans.append(Span(len(text), len(text) + len(value), entity_type, value, 1.0, "test"))
        text += value
    return text + draw(FILLER), spans


@given(doc=documents(), keep=st.lists(st.booleans(), max_size=12))
@settings(max_examples=200, deadline=None)
def test_property_unmask_inverts_mask(doc: tuple[str, list[Span]], keep: list[bool]) -> None:
    text, spans = doc
    # Drop some detections: every occurrence of a confirmed value must still be masked.
    detected = [s for i, s in enumerate(spans) if i >= len(keep) or keep[i]]
    session = Vault(TEST_KEY).session()
    masked = session.mask(text, detected)
    confirmed = {s.text for s in detected}
    for value in confirmed:
        assert value not in masked
    assert session.unmask(masked) == text


@given(text=st.text(max_size=200).filter(lambda t: "[[" not in t))
@settings(max_examples=100, deadline=None)
def test_property_arbitrary_text_without_spans_is_unchanged(text: str) -> None:
    session = Vault(TEST_KEY).session()
    assert session.unmask(session.mask(text, [])) == text


# --- fail closed ---------------------------------------------------------------------------


def test_overlapping_spans_raise(vault: Vault) -> None:
    session = vault.session()
    text = f"{NAME} {EMAIL}"
    spans = [span_of(text, NAME, "PERSON"), span_of(text, "Elek", "PERSON")]
    with pytest.raises(MaskingError, match="overlapping spans PERSON"):
        session.mask(text, spans)
    assert session.entities() == []  # nothing recorded


def test_out_of_range_span_raises(vault: Vault) -> None:
    span = Span(0, 10, "PERSON", NAME, 1.0, "test")
    with pytest.raises(MaskingError, match="out of range"):
        vault.session().mask("rövid", [span])


def test_span_not_matching_text_raises(vault: Vault) -> None:
    span = Span(0, 10, "PERSON", NAME, 1.0, "test")
    with pytest.raises(MaskingError, match="does not match"):
        vault.session().mask(OTHER_NAME + "!", [span])


def test_visual_span_raises(vault: Vault) -> None:
    span = Span(0, 4, "FACE", "arc!", 1.0, "test")
    with pytest.raises(MaskingError, match="visual"):
        vault.session().mask("arc!", [span])


def test_blank_span_raises(vault: Vault) -> None:
    span = Span(1, 3, "PERSON", "  ", 1.0, "test")
    with pytest.raises(MaskingError, match="blank"):
        vault.session().mask("a  b", [span])


def test_non_span_raises(vault: Vault) -> None:
    with pytest.raises(MaskingError, match="not a Span"):
        vault.session().mask("abc", [(0, 1)])  # type: ignore[list-item]


def test_error_messages_never_contain_values(vault: Vault) -> None:
    session = vault.session()
    cases = [
        (f"{NAME}!", [span_of(f"{NAME}!", NAME, "PERSON"), Span(6, 10, "PERSON", "Elek", 1, "t")]),
        (f"x{OTHER_NAME}", [Span(1, 11, "PERSON", NAME, 1.0, "t")]),
    ]
    for text, spans in cases:
        with pytest.raises(MaskingError) as exc:
            session.mask(text, spans)
        for value in (NAME, OTHER_NAME, "Elek", "Minta"):
            assert value not in str(exc.value)
            assert value not in exc.value.message


# --- sessions and TTL ----------------------------------------------------------------------


def test_session_lookup_by_id(vault: Vault) -> None:
    session = vault.session()
    assert session.session_id.startswith("s_")
    assert vault.session(session.session_id) is session
    assert len(vault) == 1


def test_unknown_session_id_raises(vault: Vault) -> None:
    with pytest.raises(SessionNotFoundError) as exc:
        vault.session("s_nope")
    assert exc.value.code == "not_found"
    assert exc.value.status_code == 404


def test_ttl_expires_the_mapping(vault: Vault, clock: FakeClock) -> None:
    session = vault.session()
    masked = mask_one(session, NAME, NAME)
    clock.now += 59
    assert session.unmask(masked) == NAME  # use extends the TTL (sliding)
    clock.now += 59
    assert vault.session(session.session_id) is session
    clock.now += 61
    with pytest.raises(SessionNotFoundError):
        session.unmask(masked)
    with pytest.raises(SessionNotFoundError):
        vault.session(session.session_id)
    assert len(vault) == 0


def test_purge_expired(vault: Vault, clock: FakeClock) -> None:
    vault.session()
    vault.session()
    clock.now += 61
    assert vault.purge_expired() == 2
    assert len(vault) == 0


def test_drop_and_close(vault: Vault) -> None:
    session = vault.session()
    mask_one(session, NAME, NAME)
    vault.drop(session.session_id)
    vault.drop(session.session_id)  # idempotent
    for call in (lambda: session.mask("x", []), session.entities, lambda: session.unmask("x")):
        with pytest.raises(SessionNotFoundError):
            call()


def test_vault_validates_arguments() -> None:
    with pytest.raises(TypeError):
        Vault("0f" * 32)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least 16 bytes"):
        Vault(b"short")
    with pytest.raises(ValueError, match="ttl_seconds"):
        Vault(TEST_KEY, ttl_seconds=0)
    with pytest.raises(ValueError, match="id_length"):
        Vault(TEST_KEY, id_length=3)
    with pytest.raises(ValueError, match="id length"):
        derive_id(TEST_KEY, "s", EntityType.PERSON, "x", length=65)


def test_from_settings() -> None:
    vault = Vault.from_settings(Settings(tenant_key="0f" * 32), ttl_seconds=5)
    assert mask_one(vault.session(), NAME, NAME).startswith("[[PERSON_")
    with pytest.raises(MaskingError) as exc:
        Vault.from_settings(Settings())
    assert exc.value.code == "vault_not_configured"


# --- no leaks ------------------------------------------------------------------------------


def test_reprs_never_contain_values(vault: Vault) -> None:
    session = vault.session()
    masked = mask_one(session, f"{NAME} {EMAIL}", NAME)
    result = session.unmask_with_report(masked)
    entry = next(iter(session._by_placeholder.values()))
    for obj in (vault, session, result, entry):
        for rendered in (repr(obj), str(obj)):
            assert NAME not in rendered
            assert "Teszt" not in rendered
    assert isinstance(result, UnmaskResult)
    assert "<redacted>" in repr(result)
    assert TEST_KEY.hex() not in repr(vault)


def test_logs_never_contain_values(vault: Vault, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="pii_guard")
    session = vault.session()
    text = f"{NAME} írt {NAME}nek ({EMAIL})"
    masked = session.mask(text, [span_of(text, NAME, "PERSON"), span_of(text, EMAIL, "EMAIL")])
    session.unmask(masked + " [[PERSON_ffff]]")
    assert caplog.records, "expected debug logs"
    logged = "\n".join(r.getMessage() for r in caplog.records)
    for value in (NAME, EMAIL, "Teszt", "example.com"):
        assert value not in logged
    assert "[[PERSON_ffff]]" in logged  # unresolved ids are reported


def test_prefix_helper() -> None:
    for prefix in ("[", "[[", "[[P", "[[PERSON_", "[[PERSON_7f3a", "[[PERSON_7f3a]"):
        assert is_placeholder_prefix(prefix)
    for other in ("", "x[", "[x", "[[p", "[[PERSON_7f3a]]", "[[PERSON-", "[[[", "[[" + "A" * 200):
        assert not is_placeholder_prefix(other)
