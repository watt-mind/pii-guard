"""``python -m pii_guard.eval.baselines.records``: suite scorecards become valid run records."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pii_guard.eval.baselines import records, suite
from pii_guard.eval.record import load_schema, validate

ROOT = Path(__file__).resolve().parents[2]
EN_SMOKE = ROOT / "eval" / "fixtures" / "en-smoke.jsonl"
HU_PUBLIC = ROOT / "eval" / "fixtures" / "public" / "hu-ai4privacy.jsonl"
SCHEMA = ROOT / "eval" / "results" / "schema" / "run.schema.json"


def _card(tmp_path: Path, fixture: Path) -> dict:
    out = tmp_path / "card.json"
    assert suite.main(["--system", "rules", "--fixtures", str(fixture), "--json", str(out)]) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def test_strict_card_gets_detectors_cost_and_hardware(tmp_path):
    card = _card(tmp_path, EN_SMOKE)
    card["meta"]["detectors"] = ["rules", "ner", "llm"]
    card["run"].update(
        system="pii-guard strict",
        ner={
            "model": "/x/ckpt",
            "safetensors_sha256": {"model.safetensors": "ab" * 32},
            "device": "auto",
        },
        llm={
            "model": "meta-models/muse-spark-open-1026",
            "reasoning_effort": "low",
            "usage": {
                "requests": 10,
                "prompt_tokens": 100,
                "cached_tokens": 50,
                "completion_tokens": 20,
                "reasoning_tokens": 5,
            },
            "cost_usd": 0.01,
            "usd_per_1k_messages": 1.0,
        },
        blocked=1,
    )
    (rec,) = records.records_for(
        card, slug="comparison-en-smoke-strict", code_notes={card["meta"]["commit"][:7]: "a note"}
    )
    assert validate(rec, load_schema(SCHEMA)) == []
    names = [d["name"] for d in rec["system"]["detectors"]]
    assert names == ["rules", "ner", "llm"]
    assert rec["system"]["detectors"][1]["revision"] == "sha256:" + "ab" * 32
    assert rec["system"]["label"].startswith("pii-guard strict")
    assert rec["cost"]["usd"] == 0.01
    assert rec["cost"]["tokens"]["cached"] == 50
    assert "load average" in rec["hardware"]["description"]
    assert any("blocked" in n for n in rec["notes"])
    assert rec["code"]["note"] == "a note"
    assert rec["fixtures"][0]["origin"] == "hand-written"


@pytest.mark.slow
def test_public_fixture_is_marked_generated_with_notes(tmp_path):
    card = _card(tmp_path, HU_PUBLIC)
    card["baselines"] = {
        "llm-guard": {
            "overall": card["overall"],
            "languages": card["languages"],
            "reversible": True,
            "info": {},
        }
    }
    recs = records.records_for(card, slug="comparison-hu-ai4privacy")
    assert [r["system"]["tool"] for r in recs] == ["pii-guard", "llm-guard"]
    for rec in recs:
        assert validate(rec, load_schema(SCHEMA)) == []
        assert rec["fixture_set"] == "ai4privacy"
        assert rec["fixtures"][0]["origin"] == "generated"
        assert "ai4privacy" in rec["fixtures"][0]["generator"]
    assert any("contamination" in n for n in recs[1]["notes"])
    assert not any("contamination" in n for n in recs[0]["notes"])


def test_main_writes_one_record_per_system(tmp_path):
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "en-smoke-fast.json").write_text(json.dumps(_card(tmp_path, EN_SMOKE)), "utf-8")
    (cards / "ignored.json").write_text("{}", "utf-8")
    runs = tmp_path / "results" / "runs"
    (tmp_path / "results" / "schema").mkdir(parents=True)
    (tmp_path / "results" / "schema" / "run.schema.json").write_text(
        SCHEMA.read_text(encoding="utf-8"), "utf-8"
    )
    assert records.main([str(cards), "--runs-dir", str(runs), "--code-note", "x=y"]) == 0
    (written,) = runs.glob("*.json")
    assert written.name.endswith("-comparison-en-smoke-fast.json")
    assert records.main([str(cards), "--runs-dir", str(runs)]) == 2  # exists, no --overwrite
