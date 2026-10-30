"""NER v4.1 mix builder (LAB-1547): the loose-address treatment and the targeted documents."""

# Seeded synthetic data: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "training" / "ner"))

import v41_data

ROW = json.dumps(
    {
        "id": "x",
        "language": "lv",
        "text": "Anna Ozola, Rīgas iela 5",
        "spans": [
            {"start": 0, "end": 10, "entity_type": "PERSON"},
            {"start": 12, "end": 24, "entity_type": "ADDRESS"},
        ],
    }
)


def test_ign_moves_addresses_to_loss_ignore() -> None:
    (line,), moved = v41_data._address_mode([ROW], "ign")
    doc = json.loads(line)
    assert moved == 1
    assert [s["entity_type"] for s in doc["spans"]] == ["PERSON"]
    assert doc["meta"]["loss_ignore"] == [[12, 24]]


def test_o_drops_addresses_without_ignoring_them() -> None:
    (line,), moved = v41_data._address_mode([ROW], "o")
    doc = json.loads(line)
    assert moved == 1
    assert [s["entity_type"] for s in doc["spans"]] == ["PERSON"]
    assert "loss_ignore" not in doc.get("meta", {})


def test_targeted_documents_have_consistent_spans() -> None:
    for part in ("hu-poa", "mt-dob"):
        language, builder = v41_data.BUILDERS[part]
        rng = random.Random(1)
        for i in range(30):
            doc = builder(rng).document(f"{part}-{i}", language, {"source": "synthetic"})
            assert doc.spans
            for s in doc.spans:
                assert doc.text[s.start : s.end] == s.text


def test_hu_poa_names_the_agent_in_the_accusative() -> None:
    rng = random.Random(7)
    found = 0
    for _ in range(50):
        b = v41_data.hu_poa_doc(rng)
        text = "".join(b.parts)
        if "Alulírott" in text:
            agent = [s for s in b.spans if s.entity_type.value == "PERSON"][1]
            found += agent.text.endswith("t")
    assert found > 30
