"""Durable configuration, immutable versions and endpoint credential boundaries (synthetic)."""

from __future__ import annotations

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from pii_guard.policy import PolicySet
from pii_guard.projects.store import (
    InvalidProjectConfigError,
    ProjectNotFoundError,
    ProjectStorageError,
    ProjectStore,
)

MASTER_KEY = b"synthetic-project-store-masterkey"
UPSTREAM_KEY = "synthetic-upstream-secret"


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state" / "projects.sqlite3"


@pytest.fixture
def store(store_path: Path):
    instance = ProjectStore(str(store_path), MASTER_KEY, PolicySet(), "standard")
    try:
        yield instance
    finally:
        instance.close()


def endpoint(store: ProjectStore, *, owner: str = "owner-a", name: str = "Test endpoint"):
    project = store.default_project(owner)
    policy = store.list_policies(owner, project["id"])[0]
    result = store.save_endpoint(
        owner,
        project["id"],
        {
            "name": name,
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "synthetic-model",
            "api_key": UPSTREAM_KEY,
            "policy_version_id": policy["policy_version_id"],
        },
    )
    return project, policy, result


def test_restart_preserves_configuration_and_only_encrypted_credentials(store_path: Path) -> None:
    first = ProjectStore(str(store_path), MASTER_KEY, PolicySet(), "standard")
    project, policy, configured = endpoint(first)
    issued = first.issue_key("owner-a", project["id"], configured["id"], "Synthetic client")
    first.close()

    persisted = store_path.read_bytes()
    assert UPSTREAM_KEY.encode() not in persisted
    assert issued["key"].encode() not in persisted
    assert hashlib.sha256(issued["key"].encode()).digest() in persisted
    assert store_path.stat().st_mode & 0o077 == 0
    assert store_path.parent.stat().st_mode & 0o077 == 0

    reopened = ProjectStore(str(store_path), MASTER_KEY, PolicySet(), "standard")
    try:
        assert reopened.default_project("owner-a")["id"] == project["id"]
        assert reopened.list_endpoints("owner-a", project["id"]) == [configured]
        snapshot = reopened.resolve_key(issued["key"], configured["id"])
        assert snapshot is not None
        assert snapshot.api_key is not None
        assert snapshot.api_key.get_secret_value() == UPSTREAM_KEY
        assert snapshot.policy_version_id == policy["policy_version_id"]
        assert UPSTREAM_KEY not in repr(snapshot)
        assert "key" not in reopened.list_keys("owner-a", project["id"], configured["id"])[0]
    finally:
        reopened.close()


def test_keys_are_endpoint_scoped_revocable_and_disabled_endpoint_denies(
    store: ProjectStore,
) -> None:
    project, _, configured = endpoint(store)
    _, _, other = endpoint(store, name="Other endpoint")
    key = store.issue_key("owner-a", project["id"], configured["id"], "Synthetic client")
    assert store.resolve_key(key["key"], configured["id"]) is not None
    assert store.resolve_key(key["key"], other["id"]) is None
    assert store.resolve_key("pg_ep_synthetic-invalid", configured["id"]) is None
    store.revoke_key("owner-a", project["id"], configured["id"], key["id"])
    store.revoke_key("owner-a", project["id"], configured["id"], key["id"])
    assert store.resolve_key(key["key"], configured["id"]) is None
    assert store.list_keys("owner-a", project["id"], configured["id"])[0]["revoked_at"]

    replacement = store.issue_key("owner-a", project["id"], configured["id"], "Replacement")
    store.save_endpoint(
        "owner-a", project["id"], {**configured, "enabled": False}, configured["id"]
    )
    assert store.resolve_key(replacement["key"], configured["id"]) is None
    with pytest.raises(ProjectNotFoundError):
        store.endpoint_snapshot("owner-a", project["id"], configured["id"])


