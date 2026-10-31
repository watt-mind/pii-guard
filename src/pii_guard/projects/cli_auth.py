"""CLI browser-handoff login with a one-time code and telemetry-only keys (LAB-1708).

``pii-guard login`` opens ``/#cli-auth?port=<port>&state=<state>`` on the dashboard. The
signed-in owner picks a project and a telemetry level; the dashboard then creates a one-time
code (:func:`create_cli_code`, ``POST /v1/projects/{id}/cli-codes``) and sends the browser to
the CLI's loopback callback with ``state`` and ``code`` only. The CLI exchanges the code
(:func:`exchange_cli_code`, ``POST /v1/cli/token``) for a ``telemetry``-scoped ``pg_ep_`` key
on the project's "CLI telemetry" endpoint. The key can only ``POST /e/<endpoint>/v1/traffic``
and revoke itself (``DELETE /v1/cli/token``); no long-lived secret ever travels in a URL.

Codes are 256-bit, stored as SHA-256 digests, live five minutes and are deleted on first use.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pii_guard.projects.store import ProjectStore
from pii_guard.types import PiiGuardError
from pii_guard.upstreams import PRESETS

__all__ = [
    "CLI_ENDPOINT_NAME",
    "DEFAULT_CLI_MODEL",
    "InvalidCliCodeError",
    "TelemetryChoice",
    "cli_key_name",
    "create_cli_code",
    "exchange_cli_code",
]

CLI_ENDPOINT_NAME = "CLI telemetry"
DEFAULT_CLI_MODEL = "muse-spark-1.3"
TelemetryChoice = Literal["masked", "stats"]
#: Live keys per endpoint the store allows; a new CLI login past it retires the oldest CLI key.
_ACTIVE_KEY_LIMIT = 32


class InvalidCliCodeError(PiiGuardError):
    """The one-time CLI code is unknown, already used or expired."""

    code = "invalid_code"
    status_code = 400

    def __init__(self) -> None:
        super().__init__("The CLI login code is invalid or expired; run 'pii-guard login' again")


def cli_key_name(hostname: str | None) -> str:
    """``CLI (<hostname>)``, or ``CLI`` when the CLI sent no host name."""
    return f"CLI ({hostname})" if hostname else "CLI"


def _ensure_cli_endpoint(
    store: ProjectStore, owner: str, project: Mapping[str, Any], *, default_model: str
) -> dict[str, Any]:
    """The project's own enabled "CLI telemetry" endpoint, created when absent.

    Never another endpoint: the owner's other endpoints may carry their own provider keys.
    """
    for endpoint in store.list_endpoints(owner, str(project["id"])):
        if endpoint.get("enabled") and endpoint.get("name") == CLI_ENDPOINT_NAME:
            return endpoint
    return store.save_endpoint(
        owner,
        str(project["id"]),
        {
            "name": CLI_ENDPOINT_NAME,
            "policy_version_id": project["default_policy_version_id"],
            "provider": "sponsored",
            "base_url": PRESETS["meta"].base_url,
            "model": default_model,
            "enabled": True,
        },
    )


def create_cli_code(
    store: Any,
    owner: str,
    *,
    project_id: str,
    telemetry_level: TelemetryChoice,
    hostname: str | None,
) -> dict[str, Any]:
    """A one-time code for ``project_id`` (``default`` names the owner's default project)."""

    def operation(engine: ProjectStore) -> dict[str, Any]:
        project = (
            engine.default_project(owner)
            if project_id == "default"
            else engine.get_project(owner, project_id)
        )
        return engine.create_cli_code(owner, str(project["id"]), telemetry_level, hostname)

    result: dict[str, Any] = store.run_atomic(operation)
    return result


def exchange_cli_code(
    store: Any, code: str, *, origin: str, default_model: str = DEFAULT_CLI_MODEL
) -> dict[str, Any]:
    """Consume ``code`` and mint a ``telemetry``-scoped key on the project's CLI endpoint."""

    def operation(engine: ProjectStore) -> dict[str, Any] | None:
        redeemed = engine.redeem_cli_code(code)
        if redeemed is None:
            # Returned, not raised: deleting an expired code must still be committed.
            return None
        owner = redeemed["owner_id"]
        project = engine.get_project(owner, redeemed["project_id"])
        endpoint = _ensure_cli_endpoint(engine, owner, project, default_model=default_model)
        project_id, endpoint_id = str(project["id"]), str(endpoint["id"])
        active = [
            key
            for key in engine.list_keys(owner, project_id, endpoint_id)
            if key["revoked_at"] is None
        ]
        if len(active) >= _ACTIVE_KEY_LIMIT:
            oldest = next((key for key in active if key["scope"] == "telemetry"), None)
            if oldest is not None:
                engine.revoke_key(owner, project_id, endpoint_id, oldest["id"])
        issued = engine.issue_key(
            owner, project_id, endpoint_id, cli_key_name(redeemed["hostname"]), scope="telemetry"
        )
        return {
            "dashboard_url": origin.rstrip("/"),
            "project_id": project_id,
            "project_name": str(project["name"]),
            "endpoint_id": endpoint_id,
            "key": issued["key"],
            "telemetry_level": redeemed["telemetry_level"],
        }

    result: dict[str, Any] | None = store.run_atomic(operation)
    if result is None:
        raise InvalidCliCodeError()
    return result
