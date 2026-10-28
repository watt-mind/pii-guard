"""Request snapshots and isolated ephemeral processing state for durable projects."""

from __future__ import annotations

import hmac
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import Request

from pii_guard.api.routes.vault import SessionDirectory
from pii_guard.config import Settings
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.gateway.cache import DetectionCache
from pii_guard.gateway.config import GatewayConfig, Mode
from pii_guard.gateway.detection import ModeDetector, build_mode_detectors
from pii_guard.gateway.service import Gateway
from pii_guard.hosted.runtime import HostedCapacityError, HostedVault, Runtime, SessionBudget
from pii_guard.observability import Observability, ObservabilitySettings, TrafficLevel
from pii_guard.policy import PolicySet
from pii_guard.projects.blob import BlobProjectStore, configured_blob_store
from pii_guard.projects.store import EndpointSnapshot, ProjectStore
from pii_guard.types import Analyzer, DetectionError, PiiGuardError, Span
from pii_guard.workers import BoundedWorkers


class ProjectAccessError(PiiGuardError):
    status_code = 403
    code = "project_access_denied"


def policy_pipeline(pipeline: DetectionPipeline, policies: PolicySet) -> DetectionPipeline:
    """A new resolver around shared detector instances; never mutate shared keep_types."""
    return DetectionPipeline(
        pipeline.detectors,
        authoritative=pipeline.authoritative,
        adjudicator=pipeline.adjudicator,
        keep_types=policies.keep_types,
        min_score=pipeline.min_score,
        overriding=pipeline.overriding,
    )


class PolicyAnalyzer:
    def __init__(self, inner: Analyzer, policies: PolicySet) -> None:
        pipeline = getattr(inner, "pipeline", None)
        if not isinstance(pipeline, DetectionPipeline):
            raise DetectionError("Project policy requires a configurable detection pipeline")
        self.inner = inner
        self.pipeline = policy_pipeline(pipeline, policies)

    def analyze(self, text: str, language: str) -> list[Span]:
        require = getattr(self.inner, "require_available", None)
        if require is not None:
            require()
        return self.pipeline.detect(text, language)


