"""Journey milestones as files, folded into docs/journey.md with render-time numbers (LAB-1269)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pii_guard import cli
from pii_guard.eval.report_journey import (
    BEGIN,
    END,
    JourneyError,
    load_entries,
    numbers_of,
    render,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

DOC = f"""# Journey

### 1. First (2026-10-26)

Text.

### 2. Second (2026-10-27)

See [the runs](../eval/results/runs/).

{BEGIN}
{END}

Newer milestones are in [journey/](journey/).

## What's next

- More.
"""


def _entry(root: Path, name: str, text: str) -> None:
    path = root / "docs" / "journey" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "journey.md").write_text(DOC, encoding="utf-8")
    return tmp_path


def _render() -> str:
    return render(Path("docs/journey.md").read_text(encoding="utf-8"), load_entries())


# --- Numbering ------------------------------------------------------------------------------


def test_new_entries_take_the_next_numbers_in_file_name_order(repo: Path) -> None:
    _entry(repo, "2026-10-28-lab-2-b.md", "# Bee (2026-10-28)\n\nB.\n")
    _entry(repo, "2026-10-28-lab-1-a.md", "# Ay (2026-10-28)\n\nA.\n")
    out = _render()
    assert numbers_of(out) == {
        "docs/journey/2026-10-28-lab-1-a.md": 3,
        "docs/journey/2026-10-28-lab-2-b.md": 4,
    }
    assert out.index("### 3. Ay (2026-10-28)") < out.index("### 4. Bee (2026-10-28)")
    # Everything outside the block is byte for byte what was there.
    head, tail = DOC.split(BEGIN)[0], DOC.split(END)[1]
    assert out.startswith(head) and out.endswith(tail)


def test_numbers_never_move_once_given(repo: Path) -> None:
    """Merge order, not file-name order: an older-dated entry merged later goes last."""
    _entry(repo, "2026-10-28-lab-5-later.md", "# Later\n\nL.\n")
    Path("docs/journey.md").write_text(_render())
    _entry(repo, "2026-10-20-lab-4-older.md", "# Older\n\nO.\n")
    out = _render()
    assert numbers_of(out) == {
        "docs/journey/2026-10-28-lab-5-later.md": 3,
        "docs/journey/2026-10-20-lab-4-older.md": 4,
    }
    assert render(out, load_entries()) == out  # idempotent
    # An edit to a rendered entry keeps its number.
    _entry(repo, "2026-10-28-lab-5-later.md", "# Later, edited\n\nL2.\n")
    Path("docs/journey.md").write_text(out)
    assert "### 3. Later, edited" in _render()


def test_numbers_continue_after_hand_written_milestones(repo: Path) -> None:
    Path("docs/journey.md").write_text(
        DOC.replace(BEGIN, "### 7. Hand-numbered, before the block\n\nH.\n\n" + BEGIN)
    )
    _entry(repo, "2026-10-28-lab-1-a.md", "# A\n")
    assert numbers_of(_render()) == {"docs/journey/2026-10-28-lab-1-a.md": 8}


def test_a_hand_written_number_the_block_already_uses_is_an_error(repo: Path) -> None:
    _entry(repo, "2026-10-28-lab-1-a.md", "# A\n")
    rendered = _render()
    clash = rendered.replace(BEGIN, "### 3. Hand-numbered later\n\nH.\n\n" + BEGIN)
    with pytest.raises(JourneyError, match="milestone 3 is both"):
        render(clash, load_entries())
    twice = DOC.replace(BEGIN, "### 2. Again\n\n" + BEGIN)
    with pytest.raises(JourneyError, match="numbered twice"):
        render(twice, load_entries())


def test_hand_written_text_inside_the_block_is_an_error(repo: Path) -> None:
    doc = DOC.replace(END, "### 9. Typed into the block\n\nX.\n" + END)
    with pytest.raises(JourneyError, match="no entry file produced it"):
        render(doc, [])


def test_a_deleted_entry_leaves_its_number_unused(repo: Path) -> None:
    _entry(repo, "2026-10-28-lab-1-a.md", "# A\n")
    _entry(repo, "2026-10-28-lab-2-b.md", "# B\n")
    Path("docs/journey.md").write_text(_render())
    (repo / "docs" / "journey" / "2026-10-28-lab-1-a.md").unlink()
    _entry(repo, "2026-10-29-lab-3-c.md", "# C\n")
    assert numbers_of(_render()) == {
        "docs/journey/2026-10-28-lab-2-b.md": 4,
        "docs/journey/2026-10-29-lab-3-c.md": 5,
    }


# --- Content --------------------------------------------------------------------------------


def test_links_are_rewritten_and_sub_headings_moved_down(repo: Path) -> None:
    _entry(
        repo,
        "2026-10-28-lab-1-a.md",
        "# Links (2026-10-28)\n\n"
        "[runs](../../eval/results/runs/) [page](../benchmarks.md#run-log) "
        "[ms 2](../journey.md#2-second-2026-10-27) [readme](README.md) "
        '[web](https://example.org/x) [here](#details) <img src="../benchmarks/progress.svg">\n\n'
        "## Details\n\n[ref]: ../../eval/x.json\n\n"
        "```\n## not a heading\n[x](../../not/rewritten)\n```\n",
    )
    out = _render()
    assert "[runs](../eval/results/runs/)" in out
    assert "[page](benchmarks.md#run-log)" in out
    assert "[ms 2](#2-second-2026-10-27)" in out
    assert "[readme](journey/README.md)" in out
    assert "[web](https://example.org/x)" in out
    assert "[here](#details)" in out
    assert '<img src="benchmarks/progress.svg">' in out
    assert "\n#### Details\n" in out
    assert "[ref]: ../eval/x.json" in out
    assert "\n## not a heading\n[x](../../not/rewritten)\n" in out


@pytest.mark.parametrize(
    ("name", "text", "match"),
    [
        ("lab-1-no-date.md", "# A\n", "name it"),
        ("2026-10-28-Lab-1-Upper.md", "# A\n", "name it"),
        ("2026-10-28-lab-1-a.md", "No title line\n", "first line must be the title"),
        ("2026-10-28-lab-1-a.md", "### 40. Numbered by hand\n", "first line must be the title"),
    ],
)
def test_bad_entries_are_rejected(repo: Path, name: str, text: str, match: str) -> None:
    _entry(repo, name, text)
    with pytest.raises(JourneyError, match=match):
        load_entries()


def test_readme_is_not_an_entry(repo: Path) -> None:
    _entry(repo, "README.md", "# How to add a milestone\n")
    assert load_entries() == []
    assert _render() == DOC


# --- The committed journey and the CLI --------------------------------------------------------


def test_committed_journey_renders_and_keeps_every_hand_written_milestone() -> None:
    doc = (REPO_ROOT / "docs" / "journey.md").read_text(encoding="utf-8")
    entries = load_entries(REPO_ROOT / "docs" / "journey")
    out = render(doc, entries, journey_path=REPO_ROOT / "docs" / "journey.md")
    head = doc.split(BEGIN)[0]
    assert out.startswith(head)  # milestones 1-39 are never rewritten or renumbered
    assert "### 1. " in head and "### 39. " in head


def test_cli_validates_journey_entries_in_every_mode_and_writes_only_with_journey(
    report_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (report_repo / "docs" / "journey.md").write_text(DOC, encoding="utf-8")
    monkeypatch.chdir(report_repo)
    assert cli.main(["eval", "report"]) == 0  # this checkout's report, whatever its state
    _entry(report_repo, "2026-10-28-lab-1-a.md", "# A\n\nBody.\n")
    # Without --journey an entry never touches docs/journey.md, and the report is current.
    assert cli.main(["eval", "report", "--check"]) == 0
    assert cli.main(["eval", "report"]) == 0
    assert Path("docs/journey.md").read_text() == DOC
    # With it, --check sees the block is stale, and a write folds the entry in.
    assert cli.main(["eval", "report", "--check", "--journey"]) == 1
    assert cli.main(["eval", "report", "--journey"]) == 0
    assert "### 3. A" in Path("docs/journey.md").read_text()
    assert cli.main(["eval", "report", "--check", "--journey"]) == 0
    # A broken entry fails every mode, --validate included.
    _entry(report_repo, "2026-10-29-lab-2-b.md", "no title\n")
    capsys.readouterr()
    for mode in ([], ["--check"], ["--validate"]):
        assert cli.main(["eval", "report", *mode]) == 2
    assert "first line must be the title" in capsys.readouterr().err


# --- The acceptance test: two pull requests from the same base ------------------------------


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed git arguments from this test
        ["git", *args],  # noqa: S607 - git from PATH is intended
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.org",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.org",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        },
    ).stdout


@pytest.mark.slow
def test_two_prs_adding_a_run_and_a_milestone_merge_without_conflict(
    report_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance (LAB-1269): two branches from the same base each add a run record and a
    journey entry; they merge one after the other with no conflict and nothing regenerated
    by hand. Pull requests run --validate; the render after the merge numbers the entries."""
    repo = report_repo
    (repo / "docs" / "journey.md").write_text(DOC, encoding="utf-8")
    shutil.copy(REPO_ROOT / ".gitignore", repo / ".gitignore")
    monkeypatch.chdir(repo)
    assert cli.main(["eval", "report", "--journey"]) == 0
    _git(repo, "init", "-q", "-b", "develop")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")

    src = (repo / "eval/results/runs/2026-10-26-comparison-smoke.json").read_text()
    for branch, run_id, entry in (
        ("pr-a", "2026-10-26-a-smoke", "2026-10-28-lab-1-a.md"),
        ("pr-b", "2026-10-26-b-smoke", "2026-10-28-lab-2-b.md"),
    ):
        _git(repo, "checkout", "-q", "-b", branch, "develop")
        rec = src.replace('"2026-10-26-comparison-smoke"', f'"{run_id}"')
        assert rec != src
        (repo / f"eval/results/runs/{run_id}.json").write_text(rec)
        _entry(repo, entry, f"# {branch} (2026-10-28)\n\nWhat {branch} did.\n")
        assert cli.main(["eval", "report", "--validate"]) == 0  # the pull request's CI
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", branch)

    _git(repo, "checkout", "-q", "develop")
    for branch in ("pr-a", "pr-b"):
        # What GitHub does for a mergeability check: a three-way merge, no drivers, no hooks.
        _git(repo, "merge-tree", "--write-tree", "develop", branch)  # exit 1 on a conflict
        _git(repo, "merge", "-q", "--squash", branch)
        _git(repo, "commit", "-qm", f"squash {branch}")
        # The render-docs workflow, after each merge.
        assert cli.main(["eval", "report", "--journey"]) == 0
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", f"render after {branch}", "--allow-empty")

    assert numbers_of(Path("docs/journey.md").read_text()) == {
        "docs/journey/2026-10-28-lab-1-a.md": 3,
        "docs/journey/2026-10-28-lab-2-b.md": 4,
    }
    assert cli.main(["eval", "report", "--check", "--journey"]) == 0
    page = Path("docs/benchmarks.md").read_text()
    assert "2026-10-26-a-smoke" in page and "2026-10-26-b-smoke" in page
