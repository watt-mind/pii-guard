"""The quality regression gate (``pii-guard eval gate``, ``python -m pii_guard.eval.gate``)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pii_guard.eval import gate

REPO_ROOT = Path(__file__).resolve().parents[2]

SUITE = {
    "name": "s",
    "fixtures": [],
    "detectors": ["rules"],
    "tolerance": {"leak_rate": 0.01},
    "limits": {"leak_rate_max": 0.5, "roundtrip_rate_min": 1.0, "over_masking_rate_max": 0.0},
}
BASE = {"leak_rate": 0.40, "roundtrip_rate": 1.0, "over_masking_rate": 0.0}


@pytest.fixture
def in_repo(monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(REPO_ROOT)
    return REPO_ROOT


def test_same_or_better_passes() -> None:
    assert gate.check_suite(SUITE, BASE, BASE) == []
    assert gate.check_suite(SUITE, {**BASE, "leak_rate": 0.30}, BASE) == []
    assert gate.check_suite(SUITE, {**BASE, "leak_rate": 0.41}, BASE) == []  # within tolerance


@pytest.mark.parametrize(
    ("current", "needle"),
    [
        ({**BASE, "leak_rate": 0.42}, "leak_rate rose"),
        ({**BASE, "roundtrip_rate": 0.98}, "roundtrip_rate fell"),
        ({**BASE, "over_masking_rate": 0.01}, "over_masking_rate rose"),
    ],
)
def test_regression_versus_baseline_fails(current: dict[str, float], needle: str) -> None:
    failures = gate.check_suite(SUITE, current, BASE)
    assert any(needle in f for f in failures)


def test_absolute_limits_hold_without_a_baseline() -> None:
    assert gate.check_suite(SUITE, BASE, None) == []
    failures = gate.check_suite(SUITE, {**BASE, "leak_rate": 0.6}, None)
    assert failures == ["leak_rate 0.600000 breaks the committed leak_rate_max 0.500000"]


def test_metrics_of_reads_a_summary() -> None:
    summary = {"leak": {"rate": 0.25}, "roundtrip": {"rate": 1.0}, "over_masking": {}}
    assert gate.metrics_of(summary) == {"leak_rate": 0.25, "roundtrip_rate": 1.0}


def _record(run_id: str, at: str, path: Path, sha: str, *, key: str = "rules") -> dict:
    return {
        "run_id": run_id,
        "kind": "text",
        "source": "recorded",
        "recorded_at": at,
        "system": {"family": "pii-guard", "key": key, "detectors": [{"name": "rules"}]},
        "fixtures": [{"path": str(path), "sha256": sha}],
    }


def test_baseline_is_the_newest_record_on_the_same_files(tmp_path: Path) -> None:
    fixture = tmp_path / "f.jsonl"
    fixture.write_text("{}\n", encoding="utf-8")
    sha = gate.file_sha256(fixture)
    records = [
        _record("old", "2026-01-01T00:00:00+00:00", fixture, sha),
        _record("new", "2026-02-01T00:00:00+00:00", fixture, sha),
        _record("stale-fixture", "2026-03-01T00:00:00+00:00", fixture, "0" * 64),
        _record("other-system", "2026-03-01T00:00:00+00:00", fixture, sha, key="rules+ner:x"),
    ]
    found = gate.baseline_record(records, detectors=["rules"], fixtures=[fixture])
    assert found is not None and found["run_id"] == "new"
    assert gate.baseline_record(records[2:3], detectors=["rules"], fixtures=[fixture]) is None


# untraced: under the branch tracer this one call took 106 s of the CI test job (LAB-1447);
# without it, about 5 s. It checks the committed data, not the code: the gate's code paths
# are covered by the other tests here (test_a_tightened_limit_fails runs a whole suite).
@pytest.mark.slow
@pytest.mark.untraced
def test_committed_gates_pass(in_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert gate.main([]) == 0
    out = capsys.readouterr().out
    assert "eval gate: OK" in out
    assert "baseline -" not in out  # every committed suite has a matching run record


def test_a_tightened_limit_fails(
    in_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gates = json.loads((in_repo / "eval/gates.json").read_text(encoding="utf-8"))
    gates["suites"] = gates["suites"][:1]
    gates["suites"][0]["limits"]["leak_rate_max"] = 0.01
    path = tmp_path / "gates.json"
    path.write_text(json.dumps(gates), encoding="utf-8")
    # No run records: the absolute limit holds without a baseline, and the 700+ committed
    # records need not be validated again (LAB-1447; test_committed_gates_pass reads them).
    runs = tmp_path / "results" / "runs"
    runs.mkdir(parents=True)
    (tmp_path / "results" / "schema").mkdir()
    shutil.copy(in_repo / "eval/results/schema/run.schema.json", tmp_path / "results" / "schema")
    assert gate.main(["--gates", str(path), "--runs-dir", str(runs)]) == 1
    captured = capsys.readouterr()
    assert "breaks the committed leak_rate_max" in captured.err
    assert "baseline -" in captured.out and "only the absolute limits apply" in captured.out


@pytest.mark.parametrize(
    "gates",
    [
        {"suites": []},
        {"suites": [{"name": "x", "fixtures": []}]},
        {"suites": [{"name": "x", "fixtures": [], "detectors": ["rules"], "limits": {"y": 1}}]},
    ],
)
def test_malformed_gates_exit_2(in_repo: Path, tmp_path: Path, gates: dict) -> None:
    path = tmp_path / "gates.json"
    path.write_text(json.dumps(gates), encoding="utf-8")
    assert gate.main(["--gates", str(path)]) == 2


def _one_suite(in_repo: Path, tmp_path: Path, leak_rate_max: float) -> list[str]:
    gates = json.loads((in_repo / "eval/gates.json").read_text(encoding="utf-8"))
    gates["suites"] = gates["suites"][:1]
    gates["suites"][0]["limits"]["leak_rate_max"] = leak_rate_max
    path = tmp_path / "gates.json"
    path.write_text(json.dumps(gates), encoding="utf-8")
    runs = tmp_path / "results" / "runs"
    runs.mkdir(parents=True)
    (tmp_path / "results" / "schema").mkdir()
    shutil.copy(in_repo / "eval/results/schema/run.schema.json", tmp_path / "results" / "schema")
    return ["--gates", str(path), "--runs-dir", str(runs)]


@pytest.mark.parametrize(("leak_rate_max", "code"), [(1.0, 0), (0.01, 1)])
def test_pii_guard_eval_gate_exits_like_the_module(
    in_repo: Path, tmp_path: Path, leak_rate_max: float, code: int
) -> None:
    """``pii-guard eval gate`` dispatches to the module and keeps its 0/1/2 exit codes."""
    from pii_guard.eval import cli as eval_cli

    args = _one_suite(in_repo, tmp_path, leak_rate_max)
    assert eval_cli.main(["gate", *args]) == code == gate.main(args)


def test_pii_guard_eval_gate_bad_gates_exit_2(in_repo: Path, tmp_path: Path) -> None:
    from pii_guard.eval import cli as eval_cli

    path = tmp_path / "gates.json"
    path.write_text(json.dumps({"suites": []}), encoding="utf-8")
    assert eval_cli.main(["gate", "--gates", str(path)]) == 2
