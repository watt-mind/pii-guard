"""train.py: regions in meta.loss_ignore are excluded from the loss."""

from __future__ import annotations

import pytest

pytest.importorskip("torch")
pytest.importorskip("transformers")

from .conftest import load_script


def test_token_labels_ignores_regions() -> None:
    train = load_script("training/ner/train.py", "ner_train")
    offsets = [(0, 0), (0, 3), (4, 9), (10, 15), (0, 0)]
    labels = train.token_labels(offsets, [(4, 9, "PERSON")], ignore=[(10, 15)])
    assert labels == [
        train.IGNORE,
        train.LABEL2ID["O"],
        train.LABEL2ID["B-PERSON"],
        train.IGNORE,
        train.IGNORE,
    ]
