"""Observability settings: the traffic log, ``Server-Timing`` headers and ``/metrics``.

| Env var | Field | Default |
|---|---|---|
| ``PII_GUARD_TRAFFIC_LOG`` | ``traffic_log`` (``off`` / ``masked`` / ``full``) | ``off`` |
| ``PII_GUARD_TRAFFIC_LOG_SIZE`` | ``traffic_log_size`` (events kept in memory) | ``200`` |
| ``PII_GUARD_SERVER_TIMING`` | ``server_timing`` (``Server-Timing`` response header) | ``false`` |
| ``PII_GUARD_METRICS`` | ``metrics`` (Prometheus text at ``GET /metrics``) | ``false`` |
| ``PII_GUARD_REMOTE_URL`` | ``remote_url`` (remote dashboard URL for telemetry) | ``None`` |
| ``PII_GUARD_REMOTE_KEY`` | ``remote_key`` (bearer key for remote telemetry ingest) | ``None`` |
| ``PII_GUARD_REMOTE_LEVEL`` | ``remote_level`` (``masked`` / ``stats``) | ``masked`` |

``full`` keeps the original (unmasked) request and the restored answer next to what was sent
upstream. It is refused unless the server binds to a loopback address (:func:`check_bind`):
the API and ``pii-guard serve`` stop at startup instead, and so does an allowed ``Host`` list
(``PII_GUARD_ALLOWED_HOSTS``) with a name other than a loopback one (:func:`check_allowed_hosts`).
A launcher that binds elsewhere than ``PII_GUARD_HOST`` (``uvicorn --host 0.0.0.0``) is caught
per request: the API answers 403 to any connection that is not loopback on both ends. See
``docs/operations.md``.
"""

from __future__ import annotations

import ipaddress
from enum import StrEnum

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "ObservabilitySettings",
    "RemoteTrafficLevel",
    "TrafficLevel",
    "TrafficLogConfigError",
    "check_allowed_hosts",
    "check_bind",
    "is_loopback",
]


class TrafficLevel(StrEnum):
    """``off``: no events. ``masked``: only what left the machine. ``full``: also originals."""

    OFF = "off"
    MASKED = "masked"
    FULL = "full"


class RemoteTrafficLevel(StrEnum):
    """What leaves the local gateway when shipping telemetry to a remote dashboard."""

    MASKED = "masked"
    STATS = "stats"


class TrafficLogConfigError(ValueError):
    """``PII_GUARD_TRAFFIC_LOG=full`` on a server reachable from other machines."""


class ObservabilitySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PII_GUARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    traffic_log: TrafficLevel = TrafficLevel.OFF
    traffic_log_size: int = Field(default=200, ge=1, le=10_000)
    server_timing: bool = False
    metrics: bool = False
    remote_url: str | None = None
    remote_key: SecretStr | None = None
    remote_level: RemoteTrafficLevel = RemoteTrafficLevel.MASKED


def is_loopback(host: str) -> bool:
    """``127.0.0.1``, ``::1``, any ``127/8`` address and ``localhost`` are loopback."""
    host = host.strip().strip("[]")
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False  # a host name other than localhost, or 0.0.0.0 / :: (all interfaces)


def check_bind(level: TrafficLevel, host: str) -> None:
    """Refuse ``full`` on a non-loopback bind: originals must never be served off the machine."""
    if level is TrafficLevel.FULL and not is_loopback(host):
        raise TrafficLogConfigError(
            f"PII_GUARD_TRAFFIC_LOG=full is only allowed when the server binds to a loopback "
            f"address (127.0.0.1, ::1, localhost), not {host!r}; use 'masked' or bind locally"
        )


def check_allowed_hosts(level: TrafficLevel, hosts: list[str]) -> None:
    """Refuse ``full`` when the API answers ``Host`` names other than loopback ones."""
    if level is not TrafficLevel.FULL:
        return
    public = [h for h in hosts if not is_loopback(h)]
    if public:
        raise TrafficLogConfigError(
            "PII_GUARD_TRAFFIC_LOG=full is only allowed when the API answers loopback host names "
            f"only; PII_GUARD_ALLOWED_HOSTS also allows {', '.join(public)}"
        )
