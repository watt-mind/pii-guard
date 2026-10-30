"""Owner-scoped state; only detectors and bounded compute workers are shared."""

from __future__ import annotations

import asyncio
import hmac
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from fastapi import Request

from pii_guard.api.routes.vault import SessionDirectory
from pii_guard.config import Settings
from pii_guard.gateway.cache import DetectionCache
from pii_guard.gateway.config import GatewayConfig, Mode
from pii_guard.gateway.detection import ModeDetector
from pii_guard.gateway.opaque_ids import IssuedIds
from pii_guard.gateway.service import Gateway
from pii_guard.hosted.abuse import AbuseAdmission
from pii_guard.hosted.attribution import sponsored_upstream_headers
from pii_guard.hosted.connections import ConnectionStore
from pii_guard.hosted.egress import SecureTransport
from pii_guard.hosted.identity import ApiKeyStore, GuestIdentity, Principal
from pii_guard.hosted.quotas import QuotaLedger, QuotaLimits, SponsoredUnavailableError
from pii_guard.hosted.spend import azure_spend
from pii_guard.observability import Observability, ObservabilitySettings, TrafficLevel, TrafficLog
from pii_guard.observability.traffic import TrafficFeed, TrafficFeedView
from pii_guard.types import Analyzer, PiiGuardError, Span
from pii_guard.vault import Vault
from pii_guard.workers import BoundedWorkers

if TYPE_CHECKING:
    from pii_guard.projects.runtime import ProjectService


