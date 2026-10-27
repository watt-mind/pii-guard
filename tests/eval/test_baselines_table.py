"""``python -m pii_guard.eval.baselines.table``: one row per (fixture, system)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from pii_guard.eval.baselines import suite, table

ROOT = Path(__file__).resolve().parents[2]
EN_SMOKE = ROOT / "eval" / "fixtures" / "en-smoke.jsonl"


def _card(tmp_path: Path) -> dict:
    out = tmp_path / "rules.json"
    assert suite.main(["--system", "rules", "--fixtures", str(EN_SMOKE), "--json", str(out)]) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def test_rows_name_systems_and_carry_cost(tmp_path):
    rules = _card(tmp_path)
    strict = copy.deepcopy(rules)
    strict["meta"]["detectors"] = ["rules", "ner", "llm"]
    strict["run"]["llm"] = {"usd_per_1k_messages": 2.5}
    strict["baselines"] = {
        "presidio": {"overall": rules["overall"], "reversible": False},
    }
    got = table.rows([strict, rules])
    assert [r["system"] for r in got] == ["pii-guard rules", "pii-guard strict", "presidio"]
    assert got[1]["usd_per_1k"] == 2.5
    assert got[2]["roundtrip"] is None
    md = table.render_table([strict, rules])
    assert "| `en-smoke` | presidio |" in md
    assert "n/a" in md
    assert "2.50" in md


def test_main_writes_file(tmp_path):
    card = tmp_path / "c.json"
    card.write_text(json.dumps(_card(tmp_path)), encoding="utf-8")
    out = tmp_path / "t.md"
    assert table.main([str(card), "--out", str(out)]) == 0
    assert "pii-guard rules" in out.read_text(encoding="utf-8")
