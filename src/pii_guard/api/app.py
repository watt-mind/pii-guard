"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from pii_guard import __version__
from pii_guard.api.errors import install_error_handlers
from pii_guard.api.routes import include_routers
from pii_guard.config import Settings, get_settings

__all__ = ["create_app"]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. ``settings`` defaults to :func:`pii_guard.config.get_settings`.

    The settings object is available to routes as ``request.app.state.settings``.
    """
    app = FastAPI(
        title="pii-guard",
        version=__version__,
        description="Privacy firewall for AI agents: reversible PII masking.",
    )
    app.state.settings = settings or get_settings()
    install_error_handlers(app)

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    include_routers(app)
    return app
