"""SFT pairs for the answer-only Glimmer detector (training/llm/build_sft.py). Fictional data."""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from pii_guard.detect.llm import parse_entities

from .conftest import load_script


@pytest.fixture(scope="module")
def sft() -> types.ModuleType:
    return load_script("training/llm/build_sft.py", "llm_build_sft")


TEXT_HU = "Teszt Elek (e-mail: teszt.elek@example.com) bérli a lakást. Teszt Eleknek írtunk."


def _doc(i: int, language: str, text: str, spans: list, **meta) -> dict:
    return {
        "id": f"{language}-x-{i}",
        "language": language,
        "text": text,
        "spans": spans,
        "meta": {"kind": "letter", "loss_ignore": [], **meta},
    }


def _span(text: str, value: str, entity_type: str, nth: int = 0) -> dict:
    start = -1
    for _ in range(nth + 1):
        start = text.index(value, start + 1)
    return {"start": start, "end": start + len(value), "entity_type": entity_type, "text": value}


def _corpus(tmp_path: Path, train: dict[str, list[dict]], dev: dict[str, list[dict]]) -> Path:
    labelled = tmp_path / "corpus" / "labelled"
    labelled.mkdir(parents=True)
    for split, by_lang in (("train", train), ("dev", dev)):
        for lang in ("hu", "en"):
            with (labelled / f"{lang}-distill-{split}.jsonl").open("w", encoding="utf-8") as f:
                for d in by_lang.get(lang, []):
                    f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return tmp_path / "corpus"


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_answer_is_the_detector_schema_and_parses(sft) -> None:
    content = sft.answer([("PERSON", "Teszt Elek"), ("PERSON", "Teszt Elek"), ("EMAIL", "a@b.c")])
    assert json.loads(content) == {
        "entities": [{"type": "PERSON", "text": "Teszt Elek"}, {"type": "EMAIL", "text": "a@b.c"}]
    }
    assert [e.text for e in parse_entities(content)] == ["Teszt Elek", "a@b.c"]


def test_build_writes_prompt_and_answer_only(sft, tmp_path: Path) -> None:
    spans = [
        _span(TEXT_HU, "Teszt Elek", "PERSON"),
        _span(TEXT_HU, "teszt.elek@example.com", "EMAIL"),
        _span(TEXT_HU, "Teszt Elek", "PERSON", nth=1),
    ]
    disagree = _doc(2, "hu", "Dr. Próba Zsuzsanna aláírta.", [], loss_ignore=[[0, 3]])
    negative = _doc(3, "en", "The release ships on Friday.", [], kind="negative-ops")
    en_hu_type = _doc(
        4,
        "en",
        "Tax id 8474213738 noted.",
        [_span("Tax id 8474213738 noted.", "8474213738", "NATIONAL_ID_HU_TAX")],
    )
    corpus = _corpus(
        tmp_path,
        {"hu": [_doc(1, "hu", TEXT_HU, spans), disagree], "en": [negative, en_hu_type]},
        {"en": [_doc(9, "en", "Ann Smith called.", [])]},
    )
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    manifest = sft.build(corpus, tmp_path / "out", seed=1, fixtures=fixtures)
    rows = _rows(tmp_path / "out" / "train.jsonl")
    assert len(rows) == 3
    first = rows[0]["messages"]
    assert [m["role"] for m in first] == ["system", "user", "assistant"]
    assert TEXT_HU in first[1]["content"] and "<<<TEXT-" in first[1]["content"]
    assert json.loads(first[2]["content"]) == {
        "entities": [
            {"type": "PERSON", "text": "Teszt Elek"},
            {"type": "EMAIL", "text": "teszt.elek@example.com"},
        ]
    }
    assert json.loads(rows[1]["messages"][2]["content"]) == {"entities": []}  # hard negative
    # A Hungarian-only type is not requested in English, so it is not a target there.
    assert json.loads(rows[2]["messages"][2]["content"]) == {"entities": []}
    counts = manifest["counts"]
    assert counts["excluded_disagreement"] == {"hu": 1}
    assert counts["dropped_type"]["en"] == {"NATIONAL_ID_HU_TAX": 1}
    assert manifest["output"]["examples"] == 3
    assert manifest["held_out_hashes"] == {"distill_dev": 1, "eval_fixtures": 0}
    # No raw values in the manifest.
    assert "Teszt" not in json.dumps(manifest)


def test_build_is_reproducible_and_boundaries_differ(sft, tmp_path: Path) -> None:
    docs = [_doc(i, "en", f"Note {i} for Ann Smith.", []) for i in range(3)]
    corpus = _corpus(tmp_path, {"en": docs, "hu": []}, {})
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    a = sft.build(corpus, tmp_path / "a", seed=5, fixtures=fixtures)
    b = sft.build(corpus, tmp_path / "b", seed=5, fixtures=fixtures)
    assert a["output"]["sha256"] == b["output"]["sha256"]
    users = [r["messages"][1]["content"] for r in _rows(tmp_path / "a" / "train.jsonl")]
    boundaries = {u.split("<<<TEXT-", 2)[2].split("\n", 1)[0] for u in users}
    assert len(boundaries) == 3


@pytest.mark.parametrize("where", ["dev", "fixtures"])
def test_held_out_documents_fail_the_build(sft, tmp_path: Path, where: str) -> None:
    leaked = _doc(1, "en", "Ann Smith lives at 1 Mill Road.", [])
    corpus = _corpus(
        tmp_path, {"en": [leaked], "hu": []}, {"en": [leaked]} if where == "dev" else {}
    )
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    if where == "fixtures":
        (fixtures / "x.jsonl").write_text(json.dumps({"text": leaked["text"]}) + "\n")
    with pytest.raises(AssertionError, match="held-out"):
        sft.build(corpus, tmp_path / "out", seed=1, fixtures=fixtures)
