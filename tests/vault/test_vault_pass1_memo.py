"""The pass-1 memo (LAB-1315): a text masked again from the same spans changes no output.

Each request re-sends the whole history, so :meth:`VaultSession.mask_with_report` sees the
same ``(text, spans)`` again; it scans only the entries changed since, or masks from scratch
when a newer entry or a newly confirmed lemma could change the result. Every test compares
with the memo off: masked and unmasked texts, ``entities()`` (counts included).
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_vault_mask import _requests, _session, _session_turns
from vault_helpers import span_of

from pii_guard.types import Span
from pii_guard.vault import VaultSession
from pii_guard.vault import vault as vault_module

Turn = tuple[str, list[Span], str]


def _person(text: str, *values: str) -> Turn:
    return text, [span_of(text, value, "PERSON") for value in values], "hu"


def _run(
    turns: list[Turn], memo: bool, case_sensitive: bool = False
) -> tuple[list[str], list[str], list[tuple[str, object, int]], VaultSession]:
    previous = vault_module._MASK_MEMO
    vault_module._MASK_MEMO = memo
    try:
        session = _session(case_sensitive)
        masked = _requests(session, turns, len(turns))
        return masked, [session.unmask(t) for t in masked], session.entities(), session
    finally:
        vault_module._MASK_MEMO = previous


def _same_with_and_without_memo(turns: list[Turn], case_sensitive: bool = False) -> list[str]:
    on, off = _run(turns, True, case_sensitive), _run(turns, False, case_sensitive)
    assert on[:3] == off[:3]
    return on[0]


@settings(max_examples=300, deadline=None)
@given(turns=_session_turns(), case_sensitive=st.booleans())
def test_memo_matches_a_mask_from_scratch(turns: list[Turn], case_sensitive: bool) -> None:
    _same_with_and_without_memo(turns, case_sensitive)


# no_cover: one request per turn over the whole history, twice, is about 7x slower under the
# branch tracer (42-52 s each on CI). The vault code it runs is covered by the property test
# above and the unit tests below; this one guards the outputs on the corpus (LAB-1447).
@pytest.mark.no_cover
@pytest.mark.parametrize("case_sensitive", [False, True])
@pytest.mark.parametrize("late", [False, True])
def test_memo_changes_no_output_on_the_prefilter_corpus(case_sensitive: bool, late: bool) -> None:
    from test_vault_mask import _late_turns
    from test_vault_prefilter import _turns

    turns = _late_turns() if late else _turns()
    on, off = _run(turns, True, case_sensitive), _run(turns, False, case_sensitive)
    assert on[:3] == off[:3]
    assert on[3].entries_scanned < off[3].entries_scanned
    assert sum(text.count("[[") for text in on[0]) > 300


def test_a_longer_value_confirmed_later_wins_as_from_scratch() -> None:
    # "Elek" is confirmed first; "Teszt Elek" later. From scratch the longer value takes
    # "Teszt Elek" in the first text, which the memo has as "Teszt [[Elek]]": no shortcut.
    turns = [
        _person("Elek írt, Teszt Elek is.", "Elek"),
        _person("Teszt Elek válaszolt.", "Teszt Elek"),
    ]
    masked = _same_with_and_without_memo(turns)
    first_request, last_request = masked[0], masked[-2]
    assert "Teszt [[PERSON_" in first_request
    assert "Teszt [[PERSON_" not in last_request


def test_a_weak_split_whose_lemma_is_confirmed_later_is_planned_again() -> None:
    # "Kováccsal" alone is a weak split: its own value, "Kovács" an alias. A later text
    # confirms "Kovács" (the alias's own entry), so the first text then plans the span onto
    # that lemma. Glued to "1", the span holds no occurrence of the new entry: only the
    # memo's dependency on that lemma tells it the plans changed.
    text = "Rendelés 1Kováccsal."
    spans = [span_of(text, "Kováccsal", "PERSON")]
    outputs = []
    for memo in (True, False):
        previous = vault_module._MASK_MEMO
        vault_module._MASK_MEMO = memo
        try:
            session = _session(False)
            before = session.mask(text, spans)
            session.mask("Szia Kovács!", [])
            after = session.mask(text, spans)
            outputs.append((before, after, session.entities()))
        finally:
            vault_module._MASK_MEMO = previous
    assert outputs[0] == outputs[1]
    before, after, _ = outputs[0]
    assert before != after
    assert after.endswith("]]al.")


def test_an_entry_that_gains_a_surface_masks_as_from_scratch() -> None:
    turns = [
        _person("Próba Zsuzsanna írt, Próba Zsuzsannának válaszolok.", "Próba Zsuzsanna"),
        _person("Próba Zsuzsannának küldtem.", "Próba Zsuzsannának"),
        _person("Próba Zsuzsannát hívtam.", "Próba Zsuzsannát"),
    ]
    _same_with_and_without_memo(turns)


def test_a_repeated_request_scans_only_what_changed_since() -> None:
    text = "Teszt Elek és Minta Béla írt: teszt.elek@example.com."
    spans = [span_of(text, "Teszt Elek", "PERSON"), span_of(text, "Minta Béla", "PERSON")]
    later = "Írj Minta Bélának: teszt.elek@example.com."
    later_spans = [span_of(later, "teszt.elek@example.com", "EMAIL")]
    session = _session(False)
    first = session.mask_with_report(text, spans)
    session.mask(later, later_spans)
    scanned = session.entries_scanned
    # The e-mail is newer than the first text: only its entry scans it again.
    again = session.mask_with_report(text, spans)
    assert session.entries_scanned == scanned + 1
    assert "teszt.elek@example.com" not in again.text
    assert again.generation == session.generation > first.generation
    # Then nothing changed since: no entry scans it, and the counts still grow.
    counts = {p: c for p, _, c in session.entities()}
    scanned = session.entries_scanned
    assert session.mask(text, spans) == again.text
    assert session.entries_scanned == scanned
    assert {p: c for p, _, c in session.entities()} == {
        p: c + again.text.count(p) for p, c in counts.items()
    }


def test_other_spans_are_another_memo_entry() -> None:
    text = "Teszt Elek és Minta Béla írt."
    session = _session(False)
    one = session.mask(text, [span_of(text, "Teszt Elek", "PERSON")])
    both = session.mask(
        text, [span_of(text, "Teszt Elek", "PERSON"), span_of(text, "Minta Béla", "PERSON")]
    )
    assert "Minta Béla" in one
    assert "Minta Béla" not in both
    assert len(session._masked or {}) == 2


def test_memo_is_bounded_and_forgotten(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vault_module, "_MASK_MEMO_ENTRIES", 2)
    monkeypatch.setattr(vault_module, "_MASK_MEMO_CHARS", 50)
    session = _session(False)
    for i in range(4):
        text = f"Teszt Elek {i}. levele."
        session.mask(text, [span_of(text, "Teszt Elek", "PERSON")])
    assert session._masked is not None
    assert len(session._masked) == 2
    assert session._masked_chars <= 50
    session.mask("x" * 51, [])  # longer than the character bound: not kept
    assert all(len(key[0]) <= 50 for key in session._masked)
    assert session._masked_chars == sum(len(key[0]) for key in session._masked)
    session.close()
    assert not session._masked
    assert session._masked_chars == 0


def test_a_fork_does_not_use_the_memo_and_commits_the_same() -> None:
    text = "Teszt Elek írt."
    spans = [span_of(text, "Teszt Elek", "PERSON")]
    session = _session(False)
    masked = session.mask(text, spans)
    fork = session.fork()
    assert fork._masked is None
    assert fork.mask(text, spans) == masked
    session.commit(fork)
    assert session.mask(text, spans) == masked
