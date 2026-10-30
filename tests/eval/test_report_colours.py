"""Stable report colours (LAB-1198): adding a system never recolours another or rewrites
unrelated generated files."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from pii_guard import cli
from pii_guard.eval.report_cli import build_outputs, current_index
from pii_guard.eval.report_colours import (
    DEFAULT_REGISTRY,
    PALETTE_VISUAL,
    assign,
    dumps_registry,
    load_registry,
)
from pii_guard.eval.report_index import PALETTE_OURS
from pii_guard.eval.report_raster import Raster

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS = Path("eval/results/runs")
INDEX = Path("eval/results/index.json")
# The committed report is rendered on develop after each merge (CONTRIBUTING.md, "Generated
# files"); until then a new system has no committed colour yet (LAB-1269).
committed_report = pytest.mark.skipif(
    os.environ.get("RENDER_DOCS_ON_MERGE") == "true",
    reason="the committed report is rendered after the merge (render-docs workflow)",
)


def _copy_repo(tmp_path: Path) -> Path:
    for rel in (
        "eval/results/runs",
        "eval/results/schema",
        "docs/benchmarks",
        "eval/datasets/results",  # per-dataset CIs (LAB-1226)
    ):
        shutil.copytree(REPO_ROOT / rel, tmp_path / rel)
    # the index is a build output, not committed; README.md carries the results block
    # the README's latency line reads one model-latency measurement (config readme.model_latency)
    for rel in (
        "docs/benchmarks.md",
        "README.md",
        "eval/results/2026-10-30-lab-1625-ner-v42/latency-cpu-local.json",
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


# untraced on the committed-report checks: they rebuild the report from every committed run
# record, about 7x slower under the branch tracer, and the code they run is covered on the
# bounded ``report_repo`` copy (tests/eval/conftest.py) by the tests below (LAB-1447).
@committed_report
@pytest.mark.untraced
def test_committed_registry_covers_every_system_in_the_index() -> None:
    reg = load_registry(REPO_ROOT / DEFAULT_REGISTRY)
    index = current_index(REPO_ROOT)
    for key, style in index["systems"].items():
        assert reg["systems"][key] == {"color": style["color"], "shape": style["shape"]}
    assert set(index["colours"]["visual"]) <= set(reg["visual"])
    assert set(index["colours"]["latency"]) <= set(reg["latency"])


# --- Regeneration ---------------------------------------------------------------------------


@pytest.mark.slow
@committed_report
@pytest.mark.untraced
def test_regenerating_without_changes_is_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_copy_repo(tmp_path))
    first = build_outputs()
    for path, content in first.items():
        if path == INDEX:
            continue  # a local build output, not committed (LAB-1269)
        if isinstance(content, Raster):  # a PNG: compared by its stamp (LAB-1663)
            assert content.is_current(path), path
            continue
        assert path.read_text(encoding="utf-8") == content, path  # committed == generated
    assert build_outputs() == first


@pytest.mark.slow
def test_a_new_text_system_leaves_other_colours_and_unrelated_files_unchanged(
    report_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(report_repo)
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


@pytest.mark.slow
def test_a_new_visual_system_keeps_existing_visual_colours(
    report_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(report_repo)
    before = build_outputs()
    old_visual = json.loads(before[INDEX])["colours"]["visual"]
    _add_system("2026-10-27-visual-fictional-rules-captions", "visual:aaa-new", "pii-guard new")
    after = build_outputs()
    new_visual = json.loads(after[INDEX])["colours"]["visual"]
    assert {k: new_visual[k] for k in old_visual} == old_visual
    assert "visual:aaa-new" in new_visual
    for path in before:
        if path.suffix == ".svg" and path.name not in (
            "visual-recall.svg",
            "visual-recall-dark.svg",
        ):
            assert after[path] == before[path], path
