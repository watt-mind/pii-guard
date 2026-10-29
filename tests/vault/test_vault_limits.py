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


def test_late_commit_mismatch_preserves_all_parent_state(vault: Vault) -> None:
    session = vault.session()
    fork = session.fork()
    fork.mask(NAME, [span_of(NAME, NAME, EntityType.PERSON)])
    fork.mask(EMAIL, [])  # only this second journal entry will mismatch
    session.mask(EMAIL, [span_of(EMAIL, EMAIL, EntityType.EMAIL)])
    before = session.entities()
    generation = session.generation
    expiry = session._expires_at
    scans = session.entries_scanned
    with pytest.raises(MaskingError, match="session changed"):
        session.commit(fork)
    assert session._expires_at == expiry
    assert session.entries_scanned == scans
    assert session.entities() == before
    assert session.entry_count == len(before)
    assert session.generation == generation
    assert session.mask(NAME, []) == NAME
    assert session.entities() == before


def test_leases_skip_lru_and_refuse_when_every_slot_is_pinned(clock: FakeClock) -> None:
    vault = Vault(TEST_KEY, clock=clock, max_sessions=2)
    pinned, _, _ = vault.acquire_session(lambda: (*vault.session_or_create("active"), None))
    idle = vault.session()
    clock.now += 1
    replacement = vault.session()
    assert idle.expired
    assert not pinned.expired
    vault.acquire_session(lambda: (replacement, False, None))
    with pytest.raises(MaskingError) as error:
        vault.session()
    assert error.value.code == "vault_capacity_exhausted"
    assert error.value.status_code == 503
    assert len(vault) == 2
    vault.release_session(pinned)
    vault.session()
    assert pinned.expired
    vault.release_session(replacement)
    assert not vault._leases


@pytest.mark.parametrize("remove", ["ttl", "drop"])
def test_lease_does_not_override_expiry_or_explicit_drop(remove: str, clock: FakeClock) -> None:
    vault = Vault(TEST_KEY, clock=clock, ttl_seconds=2, max_sessions=1)
    session, _, _ = vault.acquire_session(lambda: (*vault.session_or_create("active"), None))
    if remove == "ttl":
        clock.now += 3
        assert vault.purge_expired() == 1
    else:
        vault.drop(session.session_id)
    assert session.expired
    assert len(vault) == 0
    vault.release_session(session)
    assert not vault._leases


def test_lookup_and_pin_share_the_vault_lock() -> None:
    import threading

    vault = Vault(TEST_KEY, max_sessions=1)
    attempted = threading.Event()
    finished = threading.Event()
    errors = []

    def compete() -> None:
        attempted.set()
        try:
            vault.session()
        except MaskingError as error:
            errors.append(error.code)
        finally:
            finished.set()

    def resolve():
        session = vault.session()
        thread.start()
        assert attempted.wait(5)
        assert not finished.wait(0.05)  # cannot evict between lookup and pin
        return session, True, None

    thread = threading.Thread(target=compete)
    session, _, _ = vault.acquire_session(resolve)
    thread.join(5)
    assert finished.is_set()
    assert errors == ["vault_capacity_exhausted"]
    assert not session.expired
    vault.release_session(session)
