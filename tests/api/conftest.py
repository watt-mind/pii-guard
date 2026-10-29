"""API fixtures. All values are fictional (ADR 0005); the tenant key is a fixed test key."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from api_helpers import TEST_TENANT_KEY
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings


@pytest.fixture
def api_settings() -> Settings:
    return Settings(tenant_key=TEST_TENANT_KEY)


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(api_settings), raise_server_exceptions=False) as client:
        yield client
