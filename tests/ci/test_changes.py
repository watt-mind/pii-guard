"""Packaging selection must include removed/moved inputs and fail closed on a broken diff."""

from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "changes.py"
MODULE = runpy.run_path(str(SCRIPT))
classify = MODULE["classify"]
changed_paths = MODULE["changed_paths"]
ALL = {"ui": True, "docker": True, "wheel": True, "hosted": True, "hosted-image": True}
NONE = dict.fromkeys(ALL, False)


@pytest.mark.parametrize(
    ("path", "jobs"),
    [
        ("NOTICE", ALL),
        ("LICENSE", ALL),
        ("src/pii_guard/config.py", ALL),
        ("pyproject.toml", ALL),
        ("uv.lock", ALL),
        ("scripts/ci/changes.py", ALL),
        ("unclassified/build.cfg", ALL),
        ("new-root-config.toml", ALL),
        ("docs/architecture.md", NONE),
        ("tests/vault/test_vault_mask.py", NONE),
        ("Dockerfile", {**NONE, "docker": True}),
        (".dockerignore", {**NONE, "docker": True, "hosted": True, "hosted-image": True}),
        ("Dockerfile.hosted", {**NONE, "hosted": True, "hosted-image": True}),
        ("deploy/azure/entrypoint.py", {**NONE, "hosted": True, "hosted-image": True}),
        ("deploy/azure/venv_layer.py", {**NONE, "hosted": True, "hosted-image": True}),
        ("deploy/azure/ci_hosted_smoke.py", {**NONE, "hosted": True, "hosted-image": True}),
        ("deploy/azure/modules/app.bicep", {**NONE, "hosted": True}),
        ("deploy/azure/dev_router/router.sh", {**NONE, "hosted": True}),
        ("deploy/azure/app_bindings.py", {**NONE, "hosted": True}),
        ("deploy/azure/main.bicep", {**NONE, "hosted": True}),
        ("deploy/azure/deploy.sh", {**NONE, "hosted": True}),
        ("scripts/ci/docker_smoke.sh", {**NONE, "docker": True}),
        ("scripts/ci/wheel_smoke.sh", {**NONE, "wheel": True}),
        (".github/workflows/release.yml", {**NONE, "wheel": True}),
        (
            "ui/src/App.tsx",
            {**NONE, "ui": True, "wheel": True, "hosted": True, "hosted-image": True},
        ),
        (
            "eval/results/runs/run.json",
            {**NONE, "ui": True, "wheel": True, "hosted": True, "hosted-image": True},
        ),
        ("eval/datasets/results/counts.json", {**NONE, "ui": True, "wheel": True, "hosted": True}),
        (
            "docs/benchmarks/config.json",
            {**NONE, "ui": True, "wheel": True, "hosted": True, "hosted-image": True},
        ),
        ("docs/benchmarks/colours.json", {**NONE, "ui": True, "wheel": True, "hosted": True}),
    ],
)
def test_packaging_inputs(path: str, jobs: dict[str, bool]) -> None:
    assert classify([path]) == jobs


def test_multiple_changes_combine_jobs() -> None:
    assert classify(["Dockerfile", "ui/src/App.tsx"]) == ALL
    assert classify([]) == NONE
    assert classify(["deploy/azure/main.bicep"])["hosted-image"] is False
    assert classify(["deploy/azure/main.bicep", "Dockerfile.hosted"])["hosted-image"] is True


def test_hosted_image_always_implies_hosted() -> None:
    for path in (
        "src/pii_guard/config.py",
        "ui/src/App.tsx",
        "eval/results/runs/run.json",
        "docs/benchmarks/config.json",
        "Dockerfile.hosted",
        "deploy/azure/entrypoint.py",
    ):
        selected = classify([path])
        assert not selected["hosted-image"] or selected["hosted"], path


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()  # noqa: S603,S607


def test_git_diff_includes_added_deleted_and_renamed_inputs(tmp_path: Path) -> None:
    _git("init", "-q")
    _git("config", "user.name", "Synthetic CI Test")
    _git("config", "user.email", "ci@example.test")
    (tmp_path / "NOTICE").write_text("fictional licence notice\n")
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui/old.ts").write_text("export const fixture = 1;\n")
    _git("add", ".")
    _git("commit", "-qm", "base")
    base = _git("rev-parse", "HEAD")
    (tmp_path / "NOTICE").unlink()
    (tmp_path / "docs").mkdir()
    (tmp_path / "ui/old.ts").rename(tmp_path / "docs/moved.txt")
    (tmp_path / "docs/added with\nnewline.md").write_text("synthetic\n")
    _git("add", "-A")
    _git("commit", "-qm", "change")
    paths = changed_paths(base)
    assert set(paths) == {"NOTICE", "ui/old.ts", "docs/moved.txt", "docs/added with\nnewline.md"}
    assert classify(paths) == ALL


@pytest.mark.parametrize("base", ["", "nonexistent-revision"])
def test_invalid_diff_fails_without_skip_outputs(
    base: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVENT", "pull_request")
    monkeypatch.setenv("BASE", base)
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)  # noqa: S603
    assert result.returncode != 0
    assert result.stdout == ""
    assert "refusing to skip" in result.stderr


@pytest.mark.parametrize("event", ["push", "merge_group", "schedule", "workflow_dispatch"])
def test_non_pr_events_always_run_every_package(
    event: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVENT", event)
    # Not a git repository: non-PR selection must not need a diff or a base revision.
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)  # noqa: S603
    assert result.returncode == 0
    assert result.stdout == "ui=true\ndocker=true\nwheel=true\nhosted=true\nhosted-image=true\n"
