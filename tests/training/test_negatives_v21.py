"""negatives_v21.py and publish_hf.py (LAB-1306). Fictional, generated text only."""

from __future__ import annotations

import json
import random

import pytest

from pii_guard.detect.checksums import is_valid_giro, is_valid_iban, is_valid_taj

from .conftest import load_script


@pytest.fixture(scope="module")
def mod():
    return load_script("training/ner/negatives_v21.py", "ner_negatives_v21")


@pytest.fixture(scope="module")
def publish():
    return load_script("training/ner/publish_hf.py", "ner_publish_hf")


def test_documents_are_seeded_and_mixed(mod) -> None:
    for language in mod.LANGUAGES:
        docs = mod.generate(language, 60, 1306, [])
        again = mod.generate(language, 60, 1306, [])
        assert [d.text for d in docs] == [d.text for d in again]
        kinds = [d.meta["kind"] for d in docs]
        assert kinds.count("negative-reference") == 30
        assert kinds.count("negative-street") == 15
        assert kinds.count("negative-company") == 15


def test_reference_documents_have_no_spans_and_no_valid_identifier(mod) -> None:
    rng = random.Random(7)  # noqa: S311 - seeded test data
    for _ in range(3000):
        value = mod.clean_reference(rng)
        compact = "".join(ch for ch in value if ch.isalnum()).upper()
        digits = "".join(ch for ch in value if ch.isdigit())
        assert not (compact[:2].isalpha() and len(compact) >= 15 and is_valid_iban(compact))
        assert not (len(digits) in (16, 24) and is_valid_giro(digits))
        assert not (len(digits) == 9 and is_valid_taj(digits))
    docs = mod.generate("en", 40, 1306, [])
    assert all(not d.spans for d in docs if d.meta["kind"] == "negative-reference")


def test_luhn(mod) -> None:
    assert mod.luhn_valid("4111111111111111")
    assert not mod.luhn_valid("4111111111111112")


def test_company_spans_cover_the_firm_as_organization(mod) -> None:
    for language in mod.LANGUAGES:
        for doc in mod.generate(language, 80, 1306, []):
            if doc.meta["kind"] != "negative-company":
                continue
            (span,) = doc.spans
            assert span.entity_type == "ORGANIZATION"
            assert doc.text[span.start : span.end] == span.text
            assert doc.meta["name"] in span.text


def test_street_documents_label_only_full_addresses(mod) -> None:
    docs = [d for d in mod.generate("hu", 200, 1306, []) if d.meta["kind"] == "negative-street"]
    assert any(d.spans for d in docs) and any(not d.spans for d in docs)
    for doc in docs:
        assert doc.meta["name"] in doc.text
        for span in doc.spans:
            assert span.entity_type == "ADDRESS"
            assert doc.text[span.start : span.end] == span.text
            assert doc.meta["name"] not in span.text or span.text.count(doc.meta["name"]) == 1


def test_names_in_eval_text_are_redrawn(mod) -> None:
    docs = mod.generate("de", 40, 1306, [])
    taken = [d.meta["name"] for d in docs if d.meta.get("name")][:5]
    eval_text = "Sample eval text: " + ", ".join(taken)
    assert mod.check_disjoint(docs, [eval_text]) == sorted(set(taken))
    redrawn = mod.generate("de", 40, 1306, [eval_text])
    assert mod.check_disjoint(redrawn, [eval_text]) == []
    assert len(redrawn) == 40


def test_publish_meta_drops_local_values(publish) -> None:
    meta = {"device": "cuda", "train": {"eval/generated/a.jsonl": "ab"}, "dev": {}}
    assert publish.clean_meta(meta, {"selected_epoch": 4}) == {
        "train": {"eval/generated/a.jsonl": "ab"},
        "dev": {},
        "selected_epoch": 4,
    }
    with pytest.raises(ValueError):
        publish.clean_meta({"train": {"/srv/run/x.jsonl": "ab"}})


def test_publish_stage_refuses_pickles(publish, tmp_path) -> None:
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    for name in publish.FILES:
        (ckpt / name).write_text("{}", encoding="utf-8")
    (ckpt / "training_meta.json").write_text(json.dumps({"train": {}}), encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    staged = publish.stage(ckpt, out)
    assert sorted(p.name for p in staged.iterdir()) == sorted(
        [*publish.FILES, "training_meta.json", "README.md", "NOTICE"]
    )
    assert (staged / "README.md").read_text(encoding="utf-8").startswith("---\nlicense: apache-2.0")
    (ckpt / "pytorch_model.bin").write_bytes(b"x")
    with pytest.raises(ValueError):
        publish.stage(ckpt, tmp_path)
