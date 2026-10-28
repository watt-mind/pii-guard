"""Bootstrap intervals and the per-dataset section of docs/benchmarks.md (LAB-1226)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pii_guard.eval.datasets import REGISTRY
from pii_guard.eval.datasets.ci import bootstrap, load_counts, render_section, summarize

ROOT = Path(__file__).resolve().parents[2]
COUNTS = ROOT / "eval" / "datasets" / "results"


def _doc(leaked: int = 0, **kw: int) -> dict[str, int]:
    base = {"gold": 2, "tp_gold": 2 - leaked, "pred": 2, "tp_pred": 2, "values": 2,
            "leaked": leaked, "masked": 2, "over_masked": 0, "detect_ms": 1}  # fmt: skip
    return {**base, **kw}


def test_bootstrap_is_seeded_and_brackets_the_point() -> None:
    docs = [_doc(i % 3 == 0) for i in range(60)]
    a = bootstrap(docs, resamples=200)
    assert a == bootstrap(docs, resamples=200)
    leak = a["leak"]
    assert leak["low"] <= leak["value"] <= leak["high"]
    assert leak["low"] < leak["high"]
    assert a["over_masking"] == {"value": 0.0, "low": 0.0, "high": 0.0}


def test_undefined_rates_have_no_interval() -> None:
    docs = [_doc(values=0, pred=0, tp_pred=0, masked=0)]
    s = bootstrap(docs, resamples=10)
    assert s["leak"] == {"value": None, "low": None, "high": None}
    assert s["f1"]["value"] is None
    assert bootstrap([], resamples=10)["leak"]["value"] is None


def test_summary_splits_checksum_and_perturbation() -> None:
    docs = [
        {**_doc(0), "checksum": {"true_values": 2, "true_leaked": 1, "false_values": 1,
                                 "false_leaked": 1}, "perturbed": {"perturbed_values": 1,
                                                                   "perturbed_leaked": 0}},
        _doc(1),
    ]  # fmt: skip
    s = summarize(docs, resamples=20)
    assert s["checksum"]["true"]["rate"] == 0.5 and s["checksum"]["false"]["rate"] == 1.0
    assert s["perturbed"]["perturbed"]["rate"] == 0.0
    assert s["p50_ms"] == 1


def test_per_document_counts_are_committed() -> None:
    assert list(COUNTS.glob("*.json")), "no per-document counts committed"


# One item per record lets xdist distribute the expensive bootstrap recomputations.
# Paths are sorted so every worker collects the same items in the same order.
@pytest.mark.parametrize("path", sorted(COUNTS.glob("*.json")), ids=lambda path: path.stem)
def test_stored_summaries_match_a_recompute(path: Path) -> None:
    counts = json.loads(path.read_text(encoding="utf-8"))
    assert counts["summary"] == summarize(counts["documents"]), counts["run_id"]
    assert counts["dataset"] in REGISTRY
    assert "text" not in json.dumps(counts["documents"])


def test_section_lists_every_dataset_with_runs() -> None:
    order = [(d.name, d.title, d.split) for d in REGISTRY.values()]
    section = render_section(load_counts(COUNTS), order)
    for name in ("gretel-finance", "nemotron-pii", "cee-pii", "tab-echr", "agent-traffic"):
        assert f"### `{name}`" in section
    assert "Invalid checksum" in section
    page = (ROOT / "docs" / "benchmarks.md").read_text(encoding="utf-8")
    assert section in page
    assert render_section([], order) == ""
