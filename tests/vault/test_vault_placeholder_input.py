"""Placeholder-shaped tokens in input (LAB-1092): issued ones are refused, foreign ones reserved."""

from __future__ import annotations

import pytest
from vault_helpers import TEST_KEY, span_of

from pii_guard.types import MaskingError
from pii_guard.vault import PLACEHOLDER_RE, StreamUnmasker, Vault, VaultSession
from pii_guard.vault.vault import PlaceholderInInputError

NAME = "Teszt Elek"
OTHER_NAME = "Minta Béla"
FOREIGN = "[[PERSON_deadbe]]"


def issued(session: VaultSession) -> str:
    text = f"{NAME} írt."
    masked = session.mask(text, [span_of(text, NAME, "PERSON")])
    match = PLACEHOLDER_RE.search(masked)
    assert match is not None
    return match.group(0)


@pytest.fixture
def session() -> VaultSession:
    return Vault(TEST_KEY).session()


def test_issued_token_in_input_is_rejected(session: VaultSession) -> None:
    token = issued(session)
    text = f"Ez egy {token} szöveg"
    with pytest.raises(PlaceholderInInputError) as info:
        session.mask(text, [])
    err = info.value
    assert isinstance(err, MaskingError)
    assert (err.code, err.status_code) == ("placeholder_in_input", 422)
    assert token not in err.message
    assert NAME not in err.message
    assert "1" in err.message


def test_rejection_stores_nothing(session: VaultSession) -> None:
    token = issued(session)
    before = session.entities()
    text = f"{OTHER_NAME} és {token}"
    with pytest.raises(PlaceholderInInputError):
        session.mask(text, [span_of(text, OTHER_NAME, "PERSON")])
    assert session.entities() == before
    assert session.mask(f"{OTHER_NAME}", []) == OTHER_NAME


def test_remask_accepts_own_output(session: VaultSession) -> None:
    token = issued(session)
    assert session.mask(f"{token} {NAME}", [], remask=True) == f"{token} {token}"


def test_foreign_token_survives_round_trip_and_is_unresolved(session: VaultSession) -> None:
    text = f"Ez egy {FOREIGN} szöveg"
    assert session.mask(text, []) == text
    result = session.unmask_with_report(text)
    assert result.text == text
    assert result.unresolved == (FOREIGN,)


def test_foreign_token_is_never_issued(
    session: VaultSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pii_guard.vault import session as session_module

    real = session_module.derive_id
    # Force the first candidate id to be the foreign one, then fall back to the real HMAC.
    calls: list[int] = []

    def forced(key, sid, etype, normalized, length=6):  # type: ignore[no-untyped-def]
        calls.append(length)
        return "deadbeef"[:length] if len(calls) == 1 else real(key, sid, etype, normalized, length)

    monkeypatch.setattr(session_module, "derive_id", forced)
    text = f"{FOREIGN} {NAME} írt."
    masked = session.mask(text, [span_of(text, NAME, "PERSON")], language="en")
    assert masked.startswith(FOREIGN + " ")
    match = PLACEHOLDER_RE.search(masked, len(FOREIGN))
    assert match is not None  # the value was masked
    placeholder = match.group(0)
    assert placeholder != FOREIGN
    assert len(calls) >= 2  # the colliding id was skipped
    assert session.unmask(masked) == text


def test_reservation_survives_across_calls(session: VaultSession) -> None:
    session.mask(f"{FOREIGN}", [])
    assert FOREIGN in session._reserved
    # A later mask of the same foreign token is still fine (it was never issued).
    assert session.mask(f"{FOREIGN} x", []) == f"{FOREIGN} x"


def test_stream_unmask_matches_whole_text(session: VaultSession) -> None:
    token = issued(session)
    text = f"{FOREIGN} és {token}"
    expected = session.unmask_with_report(text)
    unmasker = StreamUnmasker(session)
    chunks = [text[i : i + 3] for i in range(0, len(text), 3)]
    streamed = "".join(unmasker.feed(c) for c in chunks) + unmasker.flush()
    assert streamed == expected.text
    assert unmasker.unresolved == expected.unresolved == (FOREIGN,)


def test_closed_session_forgets_reservations(session: VaultSession) -> None:
    session.mask(FOREIGN, [])
    session.close()
    assert not session._reserved


def test_rest_mask_returns_422_without_the_text() -> None:
    from fastapi.testclient import TestClient

    from pii_guard.api.app import create_app
    from pii_guard.config import Settings

    settings = Settings(tenant_key=TEST_KEY.hex())
    with TestClient(create_app(settings), raise_server_exceptions=False) as api:
        first = api.post("/v1/mask", json={"text": f"{NAME} írt: teszt@example.com"})
        assert first.status_code == 200, first.text
        body = first.json()
        token = PLACEHOLDER_RE.search(body["masked_text"]).group(0)  # type: ignore[union-attr]
        again = api.post(
            "/v1/mask", json={"text": f"Ez egy {token} szöveg", "session_id": body["session_id"]}
        )
    assert again.status_code == 422
    error = again.json()["error"]
    assert error["code"] == "placeholder_in_input"
    assert token not in again.text
    assert NAME not in again.text
