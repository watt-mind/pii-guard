"""Vault resource limits and staged writes (LAB-1207). All values are fictional (ADR 0005)."""

from __future__ import annotations

import pytest
from vault_helpers import TEST_KEY, FakeClock, span_of

from pii_guard.config import Settings
from pii_guard.types import EntityType, MaskingError
from pii_guard.vault import SessionNotFoundError, Vault

NAME = "Teszt Elek"
EMAIL = "teszt.elek@example.com"


def test_new_sessions_beyond_the_cap_evict_the_least_recently_used(clock: FakeClock) -> None:
    vault = Vault(TEST_KEY, ttl_seconds=60.0, clock=clock, max_sessions=3)
    first = vault.session()
    clock.now += 1
    second = vault.session()
    clock.now += 1
    third = vault.session()
    clock.now += 1
    vault.session(first.session_id)  # used again: now the second is the least recent
    fourth = vault.session()

    assert len(vault) == 3
    with pytest.raises(SessionNotFoundError):
        vault.session(second.session_id)
    assert second.expired  # closed, its mapping forgotten
    for kept in (first, third, fourth):
        assert vault.session(kept.session_id) is kept


def test_a_flood_of_anonymous_sessions_stays_capped(clock: FakeClock) -> None:
    """Every ``/v1/mask`` without ``session_id`` creates one: the vault never holds more."""
    vault = Vault(TEST_KEY, ttl_seconds=3600.0, clock=clock, max_sessions=50)
    for _ in range(500):
        vault.session()
    assert len(vault) == 50


def test_max_sessions_comes_from_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_VAULT_MAX_SESSIONS", "2")
    settings = Settings(tenant_key=TEST_KEY.hex())
    assert settings.vault_max_sessions == 2
    vault = Vault.from_settings(settings)
    for _ in range(5):
        vault.session()
    assert len(vault) == 2


def test_max_sessions_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_sessions"):
        Vault(TEST_KEY, max_sessions=0)


def test_a_fork_writes_nothing_until_committed(vault: Vault) -> None:
    session = vault.session()
    fork = session.fork()
    text = f"{NAME} írt."
    masked = fork.mask(text, [span_of(text, NAME, EntityType.PERSON)])
    assert NAME not in masked
    assert session.entities() == []  # an abandoned fork leaves nothing behind

    session.commit(fork)
    assert session.unmask(masked) == text  # the placeholder the fork issued, committed
    assert [entity_type for _, entity_type, _ in session.entities()] == [EntityType.PERSON]


def test_a_fork_sees_the_values_already_in_the_session(vault: Vault) -> None:
    session = vault.session()
    text = f"{NAME}, {EMAIL}"
    session.mask(text, [span_of(text, NAME, EntityType.PERSON)])
    fork = session.fork()
    again = fork.mask(f"Üdv, {NAME}!", [])
    assert NAME not in again
    session.commit(fork)
    assert session.unmask(again) == f"Üdv, {NAME}!"


def test_a_fork_is_committed_once_and_only_to_its_session(vault: Vault) -> None:
    session, other = vault.session(), vault.session()
    fork = session.fork()
    with pytest.raises(ValueError, match="not a fork"):
        other.commit(fork)
    session.commit(fork)
    with pytest.raises(ValueError, match="not a fork"):
        session.commit(fork)


def test_commit_fails_closed_when_the_session_changed_underneath(vault: Vault) -> None:
    session = vault.session()
    fork = session.fork()
    text = f"{NAME} és {EMAIL}"
    fork.mask(text, [span_of(text, NAME, EntityType.PERSON)])
    # A concurrent request confirms the e-mail address: replaying the fork now masks more.
    session.mask(EMAIL, [span_of(EMAIL, EMAIL, EntityType.EMAIL)])
    with pytest.raises(MaskingError, match="session changed"):
        session.commit(fork)


def test_commit_to_an_expired_session_fails_closed(vault: Vault, clock: FakeClock) -> None:
    session = vault.session()
    fork = session.fork()
    fork.mask(NAME, [span_of(NAME, NAME, EntityType.PERSON)])
    session.close()
    with pytest.raises(SessionNotFoundError):
        session.commit(fork)
