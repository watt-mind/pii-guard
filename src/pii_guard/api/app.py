"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from pii_guard import __version__
from pii_guard.api.errors import install_error_handlers
from pii_guard.api.routes import include_routers
from pii_guard.config import Settings, get_settings
from pii_guard.policy import PolicySet
from pii_guard.registry import resolve_detector

__all__ = ["create_app"]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. ``settings`` defaults to :func:`pii_guard.config.get_settings`.

    The settings object is available to routes as ``request.app.state.settings``; the
    detector names (``PII_GUARD_DETECTORS``) as ``app.state.detector_names`` and the entity
    policies (``PII_GUARD_POLICY_OVERRIDES``) as ``app.state.policies``. Unknown detector
    names stop startup (:class:`~pii_guard.types.DetectionError`) rather than the first
    request.
    """
    app = FastAPI(
        title="pii-guard",
        version=__version__,
        description="Privacy firewall for AI agents: reversible PII masking.",
    )
    settings = settings or get_settings()
    for name in settings.detectors:
        resolve_detector(name)  # fail at startup on a typo, not on the first request
    app.state.settings = settings
    app.state.detector_names = list(settings.detectors)
    app.state.policies = PolicySet.from_settings(settings)
    install_error_handlers(app)

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    include_routers(app)
    return app
