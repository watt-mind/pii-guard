"""The commit and dirty flag a run is recorded with (LAB-1496)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pii_guard.eval.record import build_records, load_schema, validate
from pii_guard.eval.report import CODE_PATHS, build_scorecard, git_commit, git_dirty_paths

SCHEMA = Path(__file__).resolve().parents[2] / "eval" / "results" / "schema" / "run.schema.json"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)  # noqa: S603, S607


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    for rel in ("src/pkg/mod.py", "eval/fixtures/en-x.jsonl", "docs/benchmarks.md", "README.md"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("v1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_clean_tree_is_not_dirty(repo: Path) -> None:
    head, dirty = git_commit(repo)
    assert len(head) == 40
    assert dirty is False
    assert git_dirty_paths(repo) == []


def test_docs_and_results_churn_does_not_dirty_the_run(repo: Path) -> None:
    (repo / "docs/benchmarks.md").write_text("regenerated\n")
    (repo / "README.md").write_text("regenerated\n")
    (repo / "models").mkdir()
    (repo / "models/weights.bin").write_text("untracked\n")
    assert git_commit(repo)[1] is False
    assert git_dirty_paths(repo) == []


@pytest.mark.parametrize("rel", ["src/pkg/mod.py", "eval/fixtures/en-x.jsonl"])
def test_code_and_fixture_changes_dirty_the_run(repo: Path, rel: str) -> None:
    (repo / rel).write_text("changed\n")
    assert git_commit(repo)[1] is True
    assert git_dirty_paths(repo) == [rel]


def test_new_staged_code_file_counts(repo: Path) -> None:
    (repo / "src/pkg/new.py").write_text("x = 1\n")
    _git(repo, "add", "src/pkg/new.py")
    assert git_dirty_paths(repo) == ["src/pkg/new.py"]


def test_outside_a_repository(tmp_path: Path) -> None:
    assert git_commit(tmp_path) == ("unknown", False)
    assert git_dirty_paths(tmp_path) == []


def test_code_paths_cover_detection_inputs() -> None:
    assert {"src", "eval/fixtures"} <= set(CODE_PATHS)
    assert "docs" not in CODE_PATHS


def test_dirty_paths_reach_the_run_record() -> None:
    card = build_scorecard([], detectors=["rules"], commit=("a" * 40, True))
    card["meta"]["dirty_paths"] = ["src/pii_guard/detect/rules.py"]
    (rec,) = build_records(card, slug="dirty-paths", day="2026-10-30")
    assert rec["code"]["dirty"] is True
    assert rec["code"]["dirty_paths"] == ["src/pii_guard/detect/rules.py"]
    assert validate(rec, load_schema(SCHEMA)) == []


def test_clean_record_has_no_dirty_paths() -> None:
    card = build_scorecard([], detectors=["rules"], commit=("a" * 40, False))
    (rec,) = build_records(card, slug="clean", day="2026-10-30")
    assert rec["code"]["dirty_paths"] == []
    assert validate(rec, load_schema(SCHEMA)) == []
