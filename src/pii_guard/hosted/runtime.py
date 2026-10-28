"""Owner-scoped state; only detectors and bounded compute workers are shared."""

from __future__ import annotations

import asyncio
import hmac
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
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
from pii_guard.hosted.quotas import QuotaLedger, QuotaLimits, SponsoredUnavailableError
from pii_guard.hosted.spend import azure_spend
from pii_guard.observability import Observability, ObservabilitySettings, TrafficLevel
from pii_guard.types import Analyzer, PiiGuardError, Span
from pii_guard.vault import Vault
from pii_guard.workers import BoundedWorkers

if TYPE_CHECKING:
    from pii_guard.projects.runtime import ProjectService


class HostedCapacityError(PiiGuardError):
    code = "hosted_capacity"
    status_code = 429


class SessionBudget:
    """One account session ceiling shared by all project and endpoint namespaces."""

    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.lock = threading.RLock()
        self.vaults: list[HostedVault] = []


class HostedVault(Vault):
    """Refuse session growth rather than evicting a session an active stream may use."""

    def __init__(self, *args: Any, budget: SessionBudget | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._budget = budget
        if budget is not None:
            with budget.lock:
                budget.vaults.append(self)

    def _create_locked(self, session_id: str) -> Any:
        budget = self._budget
        if budget is None:
            return super()._create_locked(session_id)
        with budget.lock:
            if sum(len(vault._sessions) for vault in budget.vaults) >= budget.maximum:
                raise HostedCapacityError(
                    "Account session capacity reached; delete an unused session"
                )
            return super()._create_locked(session_id)

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
        if self._budget is not None:
            with self._budget.lock:
                if self in self._budget.vaults:
                    self._budget.vaults.remove(self)


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
    def __init__(self, settings: Settings, *, projects: ProjectService | None = None) -> None:
        from pii_guard.projects.runtime import ProjectService

        self.projects = projects or ProjectService(settings)
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
            sponsored_allocation_microdollars=settings.hosted_sponsored_microdollars
            if settings.hosted_spend_store == "marker"
            else 0,
            allocation_id=settings.hosted_sponsored_allocation_id,
            allocation_directory=settings.hosted_allocation_directory,
            allocation_expires_at=settings.hosted_allocation_expires_at,
        )
        self.spend = (
            azure_spend(settings, daily_ceiling=self.quotas.limits.global_daily_microdollars)
            if settings.hosted_spend_store == "azure_blob"
            else None
        )
        self._spend_workers = BoundedWorkers(2, "pii-guard-sponsored-spend")
        self._spend_refresh_lock = threading.Lock()
        self._runtimes: dict[str, Runtime] = {}
        self._session_budgets: dict[str, SessionBudget] = {}
        self._lock = threading.Lock()
        self.rest_slots = threading.BoundedSemaphore(4)
        self._ingress = 0
        self._workers = {Mode.FAST: BoundedWorkers(4, "pii-guard-hosted-fast")}

    def acquire(self, principal: Principal, *, namespace: str | None = None) -> Runtime:
        self.purge_expired()
        with self._lock:
            now = time.monotonic()
            identity = principal.id + (":" + namespace if namespace else "")
            runtime = self._runtimes.get(identity)
            if runtime is None:
                if len(self._runtimes) >= self.settings.hosted_max_principals:
                    raise HostedCapacityError("Hosted runtime capacity reached; try later")
                key = hmac.digest(self.master_key, b"vault\0" + identity.encode(), "sha256")
                budget = self._session_budgets.setdefault(
                    principal.id, SessionBudget(self.settings.hosted_max_sessions)
                )
                runtime = Runtime(
                    HostedVault(
                        key,
                        budget=budget,
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
                self._runtimes[identity] = runtime
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
            for owner, budget in list(self._session_budgets.items()):
                if not budget.vaults:
                    del self._session_budgets[owner]
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

    @property
    def sponsored_enabled(self) -> bool:
        if self.quotas.sponsored_killed:
            return False
        return self.spend.available if self.spend is not None else self.quotas.sponsored_enabled

    async def charge_spend(self, input_tokens: int, output_tokens: int) -> None:
        if self.spend is None or self.quotas.sponsored_killed:
            raise SponsoredUnavailableError
        limits = self.quotas.limits
        cost = (
            input_tokens * limits.input_microdollars_per_token
            + output_tokens * limits.output_microdollars_per_token
        )
        cancelled = threading.Event()
        try:
            async with asyncio.timeout(10):
                await self._spend_workers.run(self.spend.charge, cost, cancelled)
            if self.quotas.sponsored_killed:
                raise SponsoredUnavailableError
        except TimeoutError:
            raise SponsoredUnavailableError from None
        finally:
            cancelled.set()

    async def refresh_spend(self) -> None:
        """Refresh the account hint with bounded, single-flight, read-only I/O."""
        if self.spend is None or self.quotas.sponsored_killed:
            return

        def refresh() -> None:
            # Acquire inside the worker: cancellation before submission cannot leak a
            # lock, and a timed-out worker retains it until its actual read finishes.
            if not self._spend_refresh_lock.acquire(blocking=False):
                return
            try:
                if self.spend is not None:
                    self.spend.refresh()
            finally:
                self._spend_refresh_lock.release()

        try:
            async with asyncio.timeout(10):
                await self._spend_workers.run(refresh)
        except TimeoutError:
            return

    def gateway(self, request: Request) -> Gateway:
        existing = getattr(request.state, "hosted_gateway", None)
        if existing is not None:
            return existing
        from pii_guard.api.deps import get_analyzer, get_policies
        from pii_guard.projects.runtime import policy_pipeline

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
        policies = get_policies(request)
        if getattr(request.state, "project_policy", None) is not None:
            from pii_guard.detect.pipeline import DetectionPipeline

            detectors = {
                mode: ModeDetector(
                    mode,
                    policy_pipeline(
                        item.detector
                        if isinstance(item.detector, DetectionPipeline)
                        else DetectionPipeline([item.detector]),
                        policies,
                    ),
                    item.config_id
                    + ";project="
                    + request.state.project_id
                    + ";policy="
                    + request.state.project_policy["policy_version_id"],
                    policies,
                    item.unavailable,
                    item.batches,
                )
                for mode, item in detectors.items()
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
        self._spend_workers.close()
        if self.spend is not None:
            self.spend.close()

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
