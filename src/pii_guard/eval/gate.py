"""Quality regression gate: fail CI when masking quality falls below the committed baseline.

```
python -m pii_guard.eval.gate [--gates eval/gates.json] [--runs-dir eval/results/runs]
```

For every suite in ``eval/gates.json`` (a fixture set scored with a fixed detector list, rules
only by default: offline, no model download) the gate scores the fixtures now and compares
three numbers with the **baseline**, the newest committed run record of the same system on the
same fixture files (same paths, same SHA-256):

* leak rate (share of gold values that reached the masked text) must not rise,
* round-trip rate (documents restored exactly) must not fall,
* over-masking rate (masked spans with no gold value under them) must not rise,

each beyond the suite's tolerance. The suite's absolute limits (``leak_rate_max``,
``roundtrip_rate_min``, ``over_masking_rate_max``) hold too, so a suite still has a floor when
its fixtures changed and no record matches them yet (the gate says so).

This is a regression gate, not a freshness check (``pii-guard eval report --check`` is that):
an improvement passes; record a run (``pii-guard eval --record``) to make it the new baseline.

Exit codes: 0 every suite within its gates, 1 a regression, 2 a malformed gates file or
unreadable fixtures.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import file_sha256, load_fixtures
from pii_guard.eval.scorer import DetectorAnalyzer, run_documents, summarize

__all__ = [
    "DEFAULT_GATES",
    "METRICS",
    "GateError",
    "SuiteResult",
    "baseline_record",
    "check_suite",
    "load_gates",
    "main",
    "metrics_of",
]

DEFAULT_GATES = Path("eval/gates.json")
DEFAULT_RUNS_DIR = Path("eval/results/runs")

# metric -> (path in a summary block, direction: +1 higher is worse, -1 lower is worse)
METRICS: dict[str, tuple[tuple[str, str], int]] = {
    "leak_rate": (("leak", "rate"), +1),
    "roundtrip_rate": (("roundtrip", "rate"), -1),
    "over_masking_rate": (("over_masking", "rate"), +1),
}
_LIMIT_KEYS = {
    "leak_rate": "leak_rate_max",
    "roundtrip_rate": "roundtrip_rate_min",
    "over_masking_rate": "over_masking_rate_max",
}
# Rates are stored rounded to 6 digits in run records; compare with that slack.
_EPS = 1e-6


class GateError(ValueError):
    """The gates file is malformed."""


@dataclass
class SuiteResult:
    name: str
    current: dict[str, float]
    baseline_id: str | None
    baseline: dict[str, float] | None
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def load_gates(path: str | Path = DEFAULT_GATES) -> dict[str, Any]:
    gates = json.loads(Path(path).read_text(encoding="utf-8"))
    suites = gates.get("suites")
    if not isinstance(suites, list) or not suites:
        raise GateError(f"{path}: needs a non-empty 'suites' list")
    for suite in suites:
        for key in ("name", "fixtures", "detectors"):
            if key not in suite:
                raise GateError(f"{path}: suite {suite.get('name', '?')!r} has no {key!r}")
        unknown = set(suite.get("tolerance", {})) - set(METRICS)
        unknown |= set(suite.get("limits", {})) - set(_LIMIT_KEYS.values())
        if unknown:
            raise GateError(f"{path}: suite {suite['name']!r}: unknown keys {sorted(unknown)}")
    return gates


def metrics_of(summary: Mapping[str, Any]) -> dict[str, float]:
    """The gated rates from a scorecard summary or a run record's ``metrics.overall``."""
    out = {}
    for name, ((block, key), _) in METRICS.items():
        value = (summary.get(block) or {}).get(key)
        if value is not None:
            out[name] = float(value)
    return out


def _system_key(detectors: Sequence[str]) -> str:
    return "+".join(detectors)


