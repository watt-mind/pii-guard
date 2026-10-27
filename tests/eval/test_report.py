"""``pii-guard eval report``: index, charts, benchmarks.md and the ``--check`` CI gate."""

from __future__ import annotations

import copy
import json
import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from pii_guard import cli
from pii_guard.eval import report_charts as charts
from pii_guard.eval.record import load_records
from pii_guard.eval.report_cli import CHARTS, build_outputs, render_page
from pii_guard.eval.report_index import build_index, compact, pool

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS = REPO_ROOT / "eval" / "results" / "runs"
CONFIG = json.loads((REPO_ROOT / "docs" / "benchmarks" / "config.json").read_text())
SVG = "{http://www.w3.org/2000/svg}"
# The committed report is rendered on develop after each merge (CONTRIBUTING.md, "Generated
# files"), so a pull request or a merge commit may carry it stale on purpose (LAB-1269).
RENDERED_ON_MERGE = os.environ.get("RENDER_DOCS_ON_MERGE") == "true"


@pytest.fixture(scope="module")
def records() -> list[dict[str, Any]]:
    return load_records(RUNS)


@pytest.fixture(scope="module")
def index(records: list[dict[str, Any]]) -> dict[str, Any]:
    return build_index(records, featured=CONFIG["featured"])


def _copy_repo(tmp_path: Path) -> Path:
    for rel in ("eval/results/runs", "eval/results/schema", "docs/benchmarks"):
        shutil.copytree(REPO_ROOT / rel, tmp_path / rel)
    for rel in ("docs/benchmarks.md",):  # the index is a build output, not committed
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, tmp_path / rel)
    return tmp_path


# --- The committed report ------------------------------------------------------------------


def test_committed_report_is_up_to_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)
    assert cli.main(["eval", "report", "--validate" if RENDERED_ON_MERGE else "--check"]) == 0


@pytest.mark.slow
def test_check_flags_stale_and_missing_outputs_and_a_rebuild_fixes_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(_copy_repo(tmp_path))
    Path("docs/benchmarks/progress.svg").write_text("<svg/>")
    assert cli.main(["eval", "report", "--check"]) == 1
    err = capsys.readouterr().err
    assert "progress.svg" in err
    assert "index.json" not in err  # a local build output: never compared (LAB-1269)
    assert cli.main(["eval", "report"]) == 0
    assert cli.main(["eval", "report", "--check"]) == 0
    # A new run record makes the committed outputs stale.
    src = Path("eval/results/runs/2026-10-26-comparison-smoke.json")
    rec = json.loads(src.read_text())
    rec["run_id"] = "2026-10-28-comparison-smoke"
    rec["date"] = "2026-10-28"
    Path(f"eval/results/runs/{rec['run_id']}.json").write_text(json.dumps(rec))
    assert cli.main(["eval", "report", "--check"]) == 1


def test_bad_input_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(_copy_repo(tmp_path))
    config = json.loads(Path("docs/benchmarks/config.json").read_text())
    config["headline_set"] = "no-such-set"
    Path("docs/benchmarks/config.json").write_text(json.dumps(config))
    assert cli.main(["eval", "report", "--check"]) == 2
    Path("eval/results/runs/broken.json").write_text('{"run_id": "broken"}')
    assert cli.main(["eval", "report"]) == 2


# --- Index ---------------------------------------------------------------------------------


def test_index_has_every_run_and_derived_vocabularies(
    index: dict[str, Any], records: list[dict[str, Any]]
) -> None:
    assert {r["run_id"] for r in index["runs"]} == {r["run_id"] for r in records}
    assert {"en", "hu"} <= set(index["languages"])  # the committed runs add more over time
    assert index["languages"] == sorted(index["languages"])
    assert {"smoke", "synth-sample", "synth-dev", "specimens"} <= set(index["fixture_sets"])
    assert index["fixture_sets"]["smoke"]["origin"] == "hand-written"
    assert index["fixture_sets"]["synth-sample"]["origin"] == "generated"
    assert index["featured"] == [k for k in CONFIG["featured"] if k in index["systems"]]
    assert sum(1 for s in index["systems"].values() if s["default"]) == 1
    assert len(index["visual"]) == sum(1 for r in records if r["kind"] == "visual")
    assert {v["fixture_set"] for v in index["visual"]} == {"specimens", "fictional-specimens"}
    assert index["fixture_sets"]["fictional-specimens"]["origin"] == "generated"
    dates = [r["date"] for r in index["runs"]]
    assert dates == sorted(dates)


