"""Stable report colours (LAB-1198): adding a system never recolours another or rewrites
unrelated generated files."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from pii_guard import cli
from pii_guard.eval.report_cli import build_outputs
from pii_guard.eval.report_colours import (
    DEFAULT_REGISTRY,
    PALETTE_VISUAL,
    assign,
    dumps_registry,
    load_registry,
)
from pii_guard.eval.report_index import PALETTE_OURS

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS = Path("eval/results/runs")
INDEX = Path("eval/results/index.json")


def _copy_repo(tmp_path: Path) -> Path:
    for rel in ("eval/results/runs", "eval/results/schema", "docs/benchmarks"):
        shutil.copytree(REPO_ROOT / rel, tmp_path / rel)
    for rel in (
        "eval/results/index.json",
        "docs/benchmarks.md",
        "ui/src/api/benchmarks.index.json",
    ):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, tmp_path / rel)
    return tmp_path


def _add_system(source_run: str, key: str, label: str) -> None:
    """A copy of ``source_run`` under a new system key, sorted ahead of every existing key."""
    rec: dict[str, Any] = json.loads((RUNS / f"{source_run}.json").read_text(encoding="utf-8"))
    rec["run_id"] = f"{source_run}-{key.replace(':', '-')}"
    rec["system"]["key"] = key
    rec["system"]["label"] = label
    (RUNS / f"{rec['run_id']}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")


# --- The registry ---------------------------------------------------------------------------


def test_assign_keeps_existing_entries_and_takes_the_least_used_colour() -> None:
    section = {"b": PALETTE_OURS[0], "c": PALETTE_OURS[1]}
    assign(section, ["a", "b", "c", "d"], PALETTE_OURS)
    assert section["b"] == PALETTE_OURS[0] and section["c"] == PALETTE_OURS[1]
    assert section["a"] == PALETTE_OURS[2]  # first unused, in palette order
    assert section["d"] == PALETTE_OURS[3]
    # A full palette wraps to the least-used entry instead of colliding with a recent one.
    many = {f"s{i}": c for i, c in enumerate(PALETTE_VISUAL)}
    many["s0-dup"] = PALETTE_VISUAL[0]
    assign(many, ["new"], PALETTE_VISUAL)
    assert many["new"] == PALETTE_VISUAL[1]


def test_assign_reassigns_an_entry_outside_the_palette() -> None:
    section = {"moved": "#595959"}
    assign(section, ["moved"], PALETTE_OURS)
    assert section["moved"] == PALETTE_OURS[0]


def test_registry_round_trips_with_sorted_keys(tmp_path: Path) -> None:
    path = tmp_path / "colours.json"
    assert load_registry(path) == {"systems": {}, "visual": {}, "latency": {}}
    reg = {"systems": {"z": {"color": "#0072B2"}, "a": {"color": "#009E73"}}, "visual": {}}
    path.write_text(dumps_registry(reg), encoding="utf-8")
    loaded = load_registry(path)
    assert list(json.loads(path.read_text())["systems"]) == ["a", "z"]
    assert dumps_registry(loaded) == path.read_text(encoding="utf-8")


def test_committed_registry_covers_every_system_in_the_index() -> None:
    reg = load_registry(REPO_ROOT / DEFAULT_REGISTRY)
    index = json.loads((REPO_ROOT / INDEX).read_text(encoding="utf-8"))
    for key, style in index["systems"].items():
        assert reg["systems"][key] == {"color": style["color"], "shape": style["shape"]}
    assert set(index["colours"]["visual"]) <= set(reg["visual"])
    assert set(index["colours"]["latency"]) <= set(reg["latency"])


# --- Regeneration ---------------------------------------------------------------------------


def test_regenerating_without_changes_is_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_copy_repo(tmp_path))
    first = build_outputs()
    for path, content in first.items():
        assert path.read_text(encoding="utf-8") == content, path  # committed == generated
    assert build_outputs() == first


def test_a_new_text_system_leaves_other_colours_and_unrelated_files_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_copy_repo(tmp_path))
    before = build_outputs()
    old = json.loads(before[INDEX])["systems"]
    _add_system("2026-10-26-rules-en-smoke", "aaa-new-system", "pii-guard aaa new system")
    assert cli.main(["eval", "report"]) == 0

    after = build_outputs()
    new = json.loads(after[INDEX])["systems"]
    assert {k: (v["color"], v["shape"]) for k, v in new.items() if k in old} == {
        k: (v["color"], v["shape"]) for k, v in old.items()
    }
    used = [v["color"] for v in old.values() if v["family"] == "pii-guard"]
    assert new["aaa-new-system"]["color"] == min(
        PALETTE_OURS, key=lambda c: (used.count(c), PALETTE_OURS.index(c))
    )
    # Charts of featured systems, the visual and latency charts: not one byte changes.
    for path in before:
        if path.suffix == ".svg":
            assert after[path] == before[path], path
    # The registry gains exactly one line-sized entry; nothing else in it moves.
    reg_before = json.loads(before[DEFAULT_REGISTRY])
    reg_after = json.loads(after[DEFAULT_REGISTRY])
    assert set(reg_after["systems"]) - set(reg_before["systems"]) == {"aaa-new-system"}
    for section in ("systems", "visual", "latency"):
        for key, value in reg_before[section].items():
            assert reg_after[section][key] == value
    assert cli.main(["eval", "report", "--check"]) == 0


def test_a_new_visual_system_keeps_existing_visual_colours(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_copy_repo(tmp_path))
    before = build_outputs()
    old_visual = json.loads(before[INDEX])["colours"]["visual"]
    _add_system("2026-10-27-visual-fictional-rules-captions", "visual:aaa-new", "pii-guard new")
    after = build_outputs()
    new_visual = json.loads(after[INDEX])["colours"]["visual"]
    assert {k: new_visual[k] for k in old_visual} == old_visual
    assert "visual:aaa-new" in new_visual
    for path in before:
        if path.suffix == ".svg" and path.name != "visual-recall.svg":
            assert after[path] == before[path], path