def baseline_record(
    records: Sequence[Mapping[str, Any]], *, detectors: Sequence[str], fixtures: Sequence[Path]
) -> Mapping[str, Any] | None:
    """The newest text run record of ``detectors`` on exactly these fixture files."""
    want = {str(p): file_sha256(p) for p in fixtures}
    key = _system_key(detectors)
    matches = []
    for record in records:
        if record.get("kind") != "text" or record.get("source") != "recorded":
            continue
        system = record.get("system") or {}
        if system.get("family") != "pii-guard" or system.get("key") != key:
            continue
        if any((d.get("settings") or {}) for d in system.get("detectors") or ()):
            continue  # a tuned detector is not the default configuration the gate scores
        got = {f["path"]: f.get("sha256") for f in record.get("fixtures") or ()}
        if got == want:
            matches.append(record)
    return max(matches, key=lambda r: (r.get("recorded_at") or "", r["run_id"]), default=None)


def check_suite(
    suite: Mapping[str, Any], current: Mapping[str, float], baseline: Mapping[str, float] | None
) -> list[str]:
    failures = []
    tolerance = suite.get("tolerance") or {}
    limits = suite.get("limits") or {}
    for name, (_, direction) in METRICS.items():
        now = current.get(name)
        if now is None:
            continue
        if baseline is not None and name in baseline:
            allowed = baseline[name] + direction * float(tolerance.get(name, 0.0))
            if direction * (now - allowed) > _EPS:
                worse = "rose" if direction > 0 else "fell"
                failures.append(
                    f"{name} {worse}: {now:.6f} vs baseline {baseline[name]:.6f} "
                    f"(tolerance {float(tolerance.get(name, 0.0)):.6f})"
                )
        limit_key = _LIMIT_KEYS[name]
        if limit_key in limits:
            limit = float(limits[limit_key])
            if direction * (now - limit) > _EPS:
                failures.append(f"{name} {now:.6f} breaks the committed {limit_key} {limit:.6f}")
    return failures


def run_suite(suite: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> SuiteResult:
    fixtures = [Path(p) for p in suite["fixtures"]]
    detectors = list(suite["detectors"])
    analyzer = DetectorAnalyzer(detectors)
    if analyzer.skipped:
        raise GateError(f"suite {suite['name']!r}: detectors not loadable: {analyzer.skipped}")
    documents = load_fixtures(fixtures)
    results = run_documents(documents, analyzer)
    current = metrics_of(summarize(results))
    record = baseline_record(records, detectors=detectors, fixtures=fixtures)
    baseline = metrics_of(record["metrics"]["overall"]) if record else None
    result = SuiteResult(
        name=suite["name"],
        current=current,
        baseline_id=record["run_id"] if record else None,
        baseline=baseline,
    )
    if record is None:
        result.notes.append(
            "no committed run record matches these fixture files; only the absolute limits apply"
        )
    result.failures = check_suite(suite, current, baseline)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pii_guard.eval.gate",
        description="Fail when leak, round trip or over-masking regress versus the committed "
        "run records (eval/gates.json).",
    )
    parser.add_argument("--gates", type=Path, default=DEFAULT_GATES)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from pii_guard.eval.record import RecordError, load_records

    try:
        gates = load_gates(args.gates)
        records = load_records(args.runs_dir)
        results = [run_suite(s, records) for s in gates["suites"]]
    except (GateError, RecordError, OSError, ValueError) as exc:
        print(f"eval gate: {exc}", file=sys.stderr)
        return 2
    failed = 0
    for r in results:
        state = "FAIL" if r.failures else "ok"
        rates = "  ".join(f"{k} {v:.4f}" for k, v in r.current.items())
        print(f"  {r.name:<16} {state:<5} {rates}  baseline {r.baseline_id or '-'}")
        for note in r.notes:
            print(f"    note: {note}")
        for failure in r.failures:
            print(f"    - {failure}", file=sys.stderr)
        failed += bool(r.failures)
    if failed:
        print(f"eval gate: FAILED ({failed} of {len(results)} suites regressed)", file=sys.stderr)
        return 1
    print(f"eval gate: OK ({len(results)} suites within their gates)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
