"""Case-sensitive entity types and the restore budget (LAB-1350).

A credential's letter case is part of it: two secrets that differ only in case are two values.
Restoring is bounded per output. Every value here is fictional (ADR 0005); the tokens are
built at runtime so no literal looks like a credential.
"""

from __future__ import annotations

import pytest
from vault_helpers import TEST_KEY, FakeClock, span_of

from pii_guard.types import EntityType
from pii_guard.vault import (
    CASE_SENSITIVE_TYPES,
    PLACEHOLDER_RE,
    RestoreBudget,
    StreamUnmasker,
    UnmaskOutputTooLargeError,
    Vault,
)

_PREFIX = "gh" + "p_"
TOKEN_A = _PREFIX + "AbCdEfGhIjKlMnOpQrStUvWxYz" + "0123456789"
TOKEN_B = _PREFIX + "aBcDeFgHiJkLmNoPqRsTuVwXyZ" + "0123456789"
assert TOKEN_A.casefold() == TOKEN_B.casefold() and TOKEN_A != TOKEN_B


def _vault(case_sensitive: bool = False, **kwargs: int) -> Vault:
    return Vault(
        TEST_KEY,
        ttl_seconds=60.0,
        clock=FakeClock(),
        case_sensitive_placeholders=case_sensitive,
        **kwargs,
    )


def test_secret_is_the_only_case_sensitive_type() -> None:
    assert frozenset({EntityType.SECRET}) == CASE_SENSITIVE_TYPES


@pytest.mark.parametrize("case_sensitive", [False, True], ids=["default", "case-sensitive"])
def test_secrets_that_differ_only_in_case_get_two_placeholders(case_sensitive: bool) -> None:
    session = _vault(case_sensitive).session()
    text = f"first {TOKEN_A} then {TOKEN_B} and again {TOKEN_A}"
    spans = [
        span_of(text, TOKEN_A, "SECRET"),
        span_of(text, TOKEN_B, "SECRET"),
        span_of(text, TOKEN_A, "SECRET", nth=1),
    ]
    masked = session.mask(text, spans)
    placeholders = [m.group(0) for m in PLACEHOLDER_RE.finditer(masked)]
    assert len(placeholders) == 3
    assert placeholders[0] != placeholders[1]
    assert placeholders[0] == placeholders[2]
    assert TOKEN_A not in masked and TOKEN_B not in masked
    assert session.unmask(masked) == text


@pytest.mark.parametrize("case_sensitive", [False, True], ids=["default", "case-sensitive"])
def test_mixed_casing_class_does_not_merge_secrets(case_sensitive: bool) -> None:
    """Both tokens are mixed case: the casing-class setting alone never told them apart."""
    session = _vault(case_sensitive).session()
    first = session.mask(f"a {TOKEN_A}", [span_of(f"a {TOKEN_A}", TOKEN_A, "SECRET")])
    second = session.mask(f"b {TOKEN_B}", [span_of(f"b {TOKEN_B}", TOKEN_B, "SECRET")])
    assert first[2:] != second[2:]
    assert session.unmask(second) == f"b {TOKEN_B}"
    assert session.unmask(first) == f"a {TOKEN_A}"


def test_occurrence_of_a_secret_in_its_own_case_is_still_masked() -> None:
    session = _vault().session()
    session.mask(f"x {TOKEN_A}", [span_of(f"x {TOKEN_A}", TOKEN_A, "SECRET")])
    later = session.mask(f"again: {TOKEN_A}.", [])
    assert TOKEN_A not in later
    assert session.unmask(later) == f"again: {TOKEN_A}."


def test_occurrence_in_another_case_is_not_the_confirmed_secret() -> None:
    """``TOKEN_B`` is a different credential: never restored as ``TOKEN_A``."""
    session = _vault().session()
    session.mask(f"x {TOKEN_A}", [span_of(f"x {TOKEN_A}", TOKEN_A, "SECRET")])
    later = session.mask(f"other: {TOKEN_B}.", [])
    assert later == f"other: {TOKEN_B}."


def test_names_stay_case_insensitive() -> None:
    """Names keep sharing one placeholder across casings (LAB-1337 / inflection unchanged)."""
    session = _vault().session()
    text = "Teszt Elek és TESZT ELEKNEK írtam."
    masked = session.mask(text, [span_of(text, "Teszt Elek", "PERSON")])
    placeholders = {m.group(0) for m in PLACEHOLDER_RE.finditer(masked)}
    assert len(placeholders) == 1
    assert "ELEK" not in masked
    assert masked.endswith("NEK írtam.")


def test_unmask_over_the_limit_fails_closed() -> None:
    session = _vault(max_restored_chars=100).session()
    text = f"k {TOKEN_A}"
    masked = session.mask(text, [span_of(text, TOKEN_A, "SECRET")])
    placeholder = PLACEHOLDER_RE.search(masked)
    assert placeholder is not None
    assert session.unmask(" ".join([placeholder.group(0)] * 2)).count(TOKEN_A) == 2
    with pytest.raises(UnmaskOutputTooLargeError) as raised:
        session.unmask(" ".join([placeholder.group(0)] * 3))
    assert raised.value.code == "unmask_output_too_large"
    assert raised.value.status_code == 413
    assert TOKEN_A not in str(raised.value)


def test_budget_is_shared_across_calls_of_one_output() -> None:
    session = _vault(max_restored_chars=100).session()
    text = f"k {TOKEN_A}"
    masked = session.mask(text, [span_of(text, TOKEN_A, "SECRET")])
    placeholder = masked[2:]
    budget = session.restore_budget()
    session.unmask(placeholder, budget=budget)
    session.unmask(placeholder, budget=budget)
    with pytest.raises(UnmaskOutputTooLargeError):
        session.unmask(placeholder, budget=budget)
    assert budget.spent == 2 * len(TOKEN_A)


def test_stream_unmasker_stops_at_the_limit() -> None:
    session = _vault(max_restored_chars=100).session()
    text = f"k {TOKEN_A}"
    placeholder = session.mask(text, [span_of(text, TOKEN_A, "SECRET")])[2:]
    unmasker = StreamUnmasker(session)
    emitted = ""
    with pytest.raises(UnmaskOutputTooLargeError):
        for _ in range(10):
            emitted += unmasker.feed(placeholder + " ")
        emitted += unmasker.flush()
    assert emitted.count(TOKEN_A) <= 100 // len(TOKEN_A)


def test_restore_budget_rejects_a_negative_limit() -> None:
    with pytest.raises(ValueError):
        RestoreBudget(-1)
    with pytest.raises(ValueError):
        _vault(max_restored_chars=0)
