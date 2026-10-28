"""Owner-scoped state; only detectors and bounded compute workers are shared."""

from __future__ import annotations

import hmac
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request

from pii_guard.api.routes.vault import SessionDirectory
from pii_guard.config import Settings
from pii_guard.gateway.cache import DetectionCache
from pii_guard.gateway.config import GatewayConfig, Mode
from pii_guard.gateway.detection import ModeDetector
from pii_guard.gateway.service import Gateway
from pii_guard.hosted.abuse import AbuseAdmission
from pii_guard.hosted.connections import ConnectionStore
from pii_guard.hosted.egress import SecureTransport
from pii_guard.hosted.identity import ApiKeyStore, GuestIdentity, Principal
from pii_guard.hosted.quotas import QuotaLedger, QuotaLimits
from pii_guard.observability import Observability, ObservabilitySettings, TrafficLevel
from pii_guard.types import Analyzer, PiiGuardError, Span
from pii_guard.vault import Vault
from pii_guard.workers import BoundedWorkers


class HostedCapacityError(PiiGuardError):
    code = "hosted_capacity"
    status_code = 429


class HostedVault(Vault):
    """Refuse session growth rather than evicting a session an active stream may use."""

    def _evict_locked(self, keep: int) -> None:
        if len(self._sessions) > keep:
            raise HostedCapacityError("Session capacity reached; delete an unused session")

    def close(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                session.close()
            self._sessions.clear()
            self._generations.clear()
            self._tenant_key = b""


@dataclass(repr=False)
class Runtime:
    vault: HostedVault
    cache: DetectionCache
    observability: Observability
    directory: SessionDirectory
    touched: float = field(default_factory=time.monotonic)
    active: int = 0
    session_holds: dict[str, Any] = field(default_factory=dict)
    holds_lock: Any = field(default_factory=threading.Lock)


class BoundedAnalyzer:
    def __init__(self, inner: Analyzer, slots: threading.BoundedSemaphore) -> None:
        self.inner, self.slots = inner, slots
        self.pipeline = getattr(inner, "pipeline", None)

    def analyze(self, text: str, language: str) -> list[Span]:
        if not self.slots.acquire(blocking=False):
            raise HostedCapacityError("Detection capacity reached; try later")
        try:
            return self.inner.analyze(text, language)
        finally:
            self.slots.release()


class HostedService:
    def __init__(self, settings: Settings) -> None:
        key = settings.tenant_key_bytes()
        origin = urlsplit(settings.hosted_public_origin or "")
        if (
            not settings.hosted_trust_easy_auth
            or not settings.hosted_single_process
            or key is None
            or len(key) < 32
            or origin.scheme != "https"
            or not origin.hostname
            or origin.port not in (None, 443)
            or origin.username is not None
            or origin.password is not None
            or origin.path not in ("", "/")
            or origin.query
            or origin.fragment
            or settings.api_token is not None
            or not settings.hosted_models
            or (settings.detectors and any(d not in {"rules", "ner"} for d in settings.detectors))
        ):
            raise ValueError(
                "Hosted mode requires trusted ingress, one process, HTTPS origin, "
                "a 32-byte tenant key and local fast detectors"
            )
        self.settings = settings
        self.master_key = key
        self.origin = f"https://{origin.hostname}"
        self.keys = ApiKeyStore()
        self.guests = GuestIdentity(key, ttl_seconds=settings.hosted_runtime_ttl)
        self.connections = ConnectionStore(ttl_seconds=settings.hosted_runtime_ttl)
        self.abuse = AbuseAdmission(settings.hosted_client_ip_source)
        self.quotas = QuotaLedger(
            QuotaLimits(
                input_microdollars_per_token=settings.hosted_input_microdollars_per_token,
                output_microdollars_per_token=settings.hosted_output_microdollars_per_token,
            ),
            sponsored_allocation_microdollars=settings.hosted_sponsored_microdollars,
            allocation_id=settings.hosted_sponsored_allocation_id,
            allocation_directory=settings.hosted_allocation_directory,
            allocation_expires_at=settings.hosted_allocation_expires_at,
        )
        self._runtimes: dict[str, Runtime] = {}
        self._lock = threading.Lock()
        self.rest_slots = threading.BoundedSemaphore(4)
        self._ingress = 0
        self._workers = {Mode.FAST: BoundedWorkers(4, "pii-guard-hosted-fast")}

    def acquire(self, principal: Principal) -> Runtime:
        self.purge_expired()
        with self._lock:
            now = time.monotonic()
            runtime = self._runtimes.get(principal.id)
            if runtime is None:
                if len(self._runtimes) >= self.settings.hosted_max_principals:
                    raise HostedCapacityError("Hosted runtime capacity reached; try later")
                key = hmac.digest(self.master_key, b"vault\0" + principal.id.encode(), "sha256")
                runtime = Runtime(
                    HostedVault(
                        key,
                        ttl_seconds=self.settings.hosted_runtime_ttl,
                        max_sessions=self.settings.hosted_max_sessions,
                        max_entries=2000,
                        max_restored_chars=100000,
                    ),
                    DetectionCache(256, ttl_seconds=self.settings.hosted_runtime_ttl),
                    Observability(
                        ObservabilitySettings(
                            traffic_log=TrafficLevel.MASKED,
                            traffic_log_size=50,
                            metrics=False,
                            server_timing=False,
                        )
                    ),
                    SessionDirectory(self.settings.hosted_max_sessions),
                )
                self._runtimes[principal.id] = runtime
            runtime.active += 1
            runtime.touched = now
            return runtime

    def release(self, runtime: Runtime) -> None:
        with self._lock:
            runtime.active -= 1
            runtime.touched = time.monotonic()

    def purge_expired(self) -> None:
        with self._lock:
            now = time.monotonic()
            for owner, runtime in list(self._runtimes.items()):
                if not runtime.active and now - runtime.touched >= self.settings.hosted_runtime_ttl:
                    runtime.vault.close()
                    self.connections.clear_owner(owner)
                    del self._runtimes[owner]
        self.keys.purge_expired()
        self.connections.purge_expired()
        self.abuse.purge_expired()

    def provider_settings(self, request: Request) -> Settings:
        connection = getattr(request.state, "hosted_connection", None)
        return self.settings.model_copy(
            update={
                "upstream_base_url": connection.base_url
                if connection
                else "https://api.meta.ai/v1",
                "upstream_api_key": connection.api_key
                if connection
                else self.settings.upstream_api_key,
                "segmenter": "off",
            }
        )

    def gateway(self, request: Request) -> Gateway:
        existing = getattr(request.state, "hosted_gateway", None)
        if existing is not None:
            return existing
        from pii_guard.api.deps import get_analyzer

        runtime = request.state.hosted_runtime
        analyzer = get_analyzer(request)
        # RegistryAnalyzer's pipeline is shared across all owners and REST/gateway requests.
        detectors = getattr(request.app.state, "gateway_detectors", None)
        if detectors is None:
            pipeline = getattr(analyzer, "pipeline", None)
            if pipeline is None:
                raise PiiGuardError("Hosted detector configuration unavailable")
            detectors = {
                Mode.FAST: ModeDetector(
                    Mode.FAST, pipeline, "hosted-fast", request.app.state.policies, batches=True
                )
            }
        gateway = Gateway(
            settings=self.provider_settings(request),
            vault=runtime.vault,
            config=GatewayConfig(
                mode=Mode.FAST,
                max_images=0,
                upstream_timeout=120,
                cache_size=256,
                concurrency=4,
            ),
            detectors=detectors,
            cache=runtime.cache,
            transport=SecureTransport(),
            observability=runtime.observability,
        )
        gateway._detect_workers = self._workers
        gateway._session_holds = runtime.session_holds
        gateway._holds_lock = runtime.holds_lock
        request.state.hosted_gateway = gateway
        return gateway

    async def close(self) -> None:
        with self._lock:
            for runtime in self._runtimes.values():
                runtime.vault.close()
            self._runtimes.clear()
        self.keys.clear()
        self.connections.clear()
        for workers in self._workers.values():
            workers.close()

    def enter_ingress(self) -> None:
        with self._lock:
            if self._ingress >= 32:
                raise HostedCapacityError("Request capacity reached; try later")
            self._ingress += 1

    def leave_ingress(self) -> None:
        with self._lock:
            self._ingress -= 1


def hosted_state(request: Request, name: str) -> Any:
    """Return an owner-scoped dependency, or the original local app dependency."""
    runtime = getattr(request.state, "hosted_runtime", None)
    if runtime is not None:
        return getattr(runtime, name)
    return getattr(request.app.state, name, None)
