"""Project policies hold visual actions and ``visual_detection``, versioned like text (LAB-1444).

Synthetic owners and store keys only.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from pii_guard.policy import Policy, PolicySet
from pii_guard.projects.store import InvalidProjectConfigError, ProjectStore
from pii_guard.types import EntityType

MASTER_KEY = b"synthetic-project-store-masterkey"
OWNER = "synthetic-owner"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ProjectStore]:
    instance = ProjectStore(
        str(tmp_path / "state" / "p.sqlite3"), MASTER_KEY, PolicySet(), "standard"
    )
    try:
        yield instance
    finally:
        instance.close()


def test_defaults_hold_visual_types_and_local_detection(store: ProjectStore) -> None:
    project = store.default_project(OWNER)
    policy = store.get_policy(OWNER, project["id"], project["default_policy_version_id"])
    assert policy["visual_detection"] == "local"
    assert {
        k: policy["entity_policies"][k] for k in ("FACE", "ID_PHOTO", "SIGNATURE", "STAMP")
    } == {
        "FACE": "mask",
        "ID_PHOTO": "mask",
        "SIGNATURE": "mask",
        "STAMP": "keep",
    }


def test_visual_actions_and_detection_are_versioned(store: ProjectStore) -> None:
    project = store.default_project(OWNER)
    first = store.create_policy(
        OWNER,
        project["id"],
        {"name": "Images", "entity_policies": {"SIGNATURE": "keep", "STAMP": "mask"}},
    )
    assert first["entity_policies"]["SIGNATURE"] == "keep"
    assert first["entity_policies"]["STAMP"] == "mask"
    second = store.create_policy(
        OWNER,
        project["id"],
        {"name": "Images", "visual_detection": "sam"},
        policy_id=first["policy_id"],
    )
    assert second["version"] == 2 and second["visual_detection"] == "sam"
    # The earlier version is unchanged (append-only).
    again = store.get_policy(OWNER, project["id"], first["policy_version_id"])
    assert again["visual_detection"] == "local"
    assert again["entity_policies"]["SIGNATURE"] == "keep"


@pytest.mark.parametrize(
    "data",
    [
        {"entity_policies": {"SIGNATURE": "block"}},
        {"entity_policies": {"FACE": "blur"}},
        {"entity_policies": {"NOT_A_TYPE": "mask"}},
        {"visual_detection": "cloud"},
        {"visual_detection": ["sam"]},
    ],
)
def test_invalid_visual_settings_are_refused(store: ProjectStore, data: dict) -> None:
    project = store.default_project(OWNER)
    with pytest.raises(InvalidProjectConfigError):
        store.create_policy(OWNER, project["id"], {"name": "Bad", **data})


def test_local_only_deployments_refuse_sam(tmp_path: Path) -> None:
    store = ProjectStore(str(tmp_path / "s" / "p.sqlite3"), MASTER_KEY, PolicySet(), "local-only")
    try:
        project = store.default_project(OWNER)
        with pytest.raises(InvalidProjectConfigError):
            store.create_policy(OWNER, project["id"], {"name": "R", "visual_detection": "sam"})
        local = store.create_policy(OWNER, project["id"], {"name": "L"})
        assert local["visual_detection"] == "local"
    finally:
        store.close()


def test_server_defaults_seed_visual_actions(tmp_path: Path) -> None:
    server = PolicySet({EntityType.SIGNATURE: Policy.KEEP, EntityType.FACE: Policy.BLOCK})
    store = ProjectStore(str(tmp_path / "s" / "p.sqlite3"), MASTER_KEY, server, "standard")
    try:
        project = store.default_project(OWNER)
        policy = store.get_policy(OWNER, project["id"], project["default_policy_version_id"])
        assert policy["entity_policies"]["SIGNATURE"] == "keep"
        # Visual types are mask or keep: a blocked server default is stored as mask (and
        # the server's block still wins at request time).
        assert policy["entity_policies"]["FACE"] == "mask"
    finally:
        store.close()


def test_versions_saved_before_visual_types_still_read(store: ProjectStore) -> None:
    project = store.default_project(OWNER)
    version = project["default_policy_version_id"]
    with store._transaction() as db:
        row = db.execute(
            "SELECT data FROM policy_versions WHERE policy_version_id = ?", (version,)
        ).fetchone()
        data = json.loads(row["data"])
        for key in ("FACE", "ID_PHOTO", "SIGNATURE", "STAMP"):
            del data["entity_policies"][key]
        del data["visual_detection"]
        db.execute(
            "UPDATE policy_versions SET data = ? WHERE policy_version_id = ?",
            (json.dumps(data), version),
        )
    legacy = store.get_policy(OWNER, project["id"], version)
    assert "visual_detection" not in legacy and "SIGNATURE" not in legacy["entity_policies"]
