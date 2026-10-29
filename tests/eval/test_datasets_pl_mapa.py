"""pl-pii-bench and MAPA EUR-Lex (LAB-1392): readers, label mapping, what is committed.

The fake source rows are fictional (ADR 0005); no download is made.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pii_guard.eval.datasets import get, mapa, pl_pii_bench, test_datasets
from pii_guard.eval.datasets._common import text_sha256
from pii_guard.eval.fixtures import load_fixtures
from pii_guard.types import EntityType

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _repo_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)


def _entity(text: str, value: str, label: str, **kw: object) -> dict[str, object]:
    start = text.index(value)
    return {"text": value, "label": label, "start": start, "end": start + len(value), **kw}


def test_pl_pii_bench_reader_and_label_mapping(tmp_path: Path) -> None:
    text = (
        "Pracownik: Jan Testowy, PESEL 00000000000, zam. ul. Próbna 1, 00-001 Miastko. "
        "Spotkanie w Miastku. REGON 000000000."
    )
    doc = {
        "doc_id": "core-test",
        "lane": "core",
        "axes": {"doc_type": "umowa"},
        "text": text,
        "entities": [
            _entity(text, "Jan Testowy", "PERSON"),
            _entity(text, "00000000000", "PESEL"),
            _entity(text, "ul. Próbna 1", "LOC"),
            _entity(text, "00-001", "POSTAL"),
            _entity(text, "Miastko", "LOC"),
            _entity(text, "Miastku", "LOC"),
            _entity(text, "000000000", "REGON"),
        ],
    }
    core = tmp_path / "core-test.json"
    core.write_text(json.dumps(doc), encoding="utf-8")
    sentence = "Sprawę prowadzi Testowego."
    inflection = tmp_path / "inflection.jsonl"
    row = {"text": sentence, "label": "PERSON", "start": 16, "end": 25, "case": "gen"}
    row |= {"entity_id": "surname-m:Testowy", "category": "surname-m-adj"}
    inflection.write_text(json.dumps(row) + "\n", encoding="utf-8")

    rows = list(pl_pii_bench.rows([core, inflection]))
    assert [r.uid for r in rows] == ["core-test", "inflection-surname-m-Testowy-gen"]
    assert rows[1].meta == {"lane": "inflection", "case": "gen", "category": "surname-m-adj"}
    converted = get("pl-pii-bench").to_document(rows[0])
    spans = {(text[s.start : s.end], s.entity_type) for s in converted.document.spans}
    assert spans == {
        ("Jan Testowy", EntityType.PERSON),
        ("00000000000", EntityType.ID_DOCUMENT),
        ("ul. Próbna 1, 00-001 Miastko", EntityType.ADDRESS),  # street + postcode + town
    }
    # A town on its own and a business number are ignore regions, not gold.
    ignored = {lab for lab in converted.dropped}
    assert {"LOC_PLACE (on its own)", "REGON"} <= ignored
    inflected = get("pl-pii-bench").to_document(rows[1]).document
    assert [sentence[s.start : s.end] for s in inflected.spans] == ["Testowego"]


def test_pl_pii_bench_committed_slice_is_attributed_and_pinned() -> None:
    ds = get("pl-pii-bench")
    assert ds in test_datasets() and ds.commit_rows and ds.synthetic
    assert ds.license == "CC-BY-4.0" and "Anonimator" in ds.attribution
    assert len(ds.files) == len(pl_pii_bench.FILES) == 74
    assert all(pl_pii_bench.REVISION in f.url for f in ds.files)
    manifest = json.loads(ds.manifest_path.read_text(encoding="utf-8"))
    docs = load_fixtures(ds.fixture_paths())
    assert len(docs) == manifest["languages"]["pl"]["documents"] == 346
    assert {d.meta["lane"] for d in docs} == {
        "core",
        "identifiers",
        "address",
        "negative",
        "inflection",
    }
    readme = (ROOT / "eval/datasets/pl-pii-bench/README.md").read_text(encoding="utf-8")
    assert "CC BY 4.0" in readme and pl_pii_bench.REVISION in readme


def test_mapa_reader_and_label_mapping(tmp_path: Path) -> None:
    text = "Opinion of Advocate General Testname in Case C-000/00, Ana Probe, a teacher."
    raw = {
        "uid": "000001_cs.txt",
        "language": "cs",
        "text": text,
        "entities": [
            _entity(text, "Testname", "last_name"),
            _entity(text, "C-000/00", "unique_id"),
            _entity(text, "Ana", "first_name"),
            _entity(text, "Probe", "last_name"),
            _entity(text, "teacher", "occupation"),
        ],
    }
    path = tmp_path / "test.jsonl"
    path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    (row,) = mapa.rows([path])
    assert row.uid == "000001_cs" and row.language == "cs"
    assert row.meta == {"annotation": "llm-projected"}
    converted = get("mapa-eur-lex").to_document(row)
    spans = [(text[s.start : s.end], s.entity_type) for s in converted.document.spans]
    assert spans == [("Testname", EntityType.PERSON), ("Ana Probe", EntityType.PERSON)]
    assert set(converted.dropped) == {"unique_id", "occupation"}


def test_mapa_real_documents_are_never_committed() -> None:
    ds = get("mapa-eur-lex")
    assert ds in test_datasets() and not ds.commit_rows and not ds.synthetic
    assert all(str(p).startswith("data/") for p in ds.fixture_paths())
    assert set(ds.languages) >= {"hu", "cs", "sk", "ro"} and len(ds.languages) == 21
    committed = sorted(p.name for p in (ROOT / "eval/datasets/mapa-eur-lex").iterdir())
    assert committed == ["README.md", "manifest.json"]
    manifest = json.loads(ds.manifest_path.read_text(encoding="utf-8"))
    assert manifest["rows_committed"] is False
    assert "text" not in json.dumps(manifest["languages"]).replace("text_sha256", "")
    assert sum(b["documents"] for b in manifest["languages"].values()) == 42
    for block in manifest["languages"].values():
        assert len(block["text_sha256"]) == block["documents"]
    # When the cache has been rebuilt, it matches the manifest.
    for path, lang in zip(ds.fixture_paths(), ds.languages, strict=True):
        if (ROOT / path).is_file():
            hashes = [text_sha256(d.text) for d in load_fixtures([ROOT / path])]
            assert hashes == manifest["languages"][lang]["text_sha256"]
