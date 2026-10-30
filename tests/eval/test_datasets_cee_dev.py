"""The synthetic CEE dev split (LAB-1344): seeded, gold from construction, negatives unlabelled."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from pii_guard.eval.datasets import REGISTRY
from pii_guard.eval.datasets import cee_dev as cd
from pii_guard.eval.fixtures import load_fixtures

ROOT = Path(__file__).resolve().parents[2]
FILES = [ROOT / p for p in cd.paths()]


@pytest.fixture(scope="module")
def docs() -> list:
    return load_fixtures(FILES)


def test_registered_as_a_dev_split() -> None:
    ds = REGISTRY["cee-dev"]
    assert ds.split == "dev"
    assert ds.languages == ("hu", "en")


def test_committed_split_is_the_generator_output() -> None:
    for path, lang in zip(FILES, cd.LANGUAGES, strict=True):
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == cd.SIZE
        for i in (0, cd.SIZE - 1):
            doc = cd.document(lang, i)
            assert json.loads(lines[i]) == json.loads(json.dumps(doc.to_dict(), ensure_ascii=False))


def test_every_register_and_negative_kind_is_present(docs: list) -> None:
    assert set(Counter(d.meta["shape"] for d in docs)) == set(cd.REGISTERS)
    kinds = Counter(k for d in docs for k in d.meta["negatives"])
    assert set(kinds) == set(cd.NEGATIVES)
    assert min(kinds.values()) >= 20


def test_every_document_has_gold_and_negatives(docs: list) -> None:
    for d in docs:
        assert d.spans, d.id
        assert d.meta["negatives"], d.id
        assert d.meta["source"] == "synthetic" and d.meta["split"] == "dev"


def test_negative_shapes() -> None:
    import random

    rng = random.Random(0)  # noqa: S311 (seeded test data)
    for _ in range(50):
        assert re.fullmatch(r"1[78]\d{11}", cd.epoch_ms(rng))
        assert re.fullmatch(r"20(2[4-7])\d{10}", cd.stamp14(rng))
        assert re.fullmatch(r"1Z[0-9A-Z]{16}", cd.ups(rng))
        s10 = cd.s10(rng)
        assert re.fullmatch(r"[A-Z]{2}\d{9}[A-Z]{2}", s10)
        serial = s10[2:10]
        total = sum(int(d) * w for d, w in zip(serial, (8, 6, 4, 2, 3, 5, 9, 7), strict=True))
        assert int(s10[10]) == {10: 0, 11: 5}.get(11 - total % 11, 11 - total % 11)
