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


def test_v2_label_set_and_batch_order() -> None:
    import random

    train = load_script("training/ner/train.py", "ner_train_v2")
    assert "B-PHONE" in train.LABELS and "I-NATIONAL_ID_HU_TAJ" in train.LABELS
    train.set_types(train.TYPES_V1)
    assert "B-PHONE" not in train.LABELS
    train.set_types(train.TYPES_V2)
    lengths = [5, 50, 6, 49, 7, 48, 8, 47]
    order = train.batch_order(lengths, 2, random.Random(1), pool=4)  # noqa: S311
    assert sorted(i for b in order for i in b) == list(range(8))
    for batch in order:  # similar lengths end up together
        assert max(lengths[i] for i in batch) - min(lengths[i] for i in batch) <= 3


def test_encode_ignores_gold_of_untrained_types() -> None:
    from transformers import AutoTokenizer  # noqa: F401  (needs the extra)

    train = load_script("training/ner/train.py", "ner_train_v2b")
    train.set_types(("PERSON",))

    class Tok:
        def __call__(self, text, **kwargs):
            return {
                "input_ids": [[0, 1, 2, 3]],
                "attention_mask": [[1, 1, 1, 1]],
                "offset_mapping": [[(0, 0), (0, 5), (6, 10), (11, 20)]],
            }

    from pii_guard.eval.fixtures import Document, GoldSpan
    from pii_guard.types import EntityType

    text = "Teszt Elek +36301234567"
    doc = Document(
        "d1",
        "hu",
        text,
        (
            GoldSpan(0, 10, EntityType.PERSON, "Teszt Elek"),
            GoldSpan(11, 23, EntityType.PHONE, "+36301234567"),
        ),
        {},
    )
    features, ignored = train.encode(Tok(), [doc], dict(train.DEFAULTS))
    labels = features[0]["labels"]
    assert labels[-1] == train.IGNORE and ignored == 1
    cfg = dict(train.DEFAULTS, other_types="o")
    labels_o = train.encode(Tok(), [doc], cfg)[0][0]["labels"]
    assert labels_o[-1] == train.LABEL2ID["O"]
