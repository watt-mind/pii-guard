"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from pii_guard import __version__
from pii_guard.api.errors import error_responses, install_error_handlers
from pii_guard.api.routes import include_routers
from pii_guard.api.routes.vault import (
    InspectMode,
    SessionDirectory,
    SessionRecorderMiddleware,
    check_inspect_bind,
)
from pii_guard.api.security import BearerTokenMiddleware, LoopbackOnlyMiddleware, allowed_hosts
from pii_guard.config import Settings, get_settings
from pii_guard.detect import stack
from pii_guard.detect.stack import rest_detector_names
from pii_guard.gateway.sessions import SessionPathMiddleware
from pii_guard.observability import (
    Observability,
    ObservabilitySettings,
    TrafficLevel,
    check_bind,
    is_loopback,
)
from pii_guard.observability.config import check_allowed_hosts
from pii_guard.policy import PolicySet
from pii_guard.registry import resolve_detector

__all__ = ["create_app"]

logger = logging.getLogger("pii_guard.api")


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
    race to load it; a model that can't be loaded stops startup. The gateway
    (``app.state.gateway``) keeps one upstream HTTP client; the lifespan closes it on shutdown
    (LAB-1176).
    """
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if await anyio.to_thread.run_sync(stack.warm_up, settings):
            logger.info("ner model warmed up before serving")
        yield
        close = getattr(getattr(app.state, "gateway", None), "aclose", None)
        if close is not None:
            await close()

    app = FastAPI(
        title="pii-guard",
        version=__version__,
        description="Privacy firewall for AI agents: reversible PII masking.",
        lifespan=lifespan,
    )
    # Explicit PII_GUARD_DETECTORS, else the gateway fast-mode stack (LAB-1270). A configured
    # but missing NER raises here, like an unknown name: at startup, not on the first request.
    detector_names = rest_detector_names(settings)
    for name in detector_names:
        resolve_detector(name)
    app.state.settings = settings
    app.state.detector_names = list(detector_names)
    app.state.policies = PolicySet.from_settings(settings)
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
    )
    install_error_handlers(app)

    @app.get(
        "/healthz",
        tags=["health"],
        summary="Liveness check",
        responses={
            200: {
                "description": "The server is up.",
                "content": {
                    "application/json": {"example": {"status": "ok", "version": __version__}}
                },
            },
            **error_responses("traffic_log_not_local", common=False),
        },
    )
    def healthz() -> dict[str, str]:
        """``{"status": "ok", "version": ...}`` while the server is up. Needs no token, and
        touches no detector, vault or upstream."""
        return {"status": "ok", "version": __version__}

    include_routers(app)
    # Innermost: /s/<session>/v1/... reaches the /v1 routes with that vault session (LAB-1286);
    # the Host, loopback and token checks see the URL as sent.
    if inspect_mode is not InspectMode.OFF:  # where each gateway session came from
        app.add_middleware(SessionRecorderMiddleware, directory=app.state.vault_directory)
    app.add_middleware(SessionPathMiddleware)

    # Outermost last: Host check, then (full only) loopback sockets, then the token.
    token = settings.api_token
    if token is not None:
        app.add_middleware(BearerTokenMiddleware, token=token.get_secret_value())
    elif not is_loopback(settings.host):
        logger.warning(
            "pii-guard binds %s without authentication: anyone who can reach it can unmask, "
            "read the traffic log and use the gateway (and PII_GUARD_UPSTREAM_API_KEY). Set "
            "PII_GUARD_API_TOKEN or put it behind an authenticating proxy",
            settings.host,
        )
    if obs_settings.traffic_log is TrafficLevel.FULL:
        app.add_middleware(LoopbackOnlyMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts, www_redirect=False)
    return app
