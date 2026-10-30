"""Hosted first run: one ready default endpoint per owner, provisioned idempotently (LAB-1455).

A new owner gets their default project (with its default policy, as before), one default
endpoint in it and that endpoint's first key (shown once), so the console can show copy-paste
client snippets straight after sign-in:

- the endpoint uses the server-owned sponsored Meta route with the first allow-listed model;
- while sponsored inference is unavailable, that endpoint is reported as ``needs_key``: the
  owner adds their own Meta key once, which converts it to an own-key (``meta``) endpoint with
  the same id, URL, model and policy. Only a ``needs_key`` endpoint can be converted, and the
  conversion never touches a custom destination, so the sponsored key is never sent to an owner
  endpoint and an own-key endpoint never falls back to sponsored inference.

Provisioning is owner-scoped and idempotent: it creates the endpoint only when the default
project has none, and it runs as one atomic store operation (one snapshot read and conditional
write for the Blob store, retried after a conflict; the store's lock for the local one), so
repeat sign-ins and concurrent first requests never create a second one. No schema change: an
existing snapshot loads as is.

The owner's Meta key is checked for shape before anything is saved (LAB-1463), so an obvious
paste mistake is refused with ``invalid_provider_key`` instead of turning the endpoint ready and
failing at the first request. It is a format check only, never a provider call.
"""

from __future__ import annotations

from typing import Any

from pydantic import SecretStr

from pii_guard.projects.blob import BlobProjectStore
from pii_guard.projects.store import InvalidProjectConfigError, ProjectStorageError, ProjectStore
from pii_guard.types import PiiGuardError
from pii_guard.upstreams import PRESETS

DEFAULT_ENDPOINT_NAME = "Default endpoint"
FIRST_RUN_KEY_NAME = "First-run key"
META_BASE_URL = PRESETS["meta"].base_url
# Conditional-write attempts on the Blob store before a conflict is reported.
BLOB_ATTEMPTS = 3
# The shape of a Meta API key: one token of printable ASCII, no spaces or quotes, not a URL.
# Real keys are far longer than the floor; the ceiling matches the request body limit.
META_KEY_MIN_CHARS = 20
META_KEY_MAX_CHARS = 4096
_META_KEY_REFUSED = frozenset("\"'`")


class InvalidProviderKeyError(PiiGuardError):
    """The provider key is obviously malformed; the message names the shape, never the value."""

    code = "invalid_provider_key"
    status_code = 422

    def __init__(self) -> None:
        super().__init__(
            "The Meta API key is not in the expected format: one token of at least "
            f"{META_KEY_MIN_CHARS} printable characters, without spaces, quotes or a URL."
        )


def check_meta_key(value: SecretStr) -> SecretStr:
    """The key without surrounding whitespace, or :class:`InvalidProviderKeyError`."""
    key = value.get_secret_value().strip()
    if (
        not META_KEY_MIN_CHARS <= len(key) <= META_KEY_MAX_CHARS
        or any(not "!" <= char <= "~" or char in _META_KEY_REFUSED for char in key)
        or "://" in key
    ):
        raise InvalidProviderKeyError()
    return SecretStr(key)


def endpoint_state(endpoint: dict[str, Any], *, sponsored_enabled: bool) -> str:
    """``ready``, ``needs_key`` (sponsored while unavailable) or ``disabled``."""
    if not endpoint["enabled"]:
        return "disabled"
    if endpoint["provider"] == "sponsored":
        return "ready" if sponsored_enabled else "needs_key"
    return "ready" if endpoint["credential_configured"] else "needs_key"


def _provision(
    store: ProjectStore,
    owner: str,
    *,
    model: str,
    sponsored_enabled: bool,
    issue_key: bool,
    meta_api_key: SecretStr | None,
) -> dict[str, Any]:
    project = store.default_project(owner)
    endpoints = store.list_endpoints(owner, project["id"])
    created = False
    if not endpoints:
        endpoint = store.save_endpoint(
            owner,
            project["id"],
            {
                "name": DEFAULT_ENDPOINT_NAME,
                "policy_version_id": project["default_policy_version_id"],
                "provider": "sponsored",
                "base_url": META_BASE_URL,
                "model": model,
                "enabled": True,
            },
        )
        created = True
    else:
        # The oldest enabled endpoint of the default project; never a new one beside it.
        enabled = [e for e in endpoints if e["enabled"]]
        endpoint = enabled[0] if enabled else endpoints[0]
    state = endpoint_state(endpoint, sponsored_enabled=sponsored_enabled)
    if meta_api_key is not None:
        # Exactly one conversion: the sponsored placeholder to the owner's own Meta key, on
        # Meta's fixed URL. Anything else is edited in Projects.
        if state != "needs_key" or endpoint["provider"] != "sponsored":
            raise InvalidProjectConfigError()
        endpoint = store.save_endpoint(
            owner,
            project["id"],
            {
                "name": endpoint["name"],
                "policy_version_id": endpoint["policy_version_id"],
                "provider": "meta",
                "base_url": META_BASE_URL,
                "model": endpoint["model"],
                "enabled": True,
                "api_key": meta_api_key,
            },
            endpoint_id=endpoint["id"],
        )
        state = endpoint_state(endpoint, sponsored_enabled=sponsored_enabled)
    keys = store.list_keys(owner, project["id"], endpoint["id"])
    active = sum(1 for key in keys if key["revoked_at"] is None)
    issued = None
    # One key, shown once, for an enabled endpoint that has none yet: a needs-key endpoint gets
    # it too, so the snippets work as soon as the owner adds their Meta key.
    if issue_key and state != "disabled" and active == 0:
        issued = store.issue_key(owner, project["id"], endpoint["id"], FIRST_RUN_KEY_NAME)
        active = 1
    return {
        "project_id": project["id"],
        "endpoint": endpoint,
        "state": state,
        "created": created,
        "active_keys": active,
        "key": issued,
    }


def ensure_first_run(
    store: ProjectStore | BlobProjectStore,
    owner: str,
    *,
    model: str,
    sponsored_enabled: bool,
    issue_key: bool = False,
    meta_api_key: SecretStr | None = None,
) -> dict[str, Any]:
    """Provision (once) and describe the owner's default endpoint; synchronous, run off-loop."""
    if not owner or not model:
        raise InvalidProjectConfigError()

    def operation(engine: ProjectStore) -> dict[str, Any]:
        return _provision(
            engine,
            owner,
            model=model,
            sponsored_enabled=sponsored_enabled,
            issue_key=issue_key,
            meta_api_key=meta_api_key,
        )

    if isinstance(store, BlobProjectStore):
        # A concurrent writer that wins the conditional write makes ours fail: read again and
        # decide again, so the loser sees the winner's endpoint (and key) instead of creating
        # its own. Bounded, so a store that keeps failing still surfaces as an error.
        for _ in range(BLOB_ATTEMPTS - 1):
            try:
                return store.run_atomic(operation)
            except ProjectStorageError:
                continue
        return store.run_atomic(operation)
    return store.run_atomic(operation)
