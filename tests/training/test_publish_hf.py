"""publish_hf.py staging rules (LAB-1306; v4.2 metadata, LAB-1625)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "publish_hf", ROOT / "training" / "ner" / "publish_hf.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["publish_hf"] = module
    spec.loader.exec_module(module)
    return module


publish_hf = _load()


def test_modal_data_root_becomes_a_data_ref() -> None:
    meta = {
        "device": "cuda",
        "train": {
            "/root/data/v41/court/labelled/bg-distill-train.jsonl": "aa",
            "eval/generated/negatives/hu-negatives-train.jsonl": "bb",
        },
        "report_dev": {"eval/generated/selection-v42/hu-selection-v42.jsonl": "cc"},
        "decontam": {"files": {"/root/data/phase1b/labelled/fr-distill-train.jsonl": {"kept": 1}}},
    }
    out = publish_hf.clean_meta(meta)
    assert "device" not in out
    assert list(out["train"]) == [
        "data:v41/court/labelled/bg-distill-train.jsonl",
        "eval/generated/negatives/hu-negatives-train.jsonl",
    ]
    assert out["report_dev"] == meta["report_dev"]
    assert list(out["decontam"]["files"]) == ["data:phase1b/labelled/fr-distill-train.jsonl"]


def test_other_absolute_paths_are_refused() -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        publish_hf.clean_meta({"train": {"/srv/x/hu-train.jsonl": "aa"}})


def test_front_matter_names_every_hf_training_dataset() -> None:
    for repo in (
        "ai4privacy/pii-masking-openpii-1m",
        "DataikuNLP/kiji-pii-training-data",
        "Wismut/nym-pii-multilingual-data",
        "E3-JSI/synthetic-multi-pii-ner-v1",
        "subhash-holla/pii-anon",
    ):
        assert f"- {repo}\n" in publish_hf.FRONT_MATTER
        assert repo in publish_hf.NOTICE
    assert "Ai4Privacy / Ai Suisse SA" in publish_hf.NOTICE
