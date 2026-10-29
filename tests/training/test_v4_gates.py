"""The NER v4 gate rules (LAB-1535): the thresholds the README fixed before training."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "training" / "ner"))

import gates_v4


def _r(leak: float, over: float) -> dict[str, float]:
    return {"leak": leak, "over": over, "leaked": 0, "values": 1}


def _metrics(**over: object) -> dict[str, object]:
    m: dict[str, object] = {
        "smoke": _r(0.0, 1.09),
        "inflection": _r(2.0, 0.0),
        "agent-traffic-dev": _r(0.13, 1.84),
        "eu": {"lv": _r(0.0, 0.0), "mt": _r(0.0, 12.9)},
        "eu-total": _r(0.95, 1.8),
    }
    m.update(over)
    return m


def test_v20_itself_passes_nothing_new() -> None:
    base = _metrics()
    g = gates_v4.gates(base, base, 1.0)
    assert not g["eu_total_lower"] and not g["beats_v20"] and not g["all_gates"]


def test_candidate_that_wins_everywhere_is_selected() -> None:
    base = _metrics()
    cand = _metrics(**{"agent-traffic-dev": _r(0.0, 1.5), "eu-total": _r(0.6, 1.0)})
    g = gates_v4.gates(base, cand, 1.1)
    assert g["all_gates"] and g["beats_v20"]


def test_smoke_over_masking_margin_is_half_a_point() -> None:
    base = _metrics()
    ok = _metrics(smoke=_r(0.0, 1.59), **{"eu-total": _r(0.6, 1.0)})
    bad = _metrics(smoke=_r(0.0, 1.60), **{"eu-total": _r(0.6, 1.0)})
    assert gates_v4.gates(base, ok, None)["smoke_over"]
    assert not gates_v4.gates(base, bad, None)["smoke_over"]


def test_one_language_regression_fails_the_eu_gate() -> None:
    base = _metrics()
    cand = _metrics(eu={"lv": _r(0.0, 0.0), "mt": _r(3.8, 6.7)}, **{"eu-total": _r(0.6, 1.0)})
    g = gates_v4.gates(base, cand, None)
    assert g["eu_failed_languages"] == ["mt"] and not g["all_gates"]


def test_latency_over_ratio_fails() -> None:
    base = _metrics()
    cand = _metrics(**{"eu-total": _r(0.6, 1.0)})
    assert not gates_v4.gates(base, cand, 1.21)["all_gates"]
