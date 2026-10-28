"""Owner isolation, credential lifecycle, immutable destinations and bounded admission."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest
from pydantic import SecretStr

from pii_guard.hosted.connections import (
    ConnectionLimitError,
    ConnectionNotFoundError,
    ConnectionStore,
    InvalidConnectionError,
)


async def validate(url: str) -> str:
    return url


def test_owner_isolation_revocation_and_secret_metadata() -> None:
    async def run() -> None:
        store = ConnectionStore(validator=validate)
        connection = await store.create("owner-a", "openai", SecretStr("fictional-secret"))
        assert store.get("owner-a", connection.id) is connection
        assert "fictional-secret" not in repr(connection)
        assert "fictional-secret" not in str(connection.metadata())
        assert set(connection.metadata()) == {"id", "provider", "origin", "expires_at"}
        assert connection.metadata()["origin"] == "https://api.openai.com"
        assert store.list("owner-b") == []
        for action in (store.get, store.delete):
            with pytest.raises(ConnectionNotFoundError):
                action("owner-b", connection.id)
        with pytest.raises(FrozenInstanceError):
            connection.base_url = "https://other.example.com"  # type: ignore[misc]
        store.delete("owner-a", connection.id)
        with pytest.raises(ConnectionNotFoundError):
            store.get("owner-a", connection.id)

    asyncio.run(run())


def test_expiry_caps_and_clear() -> None:
    async def run() -> None:
        now = [1000.0]
        store = ConnectionStore(
            ttl_seconds=10, max_per_owner=1, max_total=2, clock=lambda: now[0], validator=validate
        )
        connection = await store.create("a", "meta", SecretStr("fictional"))
        with pytest.raises(ConnectionLimitError):
            await store.create("a", "openai", SecretStr("fictional"))
        await store.create("b", "openai", SecretStr("fictional"))
        with pytest.raises(ConnectionLimitError):
            await store.create("c", "openai", SecretStr("fictional"))
        now[0] += 10
        with pytest.raises(ConnectionNotFoundError):
            store.get("a", connection.id)
        assert store.list("b") == []
        await store.create("a", "openai", SecretStr("fictional"))
        await store.create("b", "openai", SecretStr("fictional"))
        store.clear_owner("a")
        assert not store.list("a")
        assert store.list("b")
        store.clear()
        assert not store.list("b")

    asyncio.run(run())


def test_concurrent_cap_does_not_evict_others() -> None:
    async def run() -> None:
        store = ConnectionStore(max_per_owner=2, validator=validate)
        outcomes = await asyncio.gather(
            *[
                store.create("a", "custom", SecretStr("fictional"), "https://api.example.com/v1")
                for _ in range(20)
            ],
            return_exceptions=True,
        )
        assert sum(isinstance(item, ConnectionLimitError) for item in outcomes) == 18
        assert len(store.list("a")) == 2
        assert len({item["id"] for item in store.list("a")}) == 2

    asyncio.run(run())


@pytest.mark.parametrize(
    "provider,key,url",
    [
        ("unknown", "fictional", None),
        ("custom", "fictional", None),
        ("openai", "fictional", "https://attacker.example.com/v1"),
        ("meta", "fictional", "https://api.meta.ai/other"),
        ("openai", "", None),
        ("openai", "with space", None),
        ("openai", "with\nnewline", None),
        ("openai", "x" * 4097, None),
        ("openai", "pg_fictional-guard-key", None),
    ],
)
def test_invalid_connection_never_validates_or_stores(
    provider: str, key: str, url: str | None
) -> None:
    async def run() -> None:
        async def forbidden(url: str) -> str:
            raise AssertionError("must reject before DNS")

        store = ConnectionStore(validator=forbidden)
        with pytest.raises(InvalidConnectionError):
            await store.create("a", provider, SecretStr(key), url)
        assert store.list("a") == []

    asyncio.run(run())


def test_presets_fixed_custom_normalized_and_validation_failure_not_saved() -> None:
    async def run() -> None:
        store = ConnectionStore(validator=validate)
        for provider in ("meta", "openai", "fireworks", "openrouter"):
            connection = await store.create("a", provider, SecretStr("fictional"))
            assert connection.provider == provider
        custom = await store.create(
            "a", "custom", SecretStr("fictional"), "https://API.EXAMPLE.COM:443/api/v1/"
        )
        assert custom.base_url == "https://api.example.com/api/v1"

        async def failed(url: str) -> str:
            raise RuntimeError("DNS failed")

        store = ConnectionStore(validator=failed)
        with pytest.raises(RuntimeError):
            await store.create("a", "openai", SecretStr("fictional"))
        assert store.list("a") == []

    asyncio.run(run())


@pytest.mark.parametrize("kwargs", [{"ttl_seconds": 0}, {"max_per_owner": 0}, {"max_total": 0}])
def test_invalid_store_limits(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        ConnectionStore(**kwargs)


def test_periodic_purge_releases_expired_credentials_without_lookup() -> None:
    async def run() -> None:
        now = [1000.0]
        store = ConnectionStore(ttl_seconds=10, clock=lambda: now[0], validator=validate)
        expired = await store.create("a", "meta", SecretStr("fictional-expired"))
        now[0] += 5
        active = await store.create("b", "openai", SecretStr("fictional-active"))
        now[0] += 5
        store.purge_expired()
        # Inspect retained references before get/list can perform their own lazy expiration.
        assert expired.id not in store._connections
        assert store._connections == {active.id: active}
        now[0] += 5
        store.purge_expired()
        assert store._connections == {}
        store.purge_expired()

    asyncio.run(run())
