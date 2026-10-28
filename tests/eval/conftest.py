"""Bounded report inputs for behavior tests; committed-data checks use the full repository."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from pii_guard.eval.record import load_records
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


@pytest.fixture(scope="session")
def committed_record_texts() -> tuple[str, ...]:
    """The committed run records, loaded and validated once per worker, as JSON texts.

    Validating 700+ records takes seconds under the branch tracer; tests that only read them
    share one load (LAB-1447). test_every_committed_record_is_valid still loads them itself.
    """
    return tuple(json.dumps(r) for r in load_records(ROOT / "eval/results/runs"))


@pytest.fixture
def committed_records(committed_record_texts: tuple[str, ...]) -> list[dict[str, Any]]:
    """A fresh copy of the committed run records: a test may change it freely."""
    return [json.loads(text) for text in committed_record_texts]


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
