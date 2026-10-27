"""Get-or-create sessions, derived ids and the per-session entry cap (LAB-1286).

All values are fictional (ADR 0005).
"""

from __future__ import annotations

import logging
import re

import pytest
from vault_helpers import TEST_KEY, FakeClock, span_of

from pii_guard.config import Settings
from pii_guard.types import EntityType
from pii_guard.vault import DEFAULT_MAX_ENTRIES, SessionNotFoundError, Vault

EMAILS = ("teszt.elek@example.com", "minta.maria@example.org", "jane.placeholder@example.net")


def mask_email(vault: Vault, session_id: str, email: str) -> str:
    session = vault.session(session_id)
    return session.mask(email, [span_of(email, email, EntityType.EMAIL)])


def test_session_or_create_creates_once(vault: Vault) -> None:
    session, created = vault.session_or_create("box")
    assert created and session.session_id == "box"
    again, created = vault.session_or_create("box")
    assert again is session and not created
    assert vault.session("box") is session  # addressable by id afterwards
    with pytest.raises(ValueError):
        vault.session_or_create("")


def test_session_still_404s_for_unknown_ids(vault: Vault) -> None:
    with pytest.raises(SessionNotFoundError):
        vault.session("never-created")
    assert len(vault) == 0


def test_an_expired_get_or_create_session_starts_empty(vault: Vault, clock: FakeClock) -> None:
    session, _ = vault.session_or_create("box")
    first = mask_email(vault, "box", EMAILS[0])
    clock.now += 61
    fresh, created = vault.session_or_create("box")
    assert created and fresh is not session and fresh.entry_count == 0
    # Same id, same tenant key: the same placeholder as before (ids are derived).
    assert mask_email(vault, "box", EMAILS[0]) == first


def test_derived_ids_are_keyed_and_fit_the_session_grammar() -> None:
    a = Vault(TEST_KEY)
    b = Vault(bytes(range(32)))
    derived = a.derive_session_id("default:anonymous")
    assert re.fullmatch(r"d_[0-9a-f]{32}", derived)
    assert derived == Vault(TEST_KEY).derive_session_id("default:anonymous")
    assert derived != b.derive_session_id("default:anonymous")
    assert derived != a.derive_session_id("default:someone-else")


def test_a_full_session_rotates_to_a_new_generation(
    clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    vault = Vault(TEST_KEY, ttl_seconds=60.0, clock=clock, max_entries=2)
    gen0, _ = vault.session_or_create("box")
    mask_email(vault, "box", EMAILS[0])
    assert vault.session_or_create("box") == (gen0, False)  # 1 of 2
    mask_email(vault, "box", EMAILS[1])
    with caplog.at_level(logging.INFO, logger="pii_guard.vault.vault"):
        gen1, created = vault.session_or_create("box")
    assert created and gen1 is not gen0 and gen1.session_id != "box"
    assert gen1.entry_count == 0
    assert [r.getMessage() for r in caplog.records].count(
        "vault: a session reached 2 placeholders; starting generation 1"
    ) == 1
    assert "teszt" not in caplog.text and "box" not in caplog.text
    # The new generation is the one handed out from now on; the old one is still addressable
    # by its id (an in-flight request) until its TTL ends.
    assert vault.session_or_create("box") == (gen1, False)
    assert vault.session("box") is gen0
    # Rotation is deterministic: generation ids are derived from the base id.
    other = Vault(TEST_KEY, ttl_seconds=60.0, clock=clock, max_entries=2)
    other.session_or_create("box")
    for email in EMAILS[:2]:
        mask_email(other, "box", email)
    assert other.session_or_create("box")[0].session_id == gen1.session_id


def test_rotation_state_is_forgotten_with_the_sessions(clock: FakeClock) -> None:
    vault = Vault(TEST_KEY, ttl_seconds=60.0, clock=clock, max_entries=1)
    vault.session_or_create("box")
    mask_email(vault, "box", EMAILS[0])
    rotated, _ = vault.session_or_create("box")
    assert rotated.session_id != "box"
    clock.now += 61
    assert vault.purge_expired() == 2
    fresh, created = vault.session_or_create("box")
    assert created and fresh.session_id == "box"  # back to generation 0


def test_max_entries_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings(tenant_key=TEST_KEY.hex()).vault_max_entries == DEFAULT_MAX_ENTRIES
    monkeypatch.setenv("PII_GUARD_VAULT_MAX_ENTRIES", "1")
    vault = Vault.from_settings(Settings(tenant_key=TEST_KEY.hex()))
    vault.session_or_create("box")
    mask_email(vault, "box", EMAILS[0])
    assert vault.session_or_create("box")[0].session_id != "box"
    with pytest.raises(ValueError, match="max_entries"):
        Vault(TEST_KEY, max_entries=0)
