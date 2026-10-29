"""Vault fixtures. All values are fictional (ADR 0005)."""

from __future__ import annotations

import pytest
from vault_helpers import TEST_KEY, FakeClock

from pii_guard.vault import Vault


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def vault(clock: FakeClock) -> Vault:
    return Vault(TEST_KEY, ttl_seconds=60.0, clock=clock)