class ProjectService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._store: ProjectStore | BlobProjectStore | None = None
        self._lock = threading.RLock()
        self._runtimes: dict[str, Runtime] = {}
        self._session_budget = SessionBudget(settings.vault_max_sessions)
        self._detectors: dict[Mode, ModeDetector] | None = None
        self.workers: dict[Mode, BoundedWorkers] = {}
        self._worker_concurrency: int | None = None

    def worker_pools(self, concurrency: int) -> dict[Mode, BoundedWorkers]:
        """Share one configured pool per mode, including work held after caller timeouts."""
        with self._lock:
            if self._worker_concurrency is None:
                self.workers.update(
                    {
                        mode: BoundedWorkers(concurrency, "pii-guard-project-" + mode.value)
                        for mode in Mode
                    }
                )
                self._worker_concurrency = concurrency
            elif concurrency != self._worker_concurrency:
                # Never swap pools while a timed-out detection may still hold its slot.
                raise PiiGuardError("Gateway concurrency cannot change while the app is running")
            return self.workers

    @property
    def store(self) -> ProjectStore | BlobProjectStore:
        with self._lock:
            if self._store is None:
                if self.settings.hosted_project_store == "azure_blob":
                    self._store = configured_blob_store(self.settings)
                    self._key = self._store._key
                    return self._store
                path = Path(self.settings.project_state_path).expanduser()
                key = self.settings.tenant_key_bytes()
                if self.settings.hosted and (key is None or len(key) < 32):
                    raise ValueError("Hosted project storage requires a stable 32-byte tenant key")
                if key is None:
                    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    key_path = path.parent / "project-storage.key"
                    if key_path.is_symlink():
                        raise ValueError("Project storage key must be a regular private file")
                    try:
                        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    except FileExistsError:
                        info = key_path.stat(follow_symlinks=False)
                        if (
                            not key_path.is_file()
                            or info.st_uid != os.getuid()
                            or info.st_size != 32
                            or info.st_nlink != 1
                        ):
                            raise ValueError(
                                "Project storage key must be a private regular 32-byte file"
                            ) from None
                        descriptor = os.open(key_path, os.O_RDONLY | os.O_NOFOLLOW)
                        with os.fdopen(descriptor, "rb") as stream:
                            key = stream.read(33)
                    else:
                        key = secrets.token_bytes(32)
                        with os.fdopen(fd, "wb") as stream:
                            stream.write(key)
                            stream.flush()
                            os.fsync(stream.fileno())
                    if key_path.stat().st_mode & 0o077 or len(key) < 32:
                        raise ValueError("Project storage key must be private and contain 32 bytes")
                self._key = key
                self._store = ProjectStore(
                    str(path),
                    key,
                    PolicySet.from_settings(self.settings),
                    self.settings.detection_profile,
                )
            return self._store

    def prepare(
        self,
        state: dict[str, Any],
        owner: str,
        project_id: str | None,
        endpoint: EndpointSnapshot | None = None,
    ) -> None:
        store = self.store
        project = (
            store.get_project(owner, project_id) if project_id else store.default_project(owner)
        )
        if endpoint is not None and (
            endpoint.owner_id != owner or endpoint.project_id != project["id"]
        ):
            raise ProjectAccessError("Endpoint is outside the selected project")
        policy = (
            endpoint.policy
            if endpoint
            else store.get_policy(owner, project["id"], project["default_policy_version_id"])
        )
        state.update(
            project_owner_id=owner,
            project_id=project["id"],
            project_endpoint=endpoint,
            project_policy=policy,
            project_policies=PolicySet(policy["entity_policies"]),
        )

    def acquire(self, state: dict[str, Any]) -> Runtime:
        namespace = state["project_owner_id"] + ":" + state["project_id"]
        endpoint = state.get("project_endpoint")
        if endpoint is not None:
            namespace += ":" + endpoint.id
        with self._lock:
            if sum(runtime.active for runtime in self._runtimes.values()) >= 4:
                raise HostedCapacityError("Project processing capacity reached; try later")
            now = time.monotonic()
            for identity, old_runtime in list(self._runtimes.items()):
                if old_runtime.active == 0 and now - old_runtime.touched >= 3600:
                    old_runtime.vault.close()
                    del self._runtimes[identity]
            runtime = self._runtimes.get(namespace)
            if runtime is None:
                if len(self._runtimes) >= 256:
                    raise HostedCapacityError("Project runtime capacity reached; try later")
                key = hmac.digest(self._key, b"project-vault\0" + namespace.encode(), "sha256")
                runtime = Runtime(
                    HostedVault(
                        key,
                        budget=self._session_budget,
                        max_sessions=self.settings.vault_max_sessions,
                        max_entries=self.settings.vault_max_entries,
                        max_restored_chars=self.settings.unmask_max_restored_chars,
                    ),
                    DetectionCache(256, ttl_seconds=3600),
                    Observability(
                        ObservabilitySettings(
                            traffic_log=TrafficLevel.MASKED, traffic_log_size=50, metrics=False
                        )
                    ),
                    SessionDirectory(self.settings.vault_max_sessions),
                )
                self._runtimes[namespace] = runtime
            runtime.active += 1
            runtime.touched = now
            return runtime

    def release(self, runtime: Runtime) -> None:
        with self._lock:
            runtime.active -= 1
            runtime.touched = time.monotonic()

    def gateway(self, request: Request) -> Gateway:
        existing = getattr(request.state, "project_gateway", None)
        if existing is not None:
            return existing
        endpoint = request.state.project_endpoint
        policies = request.state.project_policies
        policy = request.state.project_policy
        settings = self.settings
        if endpoint is None:
            base_url, credential = settings.upstream_base_url, settings.upstream_api_key
        elif endpoint.provider == "sponsored":
            if not settings.hosted:
                raise ProjectAccessError("Sponsored inference requires hosted mode")
            base_url, credential = "https://api.meta.ai/v1", settings.upstream_api_key
        else:
            base_url, credential = endpoint.base_url, endpoint.api_key
        settings = settings.model_copy(
            update={
                "upstream_base_url": base_url,
                "upstream_api_key": credential,
                "segmenter": "off",
            }
        )
        hosted = getattr(request.app.state, "hosted", None)
        base_config = getattr(request.app.state, "gateway_config", None) or GatewayConfig()
        config = base_config.model_copy(
            update={
                "mode": Mode(policy["mode"]),
                "max_images": 0,
                "cache_size": 256,
            }
        )
        with self._lock:
            bases = getattr(request.app.state, "gateway_detectors", None)
            if bases is None:
                if self._detectors is None:
                    self._detectors = build_mode_detectors(self.settings, config)
                bases = self._detectors
        detectors = {}
        for mode, detector in bases.items():
            original = detector.detector
            pipeline = (
                original
                if isinstance(original, DetectionPipeline)
                else DetectionPipeline([original])
            )
            detectors[mode] = ModeDetector(
                mode,
                policy_pipeline(pipeline, policies),
                detector.config_id
                + ";project="
                + request.state.project_id
                + ";policy="
                + policy["policy_version_id"]
                + ";"
                + policies.fingerprint(),
                policies,
                detector.unavailable,
                detector.batches,
            )
        runtime = request.state.hosted_runtime
        transport: Any
        if hosted is not None:
            from pii_guard.hosted.egress import SecureTransport

            transport = SecureTransport()
        else:
            transport = getattr(request.app.state, "gateway_transport", None)
        observability = Observability(
            runtime.observability.settings,
            secrets=[credential.get_secret_value()] if credential else [],
        )
        observability.traffic = runtime.observability.traffic
        observability.metrics = runtime.observability.metrics
        gateway = Gateway(
            settings=settings,
            vault=runtime.vault,
            config=config,
            detectors=detectors,
            cache=runtime.cache,
            transport=transport,
            observability=observability,
        )
        gateway._detect_workers = (
            hosted._workers if hosted is not None else self.worker_pools(config.concurrency)
        )
        gateway._session_holds, gateway._holds_lock = runtime.session_holds, runtime.holds_lock
        request.state.project_gateway = gateway
        return gateway

    def close(self) -> None:
        with self._lock:
            for runtime in self._runtimes.values():
                runtime.vault.close()
            self._runtimes.clear()
            for workers in self.workers.values():
                workers.close()
            if self._store is not None:
                self._store.close()