def test_owner_isolation_and_policy_versions_remain_pinned(store: ProjectStore) -> None:
    project, policy, configured = endpoint(store)
    _, _, other_owner_endpoint = endpoint(store, owner="owner-b")
    before = store.endpoint_snapshot("owner-a", project["id"], configured["id"])
    next_policy = store.create_policy(
        "owner-a",
        project["id"],
        {"name": "Revised policy", "entity_policies": {"EMAIL": "block"}},
        policy["policy_id"],
    )
    assert next_policy["version"] == 2
    assert next_policy["policy_version_id"] != policy["policy_version_id"]
    assert store.get_policy("owner-a", project["id"], policy["policy_version_id"]) == policy
    assert (
        store.default_project("owner-a")["default_policy_version_id"] == policy["policy_version_id"]
    )
    assert before.policy["entity_policies"]["EMAIL"] == "mask"
    assert store.endpoint_snapshot("owner-a", project["id"], configured["id"]) == before
    with pytest.raises(FrozenInstanceError):
        before.model = "changed-model"  # type: ignore[misc]
    with pytest.raises(TypeError):
        before.policy["entity_policies"]["EMAIL"] = "keep"
    with pytest.raises(ProjectNotFoundError):
        store.get_project("owner-b", project["id"])
    with pytest.raises(ProjectNotFoundError):
        store.list_policies("owner-b", project["id"])
    with pytest.raises(ProjectNotFoundError):
        store.endpoint_snapshot("owner-a", project["id"], other_owner_endpoint["id"])
    with pytest.raises(ProjectNotFoundError):
        store.delete_endpoint("owner-b", project["id"], configured["id"])
    with pytest.raises(ProjectNotFoundError):
        store.issue_key("owner-b", project["id"], configured["id"], "Forbidden")

    updated = store.save_endpoint(
        "owner-a",
        project["id"],
        {**configured, "policy_version_id": next_policy["policy_version_id"]},
        configured["id"],
    )
    assert updated["policy_version_id"] == next_policy["policy_version_id"]
    assert before.policy_version_id == policy["policy_version_id"]


def test_concurrent_default_creation_has_one_project_and_one_policy(store: ProjectStore) -> None:
    with ThreadPoolExecutor(max_workers=4) as pool:
        projects = list(pool.map(store.default_project, ["owner-a"] * 12))
    assert len({project["id"] for project in projects}) == 1
    assert len(store.list_projects("owner-a")) == 1
    assert len(store.list_policies("owner-a", projects[0]["id"])) == 1


def test_wrong_master_key_refuses_existing_store_at_startup(store_path: Path) -> None:
    first = ProjectStore(str(store_path), MASTER_KEY, PolicySet(), "standard")
    endpoint(first)
    first.close()
    with pytest.raises(ProjectStorageError):
        ProjectStore(str(store_path), b"different-synthetic-master-key!!!", PolicySet(), "standard")


def test_swapped_encrypted_credential_is_rejected(store: ProjectStore, store_path: Path) -> None:
    project, _, first = endpoint(store)
    _, _, second = endpoint(store, name="Another endpoint")
    with sqlite3.connect(store_path) as database:
        database.execute(
            "UPDATE endpoints SET credential = (SELECT credential FROM endpoints WHERE id=?) "
            "WHERE id=?",
            (first["id"], second["id"]),
        )
    with pytest.raises(ProjectStorageError):
        store.endpoint_snapshot("owner-a", project["id"], second["id"])


def test_key_rotation_keeps_history_bounded_without_evicting_active_keys(
    store: ProjectStore,
) -> None:
    project, _, configured = endpoint(store)
    other_project, _, other = endpoint(store, owner="owner-b")
    other_key = store.issue_key("owner-b", other_project["id"], other["id"], "Other active client")
    permanent = store.issue_key(
        "owner-a", project["id"], configured["id"], "Permanent active client"
    )
    revoked: list[dict[str, Any]] = []
    for _ in range(160):
        key = store.issue_key("owner-a", project["id"], configured["id"], "Rotated client")
        store.revoke_key("owner-a", project["id"], configured["id"], key["id"])
        revoked.append(key)
    current = store.issue_key("owner-a", project["id"], configured["id"], "Current client")
    assert len(store.list_keys("owner-a", project["id"], configured["id"])) <= 128
    assert store.resolve_key(current["key"], configured["id"]) is not None
    assert store.resolve_key(permanent["key"], configured["id"]) is not None
    assert store.resolve_key(other_key["key"], other["id"]) is not None
    assert all(store.resolve_key(item["key"], configured["id"]) is None for item in revoked)


def test_active_key_limit_does_not_evict_existing_keys(store: ProjectStore) -> None:
    project, _, configured = endpoint(store)
    keys = [
        store.issue_key("owner-a", project["id"], configured["id"], "Client") for _ in range(32)
    ]
    with pytest.raises(InvalidProjectConfigError):
        store.issue_key("owner-a", project["id"], configured["id"], "Over capacity")
    assert all(store.resolve_key(key["key"], configured["id"]) is not None for key in keys)
