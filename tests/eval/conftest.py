"""Bounded report inputs for behavior tests; committed-data checks use the full repository."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pii_guard.eval.report_cli import CHARTS, DEFAULT_INDEX, build_outputs

ROOT = Path(__file__).resolve().parents[2]
# Fixed records from fictional fixtures exercise text, image and latency output without
# making every CLI behavior test reprocess the project's growing benchmark history.
REPORT_RUNS = (
    "2026-10-26-rules-en-smoke",
    "2026-10-26-comparison-smoke",
    "2026-10-27-visual-fictional-rules-captions",
    "2026-10-27-segment-local-fictional",
    "2026-10-27-gateway-latency-rules-fast",
)


@pytest.fixture
def report_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A current, isolated report with every chart family and no prebuilt local index."""
    repo = tmp_path / "report"
    runs = repo / "eval/results/runs"
    runs.mkdir(parents=True)
    for run_id in REPORT_RUNS:
        shutil.copy(ROOT / "eval/results/runs" / f"{run_id}.json", runs)
    shutil.copytree(ROOT / "eval/results/schema", repo / "eval/results/schema")
    charts = repo / "docs/benchmarks"
    charts.mkdir(parents=True)
    (charts / "config.json").write_text(
        json.dumps({"headline_set": "smoke", "featured": ["rules"]}), encoding="utf-8"
    )
    with monkeypatch.context() as context:
        context.chdir(repo)
        outputs = build_outputs()
        # Keep colour-stability assertions meaningful: all chart families must be present.
        assert {Path("docs/benchmarks") / name for name, _, _ in CHARTS} <= outputs.keys()
        for path, content in outputs.items():
            if path != DEFAULT_INDEX:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
    return repo
