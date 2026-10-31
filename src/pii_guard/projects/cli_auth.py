"""CLI browser-handoff provisioning for projects and telemetry endpoints (LAB-1708).

When a developer runs ``pii-guard login`` (or ``pii-guard run <agent>`` and chooses a remote
dashboard), the browser opens ``/#cli-auth`` on the target dashboard. Once the owner selects a
project (or creates a new one) and chooses a telemetry capture level (``masked`` session traces
or ``stats``-only counts/timings), :func:`provision_cli_session` ensures an enabled endpoint in
that project, issues a revocable ``pg_ep_...`` endpoint key, and returns a portable
``pg_cli_...`` bundle for the local CLI callback or manual paste.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from typing import Any, Literal

from pii_guard.projects.store import InvalidProjectConfigError, ProjectStore
from pii_guard.upstreams import PRESETS

__all__ = [
    "CLI_BUNDLE_PREFIX",
    "CLI_ENDPOINT_NAME",
    "DEFAULT_CLI_MODEL",
    "TelemetryChoice",
    "decode_cli_bundle",
    "encode_cli_bundle",
    "provision_cli_session",
]

CLI_ENDPOINT_NAME = "CLI telemetry"
CLI_BUNDLE_PREFIX = "pg_cli_"
DEFAULT_CLI_MODEL = "muse-spark-1.3"
TelemetryChoice = Literal["masked", "stats"]


def encode_cli_bundle(payload: Mapping[str, Any]) -> str:
    """Encode a CLI session handoff dictionary into a compact ``pg_cli_...`` token."""
    raw = json.dumps(dict(payload), separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{CLI_BUNDLE_PREFIX}{encoded}"


def decode_cli_bundle(bundle: str) -> dict[str, Any]:
    """Decode and validate a ``pg_cli_...`` token into its CLI configuration fields."""
    cleaned = bundle.strip()
    if not cleaned.startswith(CLI_BUNDLE_PREFIX):
        raise ValueError("CLI bundle must start with 'pg_cli_'")
    body = cleaned.removeprefix(CLI_BUNDLE_PREFIX)
    if not body or len(body) > 8192:
        raise ValueError("CLI bundle has invalid length")
    padding = "=" * (-len(body) % 4)
    try:
        decoded = base64.urlsafe_b64decode((body + padding).encode("ascii"))
        data = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("CLI bundle is not valid base64 JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("CLI bundle must decode to an object")
    required = ("dashboard_url", "project_id", "project_name", "endpoint_id", "endpoint_key")
    for field in required:
        val = data.get(field)
        if not isinstance(val, str) or not val.strip():
            raise ValueError(f"CLI bundle is missing required field {field!r}")
    level = data.get("telemetry_level", "masked")
    if level not in ("masked", "stats"):
        raise ValueError("CLI bundle telemetry_level must be 'masked' or 'stats'")
    return {
        "dashboard_url": data["dashboard_url"].strip().rstrip("/"),
        "project_id": data["project_id"].strip(),
        "project_name": data["project_name"].strip(),
        "endpoint_id": data["endpoint_id"].strip(),
        "endpoint_key": data["endpoint_key"].strip(),
        "telemetry_level": level,
    }


def _resolve_project(
    store: ProjectStore, owner: str, project_id: str, project_name: str | None
) -> dict[str, Any]:
    if project_id == "new":
        if not project_name or not project_name.strip():
            raise InvalidProjectConfigError()
        return store.create_project(owner, project_name.strip())
    if project_id == "default":
        return store.default_project(owner)
    return store.get_project(owner, project_id)


def _ensure_cli_endpoint(
    store: ProjectStore, owner: str, project: Mapping[str, Any], *, default_model: str
) -> dict[str, Any]:
    endpoints = store.list_endpoints(owner, str(project["id"]))
    for endpoint in endpoints:
        if endpoint.get("enabled") and endpoint.get("name") == CLI_ENDPOINT_NAME:
            return endpoint
    for endpoint in endpoints:
        if endpoint.get("enabled"):
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


def provision_cli_session(
    store: ProjectStore,
    owner: str,
    *,
    project_id: str,
    project_name: str | None = None,
    telemetry_level: TelemetryChoice = "masked",
    key_name: str = "CLI",
    origin: str,
    default_model: str = DEFAULT_CLI_MODEL,
) -> dict[str, Any]:
    """Ensure a CLI telemetry endpoint in the target project and issue a ``pg_ep_...`` key."""
    if telemetry_level not in ("masked", "stats"):
        raise InvalidProjectConfigError()
    clean_origin = origin.rstrip("/")
    project = _resolve_project(store, owner, project_id, project_name)
    endpoint = _ensure_cli_endpoint(store, owner, project, default_model=default_model)
    issued = store.issue_key(owner, str(project["id"]), str(endpoint["id"]), key_name)
    bundle = encode_cli_bundle(
        {
            "v": 1,
            "dashboard_url": clean_origin,
            "project_id": project["id"],
            "project_name": project["name"],
            "endpoint_id": endpoint["id"],
            "endpoint_key": issued["key"],
            "telemetry_level": telemetry_level,
        }
    )
    return {
        "project": {"id": project["id"], "name": project["name"]},
        "endpoint": {"id": endpoint["id"], "name": endpoint["name"]},
        "key": issued,
        "telemetry_level": telemetry_level,
        "gateway_url": f"{clean_origin}/e/{endpoint['id']}/v1",
        "dashboard_url": f"{clean_origin}/#logs",
        "bundle": bundle,
    }
