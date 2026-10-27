"""Latency run records in the benchmark report: index section, chart and page table."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pii_guard.bench.latency import CellResult, build_records
from pii_guard.eval import report_charts as charts
from pii_guard.eval.record import load_records
from pii_guard.eval.report_cli import render_page
from pii_guard.eval.report_index import build_index
from pii_guard.observability.timing import STAGES

REPO = Path(__file__).resolve().parents[2]


def _event(overhead: float, *, stream: bool) -> dict[str, Any]:
    stages = dict.fromkeys(STAGES, 0.0)
    stages.update(parse=0.1, detect=overhead * 0.2, mask=0.1, forward=overhead * 0.6, upstream=50)
    return {
        "detectors": ["rules"],
        "timing": {
            "total_ms": 50 + overhead,
            "upstream_ms": 50.0,
            "overhead_ms": overhead,
            "stages_ms": stages,
            "detectors_ms": {"rules": overhead * 0.1},
            "ttft_ms": 3.0 if stream else None,
            "upstream_ttft_ms": 1.0 if stream else None,
            "added_ttft_ms": 2.0 if stream else None,
        },
    }


def latency_record(mode: str = "fast") -> dict[str, Any]:
    cells = []
    for c in (1, 8):
        for stream in (False, True):
            cell = CellResult(mode, c, stream, 3, 0, 0.5, ["rules"])
            cell.events = [_event(v * c, stream=stream) for v in (4.0, 5.0, 9.0)]
            cell.client_ms = [55.0, 56.0, 60.0]
            cell.client_ttft_ms = [5.0, 6.0, 7.0] if stream else []
            cells.append(cell)
    (record,) = build_records(
        cells, slug="latency", delay_ms=50.0, day="2026-10-27", commit=("abc1234", False)
    )
    return record


def test_index_lists_latency_runs_apart_from_detection_systems() -> None:
    records = [*load_records(REPO / "eval/results/runs"), latency_record()]
    index = build_index(records)
    (run,) = [r for r in index["latency"] if r["run_id"] == "2026-10-27-latency-fast"]
    assert run["system"] == "gateway-latency:fast:rules" and len(run["cells"]) == 4
    assert run["system"] not in index["systems"]
    assert "latency-corpus" not in index["fixture_sets"]
    assert any(r["kind"] == "latency" for r in index["runs"])


def test_chart_and_page() -> None:
    records = [*load_records(REPO / "eval/results/runs"), latency_record()]
    index = build_index(records)
    svg = charts.latency(index)
    assert svg.startswith("<svg") and "Gateway overhead" in svg
    assert "fast: rules, c=8, stream" in svg and "forward" in svg
    assert charts.latency(build_index(records)) == svg  # byte-stable
    headline = next(n for n, v in index["fixture_sets"].items() if v["kind"] == "text")
    page = render_page(index, headline_set=headline, featured=index["featured"])
    assert "![Gateway overhead](benchmarks/latency.svg)" in page
    assert "## Gateway latency" in page and "`2026-10-27-latency-fast`" in page
    assert "pii-guard gateway, fast mode (rules)" in page  # run log label


def test_stage_shares_fill_the_overhead() -> None:
    record = latency_record()
    cell = record["metrics"]["cells"][0]
    shares = dict(charts.stage_shares(cell))
    assert sum(shares.values()) >= cell["overhead_ms"]["p50"] - 1e-6
    assert shares["other"] >= 0
