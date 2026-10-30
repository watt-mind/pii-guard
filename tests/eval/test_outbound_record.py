"""The outbound re-check in run records, the latency bench and the report (LAB-1505).

``pii-guard eval --outbound-check`` replays the documents through the gateway and adds an
``outbound_check`` block (requests, re-checked, blocked, false-block rate, re-check ms) to every
text block; ``pii-guard bench latency`` adds ``outbound_check_ms`` to every cell. Both are
optional in the run schema, so older records still validate. All values are fictional.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pii_guard.bench.latency import CellResult, build_records
from pii_guard.eval import cli as eval_cli
from pii_guard.eval.fixtures import Document
from pii_guard.eval.outbound import Outcome, outbound_blocks, summarize_outcomes
from pii_guard.eval.record import load_schema, rate_errors, text_metrics, validate
from pii_guard.eval.report_cli import _false_blocks, _latency_table
from pii_guard.eval.report_index import compact, pool
from pii_guard.eval.scorer import DetectorAnalyzer
from pii_guard.observability.timing import STAGES

REPO = Path(__file__).resolve().parents[2]
HU = REPO / "eval" / "fixtures" / "hu-smoke.jsonl"
EN = REPO / "eval" / "fixtures" / "en-smoke.jsonl"
SCHEMA = load_schema(REPO / "eval/results/schema/run.schema.json")


def test_summary_counts_blocks_over_rechecked_requests() -> None:
    outcomes = [
        Outcome("en", "passed", 0.2),
        Outcome("en", "passed", 0.4),
        Outcome("en", "blocked"),
        Outcome("en", "refused"),
    ]
    block = summarize_outcomes(outcomes)
    assert block["requests"] == 4 and block["checked"] == 3 and block["blocked"] == 1
    assert block["rate"] == pytest.approx(1 / 3, abs=1e-6)
    assert block["check_ms"]["p50"] == pytest.approx(0.3)
    empty = summarize_outcomes([Outcome("en", "refused")])
    assert empty["rate"] is None and empty["check_ms"] is None


def test_replay_through_the_gateway_passes_fictional_documents() -> None:
    docs = [
        Document("d1", "en", "Please email jane.placeholder@example.net about the invoice.", ()),
        Document("d2", "en", "What is the capital of Hungary?", ()),
        Document(
            "d3",
            "hu",
            '{"messages": [{"role": "user", "content": "Írj Teszt Elek részére, '
            'teszt.elek@example.com."}]}',
            (),
        ),
    ]
    out = outbound_blocks(docs, DetectorAnalyzer(["rules"]).detectors)
    overall = out["overall"]
    assert overall["requests"] == 3 and overall["checked"] == 3 and overall["blocked"] == 0
    assert overall["rate"] == 0.0 and overall["check_ms"]["p95"] >= 0
    assert set(out["languages"]) == {"en", "hu"}
    assert out["languages"]["en"]["requests"] == 2


def _ob(requests: int, checked: int, blocked: int, p50: float) -> dict[str, Any]:
    return {
        "requests": requests,
        "checked": checked,
        "blocked": blocked,
        "rate": blocked / checked if checked else None,
        "check_ms": {"p50": p50, "p95": p50 * 2},
    }


def test_eval_cli_records_the_block_and_the_schema_accepts_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "card.json"
    runs = tmp_path / "runs"
    code = eval_cli.main(
        [
            "--fixtures", str(HU), "--fixtures", str(EN), "--outbound-check",
            "--json", str(out), "--record", "ob", "--runs-dir", str(runs),
        ]
    )  # fmt: skip
    assert code == 0
    assert "## Outbound re-check" in capsys.readouterr().out
    card = json.loads(out.read_text("utf-8"))
    ob = card["overall"]["outbound_check"]
    assert ob["requests"] == card["overall"]["documents"]
    assert (
        sum(b["outbound_check"]["requests"] for b in card["languages"].values()) == ob["requests"]
    )
    (path,) = runs.glob("*-ob.json")
    record = json.loads(path.read_text("utf-8"))
    assert record["metrics"]["overall"]["outbound_check"]["blocked"] == ob["blocked"]
    assert validate(record, SCHEMA) == []
    metrics = record["metrics"]
    pooled = compact(pool(list(metrics["languages"].values())))["outbound_check"]
    assert pooled["requests"] == ob["requests"] and pooled["blocked"] == ob["blocked"]
    assert compact(metrics["overall"])["outbound_check"]["check_p50_ms"] is not None
    # text_metrics keeps a block without the replay as before: no outbound_check key.
    plain = text_metrics({**card["overall"], "outbound_check": None})
    assert "outbound_check" not in plain


def test_both_fields_stay_optional_in_the_schema() -> None:
    record = json.loads(next((REPO / "eval/results/runs").glob("*.json")).read_text("utf-8"))
    assert validate(record, SCHEMA) == []
    assert "outbound_check" not in SCHEMA["$defs"]["text_block"]["required"]
    assert "outbound_check_ms" not in SCHEMA["$defs"]["latency_cell"]["required"]


def test_text_metrics_and_rate_check() -> None:
    from pii_guard.eval.record import outbound_check

    block = outbound_check({**_ob(10, 8, 1, 0.12345), "extra": 1})
    assert block == {
        "requests": 10,
        "checked": 8,
        "blocked": 1,
        "rate": 0.125,
        "check_ms": {"p50": 0.123, "p95": 0.247},
    }
    good = {
        "exact": {"tp_pred": 0, "pred": 0, "tp_gold": 0, "gold": 0, "precision": None},
        "overlap": {"tp_pred": 0, "pred": 0, "tp_gold": 0, "gold": 0, "precision": None},
        "leak": {"leaked": 0, "values": 0, "partial": 0, "rate": None, "partial_rate": None},
        "over_masking": {"over_masked": 0, "masked": 0, "rate": None},
    }
    for mode in ("exact", "overlap"):
        good[mode].update(recall=None, f1=None)
    assert rate_errors({**good, "outbound_check": block}, "$") == []
    bad = {**good, "outbound_check": {**block, "rate": 0.5}}
    assert rate_errors(bad, "$") == [
        "$.outbound_check.rate: 0.5 is not its counts' ratio (0.125000)"
    ]


def test_pool_sums_counts_and_weights_time_by_rechecked_requests() -> None:
    a = {"outbound_check": _ob(10, 10, 0, 1.0)}
    b = {"outbound_check": _ob(30, 30, 3, 3.0)}
    from pii_guard.eval.report_index import pool_outbound

    pooled = pool_outbound([a, b])
    assert pooled is not None
    assert (pooled["requests"], pooled["checked"], pooled["blocked"]) == (40, 40, 3)
    assert pooled["rate"] == pytest.approx(3 / 40)
    assert pooled["check_ms"]["p50"] == pytest.approx(2.5)
    assert pool_outbound([a, {}]) is None
    assert _false_blocks({"outbound_check": {"rate": 0.075, "blocked": 3, "checked": 40}}) == (
        "7.5% (3/40)"
    )
    assert _false_blocks({}) == "—"


def _event(check_ms: float | None) -> dict[str, Any]:
    stages = dict.fromkeys(STAGES, 0.0)
    return {
        "detectors": ["rules"],
        "outbound_check": None if check_ms is None else {"result": "passed", "ms": check_ms},
        "timing": {
            "total_ms": 55.0,
            "upstream_ms": 50.0,
            "overhead_ms": 5.0,
            "stages_ms": stages,
            "detectors_ms": {"rules": 0.5},
            "added_ttft_ms": None,
        },
    }


def test_bench_cell_carries_the_recheck_time_into_a_valid_record() -> None:
    cell = CellResult("fast", 1, False, 3, 0, 0.5, ["rules"])
    cell.events = [_event(0.1), _event(0.2), _event(0.3)]
    cell.client_ms = [55.0, 56.0, 57.0]
    s = cell.summary()
    assert s["outbound_check_ms"]["p50"] == pytest.approx(0.2)
    none = CellResult("fast", 1, False, 1, 0, 0.5, ["rules"])
    none.events = [_event(None)]
    none.client_ms = [55.0]
    assert none.summary()["outbound_check_ms"] is None
    (record,) = build_records(
        [cell, none], slug="ob", delay_ms=50.0, day="2026-10-30", commit=("abc1234", False)
    )
    assert validate(record, SCHEMA) == []
    run = {
        **record,
        "system": record["system"]["key"],
        "detectors": ["rules"],
        "upstream_delay_ms": 50.0,
        "cells": record["metrics"]["cells"],
    }
    index = {"latency": [run]}
    table = _latency_table(index)
    assert "Re-check p50" in table and "0.20 ms" in table
    cells = [{k: v for k, v in c.items() if k != "outbound_check_ms"} for c in run["cells"]]
    old = {"latency": [{**run, "cells": cells}]}
    assert "Re-check p50" not in _latency_table(old)
