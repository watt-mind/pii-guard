"""Observability of the gateway: traffic events, per-stage timing and latency metrics.

One :class:`Observability` per app (``app.state.observability``), built by
:func:`pii_guard.api.app.create_app` from :class:`ObservabilitySettings`. The gateway always
times its stages (a handful of ``perf_counter`` calls); it builds and stores an event only
when the traffic log or the metrics are on. See ``docs/operations.md``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pii_guard.observability.config import (
    ObservabilitySettings,
    TrafficLevel,
    TrafficLogConfigError,
    check_bind,
    is_loopback,
)
from pii_guard.observability.metrics import LatencyMetrics
from pii_guard.observability.timing import STAGES, RequestTimer
from pii_guard.observability.traffic import REDACTED, TrafficLog, scrub

__all__ = [
    "REDACTED",
    "STAGES",
    "LatencyMetrics",
    "Observability",
    "ObservabilitySettings",
    "RequestTimer",
    "TrafficLevel",
    "TrafficLog",
    "TrafficLogConfigError",
    "check_bind",
    "is_loopback",
    "scrub",
]


class Observability:
    """The traffic log, the metrics (or ``None``) and the ``Server-Timing`` switch."""

    def __init__(
        self,
        settings: ObservabilitySettings | None = None,
        *,
        secrets: Iterable[str] = (),
    ) -> None:
        settings = settings or ObservabilitySettings()
        self.settings = settings
        self.traffic = TrafficLog(settings.traffic_log, settings.traffic_log_size)
        self.metrics = LatencyMetrics() if settings.metrics else None
        self.server_timing = settings.server_timing
        self._secrets = tuple(s for s in secrets if s)

    def __repr__(self) -> str:
        return (
            f"Observability(traffic={self.traffic.level.value}, "
            f"metrics={self.metrics is not None}, server_timing={self.server_timing})"
        )

    @property
    def recording(self) -> bool:
        """Whether gateway calls produce events (traffic log or metrics on)."""
        return self.traffic.enabled or self.metrics is not None

    def scrub(self, value: Any) -> Any:
        return scrub(value, self._secrets)

    def record(self, event: dict[str, Any]) -> None:
        if self.metrics is not None:
            self.metrics.observe(event["mode"] or "-", event["outcome"], event["timing"], event)
        self.traffic.publish(event)
