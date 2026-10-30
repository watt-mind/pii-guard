"""Vault resource limits and staged writes (LAB-1207). All values are fictional (ADR 0005)."""

from __future__ import annotations

import pytest
from vault_helpers import TEST_KEY, FakeClock, span_of

import pii_guard.vault.session as session_module
from pii_guard.config import Settings
from pii_guard.types import EntityType, MaskingError
from pii_guard.vault import SessionNotFoundError, Vault, VaultSession

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


# --- LAB-1584: commit allow-list, image commit cost, per-identity lease cap -----------------


def test_commit_leaves_non_mask_state_written_during_the_replay(
    vault: Vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only mask state is published: a write elsewhere during a commit is never reverted."""
    session = vault.session()
    fork = session.fork()
    fork.mask(NAME, [span_of(NAME, NAME, EntityType.PERSON)])
    original = VaultSession.mask_with_report

    def replay(self: VaultSession, *args: object, **kwargs: object) -> object:
        # Lands on the parent while its commit replays into the staged copy.
        session._entry_limit = 7
        session.owner = "f" * 64
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(VaultSession, "mask_with_report", replay)
    session.commit(fork)
    monkeypatch.undo()
    assert session._entry_limit == 7
    assert session.owner == "f" * 64
    assert session.unmask(session.mask(NAME, [])) == NAME


def test_image_commit_does_not_deep_copy_the_memo_caches(
    vault: Vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = vault.session()
    history = f"{NAME} írt. " + "x" * 50_000
    session.mask(history, [span_of(history, NAME, EntityType.PERSON)])
    assert session._masked and session._folds
    memo, folds = session._masked, session._folds
    fork = session.fork()
    fork.mask(EMAIL, [span_of(EMAIL, EMAIL, EntityType.EMAIL)])
    copied: list[int] = []
    deepcopy = session_module.copy.deepcopy

    def spy(value: object, memo_: object = None) -> object:
        copied.append(id(value))
        if isinstance(value, dict):
            copied.extend(id(item) for item in value.values())
        return deepcopy(value, memo_)  # type: ignore[arg-type]

    monkeypatch.setattr(session_module.copy, "deepcopy", spy)
    session.commit(fork)
    monkeypatch.undo()
    assert copied, "commit stages a copy of the mask state"
    assert id(memo) not in copied
    assert id(folds) not in copied
    assert session._masked is not memo and session._folds is not folds  # reset, not copied
    assert session._masked_chars == sum(len(key[0]) for key in session._masked)
    assert NAME not in session.mask(history, [])  # the mapping survives the reset memo


def _lease(vault: Vault, identity: str) -> VaultSession:
    session, _, _ = vault.acquire_session(lambda: (vault.session(), True, None), identity=identity)
    return session


def test_one_identity_cannot_pin_every_session_slot(clock: FakeClock) -> None:
    """The ~10k in-flight streams scenario, scaled down: the over-cap identity gets 503, the
    others still acquire (LAB-1584)."""
    vault = Vault(TEST_KEY, clock=clock, max_sessions=10, max_leases_per_identity=3)
    flood = [_lease(vault, "a" * 64) for _ in range(3)]
    created = len(vault)
    with pytest.raises(MaskingError) as error:
        _lease(vault, "a" * 64)
    assert error.value.code == "vault_capacity_exhausted"
    assert error.value.status_code == 503
    assert len(vault) == created  # refused before resolving: nothing created for it
    other = _lease(vault, "b" * 64)
    anonymous = _lease(vault, "anonymous")
    vault.release_session(flood.pop(), identity="a" * 64)
    flood.append(_lease(vault, "a" * 64))  # a slot of its own is free again
    for session in flood:
        vault.release_session(session, identity="a" * 64)
    vault.release_session(other, identity="b" * 64)
    vault.release_session(anonymous, identity="anonymous")
    assert not vault._leases
    assert not vault._identity_leases


def test_releasing_an_identity_without_a_lease_fails_closed(vault: Vault) -> None:
    session = _lease(vault, "a" * 64)
    with pytest.raises(ValueError, match="identity has no lease"):
        vault.release_session(session, identity="b" * 64)
    assert vault._leases[session] == 1  # nothing released by the refused call
    vault.release_session(session, identity="a" * 64)


def test_max_leases_per_identity_comes_from_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_VAULT_MAX_LEASES_PER_IDENTITY", "1")
    settings = Settings(tenant_key=TEST_KEY.hex())
    assert settings.vault_max_leases_per_identity == 1
    vault = Vault.from_settings(settings)
    _lease(vault, "a" * 64)
    with pytest.raises(MaskingError, match="too many active requests"):
        _lease(vault, "a" * 64)
    with pytest.raises(ValueError, match="max_leases_per_identity"):
        Vault(TEST_KEY, max_leases_per_identity=0)
