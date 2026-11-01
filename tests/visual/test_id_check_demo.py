"""End to end: the "which parties have an ID?" demo and the placeholder-matching eval (LAB-1156).

Mocked upstream, recorded OCR words, SAM off: runs in CI without network or Tesseract.
Everything is fictional (the LAB-1121 specimens in ``eval/fixtures/visual/``).
"""

from __future__ import annotations

import functools
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pii_guard.detect.known import merge_known
from pii_guard.eval.visual_labels import (
    DEMO_CONTRACT,
    EVAL_KEY,
    ExactMatcher,
    _seed,
    coverage,
    demo_documents,
    evaluate,
    load_gold,
    score_demo_answer,
)
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, Vault
from pii_guard.vault.known import KnownValue

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
    parts = next(m["content"] for m in body["messages"] if m["role"] == "user")
    assert sum(p["type"] == "image_url" for p in parts) == len(demo.images)
    assert sum("Document summary:" in p.get("text", "") for p in parts) == len(demo.images)
    # Every ID card holder's placeholder in the Document summary matches the contract's placeholder.
    contract_placeholders = set(PLACEHOLDER_RE.findall(parts[0]["text"]))
    for part in parts[1:]:
        if "Document summary:" in part.get("text", ""):
            summary_line = next(
                line.removeprefix("Document summary: ")
                for line in part["text"].splitlines()
                if line.startswith("Document summary: ")
            )
            holder = json.loads(summary_line)["holder"]
            assert tuple(holder.strip("[]").split("_", 1)) in contract_placeholders


def test_demo_contract_ner_subword_cut_keeps_party_placeholders_intact() -> None:
    """Regression: when the NER model is active alongside ``known_values``, its subword cut
    ``Erika Musterman`` inside ``Erika Mustermannak`` must widen to ``Erika Mustermann`` so the
    contract and the German ID card share one placeholder that unmasks to ``Erika Mustermann``."""
    demo = demo_documents()
    session = Vault(EVAL_KEY).session()
    session.known_values.add([KnownValue(p, EntityType.PERSON) for p in demo.parties])
    cut = DEMO_CONTRACT.index("Erika Mustermannak")
    ner_spans = [
        Span(cut, cut + len("Erika Musterman"), EntityType.PERSON, "Erika Musterman", 0.99, "ner"),
    ]
    spans = merge_known(DEMO_CONTRACT, ner_spans, session.known_values, "hu")
    masked = session.mask(DEMO_CONTRACT, spans, language="hu")
    for party in demo.parties:
        assert party not in masked
    # No dangling 'n.' after the buyer's placeholder.
    assert "]]n." not in masked
    assert session.unmask(masked) == DEMO_CONTRACT


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


@functools.cache
def _evaluated(matcher: str, noise: float) -> dict[str, Any]:
    """One eval per (matcher, noise) and worker: the noiseless fuzzy run serves two tests."""
    return evaluate(matcher=matcher, noise=noise)["overall"]


# Coverage (LAB-1447): the evals spend their time in pure-Python edit distances over all 24
# specimens, 2-3x slower under the branch tracer (34-47 s each on CI). The full-set checks
# below run unmeasured (untraced), with their thresholds unchanged; the same code is measured
# on three specimens by test_the_evals_run_on_a_small_set. Unmeasured, the cache is safe.
@pytest.mark.parametrize(
    ("noise", "accuracy"),
    [(0.0, 0.95), (0.05, 0.85)],
)
@pytest.mark.slow
@pytest.mark.untraced
def test_fuzzy_matching_meets_the_acceptance_bar(noise: float, accuracy: float) -> None:
    report = _evaluated("fuzzy", noise)
    assert report["match_accuracy"] >= accuracy, report
    assert report["false_merges"] == 0, report
    assert report["leaked"] == 0, report


@pytest.mark.slow
@pytest.mark.untraced
def test_fuzzy_beats_exact_matching() -> None:
    assert _evaluated("fuzzy", 0.0)["matched"] > _evaluated("exact", 0.0)["matched"]


@pytest.mark.slow
@pytest.mark.untraced
def test_labels_cover_at_least_what_opaque_boxes_cover() -> None:
    report = coverage()
    for key in ("recall_iou50", "recall_cov90", "gold_pixels_overwritten"):
        assert report["labels"][key] >= report["opaque"][key], (key, report)


#: A card, a passport and a letter: three layouts, three languages.
SMALL_SET = ("hu-id_card-front", "de-passport-data_page", "en-letter-page")


@pytest.fixture
def small_set(tmp_path: Path) -> Path:
    """The visual fixtures with the manifest cut to :data:`SMALL_SET` (the rest linked)."""
    fixtures = ROOT / "eval" / "fixtures" / "visual"
    root = tmp_path / "visual"
    root.mkdir()
    for item in fixtures.iterdir():
        if item.name != "manifest.json":
            (root / item.name).symlink_to(item)
    manifest = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))
    manifest["specimens"] = [s for s in manifest["specimens"] if s["id"] in SMALL_SET]
    assert {s["id"] for s in manifest["specimens"]} == set(SMALL_SET)
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


@pytest.mark.slow
def test_the_evals_run_on_a_small_set(small_set: Path) -> None:
    for matcher, noise in (("fuzzy", 0.05), ("exact", 0.0)):
        report = evaluate(matcher=matcher, noise=noise, root=small_set)["overall"]
        assert report["values"] > 0, report
        assert report["false_merges"] == 0 and report["leaked"] == 0, (matcher, report)
    report = coverage(small_set)
    assert report["labels"]["regions"] == report["opaque"]["regions"] > 0
    for key in ("recall_iou50", "recall_cov90", "gold_pixels_overwritten"):
        assert report["labels"][key] >= report["opaque"][key], (key, report)


def test_exact_matcher_reuses_only_an_equal_value() -> None:
    session = Vault(EVAL_KEY).session()
    (placeholder,) = _seed(session, [("Fiktív Mária", EntityType.PERSON)])
    matcher = ExactMatcher(session, "hu")
    for same in ("Fiktív Mária", "FIKTÍV  MÁRIA"):
        found = matcher.match(same, EntityType.PERSON)
        assert found.candidate is not None and found.candidate.placeholder == placeholder
        assert found.confidence == 1.0 and found.status == "exact"
        assert matcher.match_one(same, found.candidate).candidate is found.candidate
    for other, entity_type in (
        ("Fiktív Maria", EntityType.PERSON),  # one OCR slip: fuzzy territory, not exact
        ("Fiktív Mária", EntityType.ADDRESS),  # same text, another type
    ):
        assert matcher.match(other, entity_type).candidate is None
    candidate = matcher.match("Fiktív Mária", EntityType.PERSON).candidate
    assert candidate is not None
    assert matcher.match_one("Fiktív Maria", candidate).candidate is None
