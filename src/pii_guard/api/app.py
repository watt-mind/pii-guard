"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress

import anyio.to_thread
from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from pii_guard import __version__
from pii_guard.api.errors import error_response, error_responses, install_error_handlers
from pii_guard.api.routes import include_routers
from pii_guard.api.routes.vault import (
    InspectMode,
    SessionDirectory,
    SessionRecorderMiddleware,
    check_inspect_bind,
)
from pii_guard.api.security import (
    BearerTokenMiddleware,
    BrowserRequestSecurityMiddleware,
    LoopbackOnlyMiddleware,
    allowed_hosts,
)
from pii_guard.config import Settings, get_settings
from pii_guard.detect import stack
from pii_guard.detect.stack import (
    DetectionUnavailableError,
    DetectorLoadingError,
    NerWarmup,
    rest_detector_names,
)
from pii_guard.gateway.sessions import SessionPathMiddleware
from pii_guard.observability import (
    Observability,
    ObservabilitySettings,
    TrafficLevel,
    build_remote_exporter,
    check_bind,
    is_loopback,
)
from pii_guard.observability.config import check_allowed_hosts
from pii_guard.policy import PolicySet
from pii_guard.registry import resolve_detector
from pii_guard.types import PiiGuardError

__all__ = ["create_app"]

logger = logging.getLogger("pii_guard.api")

#: The routes that run detectors (``POST``), so wait for a loading NER model (LAB-1303). Every
#: other route answers at once while it loads. ``tests/api/test_ner_warmup.py`` checks that
#: each ``POST`` route of the app, hosted or not, is either here (or in
#: ``HOSTED_DETECTING_PATHS``) or in its non-detecting lists.
DETECTING_PATHS = frozenset(
    {
        "/v1/analyze",
        "/v1/mask",
        "/v1/mask/image",
        "/v1/chat/completions",
        "/v1/responses",
        "/v1/messages",
        "/v1/messages/count_tokens",
    }
)
#: The hosted-only routes that run detectors, added to ``DETECTING_PATHS`` in hosted mode.
#: ``/v1/demo`` masks a sample through the gateway (LAB-1601).
HOSTED_DETECTING_PATHS = frozenset({"/v1/demo"})
#: Seconds a refused client is told to wait before retrying ``503 detector_loading``.
RETRY_AFTER_SECONDS = 5


