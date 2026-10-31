"""Optional endpoint model (LAB-1451): pinned vs pass-through, and old snapshots still load.

Pass-through is stored as ``''`` in the existing ``model TEXT NOT NULL`` column, so the
schema is unchanged and a snapshot written before LAB-1451 loads as is. All values synthetic.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
from typing import Any

import pytest
from cryptography.fernet import Fernet

from pii_guard.policy import PolicySet
from pii_guard.projects.blob import BlobProjectStore
from pii_guard.projects.store import InvalidProjectConfigError, ProjectStore
from pii_guard.types import TEXT_ENTITY_TYPES

MASTER_KEY = b"synthetic-endpoint-model-key".ljust(32, b"!")
OWNER = "synthetic-owner"
UPSTREAM_KEY = "synthetic-upstream-secret"

# The endpoint schema exactly as deployed before LAB-1451, frozen here on purpose: if the
# live schema ever drifts from it, existing dev/prod snapshots would stop loading.
PRE_LAB_1451_SCHEMA = """
                CREATE TABLE IF NOT EXISTS store_metadata (
                    name TEXT PRIMARY KEY, value BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL,
                    is_default INTEGER NOT NULL DEFAULT 0, default_policy_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS owner_default ON projects(owner_id)
                    WHERE is_default = 1;
                CREATE TABLE IF NOT EXISTS policy_versions (
                    policy_version_id TEXT PRIMARY KEY, policy_id TEXT NOT NULL,
                    project_id TEXT NOT NULL REFERENCES projects(id), version INTEGER NOT NULL,
                    name TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(policy_id, version)
                );
                CREATE TABLE IF NOT EXISTS endpoints (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    name TEXT NOT NULL, policy_version_id TEXT NOT NULL
                        REFERENCES policy_versions(policy_version_id),
                    provider TEXT NOT NULL, base_url TEXT NOT NULL, model TEXT NOT NULL,
                    credential BLOB, enabled INTEGER NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS endpoint_keys (
                    id TEXT PRIMARY KEY, endpoint_id TEXT NOT NULL REFERENCES endpoints(id),
                    name TEXT NOT NULL, digest BLOB NOT NULL UNIQUE,
                    created_at TEXT NOT NULL, revoked_at TEXT
                );
                """


class Blob:
    def __init__(self, value: bytes | None = None) -> None:
        self.value, self.version, self.writes = value, 1, 0

    def read(self) -> tuple[bytes, str]:
        assert self.value is not None
        return self.value, f'"{self.version}"'

    def compare_and_swap(self, value: bytes, etag: str) -> None:
        assert etag == f'"{self.version}"'
        self.value, self.version, self.writes = value, self.version + 1, self.writes + 1

    def initialize(self, value: bytes) -> None:
        assert self.value is None
        self.value = value

    def close(self) -> None:
        pass


def blob_store(blob: Blob) -> BlobProjectStore:
    return BlobProjectStore(blob, MASTER_KEY, PolicySet(), "standard", "dev")


@pytest.fixture
def store():
    instance = ProjectStore.memory(MASTER_KEY, PolicySet(), "standard")
    try:
        yield instance
    finally:
        instance.close()


def _data(project: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {
        "name": "Synthetic endpoint",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": UPSTREAM_KEY,
        "policy_version_id": project["default_policy_version_id"],
        **fields,
    }


@pytest.mark.parametrize("model", [None, "", "   "])
@pytest.mark.parametrize("provider", ["custom", "openai", "openrouter", "fireworks", "meta"])
def test_byok_endpoint_without_model_is_pass_through(store, provider, model):
    project = store.default_project(OWNER)
    data = _data(project, provider=provider)
    if model is not None:
        data["model"] = model
    saved = store.save_endpoint(OWNER, project["id"], data)
    assert saved["model"] is None
    snapshot = store.endpoint_snapshot(OWNER, project["id"], saved["id"])
    assert snapshot.model is None
    raw = store._db.execute("SELECT model FROM endpoints WHERE id = ?", (saved["id"],)).fetchone()
    assert raw[0] == ""


def test_byok_endpoint_with_model_stays_pinned_and_can_switch(store):
    project = store.default_project(OWNER)
    pinned = store.save_endpoint(OWNER, project["id"], _data(project, model=" synthetic-model "))
    assert pinned["model"] == "synthetic-model"
    assert store.endpoint_snapshot(OWNER, project["id"], pinned["id"]).model == "synthetic-model"
    # Edit to pass-through (the credential is kept), then back to pinned.
    edit = _data(project, model="")
    del edit["api_key"]
    passed = store.save_endpoint(OWNER, project["id"], edit, endpoint_id=pinned["id"])
    assert passed["model"] is None and passed["credential_configured"]
    edit["model"] = "synthetic-other"
    again = store.save_endpoint(OWNER, project["id"], edit, endpoint_id=pinned["id"])
    assert again["model"] == "synthetic-other"


@pytest.mark.parametrize("model", [None, "", "  "])
def test_sponsored_endpoint_requires_a_pinned_model(store, model):
    project = store.default_project(OWNER)
    data = _data(project, provider="sponsored", base_url="https://api.meta.ai/v1")
    del data["api_key"]
    if model is not None:
        data["model"] = model
    with pytest.raises(InvalidProjectConfigError):
        store.save_endpoint(OWNER, project["id"], data)
    data["model"] = "muse-spark-1.3"
    assert store.save_endpoint(OWNER, project["id"], data)["model"] == "muse-spark-1.3"


@pytest.mark.parametrize("model", [7, ["synthetic"], "x" * 257, "bad\nmodel"])
def test_invalid_models_are_still_rejected(store, model):
    project = store.default_project(OWNER)
    with pytest.raises(InvalidProjectConfigError):
        store.save_endpoint(OWNER, project["id"], _data(project, model=model))


def test_live_schema_is_still_the_pre_lab_1451_schema():
    def master(schema: str) -> list[tuple[Any, ...]]:
        db = sqlite3.connect(":memory:")
        try:
            db.executescript(schema)
            return db.execute("SELECT type, name, tbl_name, sql FROM sqlite_master").fetchall()
        finally:
            db.close()

    from pii_guard.projects import store as module

    # LAB-1708 only adds tables; the frozen tables and their DDL are untouched, so a snapshot
    # of this schema is recognised and upgraded on load.
    assert master(module._SCHEMA_V1) == master(PRE_LAB_1451_SCHEMA)
    assert module._SCHEMA == module._SCHEMA_V1 + module._SCHEMA_UPGRADE
    assert set(master(PRE_LAB_1451_SCHEMA)) <= set(master(module._SCHEMA))


def _old_snapshot() -> tuple[bytes, dict[str, str]]:
    """A snapshot written by raw SQL against the frozen pre-LAB-1451 schema."""
    cipher = Fernet(
        base64.urlsafe_b64encode(
            hmac.digest(MASTER_KEY, b"pii-guard-project-credentials-v1", "sha256")
        )
    )
    defaults = PolicySet()
    policy = {
        "entity_policies": {t.value: defaults.of(t).value for t in TEXT_ENTITY_TYPES},
        "language": "hu",
        "mode": "fast",
        "detection_profile": "standard",
    }
    ids = {"project": "p" * 24, "family": "f" * 24, "version": "v" * 24, "endpoint": "e" * 24}
    created = "2026-10-01T00:00:00+00:00"
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(PRE_LAB_1451_SCHEMA)
        db.execute(
            "INSERT INTO store_metadata VALUES ('key_check', ?)",
            (cipher.encrypt(b"pii-guard-project-store-v1"),),
        )
        db.execute(
            "INSERT INTO projects VALUES (?, ?, 'Default project', 1, ?, ?)",
            (ids["project"], OWNER, ids["family"], created),
        )
        db.execute(
            "INSERT INTO policy_versions VALUES (?, ?, ?, 1, 'Default policy', ?, ?)",
            (ids["version"], ids["family"], ids["project"], json.dumps(policy), created),
        )
        envelope = {
            "owner": OWNER,
            "project": ids["project"],
            "endpoint": ids["endpoint"],
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "key": UPSTREAM_KEY,
        }
        db.execute(
            "INSERT INTO endpoints VALUES (?, ?, 'Old endpoint', ?, 'openai', "
            "'https://api.openai.com/v1', 'synthetic-pinned', ?, 1, ?)",
            (
                ids["endpoint"],
                ids["project"],
                ids["version"],
                cipher.encrypt(json.dumps(envelope).encode()),
                created,
            ),
        )
        db.execute(
            "INSERT INTO endpoint_keys VALUES ('k', ?, 'Old key', ?, ?, NULL)",
            (ids["endpoint"], hashlib.sha256(b"pg_ep_synthetic-old-key").digest(), created),
        )
        db.commit()
        return db.serialize(), ids
    finally:
        db.close()


def test_pre_lab_1451_snapshot_loads_keeps_its_pin_and_accepts_pass_through():
    database, ids = _old_snapshot()
    blob = Blob()
    blob.value = blob_store(blob)._encode(database)
    original = blob.value
    instance = blob_store(blob)

    endpoints = instance.list_endpoints(OWNER, ids["project"])
    assert [(e["id"], e["model"]) for e in endpoints] == [(ids["endpoint"], "synthetic-pinned")]
    snapshot = instance.resolve_key("pg_ep_synthetic-old-key", ids["endpoint"])
    assert snapshot is not None and snapshot.model == "synthetic-pinned"
    assert snapshot.api_key is not None and snapshot.api_key.get_secret_value() == UPSTREAM_KEY
    # Reads never rewrite the blob: nothing was migrated, reset or overwritten.
    assert blob.value == original and blob.writes == 0

    # New pass-through endpoints write into the same, unchanged schema; the old pin survives.
    project = {"default_policy_version_id": ids["version"]}
    added = instance.save_endpoint(OWNER, ids["project"], _data(project, name="New endpoint"))
    assert added["model"] is None and blob.writes == 1
    reloaded = blob_store(blob)
    models = {e["name"]: e["model"] for e in reloaded.list_endpoints(OWNER, ids["project"])}
    assert models == {"Old endpoint": "synthetic-pinned", "New endpoint": None}
    assert reloaded.resolve_key("pg_ep_synthetic-old-key", ids["endpoint"]) is not None
