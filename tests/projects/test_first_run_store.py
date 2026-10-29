"""First-run provisioning (LAB-1455): one default endpoint per owner, idempotent and race-safe.

Owners, keys and stores are synthetic (ADR 0005).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import SecretStr

from pii_guard.policy import PolicySet
from pii_guard.projects.blob import BlobProjectStore
from pii_guard.projects.first_run import (
    BLOB_ATTEMPTS,
    DEFAULT_ENDPOINT_NAME,
    FIRST_RUN_KEY_NAME,
    META_BASE_URL,
    endpoint_state,
    ensure_first_run,
)
from pii_guard.projects.store import InvalidProjectConfigError, ProjectStorageError, ProjectStore

MASTER_KEY = b"synthetic-project-key".ljust(32, b"!")
OWNER = "synthetic-owner"
OTHER = "synthetic-other-owner"
MODEL = "muse-spark-1.3"
OWN_KEY = "synthetic-own-meta-key"


class SharedBlob:
    """One authoritative blob shared by independent app instances, with conditional writes."""

    def __init__(self) -> None:
        self.value: bytes | None = None
        self.version = 0
        self.writes = 0
        self.lock = threading.Lock()

    def read(self) -> tuple[bytes, str]:
        with self.lock:
            if self.value is None:
                raise RuntimeError("synthetic missing blob")
            return self.value, f'"{self.version}"'

    def compare_and_swap(self, value: bytes, etag: str) -> None:
        with self.lock:
            self.writes += 1
            if etag != f'"{self.version}"':
                raise RuntimeError("synthetic HTTP 412")
            self.value, self.version = value, self.version + 1

    def initialize(self, value: bytes) -> None:
        with self.lock:
            self.value, self.version = value, self.version + 1

    def close(self) -> None:
        pass


@pytest.fixture
def local(tmp_path: Path) -> ProjectStore:
    path = tmp_path / "projects" / "state.sqlite3"
    path.parent.mkdir(mode=0o700)
    return ProjectStore(str(path), MASTER_KEY, PolicySet(), "standard")


def blob_store(blob: SharedBlob) -> BlobProjectStore:
    return BlobProjectStore(blob, MASTER_KEY, PolicySet(), "standard", "dev")


@pytest.fixture
def blob() -> SharedBlob:
    shared = SharedBlob()
    blob_store(shared).initialize_empty()
    return shared


def test_first_run_provisions_one_sponsored_endpoint_in_the_default_project(
    local: ProjectStore,
) -> None:
    first = ensure_first_run(local, OWNER, model=MODEL, sponsored_enabled=True)
    endpoint = first["endpoint"]
    assert first["created"] is True and first["state"] == "ready"
    assert first["project_id"] == local.default_project(OWNER)["id"]
    assert endpoint["name"] == DEFAULT_ENDPOINT_NAME
    assert endpoint["provider"] == "sponsored" and endpoint["model"] == MODEL
    assert (
        endpoint["policy_version_id"] == local.default_project(OWNER)["default_policy_version_id"]
    )
    assert first["key"] is None and first["active_keys"] == 0

    # Repeat sign-ins describe the same endpoint and never add another.
    again = ensure_first_run(local, OWNER, model=MODEL, sponsored_enabled=True)
    assert again["created"] is False and again["endpoint"]["id"] == endpoint["id"]
    assert len(local.list_endpoints(OWNER, first["project_id"])) == 1


def test_sponsorship_off_marks_the_endpoint_needs_key_and_still_issues_its_key(
    local: ProjectStore,
) -> None:
    result = ensure_first_run(local, OWNER, model=MODEL, sponsored_enabled=False, issue_key=True)
    assert result["state"] == "needs_key"
    assert result["key"]["key"].startswith("pg_ep_") and result["active_keys"] == 1
    # The same endpoint becomes ready by itself once sponsorship is available.
    later = ensure_first_run(local, OWNER, model=MODEL, sponsored_enabled=True, issue_key=True)
    assert later["state"] == "ready" and later["endpoint"]["id"] == result["endpoint"]["id"]
    assert later["key"] is None


def test_disabled_endpoint_gets_no_key(local: ProjectStore) -> None:
    first = ensure_first_run(local, OWNER, model=MODEL, sponsored_enabled=True)
    endpoint = first["endpoint"]
    local.save_endpoint(
        OWNER,
        first["project_id"],
        {
            **{
                k: endpoint[k]
                for k in ("name", "policy_version_id", "provider", "base_url", "model")
            },
            "enabled": False,
        },
        endpoint_id=endpoint["id"],
    )
    again = ensure_first_run(local, OWNER, model=MODEL, sponsored_enabled=True, issue_key=True)
    assert again["state"] == "disabled" and again["key"] is None


def test_own_meta_key_converts_the_needs_key_endpoint_in_place(local: ProjectStore) -> None:
    pending = ensure_first_run(local, OWNER, model=MODEL, sponsored_enabled=False)
    assert pending["key"] is None and pending["active_keys"] == 0
    ready = ensure_first_run(
        local,
        OWNER,
        model=MODEL,
        sponsored_enabled=False,
        issue_key=True,
        meta_api_key=SecretStr(OWN_KEY),
    )
    endpoint = ready["endpoint"]
    assert ready["state"] == "ready" and endpoint["id"] == pending["endpoint"]["id"]
    assert endpoint["provider"] == "meta" and endpoint["base_url"] == META_BASE_URL
    assert endpoint["model"] == MODEL and endpoint["credential_configured"] is True
    assert OWN_KEY not in repr(ready)
    snapshot = local.endpoint_snapshot(OWNER, ready["project_id"], endpoint["id"])
    assert snapshot.api_key is not None and snapshot.api_key.get_secret_value() == OWN_KEY

    key = ready["key"]
    assert key["name"] == FIRST_RUN_KEY_NAME and key["key"].startswith("pg_ep_")
    assert local.resolve_key(key["key"], endpoint["id"]) is not None
    # Shown once: a second request with an active key returns none.
    again = ensure_first_run(local, OWNER, model=MODEL, sponsored_enabled=False, issue_key=True)
    assert again["key"] is None and again["active_keys"] == 1
    # And an own-key endpoint never turns back into sponsored inference.
    assert again["endpoint"]["provider"] == "meta"
    assert ensure_first_run(local, OWNER, model=MODEL, sponsored_enabled=True)["state"] == "ready"


def test_meta_key_is_refused_unless_the_endpoint_needs_one(local: ProjectStore) -> None:
    ensure_first_run(local, OWNER, model=MODEL, sponsored_enabled=True)
    with pytest.raises(InvalidProjectConfigError):
        ensure_first_run(
            local, OWNER, model=MODEL, sponsored_enabled=True, meta_api_key=SecretStr(OWN_KEY)
        )
    converted = ensure_first_run(
        local, OTHER, model=MODEL, sponsored_enabled=False, meta_api_key=SecretStr(OWN_KEY)
    )
    assert converted["state"] == "ready"
    with pytest.raises(InvalidProjectConfigError):
        ensure_first_run(
            local, OTHER, model=MODEL, sponsored_enabled=False, meta_api_key=SecretStr("another")
        )


def test_existing_endpoints_are_kept_and_never_joined_by_a_default(local: ProjectStore) -> None:
    project = local.default_project(OWNER)
    custom = local.save_endpoint(
        OWNER,
        project["id"],
        {
            "name": "Synthetic own endpoint",
            "policy_version_id": project["default_policy_version_id"],
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "synthetic-model",
            "api_key": "synthetic-provider-key",
        },
    )
    result = ensure_first_run(local, OWNER, model=MODEL, sponsored_enabled=True)
    assert result["created"] is False and result["endpoint"]["id"] == custom["id"]
    assert result["state"] == "ready"
    assert len(local.list_endpoints(OWNER, project["id"])) == 1
    # Converting an own-key endpoint is the endpoint form's job, not first run's.
    with pytest.raises(InvalidProjectConfigError):
        ensure_first_run(
            local, OWNER, model=MODEL, sponsored_enabled=False, meta_api_key=SecretStr(OWN_KEY)
        )


def test_first_run_is_owner_scoped(local: ProjectStore) -> None:
    mine = ensure_first_run(local, OWNER, model=MODEL, sponsored_enabled=True, issue_key=True)
    theirs = ensure_first_run(local, OTHER, model=MODEL, sponsored_enabled=True, issue_key=True)
    assert mine["project_id"] != theirs["project_id"]
    assert mine["endpoint"]["id"] != theirs["endpoint"]["id"]
    assert local.resolve_key(mine["key"]["key"], theirs["endpoint"]["id"]) is None
    assert [e["id"] for e in local.list_endpoints(OTHER, theirs["project_id"])] == [
        theirs["endpoint"]["id"]
    ]


def test_concurrent_first_requests_create_one_endpoint_locally(local: ProjectStore) -> None:
    barrier = threading.Barrier(8)

    def first() -> str:
        barrier.wait(timeout=5)
        result = ensure_first_run(local, OWNER, model=MODEL, sponsored_enabled=True, issue_key=True)
        return str(result["endpoint"]["id"])

    with ThreadPoolExecutor(8) as pool:
        ids = set(pool.map(lambda _: first(), range(8)))
    project = local.default_project(OWNER)["id"]
    assert len(ids) == 1 and len(local.list_endpoints(OWNER, project)) == 1
    keys = local.list_keys(OWNER, project, ids.pop())
    assert len(keys) == 1


class RacingBlob(SharedBlob):
    """The first two reads wait for each other, so both replicas start from one snapshot."""

    def __init__(self) -> None:
        super().__init__()
        self.race = threading.Barrier(2)
        self.racing = 2

    def read(self) -> tuple[bytes, str]:
        result = super().read()
        with self.lock:
            wait, self.racing = self.racing > 0, self.racing - 1
        if wait:
            self.race.wait(timeout=5)
        return result


def test_concurrent_replicas_create_one_endpoint_in_the_blob() -> None:
    # Two app instances read the same snapshot before either writes: the conditional write
    # lets one win, and the other reads again and finds the winner's endpoint.
    blob = RacingBlob()
    blob_store(blob).initialize_empty()
    replicas = [blob_store(blob), blob_store(blob)]

    def first(store: BlobProjectStore) -> str:
        result = ensure_first_run(store, OWNER, model=MODEL, sponsored_enabled=True)
        return str(result["endpoint"]["id"])

    with ThreadPoolExecutor(2) as pool:
        ids = set(pool.map(first, replicas))
    fresh = blob_store(blob)
    project = fresh.default_project(OWNER)["id"]
    assert len(ids) == 1 and [e["id"] for e in fresh.list_endpoints(OWNER, project)] == list(ids)
    # Exactly one conflict, resolved by one fresh read.
    assert blob.version == 2


class ConflictingBlob(SharedBlob):
    """Loses the conditional write ``conflicts`` times, as if other replicas kept winning."""

    def __init__(self, conflicts: int) -> None:
        super().__init__()
        self.conflicts = conflicts

    def compare_and_swap(self, value: bytes, etag: str) -> None:
        with self.lock:
            lose, self.conflicts = self.conflicts > 0, self.conflicts - 1
        if lose:
            with self.lock:
                self.writes += 1
            raise RuntimeError("synthetic HTTP 412")
        super().compare_and_swap(value, etag)


def test_repeated_conflicts_are_retried_then_reported() -> None:
    # Two lost writes in a row (three racing replicas) still provision exactly one endpoint.
    blob = ConflictingBlob(conflicts=0)
    blob_store(blob).initialize_empty()
    blob.conflicts = BLOB_ATTEMPTS - 1
    result = ensure_first_run(blob_store(blob), OWNER, model=MODEL, sponsored_enabled=True)
    project = blob_store(blob).default_project(OWNER)["id"]
    assert [e["id"] for e in blob_store(blob).list_endpoints(OWNER, project)] == [
        result["endpoint"]["id"]
    ]
    # A store that never accepts the write surfaces as a storage error, not a loop.
    stuck = ConflictingBlob(conflicts=0)
    blob_store(stuck).initialize_empty()
    stuck.conflicts = BLOB_ATTEMPTS
    with pytest.raises(ProjectStorageError):
        ensure_first_run(blob_store(stuck), OWNER, model=MODEL, sponsored_enabled=True)
    assert stuck.writes == BLOB_ATTEMPTS


def test_first_run_loads_and_extends_an_existing_snapshot(blob: SharedBlob) -> None:
    # An owner who signed in before first run existed: default project, no endpoint.
    before = blob_store(blob)
    project = before.default_project(OWNER)
    stored = blob.value
    result = ensure_first_run(blob_store(blob), OWNER, model=MODEL, sponsored_enabled=False)
    assert result["project_id"] == project["id"] and result["created"] is True
    assert result["state"] == "needs_key" and blob.value != stored
    # Read-only repeats do not rewrite the snapshot.
    writes = blob.writes
    ensure_first_run(blob_store(blob), OWNER, model=MODEL, sponsored_enabled=False)
    assert blob.writes == writes


def test_endpoint_state() -> None:
    sponsored = {"enabled": True, "provider": "sponsored", "credential_configured": False}
    assert endpoint_state(sponsored, sponsored_enabled=True) == "ready"
    assert endpoint_state(sponsored, sponsored_enabled=False) == "needs_key"
    assert endpoint_state({**sponsored, "enabled": False}, sponsored_enabled=True) == "disabled"
    own = {"enabled": True, "provider": "meta", "credential_configured": True}
    assert endpoint_state(own, sponsored_enabled=False) == "ready"