STREAMS_PER_OWNER = 2
MAX_STREAMS = 16
# Ingress slots (LAB-1442) are taken only after identity, path, origin and abuse checks,
# and are held from the body read to the end of the response. Signed-in principals and
# guests draw on separate pools, and each principal has its own share, so neither
# anonymous nor one signed-in client's slow uploads can starve everyone else.
INGRESS_SLOTS = 32
INGRESS_PER_PRINCIPAL = 8
GUEST_INGRESS_SLOTS = 8
GUEST_INGRESS_PER_PRINCIPAL = 2
# The one pre-authentication await (endpoint-key lookup) has its own small bound. No body
# is read under it, so a slow client cannot hold it.
PREAUTH_SLOTS = 8


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
    issued_ids: IssuedIds = field(default_factory=IssuedIds)
    session_incarnations: OrderedDict[str, Any] = field(default_factory=OrderedDict)
    #: The ``_runtimes`` key; a guest runtime is dropped as soon as it is idle.
    identity: str = ""
    guest: bool = False
    #: The principal that owns this runtime; its traffic log belongs to that owner's feed.
    owner: str = ""


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
            or (
                settings.hosted_sponsored_kill_switch_path is not None
                and not os.path.isabs(settings.hosted_sponsored_kill_switch_path)
            )
        ):
            raise ValueError(
                "Hosted mode requires trusted ingress, one process, HTTPS origin, "
                "a 32-byte tenant key and local fast detectors"
            )
        if settings.hosted_images and (
            not settings.image_require_ocr
            or ("segmenter" in settings.model_fields_set and settings.segmenter != "local")
        ):
            # ADR 0014: hosted images are processed on the replica only. A remote segmenter
            # (hybrid, sam-api) would send the original image out; "off" refuses every image;
            # SAM-only masking leaves the image's text unchecked.
            raise ValueError(
                "Hosted images require OCR and the local segmenter (PII_GUARD_SEGMENTER=local)"
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
                user_images=settings.hosted_user_images_per_day,
                global_images=settings.hosted_global_images_per_day,
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
        # One traffic sequence per owner (LAB-1492): a project's Logs merge its endpoint
        # runtimes by ``seq`` without ever touching another owner's feed.
        self._feeds: dict[str, TrafficFeed] = {}
        self._lock = threading.Lock()
        self.rest_slots = threading.BoundedSemaphore(4)
        self._ingress = 0
        self._guest_ingress = 0
        self._ingress_held: dict[str, int] = {}
        self._preauth = 0
        # Live traffic streams leave the ingress bound for their own (LAB-1412): an open
        # console must not occupy request capacity for its whole 180-second deadline.
        self._streams: dict[str, int] = {}
        self._workers = {Mode.FAST: BoundedWorkers(4, "pii-guard-hosted-fast")}
        # One image job per replica (OCR is CPU- and memory-heavy); a busy slot is a 429,
        # never a queue. A timed-out job keeps the slot until its thread has finished.
        self.image_workers = BoundedWorkers(1, "pii-guard-hosted-image")

    def acquire(self, principal: Principal, *, namespace: str | None = None) -> Runtime:
        self.purge_expired()
        with self._lock:
            now = time.monotonic()
            identity = principal.id + (":" + namespace if namespace else "")
            runtime = self._runtimes.get(identity)
            if runtime is None:
                guest = not principal.authenticated
                owner_runtimes = sum(
                    runtime_id == principal.id or runtime_id.startswith(principal.id + ":")
                    for runtime_id in self._runtimes
                )
                if owner_runtimes >= min(32, self.settings.hosted_max_sessions):
                    raise HostedCapacityError("Account runtime capacity reached; try later")
                # Guests draw on their own small pool, so anonymous traffic can never take
                # the runtimes reserved for signed-in owners (LAB-1412).
                pooled = sum(item.guest == guest for item in self._runtimes.values())
                maximum = (
                    self.settings.hosted_max_guest_runtimes
                    if guest
                    else self.settings.hosted_max_principals
                )
                if pooled >= maximum:
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
                    identity=identity,
                    guest=guest,
                    owner=principal.id,
                )
                feed = self._feeds.setdefault(principal.id, TrafficFeed())
                runtime.observability.traffic = TrafficLog(
                    TrafficLevel.MASKED, 50, feed=feed, source=identity
                )
                self._runtimes[identity] = runtime
            runtime.active += 1
            runtime.touched = now
            return runtime

    def release(self, runtime: Runtime) -> None:
        with self._lock:
            runtime.active -= 1
            runtime.touched = time.monotonic()
            # A guest's only work is one ephemeral demo: nothing outlives it.
            if runtime.guest and not runtime.active:
                runtime.vault.close()
                if self._runtimes.get(runtime.identity) is runtime:
                    del self._runtimes[runtime.identity]
                    self._detach_traffic_locked(runtime)

    def purge_expired(self) -> None:
        with self._lock:
            now = time.monotonic()
            for owner, runtime in list(self._runtimes.items()):
                if not runtime.active and now - runtime.touched >= self.settings.hosted_runtime_ttl:
                    runtime.vault.close()
                    self.connections.clear_owner(owner)
                    del self._runtimes[owner]
                    self._detach_traffic_locked(runtime)
            for owner, budget in list(self._session_budgets.items()):
                if not budget.vaults:
                    del self._session_budgets[owner]
        self.keys.purge_expired()
        self.connections.purge_expired()
        self.abuse.purge_expired()
        self.check_kill_switch()

    def _detach_traffic_locked(self, runtime: Runtime) -> None:
        feed = self._feeds.get(runtime.owner)
        if feed is None:
            return
        feed.detach(runtime.identity)
        if not feed.sources():
            del self._feeds[runtime.owner]

    def project_traffic(self, runtime: Runtime, project_id: str | None) -> TrafficFeedView:
        """Project Logs with no endpoint selected (LAB-1492): ``runtime`` (the project's own)
        and every endpoint runtime of ``project_id``, read from the owner's feed only."""
        with self._lock:
            feed = self._feeds[runtime.owner]
        base = runtime.identity
        prefix = f"{runtime.owner}:{project_id}:" if project_id else None

        def include(source: str) -> bool:
            return source == base or (prefix is not None and source.startswith(prefix))

        return TrafficFeedView(feed, include, runtime.observability.traffic.level)

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

    def spend_cost(self, input_tokens: int, output_tokens: int) -> int:
        """Microdollars for these token counts at the sponsored (upper-bound) rates."""
        limits = self.quotas.limits
        return (
            input_tokens * limits.input_microdollars_per_token
            + output_tokens * limits.output_microdollars_per_token
        )

    async def charge_spend(
        self, input_tokens: int, output_tokens: int, request_id: str | None = None
    ) -> None:
        if self.spend is None or self.quotas.sponsored_killed:
            raise SponsoredUnavailableError
        cost = self.spend_cost(input_tokens, output_tokens)
        cancelled = threading.Event()
        try:
            async with asyncio.timeout(10):
                await self._spend_workers.run(self.spend.charge, cost, cancelled, request_id)
            if self.quotas.sponsored_killed:
                raise SponsoredUnavailableError
        except TimeoutError:
            raise SponsoredUnavailableError from None
        finally:
            cancelled.set()

    async def refund_spend(self, request_id: str, input_tokens: int, output_tokens: int) -> int:
        """Settle one durable charge down to these token counts; 0 when nothing refunded.

        Runs even after the kill switch (a refund only lowers spend). Any failure, timeout
        included, leaves the charge in full and returns 0: settlement is best effort.
        """
        if self.spend is None:
            return 0
        settled = self.spend_cost(input_tokens, output_tokens)
        cancelled = threading.Event()
        try:
            async with asyncio.timeout(10):
                return await self._spend_workers.run(
                    self.spend.refund, request_id, settled, cancelled
                )
        except Exception:
            # Timeout, a closed worker pool, or the ledger's own sanitized refusal.
            return 0
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
        # Inline images admitted for this request (LAB-1439); none keeps the gateway text-only.
        images = getattr(request.state, "hosted_chat_images", 0)
        image_kwargs: dict[str, Any] = {}
        if images:
            from pii_guard.hosted.images import (
                hosted_image_limits,
                hosted_visual_policies,
                local_ocr,
                local_segmenter,
                require_local_visual_policies,
            )

            # The owner's policy, text and visual, with the operator's stricter overrides,
            # exactly as /v1/mask/image; a policy only SAM could serve is refused first.
            policy = getattr(request.state, "project_policy", None)
            request.state.project_policies = hosted_visual_policies(
                policy, get_policies(request), self.settings, request.app.state.policies
            )
            require_local_visual_policies(request.state.project_policies, policy)
            max_pixels, image_timeout = hosted_image_limits(self.settings)
            image_kwargs = {
                "sam": local_segmenter(request.app.state),
                "ocr": local_ocr(request.app.state),
                "image_workers": self.image_workers,
            }
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
        provider = self.provider_settings(request)
        if images:
            # Hosted pixel cap, OCR required: an image the text check can't read is refused.
            provider = provider.model_copy(
                update={"image_max_pixels": max_pixels, "image_require_ocr": True}
            )
        # The owner's traffic log, scrubbing the provider key this request may send (the
        # sponsored key or the selected connection's), as the local and project gateways do.
        credential = provider.upstream_api_key
        observability = Observability(
            runtime.observability.settings,
            secrets=[credential.get_secret_value()] if credential is not None else [],
        )
        observability.traffic = runtime.observability.traffic
        observability.metrics = runtime.observability.metrics
        gateway = Gateway(
            settings=provider,
            vault=runtime.vault,
            config=GatewayConfig(
                mode=Mode.FAST,
                max_images=self.settings.hosted_chat_max_images if images else 0,
                max_image_bytes=self.settings.hosted_max_image_bytes,
                image_timeout=image_timeout if images else self.settings.hosted_image_timeout,
                upstream_timeout=120,
                cache_size=256,
                concurrency=4,
            ),
            detectors=detectors,
            cache=runtime.cache,
            transport=SecureTransport(),
            observability=observability,
            **image_kwargs,
        )
        if getattr(request.state, "hosted_connection", None) is None:
            # Sponsored (operator-key) route only; a selected own connection gets neither.
            gateway.upstream_extra_headers = sponsored_upstream_headers(self.settings)
        gateway._detect_workers = self._workers
        gateway._session_holds = runtime.session_holds
        gateway._holds_lock = runtime.holds_lock
        gateway.issued_ids = runtime.issued_ids
        gateway._session_incarnations = runtime.session_incarnations
        request.state.hosted_gateway = gateway
        return gateway

    async def close(self) -> None:
        with self._lock:
            for runtime in self._runtimes.values():
                runtime.vault.close()
            self._runtimes.clear()
            self._feeds.clear()
        self.keys.clear()
        self.connections.clear()
        for workers in self._workers.values():
            workers.close()
        self.image_workers.close()
        self._spend_workers.close()
        if self.spend is not None:
            self.spend.close()

    def enter_stream(self, owner: str) -> None:
        """Admit one live traffic stream: two per owner, sixteen in all."""
        with self._lock:
            if (
                self._streams.get(owner, 0) >= STREAMS_PER_OWNER
                or sum(self._streams.values()) >= MAX_STREAMS
            ):
                raise HostedCapacityError("Live traffic stream capacity reached; try later")
            self._streams[owner] = self._streams.get(owner, 0) + 1

    def leave_stream(self, owner: str) -> None:
        with self._lock:
            remaining = self._streams.get(owner, 0) - 1
            if remaining > 0:
                self._streams[owner] = remaining
            else:
                self._streams.pop(owner, None)

    def check_kill_switch(self) -> bool:
        """Disable sponsored admission for good once the operator's kill file exists.

        Any error other than a missing file also disables it: the switch fails closed."""
        path = self.settings.hosted_sponsored_kill_switch_path
        if path is None or self.quotas.sponsored_killed:
            return self.quotas.sponsored_killed
        try:
            os.stat(path)
        except FileNotFoundError:
            return False
        except OSError:
            pass
        self.quotas.disable_sponsored()
        return True

    def enter_ingress(self, principal: Principal) -> None:
        """Take one ingress slot for an identified, admitted principal; never queue."""
        guest = not principal.authenticated
        with self._lock:
            pooled = self._guest_ingress if guest else self._ingress - self._guest_ingress
            held = self._ingress_held.get(principal.id, 0)
            if pooled >= (GUEST_INGRESS_SLOTS if guest else INGRESS_SLOTS) or held >= (
                GUEST_INGRESS_PER_PRINCIPAL if guest else INGRESS_PER_PRINCIPAL
            ):
                raise HostedCapacityError("Request capacity reached; try later")
            self._ingress += 1
            self._guest_ingress += guest
            self._ingress_held[principal.id] = held + 1

    def leave_ingress(self, principal: Principal) -> None:
        with self._lock:
            self._ingress -= 1
            self._guest_ingress -= not principal.authenticated
            remaining = self._ingress_held.get(principal.id, 0) - 1
            if remaining > 0:
                self._ingress_held[principal.id] = remaining
            else:
                self._ingress_held.pop(principal.id, None)

    def enter_preauth(self) -> None:
        with self._lock:
            if self._preauth >= PREAUTH_SLOTS:
                raise HostedCapacityError("Request capacity reached; try later")
            self._preauth += 1

    def leave_preauth(self) -> None:
        with self._lock:
            self._preauth -= 1


def hosted_state(request: Request, name: str) -> Any:
    """Return an owner-scoped dependency, or the original local app dependency."""
    runtime = getattr(request.state, "hosted_runtime", None)
    if runtime is not None:
        return getattr(runtime, name)
    return getattr(request.app.state, name, None)
