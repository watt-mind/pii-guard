"""NER v3.2 tools (LAB-1494): weight soups and the MAPA dev reader for error mining.

Fictional only: the MAPA rows here are made up and only have the dataset's shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import load_script


@pytest.fixture(scope="module")
def mine():
    return load_script("training/ner/mine_errors.py", "ner_mine_errors_v32")


def _mapa(path: Path) -> None:
    rows = [
        {"language": "en", "file_name": "1_en", "sentence_number": 1,
         "tokens": ["Spinoit", "and", "D", "."],
         "coarse_grained": ["I-PERSON", "O", "B-PERSON", "I-PERSON"]},
        {"language": "en", "file_name": "1_en", "sentence_number": 0,
         "tokens": ["represented", "by", "B", "."],
         "coarse_grained": ["O", "O", "B-PERSON", "I-PERSON"]},
    ]  # fmt: skip
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_mapa_rows_keep_an_initial_with_its_surname_across_sentences(mine, tmp_path):
    path = tmp_path / "validation.jsonl"
    _mapa(path)
    [row] = list(mine.mapa_rows(path))
    assert "\n" not in row.text
    spans = [row.text[s:e] for s, e, _ in row.spans]
    # The sentence order is restored, and the split "B ." | "Spinoit" stays one text.
    assert row.text.startswith("represented by B . Spinoit")
    assert spans[0] == "B ."
    assert "Spinoit" in spans[1]


def test_family_names_are_value_free(mine):
    from pii_guard.eval.fixtures import Document

    doc = Document("x", "en", "Dear MARTA KOWALSKA, hi", (), {})
    assert mine.family("p", doc, "PERSON", "MARTA KOWALSKA", 5) == "person:all-caps"
    assert mine.family("p", doc, "BANK_ACCOUNT", "1234 5678 9012 3456", 0) == (
        "bank_account:digits-long"
    )


def test_soup_averages_float_tensors_and_refuses_mismatches(tmp_path):
    torch = pytest.importorskip("torch")
    st = pytest.importorskip("safetensors.torch")
    soup = load_script("training/ner/soup.py", "ner_soup_v32")

    def ckpt(name: str, value: float, shape=(2, 2)) -> Path:
        d = tmp_path / name
        d.mkdir()
        st.save_file(
            {"w": torch.full(shape, value), "ids": torch.arange(3)},
            d / "model.safetensors",
            metadata={"format": "pt"},
        )
        (d / "config.json").write_text('{"id2label": {"0": "O"}}', encoding="utf-8")
        (d / "tokenizer.json").write_text("{}", encoding="utf-8")
        return d

    a, b = ckpt("a", 0.0), ckpt("b", 1.0)
    meta = soup.soup(a, b, 0.3, tmp_path / "out")
    mixed = st.load_file(tmp_path / "out" / "model.safetensors")
    assert torch.allclose(mixed["w"], torch.full((2, 2), 0.3))
    assert torch.equal(mixed["ids"], torch.arange(3))
    assert meta["soup"]["integer_tensors_copied_from_a"] == 1
    with pytest.raises(ValueError, match="shape"):
        soup.check_compatible(a, ckpt("c", 1.0, shape=(3, 2)))
    with pytest.raises(ValueError, match="alpha"):
        soup.soup(a, b, 1.5, tmp_path / "bad")