class NerWarmupMiddleware:
    """Detecting requests wait (bounded, off the event loop) for the background NER load.

    Inside the session-path rewrite, so ``/s/<session>/v1/...`` waits too, and inside the
    Host, loopback and token checks, so a refused request never waits. Still loading after
    ``PII_GUARD_NER_WARMUP_TIMEOUT``: ``503 detector_loading`` with ``Retry-After``; the load
    failed: ``503 detection_unavailable``. Either way nothing ran and nothing was sent.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        warmup: NerWarmup,
        timeout: float,
        detecting_paths: frozenset[str] = DETECTING_PATHS,
    ) -> None:
        self.app = app
        self.warmup = warmup
        self.timeout = timeout
        self.detecting_paths = detecting_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and self.warmup.pending
            and scope.get("method") == "POST"
            and scope.get("path") in self.detecting_paths
        ):
            try:
                await self.warmup.wait_async(self.timeout)
            except PiiGuardError as exc:
                response = error_response(exc.status_code, exc.code, exc.message)
                if isinstance(exc, DetectorLoadingError):
                    response.headers["Retry-After"] = str(RETRY_AFTER_SECONDS)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _build_lifespan(
    settings: Settings, warmup: NerWarmup
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.hosted and warmup.start():
            # Hosted scales to zero (LAB-1548): a cold start serves the landing page, the UI and
            # serving readiness at once while the bundled model loads; detecting requests wait.
            logger.info("bundled ner model loading in the background; detecting requests wait")
        elif await anyio.to_thread.run_sync(stack.warm_up, settings):
            warmup.mark_ready()
            logger.info("ner model warmed up before serving")
        elif warmup.start():
            logger.info("ner model loading in the background; detecting requests wait for it")

        async def cleanup_hosted() -> None:
            while True:
                await asyncio.sleep(30)
                app.state.hosted.purge_expired()
                await app.state.hosted.refresh_spend()

        cleaner = asyncio.create_task(cleanup_hosted()) if settings.hosted else None
        try:
            yield
        finally:
            if cleaner is not None:
                cleaner.cancel()
                with suppress(asyncio.CancelledError):
                    await cleaner
            close = getattr(getattr(app.state, "gateway", None), "aclose", None)
            if close is not None:
                await close()
            obs_close = getattr(getattr(app.state, "observability", None), "close", None)
            if obs_close is not None:
                obs_close()
            if settings.hosted:
                await app.state.hosted.close()
            app.state.projects.close()

    return lifespan


def _register_healthz(app: FastAPI, settings: Settings, warmup: NerWarmup) -> None:
    @app.get(
        "/healthz",
        tags=["health"],
        summary="Liveness check",
        responses={
            200: {
                "description": "The server is up. ``ner``: ``off`` (no NER in the stack), "
                "``loading`` (detecting requests wait for it), ``ready`` or ``failed`` "
                "(detecting requests get 503 ``detection_unavailable``).",
                "content": {
                    "application/json": {
                        "example": {"status": "ok", "version": __version__, "ner": "ready"}
                    }
                },
            },
            **error_responses("traffic_log_not_local", common=False),
        },
    )
    def healthz() -> dict[str, object]:
        """``{"status": "ok", "version": ..., "ner": ..., "ocr": ...}`` while the server
        is up, also while the NER model loads (``ner``: ``loading``). ``ocr`` is ``"on"``
        when Tesseract is installed and ``"off"`` otherwise; ``image_require_ocr`` says
        whether image requests are refused without it (503 ``ocr_unavailable``). Needs no
        token, and touches no detector, vault or upstream."""
        try:
            from pii_guard.visual.ocr import tesseract_available

            ocr = "on" if tesseract_available() else "off"
        except Exception:  # the ocr extra is not installed: OCR is off, not an error
            ocr = "off"
        return {
            "status": "ok",
            "version": __version__,
            "ner": warmup.state,
            "ocr": ocr,
            "image_require_ocr": settings.image_require_ocr,
        }


def _configure_hosted(app: FastAPI, settings: Settings, warmup: NerWarmup) -> None:
    from pii_guard.hosted.routes import router as hosted_router
    from pii_guard.hosted.runtime import HostedService

    app.state.hosted = HostedService(settings, projects=app.state.projects)
    app.include_router(hosted_router)
    # Hosted images (ADR 0014): the route's own byte limit and the one-job image pool.
    app.state.max_image_bytes = settings.hosted_max_image_bytes
    app.state.image_workers = app.state.hosted.image_workers

    def require_ready(*, serving: bool) -> dict[str, str]:
        if warmup.state == "failed":
            # Status only: the load error stays in the log (ADR 0006).
            raise DetectionUnavailableError("ner model unavailable")
        if warmup.state not in {"ready", "off"} and not (serving and warmup.state == "loading"):
            raise DetectorLoadingError("Detectors are not ready")
        if settings.hosted_images:
            from pii_guard.hosted.images import require_image_pipeline

            # Fail closed (ADR 0006): a replica that offers images must be able to OCR
            # them and to find faces on the CPU, or it is not ready at all.
            require_image_pipeline(app.state)
        return {"status": "ready"}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> dict[str, str]:
        """Full readiness (deploy smoke): the NER model is loaded."""
        return require_ready(serving=False)

    @app.get("/readyz/serving", include_in_schema=False)
    def readyz_serving() -> dict[str, str]:
        """Serving readiness (the platform's Readiness probe, LAB-1548): also ready while
        the NER model loads, since detecting requests wait for it; a failed load is never
        ready. A plain path: Container Apps documents no query string in probe paths."""
        return require_ready(serving=True)


def _install_middlewares(
    app: FastAPI,
    settings: Settings,
    obs_settings: ObservabilitySettings,
    warmup: NerWarmup,
    inspect_mode: InspectMode,
    hosts: list[str],
) -> None:
    # Innermost: detecting requests wait for a loading NER model (LAB-1303), on the rewritten
    # path. Then /s/<session>/v1/... reaches the /v1 routes with that vault session
    # (LAB-1286); the Host, loopback and token checks see the URL as sent.
    app.add_middleware(
        NerWarmupMiddleware,
        warmup=warmup,
        timeout=settings.ner_warmup_timeout,
        detecting_paths=(
            DETECTING_PATHS | HOSTED_DETECTING_PATHS if settings.hosted else DETECTING_PATHS
        ),
    )
    if inspect_mode is not InspectMode.OFF and not settings.hosted:
        app.add_middleware(SessionRecorderMiddleware, directory=app.state.vault_directory)
    app.add_middleware(SessionPathMiddleware)
    from pii_guard.projects.middleware import ProjectMiddleware

    app.add_middleware(ProjectMiddleware, service=app.state.projects)
    if settings.hosted:
        from pii_guard.hosted.middleware import HostedMiddleware

        app.add_middleware(HostedMiddleware, service=app.state.hosted)

    # Outermost last: Host check, local browser guard, (full only) loopback sockets, token.
    if (
        obs_settings.metrics_token is not None
        and not obs_settings.metrics_token.get_secret_value().strip()
    ):
        raise ValueError("PII_GUARD_METRICS_TOKEN is set but empty")
    token = settings.api_token
    if token is not None:
        if not token.get_secret_value().strip():
            # Fail closed at construction: Starlette builds middleware lazily, so a check in
            # BearerTokenMiddleware alone would let the server start and answer 500 (LAB-1570).
            raise ValueError("PII_GUARD_API_TOKEN is set but empty")
        app.add_middleware(BearerTokenMiddleware, token=token.get_secret_value())
    elif not settings.hosted and not is_loopback(settings.host):
        logger.warning(
            "pii-guard binds %s without authentication: anyone who can reach it can unmask, "
            "read the traffic log and use the gateway (and PII_GUARD_UPSTREAM_API_KEY). Set "
            "PII_GUARD_API_TOKEN or put it behind an authenticating proxy",
            settings.host,
        )
    if obs_settings.traffic_log is TrafficLevel.FULL:
        app.add_middleware(LoopbackOnlyMiddleware)
    if not settings.hosted:
        app.add_middleware(BrowserRequestSecurityMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts, www_redirect=False)


def create_app(
    settings: Settings | None = None, observability: ObservabilitySettings | None = None
) -> FastAPI:
    """Build the app. ``settings`` defaults to :func:`pii_guard.config.get_settings`.

    The settings object is available to routes as ``request.app.state.settings``; the
    detector names (``PII_GUARD_DETECTORS``, else rules + ner when available) as
    ``app.state.detector_names`` and the entity
    policies (``PII_GUARD_POLICY_OVERRIDES``) as ``app.state.policies``. Unknown detector
    names stop startup (:class:`~pii_guard.types.DetectionError`) rather than the first
    request.

    ``observability`` (default: from the environment) configures the traffic log, the
    ``Server-Timing`` header and ``/metrics`` (``app.state.observability``). The traffic log at
    level ``full`` on a non-loopback ``PII_GUARD_HOST`` or with non-loopback
    ``PII_GUARD_ALLOWED_HOSTS`` stops startup
    (:class:`~pii_guard.observability.TrafficLogConfigError`), and refuses every connection that
    is not loopback on both ends (403 ``traffic_log_not_local``).

    Requests with a ``Host`` header outside :func:`~pii_guard.api.security.allowed_hosts` get
    400 (DNS-rebinding guard). ``PII_GUARD_API_TOKEN`` requires a bearer token on every route
    but ``/healthz``; without it the API has no authentication.

    With ``PII_GUARD_NER_MODEL`` set, the lifespan loads the NER model before the app serves
    (:func:`~pii_guard.detect.stack.warm_up`, LAB-1274), so concurrent first requests don't
    race to load it; a model that can't be loaded stops startup. Hosted mode is the exception
    (LAB-1548, scale to zero): it loads the configured model in the background like below, so
    a cold start serves the landing page at once; a model that can't be loaded fails detecting
    requests closed (503 ``detection_unavailable``) and keeps ``/readyz`` refusing. Without
    it, when the stack
    has ``ner`` (the resolved published model or fallback), the lifespan starts loading it in
    the background (:class:`~pii_guard.detect.stack.NerWarmup`, ``app.state.ner_warmup``,
    LAB-1303): the server answers at once, ``/healthz`` and ``/v1/status`` say ``loading``,
    and detecting requests wait for the model (:class:`NerWarmupMiddleware`). The gateway
    (``app.state.gateway``) keeps one upstream HTTP client; the lifespan closes it on shutdown
    (LAB-1176).
    """
    settings = settings or get_settings()
    warmup = NerWarmup(settings)
    app = FastAPI(
        title="PII Guard",
        version=__version__,
        description="Privacy firewall for AI agents: reversible PII masking.",
        lifespan=_build_lifespan(settings, warmup),
    )
    # Explicit PII_GUARD_DETECTORS, else the gateway fast-mode stack (LAB-1270). A configured
    # but missing NER raises here, like an unknown name: at startup, not on the first request.
    detector_names = rest_detector_names(settings)
    for name in detector_names:
        resolve_detector(name)
    app.state.settings = settings
    app.state.detector_names = list(detector_names)
    app.state.max_text_chars = settings.max_text_chars
    app.state.policies = PolicySet.from_settings(settings)
    app.state.ner_warmup = warmup
    obs_settings = observability or ObservabilitySettings()
    hosts = allowed_hosts(settings)
    check_bind(obs_settings.traffic_log, settings.host)
    check_allowed_hosts(obs_settings.traffic_log, hosts)
    # The vault inspector (LAB-1328): `full` reveals originals, so it is loopback-only too.
    inspect_mode = InspectMode(settings.vault_inspect)
    check_inspect_bind(inspect_mode, settings.host, hosts)
    app.state.vault_inspect = inspect_mode
    app.state.vault_directory = SessionDirectory(settings.vault_max_sessions)
    upstream_key = settings.upstream_api_key
    app.state.observability = Observability(
        obs_settings,
        secrets=[upstream_key.get_secret_value()] if upstream_key is not None else [],
        # Hosted only ingests remote telemetry; it never ships its tenants' traffic anywhere.
        remote=None if settings.hosted else build_remote_exporter(obs_settings),
    )
    install_error_handlers(app)
    _register_healthz(app, settings, warmup)

    from pii_guard.projects.runtime import ProjectService

    app.state.projects = ProjectService(settings)
    include_routers(app)
    if settings.hosted:
        _configure_hosted(app, settings, warmup)
    _install_middlewares(app, settings, obs_settings, warmup, inspect_mode, hosts)
    return app
