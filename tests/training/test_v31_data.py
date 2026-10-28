"""NER v3.1 mixes (LAB-1410): no generator-family file, fixed candidates, derivations, max J.

Fictional only.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from pii_guard.eval.fixtures import Document, GoldSpan
from pii_guard.eval.fixtures import write_fixtures as _write
from pii_guard.types import EntityType

from .conftest import ROOT, load_script


@pytest.fixture(scope="module")
def v31():
    return load_script("training/ner/v31_data.py", "ner_v31_data")


@pytest.fixture(scope="module")
def decontam():
    return load_script("training/ner/decontam.py", "ner_decontam_v31")


def _cfg(name: str) -> dict:
    return tomllib.loads((ROOT / f"training/ner/v31-{name}.toml").read_text())


def _doc(i: int, text: str = "", lang: str = "hu") -> Document:
    text = text or f"Kovács Teszt {i} írt a Minta utca {i} alatti irodából, kérem hívja vissza."
    return Document(f"d{i}", lang, text, (GoldSpan(0, 6, EntityType.PERSON, text[:6]),), {})


def write_fixtures(path: Path, docs: list[Document]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, docs)


def test_the_candidate_list_is_fixed(v31) -> None:
    assert v31.CANDIDATES == ("a", "b", "c")
    assert sorted(p.name for p in (ROOT / "training/ner").glob("v31-*.toml")) == [
        "v31-a.toml",
        "v31-b.toml",
        "v31-c.toml",
    ]


@pytest.mark.parametrize("name", ["a", "b", "c"])
def test_no_agent_traffic_generator_file_in_any_v31_mix(v31, name: str) -> None:
    cfg = _cfg(name)
    for path in [*cfg["train"], *cfg["dev"]]:
        assert "agent-traffic" not in path, path
        assert not v31.is_generator_file(path)
        assert path.startswith("eval/generated/v31-final/")
    assert "agent" not in v31.SOURCES


def test_a_is_v3_minus_the_agent_traffic_split() -> None:
    v3 = tomllib.loads((ROOT / "training/ner/v3-xlmr-base.toml").read_text())
    a = _cfg("a")
    rebased = [p.replace("v3-final", "v31-final") for p in v3["train"]]
    dropped = [p for p in rebased if p not in a["train"]]
    assert dropped and all("/agent-traffic/" in p for p in dropped)
    assert [p for p in rebased if "/agent-traffic/" not in p] == a["train"]
    assert [p.replace("v3-final", "v31-final") for p in v3["dev"]] == a["dev"]
    settings = ("base_model", "base_revision", "epochs", "lr", "batch_size", "max_length")
    assert all(a[k] == v3[k] for k in settings)


def test_b_and_c_differ_only_as_the_ticket_says() -> None:
    a, b, c = _cfg("a"), _cfg("b"), _cfg("c")
    swap = {
        "openpii/hu-openpii-train.jsonl": "openpii/hu-openpii-train-10k.jsonl",
        "privy/en-privy-train.jsonl": "privy/en-privy-train-6k.jsonl",
        "s11/hu-distill-train.jsonl": "s11/hu-distill-train-x1.5.jsonl",
        "s11/en-distill-train.jsonl": "s11/en-distill-train-x1.5.jsonl",
    }
    expected_b = []
    for p in a["train"]:
        for old, new in swap.items():
            p = p.replace(old, new)
        expected_b.append(p)
    assert b["train"] == expected_b
    assert c["train"] == [p for p in b["train"] if "/wismut/" not in p]
    assert any("/wismut/" in p for p in b["train"])
    for cfg in (b, c):
        assert cfg["dev"] == a["dev"]  # epoch choice on the same OpenPII + s11 dev split
        assert {k: v for k, v in cfg.items() if k not in ("train", "out")} == {
            k: v for k, v in a.items() if k not in ("train", "out")
        }


def test_dev_split_is_openpii_and_s11_only() -> None:
    for name in ("a", "b", "c"):
        for path in _cfg(name)["dev"]:
            assert path.endswith(("-openpii-dev.jsonl", "-distill-dev.jsonl")), path


def test_oversample_and_head(v31) -> None:
    docs = [_doc(i) for i in range(10)]
    out = v31.oversample(docs, 1.5)
    assert len(out) == 15 and out[:10] == docs
    assert all(d.id.endswith("~rep1") for d in out[10:])
    assert len({d.id for d in out}) == 15
    assert v31.oversample(docs, 1.5) == out  # seeded
    assert len(v31.oversample(docs, 2.0)) == 20
    assert v31.head(docs, 4) == docs[:4]
    with pytest.raises(ValueError):
        v31.head(docs, 11)
    with pytest.raises(ValueError):
        v31.oversample(docs, 0.5)


def test_openpii_hu_doubles_and_nothing_else_changes(v31) -> None:
    v3 = load_script("training/ner/v3_data.py", "ner_v3_data_for_v31")
    assert v31.OPENPII_TRAIN["hu"] == 2 * v3.OPENPII_TRAIN["hu"]
    assert {k: v for k, v in v31.OPENPII_TRAIN.items() if k != "hu"} == {
        k: v for k, v in v3.OPENPII_TRAIN.items() if k != "hu"
    }
    assert v3.PRIVY_N["en"] == v31.PRIVY_HALF * 2


def test_derive_builds_every_config_file(v31, decontam, tmp_path: Path, monkeypatch) -> None:
    raw = tmp_path / "raw"
    built = raw / v31.RAW
    langs = ("hu", "en", "de", "pl", "cs", "sk", "ro", "hr", "sl")
    n = 0

    def docs(k: int, lang: str = "en") -> list[Document]:
        nonlocal n
        out = [_doc(n + i, f"Szöveg {n + i} " * 3 + "vége.", lang) for i in range(k)]
        n += k
        return out

    for lang in langs:
        k = v31.OPENPII_HU_V3 // 1000 if lang == "hu" else 2
        write_fixtures(built / "openpii" / f"{lang}-openpii-train.jsonl", docs(k, lang))
        write_fixtures(built / "openpii" / f"{lang}-openpii-dev.jsonl", docs(1, lang))
    for name, files in {
        "privy": ["en-privy-train.jsonl"],
        "wismut": [f"{lang}-wismut-train.jsonl" for lang in ("en", "de", "pl", "cs", "ro")],
        "nemotron": ["en-nemotron-train.jsonl"],
        "gretel": ["en-gretel-train.jsonl"],
    }.items():
        for f in files:
            d = docs(3)
            write_fixtures(built / name / f, d)
            write_fixtures(raw / "audited" / f, d)
    for lang in ("hu", "en", "de"):
        write_fixtures(built / "negatives" / f"{lang}-negatives-train.jsonl", docs(2, lang))
    s11 = tmp_path / "s11"
    for lang in ("hu", "en"):
        write_fixtures(s11 / f"{lang}-distill-train.jsonl", docs(4, lang))
        write_fixtures(s11 / f"{lang}-distill-dev.jsonl", docs(1, lang))
    monkeypatch.setattr(v31, "OPENPII_HU_V3", 3)
    monkeypatch.setattr(v31, "PRIVY_HALF", 2)
    monkeypatch.chdir(tmp_path)
    report = v31.derive(raw, v31.FINAL, s11=s11, index=decontam.EvalIndex())
    assert report["dropped"] == 0
    for name in ("a", "b", "c"):
        for rel in [*_cfg(name)["train"], *_cfg(name)["dev"]]:
            assert (tmp_path / rel).is_file(), rel
    final = tmp_path / v31.FINAL
    assert len((final / "openpii/hu-openpii-train.jsonl").read_text().splitlines()) == 3
    assert len((final / "privy/en-privy-train-6k.jsonl").read_text().splitlines()) == 2
    assert len((final / "s11/hu-distill-train-x1.5.jsonl").read_text().splitlines()) == 6
    assert not list(final.rglob("*agent-traffic*"))


def test_max_jaccard_is_exhaustive(decontam) -> None:
    base = "eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf"
    evals = [_doc(1, base, "de"), _doc(2, "ganz anderer text ohne jede gemeinsamkeit hier", "de")]
    near = _doc(3, base.replace("zwölf", "dreizehn"), "de")
    far = _doc(4, "völlig unabhängige wörter stehen in diesem satz drin", "de")
    out = decontam.max_jaccard([far, near], evals)
    expected = decontam.jaccard(decontam.shingles(near.text), decontam.shingles(base))
    assert out["jaccard"] == round(expected, 4)
    assert (out["train_id"], out["eval_id"]) == ("d3", "d1")
    assert decontam.max_jaccard([far], evals)["jaccard"] == 0.0
    assert out["train_documents"] == 2 and out["eval_documents"] == 2
