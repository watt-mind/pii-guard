"""LAB-1417: the smoke-style hu/en/de dev split, reported per epoch and kept out of selection."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from pii_guard.eval.fixtures import load_fixtures

from .conftest import ROOT, load_script

smoke_dev = load_script("training/ner/smoke_style_dev.py", "ner_smoke_style_dev")
decontam = load_script("training/ner/decontam.py", "ner_decontam_smoke_dev")


def test_split_is_deterministic_and_covers_languages_and_kinds() -> None:
    docs = smoke_dev.build(per_kind=4)
    assert [d.to_dict() for d in docs] == [d.to_dict() for d in smoke_dev.build(per_kind=4)]
    kinds = Counter((d.language, d.meta["kind"]) for d in docs)
    assert set(kinds) == {(lang, k) for lang in smoke_dev.LANGS for k in smoke_dev.KINDS}
    assert set(kinds.values()) == {4}
    assert len({d.id for d in docs}) == len(docs)
    for doc in docs:
        assert doc.id.startswith(f"{doc.language}-smokedev-")
        assert any(s.entity_type.value == "PERSON" for s in doc.spans)
        for span in doc.spans:
            assert doc.text[span.start : span.end] == span.text
        assert len(doc.text) < 600  # short, like the smoke sets


def test_split_never_reuses_smoke_fixture_text_or_names() -> None:
    fixtures = ROOT / "eval/fixtures"
    smoke = load_fixtures(
        [*sorted(fixtures.glob("*-smoke.jsonl")), fixtures / "hu-inflection.jsonl"]
    )
    index = decontam.EvalIndex()
    for doc in smoke:
        index.add("smoke", doc)
    smoke_people = {s.text for d in smoke for s in d.spans if s.entity_type.value == "PERSON"}
    docs = smoke_dev.build()
    assert all(index.match(d) is None for d in docs)
    dev_people = {s.text for d in docs for s in d.spans if s.entity_type.value == "PERSON"}
    assert not dev_people & smoke_people


def test_write_gates_against_the_eval_corpus(tmp_path: Path) -> None:
    index = decontam.EvalIndex()
    first = smoke_dev.build(per_kind=2)[0]
    index.add("agent-traffic-dev", first)  # pretend the selection set holds a copy
    written = smoke_dev.write(tmp_path, per_kind=2, index=index)
    docs = load_fixtures(written)
    assert first.id not in {d.id for d in docs}
    assert {p.name for p in written} == {
        f"{lang}-smoke-style-dev.jsonl" for lang in smoke_dev.LANGS
    }


def _train(name: str):
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    return load_script("training/ner/train.py", name)


def test_leak_counts_any_type_overlap_masks_the_value() -> None:
    train = _train("ner_train_leak")
    gold = {(0, 5, "PERSON"), (10, 20, "EMAIL"), (30, 40, "PERSON")}
    pred = {(0, 5, "ORGANIZATION"), (12, 18, "EMAIL")}
    missed = train.leak_counts(pred, gold)
    assert missed == Counter({"PERSON": 1})


def test_report_docs_are_indexed_so_train_copies_are_dropped() -> None:
    train = _train("ner_train_report")
    docs = smoke_dev.build(per_kind=1)
    index = decontam.EvalIndex()
    index.add("smoke", load_fixtures([ROOT / "eval/fixtures/en-smoke.jsonl"])[0])
    train.index_report_docs(index, docs)
    report = decontam.Report()
    kept = decontam.gate(docs, index, name="train", report=report)
    assert kept == []
    assert report.to_dict()["by_eval_set"] == {"report-dev": len(docs)}


def test_report_dev_config_key_and_flag() -> None:
    train = _train("ner_train_cfg")
    assert train.DEFAULTS["report_dev"] == []
    cfg = train.load_config(["--report-dev", "a.jsonl", "--report-dev", "b.jsonl"])
    assert cfg["report_dev"] == ["a.jsonl", "b.jsonl"]


def test_hungarian_dative_labels_stem_changes_whole() -> None:
    assert smoke_dev._hu_dat("Kiss Imre") == "{{PERSON|Kiss Imrének}}"
    assert smoke_dev._hu_dat("Álnév Etelka") == "{{PERSON|Álnév Etelkának}}"
    assert smoke_dev._hu_dat("Vámos Benedek") == "{{PERSON|Vámos Benedek}}nek"
    assert smoke_dev._hu_dat("Szabó Áron") == "{{PERSON|Szabó Áron}}nak"
