"""StreamUnmasker: placeholders split across chunks are restored exactly once, in order."""

from __future__ import annotations

import itertools

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from vault_helpers import TEST_KEY, FakeClock, span_of

from pii_guard.types import Span
from pii_guard.vault import SessionNotFoundError, StreamUnmasker, Vault, VaultSession

NAME = "Teszt Elek"
EMAIL = "teszt.elek@example.com"


def masked_session(text: str, values: list[tuple[str, str]]) -> tuple[VaultSession, str]:
    session = Vault(TEST_KEY).session()
    spans = [span_of(text, value, entity_type) for value, entity_type in values]
    return session, session.mask(text, spans)


def stream(session: VaultSession, chunks: list[str]) -> tuple[list[str], StreamUnmasker]:
    unmasker = StreamUnmasker(session)
    out = [unmasker.feed(chunk) for chunk in chunks]
    out.append(unmasker.flush())
    return out, unmasker


def test_contract_example_split_placeholder(vault: Vault) -> None:
    session = vault.session()
    placeholder = session.mask(NAME, [span_of(NAME, NAME, "PERSON")])
    cut = len("[[PERS")
    out, _ = stream(session, [placeholder[:cut], placeholder[cut:] + " ok"])
    assert out == ["", f"{NAME} ok", ""]
    assert "".join(out) == session.unmask(f"{placeholder} ok")


def test_holds_back_only_a_possible_prefix() -> None:
    session, masked = masked_session(f"Szia {NAME}!", [(NAME, "PERSON")])
    unmasker = StreamUnmasker(session)
    assert unmasker.feed("Szia [") == "Szia "
    assert unmasker.feed("x] és [[") == "[x] és "
    assert unmasker.feed("a") == "[[a"  # lowercase can't start a type
    assert unmasker.feed(" [[PERSON") == " "
    assert unmasker.feed("_ffff]] vége") == "[[PERSON_ffff]] vége"
    # A complete placeholder waits for the next non-word character: a suffix may follow
    # and change the restored stem (Hungarian "[[PERSON_x]]nak" -> "...Zsuzsannának").
    assert unmasker.feed(masked[5:-1]) == ""
    assert unmasker.feed("!") == f"{NAME}!"
    assert unmasker.flush() == ""
    assert unmasker.unresolved == ("[[PERSON_ffff]]",)


def test_one_character_chunks_and_flush_of_partial_tail() -> None:
    session, masked = masked_session(f"{NAME} írt, {EMAIL}", [(NAME, "PERSON"), (EMAIL, "EMAIL")])
    text = masked + " [[PERS"
    out, _ = stream(session, list(text))
    assert "".join(out) == f"{NAME} írt, {EMAIL} [[PERS"
    assert out[-1] == "[[PERS"
    # Nothing restored partially: no output piece is a fragment of a value. A value comes
    # out with the character after its placeholder (which settles any suffix).
    assert all(piece in ("", f"{NAME} ", f"{EMAIL} ") or len(piece) == 1 for piece in out[:-1])


def test_long_bracket_runs_are_not_held_forever() -> None:
    session = Vault(TEST_KEY).session()
    unmasker = StreamUnmasker(session)
    junk = "[[" + "A" * 300
    assert unmasker.feed(junk) == junk


def test_feed_after_flush_raises() -> None:
    unmasker = StreamUnmasker(Vault(TEST_KEY).session())
    unmasker.flush()
    with pytest.raises(RuntimeError):
        unmasker.feed("x")


def test_expired_session_fails_closed(clock: FakeClock) -> None:
    session = Vault(TEST_KEY, ttl_seconds=10, clock=clock).session()
    masked = session.mask(NAME, [span_of(NAME, NAME, "PERSON")])
    unmasker = StreamUnmasker(session)
    assert unmasker.feed("ok ") == "ok "
    clock.now += 11
    with pytest.raises(SessionNotFoundError):
        unmasker.feed(masked)


def test_repr_has_no_values() -> None:
    session, masked = masked_session(NAME, [(NAME, "PERSON")])
    unmasker = StreamUnmasker(session)
    unmasker.feed(masked[:-1])
    assert "Teszt" not in repr(unmasker)
    assert "PERSON" not in repr(unmasker)


# --- property: random chunk splits ---------------------------------------------------------

VALUES = [(NAME, "PERSON"), ("Minta Béla", "PERSON"), (EMAIL, "EMAIL"), ("8312345678", "PHONE")]
# Noise that looks like placeholders, brackets and ids, to stress the buffering.
NOISE = st.text(alphabet="[]_ PERSONabcdef0123456789xyz.", max_size=12)
SAFE_FILLER = st.text(alphabet=" .,:!?\n", min_size=1, max_size=6)


@st.composite
def masked_documents(draw: st.DrawFn) -> tuple[VaultSession, str, str]:
    parts = draw(st.lists(st.tuples(SAFE_FILLER, st.sampled_from(VALUES)), max_size=8))
    text = ""
    spans = []
    for filler, (value, entity_type) in parts:
        text += filler
        spans.append(Span(len(text), len(text) + len(value), entity_type, value, 1.0, "test"))
        text += value
    text += draw(SAFE_FILLER)
    session = Vault(TEST_KEY).session()
    return session, text, session.mask(text, spans)


@st.composite
def splits(draw: st.DrawFn, text: str) -> list[str]:
    cuts = sorted(draw(st.lists(st.integers(0, len(text)), max_size=20)))
    bounds = [0, *cuts, len(text)]
    return [text[a:b] for a, b in itertools.pairwise(bounds)]


@given(data=st.data(), doc=masked_documents())
@settings(max_examples=300, deadline=None)
def test_property_random_splits_unmask_to_original(
    data: st.DataObject, doc: tuple[VaultSession, str, str]
) -> None:
    session, original, masked = doc
    chunks = data.draw(splits(masked))
    out, unmasker = stream(session, chunks)
    assert "".join(out) == original
    assert unmasker.unresolved == ()


@given(data=st.data(), doc=masked_documents(), noise=st.lists(NOISE, max_size=6))
@settings(max_examples=300, deadline=None)
def test_property_stream_equals_whole_unmask_with_noise(
    data: st.DataObject, doc: tuple[VaultSession, str, str], noise: list[str]
) -> None:
    session, _, masked = doc
    # Interleave noise (fake placeholders, stray brackets) with the masked text.
    pieces = masked.split(" ")
    mixed = "".join(p + (noise[i] if i < len(noise) else "") + " " for i, p in enumerate(pieces))
    chunks = data.draw(splits(mixed))
    out, unmasker = stream(session, chunks)
    whole = session.unmask_with_report(mixed)
    assert "".join(out) == whole.text
    assert set(unmasker.unresolved) == set(whole.unresolved)
