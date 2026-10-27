"""End to end: the "which parties have an ID?" demo and the placeholder-matching eval (LAB-1156).

Mocked upstream, recorded OCR words, SAM off: runs in CI without network or Tesseract.
Everything is fictional (the LAB-1121 specimens in ``eval/fixtures/visual/``).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from pii_guard.eval.visual_labels import (
    coverage,
    demo_documents,
    evaluate,
    load_gold,
    score_demo_answer,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "which_parties_have_an_id.py"


def example() -> ModuleType:
    spec = importlib.util.spec_from_file_location("which_parties_have_an_id", EXAMPLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)  # the fixtures are addressed from the repository root


def test_demo_answers_every_party_and_forwards_no_raw_value(tmp_path: Path) -> None:
    result = example().run(out=tmp_path)
    assert result["score"]["correct"] == 3, result["score"]
    forwarded = (tmp_path / "forwarded.json").read_text(encoding="utf-8")
    demo = demo_documents()
    for party in demo.parties:
        assert party not in forwarded
        assert party.upper() not in forwarded
        assert party in result["answer"]  # restored on the way back
    for values in load_gold().values():
        for key in ("doc", "born"):
            if values.get(key):
                assert values[key] not in forwarded, key
    assert (tmp_path / "masked-1.png").is_file()
    body = json.loads(forwarded)
    parts = body["messages"][0]["content"]
    assert sum(p["type"] == "image_url" for p in parts) == len(demo.images)
    assert sum("Document summary:" in p.get("text", "") for p in parts) == len(demo.images)


def test_opaque_boxes_leave_the_model_without_an_answer() -> None:
    result = example().run(render="opaque")
    assert result["score"]["correct"] < 3


def test_score_demo_answer() -> None:
    expected = {"Fiktív Mária": "present", "Fiktív Márta": "missing"}
    answer = "- Fiktív Mária: valid ID card\n- Fiktív Márta: no ID provided"
    score = score_demo_answer(answer, expected)
    assert score["correct"] == 2 and score["statuses"] == ["present", "missing"]
    # The verdict line under the party's heading, not a later detail or the summary.
    answer = (
        "**1. Eladó: Fiktív Mária**\n* **ID present / expired**\n* `expired: true`\n\n"
        "**2. Kezes: Fiktív Márta**\n* **HIÁNYZIK**\n\nÖsszegzés: egy okmány lejárt."
    )
    assert score_demo_answer(answer, expected)["statuses"] == ["expired", "missing"]


@pytest.mark.parametrize(
    ("noise", "accuracy"),
    [(0.0, 0.95), (0.05, 0.85)],
)
def test_fuzzy_matching_meets_the_acceptance_bar(noise: float, accuracy: float) -> None:
    report = evaluate(matcher="fuzzy", noise=noise)["overall"]
    assert report["match_accuracy"] >= accuracy, report
    assert report["false_merges"] == 0, report
    assert report["leaked"] == 0, report


def test_fuzzy_beats_exact_matching() -> None:
    fuzzy = evaluate(matcher="fuzzy")["overall"]["matched"]
    exact = evaluate(matcher="exact")["overall"]["matched"]
    assert fuzzy > exact


def test_labels_cover_at_least_what_opaque_boxes_cover() -> None:
    report = coverage()
    for key in ("recall_iou50", "recall_cov90", "gold_pixels_overwritten"):
        assert report["labels"][key] >= report["opaque"][key], (key, report)
