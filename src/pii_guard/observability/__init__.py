"""Observability of the gateway: traffic events, per-stage timing and latency metrics.

One :class:`Observability` per app (``app.state.observability``), built by
:func:`pii_guard.api.app.create_app` from :class:`ObservabilitySettings`. The gateway always
times its stages (a handful of ``perf_counter`` calls); it builds and stores an event only
when the traffic log, the metrics or the remote exporter are on. See ``docs/operations.md``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pii_guard.observability.config import (
    ObservabilitySettings,
    RemoteTrafficLevel,
    TrafficLevel,
    TrafficLogConfigError,
    check_bind,
    is_loopback,
)
from pii_guard.observability.metrics import LatencyMetrics
from pii_guard.observability.remote import (
    RemoteTrafficExporter,
    resolve_ingest_url,
    sanitize_for_remote,
)
from pii_guard.observability.timing import STAGES, RequestTimer
from pii_guard.observability.traffic import REDACTED, TrafficLog, scrub

__all__ = [
    "REDACTED",
    "STAGES",
    "LatencyMetrics",
    "Observability",
    "ObservabilitySettings",
    "RemoteTrafficExporter",
    "RemoteTrafficLevel",
    "RequestTimer",
    "TrafficLevel",
    "TrafficLog",
    "TrafficLogConfigError",
    "build_remote_exporter",
    "check_bind",
    "is_loopback",
    "resolve_ingest_url",
    "sanitize_for_remote",
    "scrub",
]


def build_remote_exporter(settings: ObservabilitySettings) -> RemoteTrafficExporter | None:
    """The exporter ``PII_GUARD_REMOTE_URL`` asks for, or ``None``. One per app."""
    if not settings.remote_url:
        return None
    key = settings.remote_key.get_secret_value() if settings.remote_key else None
    return RemoteTrafficExporter(settings.remote_url, api_key=key, level=settings.remote_level)


class Observability:
    """The traffic log, the metrics (or ``None``), the remote exporter and ``Server-Timing``."""

    def __init__(
        self,
        settings: ObservabilitySettings | None = None,
        *,
        secrets: Iterable[str] = (),
        remote: RemoteTrafficExporter | None = None,
    ) -> None:
        settings = settings or ObservabilitySettings()
        self.settings = settings
        self.traffic = TrafficLog(settings.traffic_log, settings.traffic_log_size)
        self.metrics = LatencyMetrics() if settings.metrics else None
        self.server_timing = settings.server_timing
        remote_key = settings.remote_key.get_secret_value() if settings.remote_key else None
        all_secrets = [*(s for s in secrets if s), *([remote_key] if remote_key else [])]
        self._secrets = tuple(all_secrets)
        # Only the app-level instance gets an exporter (``build_remote_exporter``): runtimes and
        # per-request instances are built often and must never start a thread (LAB-1704).
        self.remote: RemoteTrafficExporter | None = remote

    def __repr__(self) -> str:
        return (
            f"Observability(traffic={self.traffic.level.value}, "
            f"metrics={self.metrics is not None}, server_timing={self.server_timing}, "
            f"remote={self.remote.url if self.remote is not None else None})"
        )

    @property
    def recording(self) -> bool:
        """Whether gateway calls produce events (traffic log, metrics or remote exporter on)."""
        return self.traffic.enabled or self.metrics is not None or self.remote is not None

    @property
    def payloads(self) -> bool:
        """Whether events attach masked payloads (local traffic log or masked remote exporter)."""
        return self.traffic.enabled or (
            self.remote is not None and self.remote.level is RemoteTrafficLevel.MASKED
        )

    def scrub(self, value: Any) -> Any:
        return scrub(value, self._secrets)

    def record(self, event: dict[str, Any]) -> None:
        if self.metrics is not None:
            self.metrics.observe(event["mode"] or "-", event["outcome"], event["timing"], event)
        self.traffic.publish(event)
        if self.remote is not None:
            self.remote.enqueue(self.scrub(event))

    def flush(self, timeout: float = 5.0) -> None:
        """Flush any queued remote telemetry events."""
        if self.remote is not None:
            self.remote.flush(timeout=timeout)

    def close(self, timeout: float = 5.0) -> None:
        """Flush and close the remote telemetry exporter, if configured."""
        if self.remote is not None:
            self.remote.close(timeout=timeout)
