"""Split discipline (LAB-1226): no ``test`` document is a training or tuning input.

A document is identified by :func:`~pii_guard.eval.datasets._common.text_sha256` (SHA-256 of the
whitespace-folded text). The held-out hashes come from every ``test`` dataset's manifest (so
fetch-only sets like TAB are covered without their text) and from its committed files. They
are checked against:

- the NER v2 training inputs (LAB-1150): the hard negatives, regenerated here from their seed;
  the OpenPII train rows, whose sampler refused every uid and text of the evaluation sample
  (its manifest records it) and, when the generated corpora exist locally (``eval/generated/``,
  never committed), every training and dev file listed in the NER v2 configs;
- the rule fixtures (``eval/fixtures/*.jsonl``, ``eval/fixtures/negative``,
  ``eval/fixtures/known-values``), which rules are written and tuned against;
- every ``dev`` split (the synthetic generator's dev split).
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import pytest

from pii_guard.eval.datasets import REGISTRY, test_datasets
from pii_guard.eval.datasets._common import text_sha256
from pii_guard.eval.fixtures import load_fixtures

ROOT = Path(__file__).resolve().parents[2]


def _held_out() -> dict[str, str]:
    """text hash -> dataset, over every test split."""
    out: dict[str, str] = {}
    for ds in test_datasets():
        manifest = json.loads((ROOT / ds.manifest_path).read_text(encoding="utf-8"))
        for block in manifest.get("languages", {}).values():
            for h in block.get("text_sha256", []):
                out[h] = ds.name
        for path in ds.fixture_paths():
            if (ROOT / path).is_file():
                for doc in load_fixtures([ROOT / path]):
                    out[text_sha256(doc.text)] = ds.name
    return out


HELD_OUT = _held_out()


def _overlap(paths: list[Path]) -> list[str]:
    hits = []
    for path in paths:
        for doc in load_fixtures([path]):
            if text_sha256(doc.text) in HELD_OUT:
                hits.append(f"{path.name}:{doc.id} is in {HELD_OUT[text_sha256(doc.text)]}")
    return hits


def test_every_test_split_has_hashes() -> None:
    names = set(HELD_OUT.values())
    assert names >= {"gretel-finance", "nemotron-pii", "cee-pii", "tab-echr", "agent-traffic"}
    assert "ai4privacy" in names


def test_hard_negatives_are_disjoint() -> None:
    sys.path.insert(0, str(ROOT / "training" / "ner"))
    try:
        import negatives  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    # The NER v2 run: --n 2000 --seed 1150, hu/en/de (training/ner/v2-base-hn.toml).
    hits = [
        f"{lang}-{i}"
        for lang in ("hu", "en", "de")
        for i in range(2000)
        if text_sha256(negatives.document(lang, 1150, i).text) in HELD_OUT
    ]
    assert hits == []


def test_openpii_training_rows_excluded_the_evaluation_sample() -> None:
    manifest = json.loads((ROOT / "training/ner/openpii-train-manifest.json").read_text())
    holdout = manifest["eval_holdout"]
    assert holdout["disjoint"] is True
    assert holdout["manifest"] == str(REGISTRY["ai4privacy"].manifest_path)
    assert all(block["eval_overlap_skipped"] == 0 for block in manifest["languages"].values())


def test_rule_fixtures_are_disjoint() -> None:
    fixtures = ROOT / "eval" / "fixtures"
    paths = [
        *sorted(fixtures.glob("*.jsonl")),
        *sorted((fixtures / "negative").glob("*.jsonl")),
        *sorted((fixtures / "known-values").glob("*.jsonl")),
    ]
    assert paths
    assert _overlap(paths) == []


def test_dev_splits_are_disjoint() -> None:
    dev = [ROOT / p for ds in REGISTRY.values() if ds.split == "dev" for p in ds.fixture_paths()]
    assert dev
    assert _overlap(dev) == []


def test_local_ner_training_corpora_are_disjoint() -> None:
    """Every train/dev file of the NER v2 configs, where the generated corpora exist."""
    files: set[str] = set()
    for config in sorted((ROOT / "training" / "ner").glob("v2-*.toml")):
        data = tomllib.loads(config.read_text(encoding="utf-8"))
        files.update(data.get("train", []) + data.get("dev", []))
    present = [ROOT / f for f in sorted(files) if (ROOT / f).is_file()]
    if not present:
        pytest.skip("eval/generated/ is not committed; the NER v2 corpora aren't here")
    assert _overlap(present) == []  # pragma: no cover - only where the corpora exist