def test_index_is_a_pure_function_of_the_records(records: list[dict[str, Any]]) -> None:
    a = build_index(records, featured=CONFIG["featured"])
    b = build_index(list(reversed(records)), featured=CONFIG["featured"])
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_pooling_languages_is_exact(records: list[dict[str, Any]]) -> None:
    """Pooling per-language blocks reproduces the run's own overall numbers."""
    checked = 0
    for rec in records:
        if rec["kind"] != "text" or len(rec["metrics"]["languages"]) < 2:
            continue
        pooled = compact(pool(list(rec["metrics"]["languages"].values())))
        overall = compact(rec["metrics"]["overall"])
        for key in ("documents", "gold", "pred", "precision", "recall", "f1", "leak"):
            assert pooled[key] == pytest.approx(overall[key], abs=1e-4), (rec["run_id"], key)
        for name, t in overall["per_type"].items():
            assert pooled["per_type"][name]["recall"] == pytest.approx(t["recall"], abs=1e-4)
        checked += 1
    assert checked >= 4


def test_history_merges_one_run_per_language(index: dict[str, Any]) -> None:
    ner = [
        h
        for h in index["history"]
        if h["system"] == "rules+ner:xlmr-base-ft-s7" and h["fixture_set"] == "smoke"
    ]
    assert len(ner) == 1
    assert set(ner[0]["languages"]) == {"en", "hu"}
    assert len(ner[0]["run_ids"]) == 2
    assert ner[0]["all"]["documents"] == 38


def test_a_new_language_needs_no_code_change(records: list[dict[str, Any]]) -> None:
    rec = copy.deepcopy(next(r for r in records if r["run_id"] == "2026-10-26-rules-en-smoke"))
    rec["run_id"] = "2026-10-26-rules-de-smoke"
    rec["languages"] = ["de"]
    rec["metrics"]["languages"] = {"de": rec["metrics"]["languages"].pop("en")}
    for f in rec["fixtures"]:
        f["language"] = "de"
    idx = build_index([*records, rec], featured=CONFIG["featured"])
    assert "de" in idx["languages"]
    svg = charts.by_language(idx, fixture_set="smoke", systems=idx["featured"])
    assert "de (" in svg
    assert "de F1" in render_page(idx, headline_set="smoke", featured=idx["featured"])


# --- Charts and page -----------------------------------------------------------------------


def test_charts_are_well_formed_captioned_and_in_bounds(index: dict[str, Any]) -> None:
    for name, title, render in CHARTS:
        svg = render(index, CONFIG["headline_set"], index["featured"])
        assert svg == render(index, CONFIG["headline_set"], index["featured"]), name
        root = ET.fromstring(svg)  # noqa: S314 - our own output
        assert root.get("viewBox") == "0 0 1600 900"
        assert root.find(f"{SVG}title").text == title, name
        texts = root.findall(f".//{SVG}text")
        caption = " ".join("".join(t.itertext()) for t in texts[-4:])
        assert "Fixture set" in caption, name
        assert "commits" in caption, name
        for t in texts:
            if t.get("transform"):
                continue
            x = float(t.get("x"))
            assert 0 <= x <= 1600, (name, "".join(t.itertext()))
            assert 0 <= float(t.get("y")) <= 900, (name, "".join(t.itertext()))
            assert float(t.get("font-size") or 20) >= 18, name  # readable at slide size


def test_page_has_method_notes_tables_and_every_run(index: dict[str, Any]) -> None:
    page = render_page(index, headline_set=CONFIG["headline_set"], featured=index["featured"])
    assert page.startswith("<!-- Generated by `pii-guard eval report`")
    assert "Generated sets flatter Muse-based detectors" in page
    assert "**Leak rate**" in page
    for name, _, _ in CHARTS:
        assert f"(benchmarks/{name})" in page
    for run in index["runs"]:
        assert run["run_id"] in page


@pytest.mark.slow
def test_print_index_is_the_compact_index_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(_copy_repo(tmp_path))
    before = {p: p.read_bytes() for p in Path(".").rglob("*") if p.is_file()}
    assert cli.main(["eval", "report", "--print-index"]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert json.loads(out) == json.loads(build_outputs()[Path("eval/results/index.json")])
    assert {p: p.read_bytes() for p in Path(".").rglob("*") if p.is_file()} == before


@pytest.mark.slow
def test_validate_compares_nothing_but_rejects_bad_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(_copy_repo(tmp_path))
    src = Path("eval/results/runs/2026-10-26-comparison-smoke.json")
    rec = json.loads(src.read_text())
    rec["run_id"] = "2026-10-28-comparison-smoke"
    rec["date"] = "2026-10-28"
    Path(f"eval/results/runs/{rec['run_id']}.json").write_text(json.dumps(rec))
    # A new run record without the regenerated report: stale for --check, fine for --validate.
    assert cli.main(["eval", "report", "--check"]) == 1
    assert cli.main(["eval", "report", "--validate"]) == 0
    assert "inputs valid" in capsys.readouterr().out
    assert not Path("eval/results/index.json").exists()
    Path("eval/results/runs/broken.json").write_text('{"run_id": "broken"}')
    assert cli.main(["eval", "report", "--validate"]) == 2
