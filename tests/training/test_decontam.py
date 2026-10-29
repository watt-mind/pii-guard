"""decontam.py (LAB-1392): near-duplicate gate of training data against every evaluation text.

Every text here is fictional (ADR 0005).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pii_guard.eval.fixtures import Document, write_fixtures

from .conftest import ROOT, load_script

decontam = load_script("training/ner/decontam.py", "ner_decontam")

BASE = (
    "Az eladó Kovács Anna, lakcíme 1111 Budapest, Példa utca 12., a vevő Nagy Péter, aki a "
    "vételárat a szerződés aláírásakor egy összegben, átutalással fizeti meg az eladó "
    "bankszámlájára, és a birtokbaadás napján átveszi az ingatlan kulcsait is."
)


def _doc(i: str, text: str, lang: str = "hu") -> Document:
    return Document(i, lang, text, (), {})


def _index(*texts: str) -> decontam.EvalIndex:
    index = decontam.EvalIndex()
    for n, text in enumerate(texts):
        index.add("eval-set", _doc(f"eval-{n}", text))
    return index


def _pl_core_text() -> str:
    path = ROOT / "eval/datasets/pl-pii-bench/pl-pl-pii-bench.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return next(r["text"] for r in rows if r["meta"]["lane"] == "core")


@pytest.fixture(autouse=True)
def _repo_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)


def test_decontam_shingles_and_jaccard() -> None:
    assert decontam.tokens("Ügyfél: KOVÁCS  Anna.") == ["ügyfél", "kovács", "anna"]
    short = decontam.shingles("Sprawę prowadzi Jan.")
    assert len(short) == 1  # shorter than five words: one shingle
    assert decontam.shingles("") == frozenset()
    a = decontam.shingles(BASE)
    assert decontam.jaccard(a, a) == 1.0
    assert decontam.jaccard(a, frozenset()) == 0.0
    # Case and spacing don't matter.
    assert decontam.shingles(BASE.upper().replace(" ", "  ")) == a


def test_decontam_numpy_and_python_signatures_agree() -> None:
    sh = decontam.shingles(BASE)
    py = decontam._signature_py(sh)
    assert len(py) == decontam.NUM_PERM
    if decontam._np is None:
        pytest.skip("numpy not installed")
    assert decontam._signature_np(sh) == py


def test_decontam_drops_exact_and_near_duplicates_only() -> None:
    index = _index(BASE, "Teljesen más szöveg egy rendelésszámról és egy szállítási címről.")
    near = BASE + " Köszönöm."  # a light edit: one more word at the end
    assert decontam.jaccard(decontam.shingles(near), decontam.shingles(BASE)) >= 0.8
    template = re.sub(r"Kovács Anna|Nagy Péter|Példa utca 12\.", "X", BASE)  # same template
    unrelated = "A csomag holnap érkezik, a futár reggel nyolc és tíz óra között csenget be."
    report = decontam.Report()
    docs = [
        _doc("t-exact", "  " + BASE + "\n"),
        _doc("t-near", near),
        _doc("t-template", template),
        _doc("t-unrelated", unrelated),
    ]
    kept = decontam.gate(docs, index, name="train.jsonl", report=report)
    assert [d.id for d in kept] == ["t-template", "t-unrelated"]
    f = report.files["train.jsonl"]
    assert (f["documents"], f["kept"], f["dropped_exact"], f["dropped_near"]) == (4, 2, 1, 1)
    assert f["by_eval_set"] == {"eval-set": 2}
    near_match = next(m for m in report.matches if m.train_id == "t-near")
    assert near_match.eval_id == "eval-0" and 0.8 <= near_match.jaccard < 1.0
    out = json.dumps(report.to_dict(index=index))
    assert "Kovács" not in out and "Budapest" not in out  # ids and counts only, never text


def test_decontam_threshold_is_exact() -> None:
    words = [f"szó{i}" for i in range(40)]
    base = " ".join(words)
    index = _index(base)
    # The last word changed: 1 of 36 shingles differs (J = 35/37). A word in the middle: 5
    # of them (J = 31/41), below the threshold: a re-filled template is not a duplicate.
    for position, dropped in ((39, True), (20, False)):
        variant = words[:]
        variant[position] = "más"
        j = decontam.jaccard(decontam.shingles(" ".join(variant)), decontam.shingles(base))
        m = index.match(_doc("t", " ".join(variant)))
        assert (m is not None) == dropped == (j >= decontam.THRESHOLD), (position, j)


def test_decontam_eval_corpus_covers_every_eval_set() -> None:
    index = decontam.eval_corpus()
    sets = set(index.sources)
    assert sets >= {
        "ai4privacy",
        "nemotron-pii",
        "gretel-finance",
        "cee-pii",
        "agent-traffic",
        "pl-pii-bench",
        "fixtures/smoke",
    }, sets
    hashed = {s for s, _ in index.hashes.values()}
    # Fetch-only sets are covered by their manifest hashes even without their text.
    assert {"tab-echr", "mapa-eur-lex"} <= hashed
    # The dev split NER candidates are selected on is indexed under its own name (LAB-1409).
    assert "agent-traffic-dev" in sets
    assert index.sources["agent-traffic-dev"] > 0
    # A committed eval document is caught, by hash and by its near-duplicate.
    pl = _pl_core_text()
    assert index.match(_doc("x", pl)) is not None
    assert index.match(_doc("y", pl + " Dziękuję.")) is not None


def test_decontam_load_training_docs_gates_by_default_and_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "hu-x-train.jsonl"
    write_fixtures(path, [_doc("a", BASE), _doc("b", "Egy egészen másik mondat, új szavakkal.")])
    report = decontam.Report()
    docs = decontam.load_training_docs([path], _index(BASE), report)
    assert [d.id for d in docs] == ["b"] and report.dropped == 1
    assert len(decontam.load_training_docs([path], None, decontam.Report())) == 2  # gate off
    with pytest.raises(RuntimeError, match="no evaluation text"):
        decontam.load_training_docs([path], decontam.EvalIndex(), decontam.Report())


def test_decontam_cli_writes_report_and_clean_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The CLI's plumbing on a corpus of the one set it must hit; building the whole eval
    # corpus (21 s on CI) is the previous test's job (LAB-1447).
    thresholds: list[float] = []

    def pl_corpus(*, threshold: float) -> decontam.EvalIndex:
        thresholds.append(threshold)
        index = decontam.EvalIndex(threshold=threshold)
        index.add("pl-pii-bench", _doc("pl-core", _pl_core_text(), "pl"))
        return index

    monkeypatch.setattr(decontam, "eval_corpus", pl_corpus)
    path = tmp_path / "pl-x-train.jsonl"
    write_fixtures(
        path, [_doc("leak", _pl_core_text(), "pl"), _doc("ok", "Zupełnie inny tekst.", "pl")]
    )
    out, report = tmp_path / "clean", tmp_path / "report.json"
    assert decontam.main([str(path), "--json", str(report), "--out", str(out)]) == 0
    data = json.loads(report.read_text())
    assert data["dropped"] == 1 and data["by_eval_set"] == {"pl-pii-bench": 1}
    assert [json.loads(line)["id"] for line in (out / path.name).read_text().splitlines()] == ["ok"]
    assert thresholds == [decontam.THRESHOLD]


def test_decontam_train_py_runs_the_gate_by_default() -> None:
    source = (ROOT / "training/ner/train.py").read_text(encoding="utf-8")
    assert "decontam.load_training_docs(train_paths, index" in source
    assert "decontam.load_training_docs(dev_paths, index" in source
    assert re.search(r'"decontam": True', source)
    assert "load_fixtures(train_paths)" not in source  # no path around the gate
    modal = (ROOT / "training/distill/modal_train.py").read_text(encoding="utf-8")
    assert "eval_upload_files(ROOT)" in modal  # the gate's texts go, by allowlist (LAB-1527)
