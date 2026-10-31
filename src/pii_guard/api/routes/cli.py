"""CLI login token exchange and logout (LAB-1708).

- ``POST /v1/cli/token`` ``{"code": "..."}``: exchange a one-time login code (made by the
  signed-in owner at ``POST /v1/projects/{project_id}/cli-codes``) for a ``telemetry``-scoped
  endpoint key. No session or token: the code is the only credential.
- ``DELETE /v1/cli/token`` with ``Authorization: Bearer pg_ep_...``: the telemetry key
  revokes itself (``pii-guard logout``).

Both bypass project and session admission in both middlewares; the hosted middleware still
rate-limits them, takes JSON only and bounds the body (see ``hosted/middleware.py``).
"""

from __future__ import annotations

from typing import Any

import anyio.to_thread
from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import Response

from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import v1_router
from pii_guard.api.security import looks_like_endpoint_key
from pii_guard.projects.cli_auth import DEFAULT_CLI_MODEL, exchange_cli_code
from pii_guard.types import PiiGuardError

router = v1_router()
router.tags = ["cli"]

#: The exchange body is one short code; anything larger is refused before parsing.
CLI_TOKEN_MAX_BODY = 1024


class CliKeyRejectedError(PiiGuardError):
    """``DELETE /v1/cli/token`` without a live telemetry key of its own."""

    code = "unauthorized"
    status_code = 401


class CliTokenRequest(BaseModel):
    """The one-time code the dashboard sent to the CLI's loopback callback."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(
        min_length=32,
        max_length=128,
        repr=False,
        description="The one-time login code (single use, valid five minutes).",
    )


def dashboard_origin(request: Request) -> str:
    """The dashboard's public origin: hosted's own, else the configured public origin, else
    this request's base URL (which a reverse proxy may have rewritten)."""
    state = request.app.state
    hosted = getattr(state, "hosted", None)
    if state.settings.hosted and hosted is not None and getattr(hosted, "origin", None):
        return str(hosted.origin).rstrip("/")
    configured = getattr(state.settings, "hosted_public_origin", None)
    if configured:
        return str(configured).rstrip("/")
    return str(request.base_url).rstrip("/")


@router.post(
    "/v1/cli/token",
    responses=error_responses("invalid_code", "invalid_request", "project_storage_unavailable"),
)
def exchange_token(body: CliTokenRequest, request: Request) -> dict[str, Any]:
    """Exchange a one-time CLI login code for a telemetry-only endpoint key. The code is
    deleted on first use, valid or not; the key can only post `/e/{endpoint_id}/v1/traffic`."""
    settings = request.app.state.settings
    default_model = (
        settings.hosted_models[0]
        if settings.hosted and settings.hosted_models
        else DEFAULT_CLI_MODEL
    )
    return exchange_cli_code(
        request.app.state.projects.store,
        body.code,
        origin=dashboard_origin(request),
        default_model=default_model,
    )


@router.delete(
    "/v1/cli/token",
    status_code=204,
    responses=error_responses("project_storage_unavailable"),
)
async def revoke_token(request: Request) -> Response:
    """Revoke the presenting telemetry key (`Authorization: Bearer pg_ep_...`) itself."""
    auths = request.headers.getlist("authorization")
    scheme, _, credential = (auths[0] if len(auths) == 1 else "").partition(" ")
    credential = credential.strip()
    if scheme.lower() != "bearer" or not looks_like_endpoint_key(credential):
        raise CliKeyRejectedError("Send the CLI key as 'Authorization: Bearer pg_ep_...'")
    store = request.app.state.projects.store
    if not await anyio.to_thread.run_sync(store.revoke_presented_key, credential):
        raise CliKeyRejectedError("The CLI key is unknown, already revoked or not a CLI key")
    return Response(status_code=204)
