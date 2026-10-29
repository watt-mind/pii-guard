"""Hosted configuration snapshots: synthetic state, bounded memory, fresh reads and CAS."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from pii_guard.policy import PolicySet
from pii_guard.projects.blob import MAX_BLOB_BYTES, MAX_DATABASE_BYTES, BlobProjectStore
from pii_guard.projects.store import ProjectNotFoundError, ProjectStorageError, ProjectStore

MASTER_KEY = b"synthetic-project-key".ljust(32, b"!")
UPSTREAM_KEY = "synthetic-upstream-secret"
OWNER = "synthetic-owner"


class SharedBlob:
    """One authoritative blob shared by independent app instances."""

    def __init__(self) -> None:
        self.value: bytes | None = None
        self.version = 0
        self.reads = 0
        self.writes = 0
        self.initializations = 0
        self.lock = threading.Lock()
        self.barrier: threading.Barrier | None = None
        self.ambiguous = False
        self.unavailable = False

    def read(self) -> tuple[bytes, str]:
        with self.lock:
            self.reads += 1
            if self.unavailable or self.value is None:
                raise RuntimeError("synthetic unavailable storage")
            result = self.value, f'"{self.version}"'
            barrier = self.barrier
        if barrier is not None:
            barrier.wait(timeout=5)
        return result

    def compare_and_swap(self, value: bytes, etag: str) -> None:
        with self.lock:
            self.writes += 1
            if self.unavailable:
                raise RuntimeError("synthetic unavailable storage")
            if etag != f'"{self.version}"':
                raise RuntimeError("synthetic HTTP 412")
            self.value = value
            self.version += 1
            if self.ambiguous:
                raise TimeoutError("synthetic unknown commit")

    def initialize(self, value: bytes) -> None:
        with self.lock:
            self.initializations += 1
            if self.value is not None:
                raise RuntimeError("synthetic already initialized")
            self.value = value
            self.version += 1

    def close(self) -> None:
        pass


def store(blob: SharedBlob, *, key: bytes = MASTER_KEY, environment: str = "dev"):
    return BlobProjectStore(blob, key, PolicySet(), "standard", environment)


@pytest.fixture
def blob() -> SharedBlob:
    blob = SharedBlob()
    store(blob).initialize_empty()
    return blob


def endpoint(instance: BlobProjectStore) -> tuple[dict[str, Any], dict[str, Any]]:
    project = instance.default_project(OWNER)
    configured = instance.save_endpoint(
        OWNER,
        project["id"],
        {
            "name": "Synthetic endpoint",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "synthetic-model",
            "api_key": UPSTREAM_KEY,
            "policy_version_id": project["default_policy_version_id"],
        },
    )
    return project, configured


def test_restart_preserves_config_credentials_and_verifier_without_plaintext(blob: SharedBlob):
    first = store(blob)
    project, configured = endpoint(first)
    policy = first.create_policy(OWNER, project["id"], {"name": "Synthetic revised policy"})
    issued = first.issue_key(OWNER, project["id"], configured["id"], "Synthetic key")
    first.close()

    assert blob.value is not None
    assert not blob.value.startswith(b"SQLite format 3")
    assert UPSTREAM_KEY.encode() not in blob.value
    assert issued["key"].encode() not in blob.value
    assert OWNER.encode() not in blob.value
    second = store(blob)
    assert second.default_project(OWNER) == project
    assert second.list_endpoints(OWNER, project["id"]) == [configured]
    assert second.get_policy(OWNER, project["id"], policy["policy_version_id"]) == policy
    snapshot = second.resolve_key(issued["key"], configured["id"])
    assert snapshot is not None and snapshot.api_key is not None
    assert snapshot.api_key.get_secret_value() == UPSTREAM_KEY
    assert UPSTREAM_KEY not in repr(snapshot)
    database = second._decode(blob.value)
    assert UPSTREAM_KEY.encode() not in database
    assert issued["key"].encode() not in database
    assert hashlib.sha256(issued["key"].encode()).digest() in database


def test_existing_read_only_operations_never_put(blob: SharedBlob):
    instance = store(blob)
    project, configured = endpoint(instance)
    issued = instance.issue_key(OWNER, project["id"], configured["id"], "Synthetic key")
    writes, reads = blob.writes, blob.reads
    assert instance.default_project(OWNER) == project
    assert instance.list_projects(OWNER) == [project]
    assert instance.get_project(OWNER, project["id"]) == project
    assert instance.list_policies(OWNER, project["id"])
    assert instance.get_policy(OWNER, project["id"], project["default_policy_version_id"])
    assert instance.list_endpoints(OWNER, project["id"]) == [configured]
    assert instance.endpoint_snapshot(OWNER, project["id"], configured["id"])
    assert instance.list_keys(OWNER, project["id"], configured["id"])
    assert instance.resolve_key(issued["key"], configured["id"])
    assert instance.resolve_key("pg_ep_synthetic-invalid", configured["id"]) is None
    assert blob.writes == writes
    assert blob.reads == reads + 10


def test_revocation_is_seen_on_next_admission_across_instances(blob: SharedBlob):
    first, second = store(blob), store(blob)
    project, configured = endpoint(first)
    issued = first.issue_key(OWNER, project["id"], configured["id"], "Synthetic key")
    assert second.resolve_key(issued["key"], configured["id"]) is not None
    first.revoke_key(OWNER, project["id"], configured["id"], issued["id"])
    assert second.resolve_key(issued["key"], configured["id"]) is None


def test_disable_and_delete_are_fresh_across_instances(blob: SharedBlob):
    first, second = store(blob), store(blob)
    project, configured = endpoint(first)
    issued = first.issue_key(OWNER, project["id"], configured["id"], "Synthetic key")
    first.save_endpoint(
        OWNER,
        project["id"],
        {**configured, "enabled": False},
        configured["id"],
    )
    assert second.resolve_key(issued["key"], configured["id"]) is None
    first.save_endpoint(OWNER, project["id"], {**configured, "enabled": True}, configured["id"])
    assert second.resolve_key(issued["key"], configured["id"]) is None
    first.delete_endpoint(OWNER, project["id"], configured["id"])
    assert second.list_endpoints(OWNER, project["id"]) == []


def test_concurrent_writers_one_commit_one_503_without_replay(blob: SharedBlob):
    first, second = store(blob), store(blob)
    first.default_project(OWNER)
    before_reads, before_writes = blob.reads, blob.writes
    blob.barrier = threading.Barrier(2)

    def create(instance: BlobProjectStore, name: str):
        try:
            return instance.create_project(OWNER, name)
        except ProjectStorageError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as workers:
        one = workers.submit(create, first, "Synthetic one")
        two = workers.submit(create, second, "Synthetic two")
        results = [one.result(timeout=10), two.result(timeout=10)]
    blob.barrier = None
    assert sum(isinstance(result, dict) for result in results) == 1
    errors = [result for result in results if isinstance(result, ProjectStorageError)]
    assert len(errors) == 1 and errors[0].status_code == 503
    assert blob.reads == before_reads + 2
    assert blob.writes == before_writes + 2
    assert len(first.list_projects(OWNER)) == 2


def test_ambiguous_key_commit_does_not_return_secret_or_replay(blob: SharedBlob):
    instance = store(blob)
    project, configured = endpoint(instance)
    before_writes, before_reads = blob.writes, blob.reads
    blob.ambiguous = True
    with pytest.raises(ProjectStorageError) as caught:
        instance.issue_key(OWNER, project["id"], configured["id"], "Synthetic ambiguous key")
    assert "pg_ep_" not in str(caught.value)
    assert UPSTREAM_KEY not in str(caught.value)
    assert blob.writes == before_writes + 1
    assert blob.reads == before_reads + 1
    blob.ambiguous = False
    # The durable verifier may exist, but no key value was returned to the caller.
    keys = store(blob).list_keys(OWNER, project["id"], configured["id"])
    assert len(keys) == 1
    assert "key" not in keys[0]


def test_missing_blob_never_initializes_or_falls_back():
    blob = SharedBlob()
    instance = store(blob)
    with pytest.raises(ProjectStorageError):
        instance.default_project(OWNER)
    assert blob.initializations == 0
    assert blob.writes == 0
    assert blob.value is None


def test_initializer_is_explicit_create_only(blob: SharedBlob):
    original = blob.value
    with pytest.raises(ProjectStorageError):
        store(blob).initialize_empty()
    assert blob.value == original
    assert blob.writes == 0


def test_outage_never_uses_previous_snapshot(blob: SharedBlob):
    instance = store(blob)
    project, configured = endpoint(instance)
    issued = instance.issue_key(OWNER, project["id"], configured["id"], "Synthetic key")
    assert instance.resolve_key(issued["key"], configured["id"])
    blob.unavailable = True
    with pytest.raises(ProjectStorageError):
        instance.resolve_key(issued["key"], configured["id"])
    with pytest.raises(ProjectStorageError):
        instance.get_project(OWNER, project["id"])


@pytest.mark.parametrize("key,environment", [(b"x" * 32, "dev"), (MASTER_KEY, "prod")])
def test_wrong_key_or_environment_fails_closed(blob: SharedBlob, key: bytes, environment: str):
    with pytest.raises(ProjectStorageError):
        store(blob, key=key, environment=environment).default_project(OWNER)
    assert blob.writes == 0


@pytest.mark.parametrize(
    "value",
    [b"", b"synthetic corrupt blob", b"x" * (MAX_BLOB_BYTES + 1)],
    ids=["empty", "corrupt", "oversized"],
)
def test_invalid_or_oversized_blob_fails_closed(blob: SharedBlob, value: bytes):
    blob.value = value
    with pytest.raises(ProjectStorageError):
        store(blob).default_project(OWNER)
    assert blob.writes == 0


def test_authenticated_oversized_database_fails_closed(blob: SharedBlob):
    instance = store(blob)
    blob.value = instance._cipher.encrypt(instance._binding + b"x" * (MAX_DATABASE_BYTES + 1))
    with pytest.raises(ProjectStorageError):
        instance.default_project(OWNER)
    assert blob.writes == 0


def test_authenticated_wrong_environment_binding_fails_closed(blob: SharedBlob):
    instance = store(blob)
    engine = ProjectStore.memory(MASTER_KEY, PolicySet(), "standard")
    try:
        blob.value = instance._cipher.encrypt(
            b"pii-guard-project-snapshot-v1\0prod\0" + engine.serialized()
        )
    finally:
        engine.close()
    with pytest.raises(ProjectStorageError):
        instance.default_project(OWNER)
    assert blob.writes == 0


@pytest.mark.parametrize("damage", ["schema", "sentinel", "missing_sentinel", "foreign_key"])
def test_authenticated_invalid_database_is_not_repaired(blob: SharedBlob, damage: str):
    instance = store(blob)
    engine = ProjectStore.memory(MASTER_KEY, PolicySet(), "standard")
    try:
        if damage == "schema":
            engine._db.execute("CREATE TABLE synthetic_unexpected (value TEXT)")
        elif damage == "sentinel":
            engine._db.execute("UPDATE store_metadata SET value = ?", (b"synthetic invalid token",))
        elif damage == "missing_sentinel":
            engine._db.execute("DELETE FROM store_metadata")
        else:
            engine._db.execute("PRAGMA foreign_keys = OFF")
            engine._db.execute(
                "INSERT INTO endpoint_keys VALUES (?, ?, ?, ?, ?, NULL)",
                (
                    "synthetic-key",
                    "synthetic-missing-endpoint",
                    "Synthetic key",
                    b"x" * 32,
                    "2026-10-28",
                ),
            )
        engine._db.commit()
        blob.value = instance._encode(engine.serialized())
    finally:
        engine.close()
    original = blob.value
    with pytest.raises(ProjectStorageError):
        instance.default_project(OWNER)
    assert blob.value == original
    assert blob.writes == 0


def test_inner_key_sentinel_is_checked_with_valid_outer_envelope(blob: SharedBlob):
    instance = store(blob)
    wrong_inner = ProjectStore.memory(b"x" * 32, PolicySet(), "standard")
    try:
        blob.value = instance._encode(wrong_inner.serialized())
    finally:
        wrong_inner.close()
    with pytest.raises(ProjectStorageError):
        instance.default_project(OWNER)
    assert blob.writes == 0


def test_memory_engine_has_no_file_and_enforces_page_limit():
    engine = ProjectStore.memory(MASTER_KEY, PolicySet(), "standard")
    try:
        assert engine._db.execute("PRAGMA database_list").fetchone()[2] == ""
        assert engine._db.execute("PRAGMA temp_store").fetchone()[0] == 2
        assert engine._db.execute("PRAGMA page_size").fetchone()[0] == 4096
        assert engine._db.execute("PRAGMA max_page_count").fetchone()[0] == 2048
        with pytest.raises(sqlite3.OperationalError, match="full"):
            engine._db.execute(
                "INSERT INTO store_metadata VALUES ('synthetic-too-large', zeroblob(?))",
                (MAX_DATABASE_BYTES,),
            )
        engine._db.rollback()
        assert len(engine.serialized()) <= MAX_DATABASE_BYTES
    finally:
        engine.close()


def test_invalid_etag_fails_before_mutation(blob: SharedBlob, monkeypatch: pytest.MonkeyPatch):
    assert blob.value is not None
    monkeypatch.setattr(blob, "read", lambda: (blob.value, "*"))
    with pytest.raises(ProjectStorageError):
        store(blob).default_project(OWNER)
    assert blob.writes == 0


def test_owner_boundaries_remain_enforced(blob: SharedBlob):
    instance = store(blob)
    project = instance.default_project(OWNER)
    with pytest.raises(ProjectNotFoundError):
        instance.get_project("synthetic-other-owner", project["id"])


def test_closed_store_fails_without_storage_access(blob: SharedBlob):
    instance = store(blob)
    instance.close()
    before = blob.reads
    with pytest.raises(ProjectStorageError):
        instance.default_project(OWNER)
    assert blob.reads == before
