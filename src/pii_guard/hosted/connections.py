"""Bounded, owner-scoped, ephemeral BYOK profiles; never a fallback credential source."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

from pydantic import SecretStr

from pii_guard.hosted.egress import validate_base_url, validate_destination
from pii_guard.types import PiiGuardError
from pii_guard.upstreams import PRESETS

PROVIDERS = (*PRESETS, "custom")


class ConnectionNotFoundError(PiiGuardError):
    code = "connection_not_found"
    status_code = 404

    def __init__(self) -> None:
        super().__init__("connection is unknown or expired")


class ConnectionLimitError(PiiGuardError):
    code = "connection_limit"
    status_code = 429

    def __init__(self) -> None:
        super().__init__("connection limit reached; delete an existing connection")


class InvalidConnectionError(PiiGuardError):
    code = "invalid_connection"
    status_code = 422

    def __init__(self) -> None:
        super().__init__("invalid provider connection")


@dataclass(frozen=True, slots=True)
class Connection:
    id: str
    owner_id: str = field(repr=False)
    provider: str
    base_url: str
    api_key: SecretStr = field(repr=False)
    expires_at: float

    def metadata(self) -> dict[str, str]:
        parts = urlsplit(self.base_url)
        return {
            "id": self.id,
            "provider": self.provider,
            "origin": f"https://{parts.netloc}",
            "expires_at": datetime.fromtimestamp(self.expires_at, UTC).isoformat(),
        }


class ConnectionStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = 3600,
        max_per_owner: int = 5,
        max_total: int = 256,
        clock: Callable[[], float] = time.time,
        validator: Callable[[str], Awaitable[str]] = validate_destination,
    ) -> None:
        if ttl_seconds <= 0 or max_per_owner < 1 or max_total < 1:
            raise ValueError("connection store limits must be positive")
        self._ttl = ttl_seconds
        self._max_per_owner = max_per_owner
        self._max_total = max_total
        self._clock = clock
        self._validator = validator
        self._connections: dict[str, Connection] = {}
        self._lock = threading.Lock()

    def _expire(self) -> None:
        now = self._clock()
        expired = [key for key, value in self._connections.items() if value.expires_at <= now]
        for key in expired:
            del self._connections[key]

    async def create(
        self,
        owner_id: str,
        provider: str,
        api_key: SecretStr,
        base_url: str | None = None,
    ) -> Connection:
        key = api_key.get_secret_value()
        if (
            not owner_id
            or provider not in PROVIDERS
            or not 1 <= len(key) <= 4096
            or any(ord(c) <= 32 or ord(c) >= 127 for c in key)
            or key.startswith("pg_")
        ):
            raise InvalidConnectionError()
        if provider == "custom":
            if base_url is None:
                raise InvalidConnectionError()
            destination = validate_base_url(base_url)
        else:
            destination = PRESETS[provider].base_url
            if base_url is not None and validate_base_url(base_url) != destination:
                raise InvalidConnectionError()
        # Preflight has no credential and no HTTP traffic. Transport checks again at use.
        destination = await self._validator(destination)
        with self._lock:
            self._expire()
            owned = sum(item.owner_id == owner_id for item in self._connections.values())
            if owned >= self._max_per_owner or len(self._connections) >= self._max_total:
                raise ConnectionLimitError()
            connection = Connection(
                secrets.token_urlsafe(24),
                owner_id,
                provider,
                destination,
                api_key,
                self._clock() + self._ttl,
            )
            self._connections[connection.id] = connection
            return connection

    def get(self, owner_id: str, connection_id: str) -> Connection:
        with self._lock:
            self._expire()
            connection = self._connections.get(connection_id)
            if connection is None or connection.owner_id != owner_id:
                raise ConnectionNotFoundError()
            return connection

    def list(self, owner_id: str) -> list[dict[str, str]]:
        with self._lock:
            self._expire()
            return [
                item.metadata() for item in self._connections.values() if item.owner_id == owner_id
            ]

    def delete(self, owner_id: str, connection_id: str) -> None:
        with self._lock:
            self._expire()
            connection = self._connections.get(connection_id)
            if connection is None or connection.owner_id != owner_id:
                raise ConnectionNotFoundError()
            del self._connections[connection_id]

    def purge_expired(self) -> None:
        """Release expired credentials even when no account requests arrive."""
        with self._lock:
            self._expire()

    def clear_owner(self, owner_id: str) -> None:
        with self._lock:
            keys = [key for key, item in self._connections.items() if item.owner_id == owner_id]
            for key in keys:
                del self._connections[key]

    def clear(self) -> None:
        with self._lock:
            self._connections.clear()
