"""openpii.py: OpenPII train rows never include the eval sample (LAB-1150). Fictional rows only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import ROOT, load_script


@pytest.fixture(scope="module")
def mod():
    return load_script("training/ner/openpii.py", "ner_openpii")


def row(uid: str, text: str, mask: list[tuple[str, str]], language: str = "en") -> dict:
    spans = []
    for label, value in mask:
        start = text.index(value)
        spans.append({"label": label, "start": start, "end": start + len(value), "value": value})
    return {"uid": uid, "language": language, "source_text": text, "privacy_mask": spans}


def test_selection_skips_eval_rows_and_ignores_dates(mod) -> None:
    rows = [
        row("eval-1", "Call Teszt Elek on 1999-01-01.", [("GIVENNAME", "Teszt")]),
        row(
            "t1",
            "Mail Minta Anna on 2020-02-02.",
            [("GIVENNAME", "Minta"), ("SURNAME", "Anna"), ("DATE", "2020-02-02")],
        ),
        row("t2", "Same text as eval.", []),
        row("t3", "Hívja Próba Zsuzsit May 3.", [("GIVENNAME", "Próba")], language="hu"),
    ]
    eval_texts = {mod.text_sha(rows[2]["source_text"])}
    chosen, counts = mod.select(
        rows, {"en": 5, "hu": 5}, 7, eval_uids={"eval-1"}, eval_texts=eval_texts
    )
    ids = [d.meta["uid"] for d in chosen["en"]]
    assert ids == ["t1"]
    assert counts["eval_overlap_skipped_en"] == 2
    assert counts["filtered_hu_english_dates_hu"] == 1 and chosen["hu"] == []
    doc = chosen["en"][0]
    assert [s.entity_type.value for s in doc.spans] == ["PERSON"]  # given + surname merged
    start = doc.text.index("2020")
    assert doc.meta["loss_ignore"] == [[start, start + 10]]
    assert mod.assert_disjoint(chosen["en"], {"eval-1"}, set()) == 1


def test_assert_disjoint_raises_on_an_eval_uid_or_text(mod) -> None:
    rows = [row("x1", "Teszt Elek here.", [("GIVENNAME", "Teszt")])]
    docs = [mod.training_document(r) for r in rows]
    with pytest.raises(mod.DisjointnessError, match="uid"):
        mod.assert_disjoint(docs, {"x1"}, set())
    with pytest.raises(mod.DisjointnessError, match="text"):
        mod.assert_disjoint(docs, set(), {mod.text_sha("Teszt Elek here.")})


def test_committed_manifest_is_disjoint_from_the_eval_sample(mod) -> None:
    manifest = json.loads((ROOT / "training/ner/openpii-train-manifest.json").read_text("utf-8"))
    assert manifest["file"] == "data/train.jsonl" and manifest["rows_committed"] is False
    assert manifest["eval_holdout"]["disjoint"] is True
    eval_manifest = ROOT / "eval/fixtures/public/ai4privacy-openpii-1m.json"
    evaluated = json.loads(eval_manifest.read_text("utf-8"))
    assert evaluated["file"] == "data/validation.jsonl"  # eval comes from another split
    for lang, block in manifest["languages"].items():
        assert block["eval_overlap_skipped"] == 0, lang
        assert block["train"]["documents"] > 0


def test_eval_holdout_reads_uids_and_texts(mod) -> None:
    uids, texts = mod.eval_holdout(
        ROOT / "eval/fixtures/public/ai4privacy-openpii-1m.json",
        [ROOT / p for p in mod.EVAL_FIXTURES],
    )
    assert len(uids) == 600 and len(texts) >= 590


def test_generated_rows_if_present_are_disjoint(mod) -> None:
    out = ROOT / "eval/generated/openpii-train"
    files = sorted(out.glob("*-openpii-*.jsonl")) if out.is_dir() else []
    if not files:
        pytest.skip("OpenPII training rows not built locally")
    from pii_guard.eval.fixtures import load_fixtures

    uids, texts = mod.eval_holdout(
        ROOT / "eval/fixtures/public/ai4privacy-openpii-1m.json",
        [ROOT / p for p in mod.EVAL_FIXTURES],
    )
    assert mod.assert_disjoint(load_fixtures(files), uids, texts) > 0


def test_cli_rejects_mismatched_languages(mod, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        mod.main(["--source", str(tmp_path / "x.jsonl"), "--train", "en=1", "--dev", "hu=1"])
