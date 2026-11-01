"""Config rewrites must not expose another provider's credentials (LAB-1760)."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from pii_guard.integrations import common
from pii_guard.integrations.run import _restored_files

OLD = b'{"providers":{"other":{"apiKey":"synthetic-other-provider-key"}}}\n'
NEW = common.render_json(
    {"providers": {"other": {"apiKey": "synthetic-other-provider-key"}, "pii-guard": {}}}
)
STAMP = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.parametrize("existing", [False, True])
def test_config_and_backup_are_private_before_any_bytes_are_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    path = tmp_path / "settings.json"
    if existing:
        path.write_bytes(OLD)
        path.chmod(0o600)
    fdopen = os.fdopen
    opened = []

    def private_fdopen(fd: int, *args: Any, **kwargs: Any) -> Any:
        opened.append(stat.S_IMODE(os.fstat(fd).st_mode))
        assert opened[-1] == 0o600
        return fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(common.os, "fdopen", private_fdopen)
    backup = common.write_json(path, NEW, now=STAMP)
    assert mode(path) == 0o600
    assert path.read_text() == NEW
    assert json.loads(path.read_bytes())["providers"]["other"]["apiKey"]
    if existing:
        assert backup is not None and mode(backup) == 0o600 and backup.read_bytes() == OLD
    else:
        assert backup is None
    assert len(opened) == (2 if existing else 1)
    assert not list(tmp_path.glob(".*.pii-guard-*"))


def test_existing_mode_is_preserved_and_backup_is_more_restrictive(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(OLD)
    path.chmod(0o640)
    backup = common.write_json(path, NEW)
    assert mode(path) == 0o640
    assert backup is not None and mode(backup) == 0o600


def test_predictable_symlinks_and_existing_backups_are_not_followed(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(OLD)
    path.chmod(0o600)
    victim = tmp_path / "unrelated.txt"
    victim.write_text("synthetic unrelated content")
    predictable_tmp = path.with_name(path.name + ".pii-guard-tmp")
    predictable_tmp.symlink_to(victim)
    predictable_backup = path.with_name(path.name + ".pii-guard-backup-20261101-120000")
    predictable_backup.symlink_to(victim)
    backup = common.write_json(path, NEW, now=STAMP)
    assert victim.read_text() == "synthetic unrelated content"
    assert predictable_tmp.is_symlink() and predictable_backup.is_symlink()
    assert backup is not None and backup != predictable_backup
    assert mode(backup) == 0o600 and backup.read_bytes() == OLD
    second = common.write_json(path, "{}\n", now=STAMP)
    assert second is not None and second != backup and second.read_text() == NEW


@pytest.mark.parametrize("fail", [False, True])
def test_run_restores_original_bytes_and_mode_even_on_error(tmp_path: Path, fail: bool) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(OLD)
    path.chmod(0o600)
    existing_backup = tmp_path / "settings.json.pii-guard-backup-existing"
    existing_backup.write_text("preexisting backup")

    def run() -> None:
        with _restored_files([path]):
            backup = common.write_json(path, NEW)
            assert mode(path) == 0o600 and path.read_text() == NEW
            assert backup is not None and mode(backup) == 0o600
            # Restore the saved metadata even if the child replaced its config file.
            path.unlink()
            path.write_text("child replacement")
            path.chmod(0o640)
            if fail:
                raise RuntimeError("synthetic child failure")

    if fail:
        with pytest.raises(RuntimeError, match="synthetic child failure"):
            run()
    else:
        run()
    assert path.read_bytes() == OLD and mode(path) == 0o600
    assert set(tmp_path.glob("*.pii-guard-backup-*")) == {existing_backup}


def test_failed_atomic_publish_keeps_original_and_cleans_staging_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(OLD)
    path.chmod(0o600)

    def fail_replace(self: Path, target: Path) -> None:
        assert mode(self) == 0o600
        raise OSError("synthetic publish failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic publish failure"):
        common.write_json(path, NEW)
    assert path.read_bytes() == OLD and mode(path) == 0o600
    assert not list(tmp_path.glob(".*.pii-guard-*"))


def test_restore_replaces_child_symlink_without_touching_target(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(OLD)
    path.chmod(0o600)
    victim = tmp_path / "unrelated.txt"
    victim.write_text("synthetic unrelated content")
    with _restored_files([path]):
        path.unlink()
        path.symlink_to(victim)
    assert not path.is_symlink()
    assert path.read_bytes() == OLD and mode(path) == 0o600
    assert victim.read_text() == "synthetic unrelated content"


def test_run_removes_new_config_and_backup_after_error(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    with pytest.raises(RuntimeError, match="synthetic child failure"), _restored_files([path]):
        common.write_json(path, NEW)
        common.write_json(path, "{}\n")
        assert mode(path) == 0o600
        raise RuntimeError("synthetic child failure")
    assert not path.exists()
    assert not list(tmp_path.glob("*.pii-guard-backup-*"))


def test_group_is_restored_while_staging_is_private_before_enabling_group_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    requested_gid = tmp_path.stat().st_gid + 1
    steps = []
    fchmod = os.fchmod

    def fchown(fd: int, uid: int, gid: int) -> None:
        assert stat.S_IMODE(os.fstat(fd).st_mode) == 0o600
        assert uid == -1 and gid == requested_gid
        steps.append("group")

    def chmod(fd: int, permissions: int) -> None:
        assert steps == ["group"]
        steps.append("permissions")
        fchmod(fd, permissions)

    monkeypatch.setattr(common.os, "fchown", fchown)
    monkeypatch.setattr(common.os, "fchmod", chmod)
    common._atomic_write(path, OLD, mode=0o640, gid=requested_gid)
    assert steps == ["group", "permissions"]
    assert path.read_bytes() == OLD and mode(path) == 0o640


def test_group_restore_failure_keeps_original_private_and_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(OLD)
    path.chmod(0o600)

    def denied(fd: int, uid: int, gid: int) -> None:
        assert stat.S_IMODE(os.fstat(fd).st_mode) == 0o600
        raise PermissionError("synthetic group refusal")

    monkeypatch.setattr(common.os, "fchown", denied)
    with pytest.raises(PermissionError, match="synthetic group refusal"):
        common._atomic_write(path, NEW.encode(), mode=0o640, gid=path.stat().st_gid + 1)
    assert path.read_bytes() == OLD and mode(path) == 0o600
    assert not list(tmp_path.glob(".*.pii-guard-*"))


def test_write_and_run_restore_snapshot_the_original_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pii_guard.integrations import run

    path = tmp_path / "settings.json"
    path.write_bytes(OLD)
    path.chmod(0o640)
    original_gid = path.stat().st_gid
    write = common._atomic_write
    requested = []

    def record(target: Path, data: bytes, *, mode: int = 0o600, gid: int | None = None) -> None:
        requested.append((mode, gid))
        write(target, data, mode=mode, gid=gid)

    monkeypatch.setattr(common, "_atomic_write", record)
    monkeypatch.setattr(run, "_atomic_write", record)
    with _restored_files([path]):
        common.write_json(path, NEW)
        assert path.stat().st_gid == original_gid
    assert requested == [(0o640, original_gid), (0o640, original_gid)]
    assert path.stat().st_gid == original_gid and path.read_bytes() == OLD
