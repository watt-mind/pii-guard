"""Generated corpora live outside the worktree and only synthetic data is pushed (LAB-1542)."""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from pii_guard.eval.datasets import REGISTRY

from .conftest import load_script

DOC = '{"id": "x", "text": "t", "spans": []}\n'


@pytest.fixture(scope="module")
def sync() -> types.ModuleType:
    return load_script("training/ner/data_sync.py", "data_sync")


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PII_GUARD_DATA_DIR", str(tmp_path))
    return tmp_path


def _corpus(root: Path, files: dict[str, str], manifest: dict | None) -> Path:
    corpus = root / "c1"
    for rel, text in files.items():
        (corpus / rel).parent.mkdir(parents=True, exist_ok=True)
        (corpus / rel).write_text(text, encoding="utf-8")
    if manifest is not None:
        (corpus / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return corpus


@pytest.fixture
def no_network(sync: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail() -> None:
        raise AssertionError("the Hub was contacted for a refused corpus")

    monkeypatch.setattr(sync, "_api", _fail)


def test_data_root_setting(sync: types.ModuleType, root: Path) -> None:
    assert sync.data_root() == root
    assert sync.resolve("data:phase1b/a/x.jsonl") == root / "phase1b" / "a" / "x.jsonl"
    assert sync.resolve("eval/generated/x.jsonl") == Path("eval/generated/x.jsonl")
    assert sync.corpus_of(root / "phase1b" / "distill" / "x.jsonl") == "phase1b"
    assert sync.corpus_of(root.parent / "elsewhere" / "eval" / "generated" / "x") is None


def test_default_data_root_is_outside_the_worktree(
    sync: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PII_GUARD_DATA_DIR", raising=False)
    assert sync.data_root() == Path("~/Develop/.worktrees/pii-guard/data-eu").expanduser()


@pytest.mark.parametrize(
    "manifest", [None, {"corpus": "c1"}, {"synthetic": False}, {"synthetic": "yes"}]
)
def test_refuses_a_corpus_not_marked_synthetic(
    sync: types.ModuleType, root: Path, no_network: None, manifest: dict | None
) -> None:
    _corpus(root, {"d/en-distill-train.jsonl": DOC}, manifest)
    with pytest.raises(sync.SyncRefused):
        sync.push("c1")


@pytest.mark.parametrize(
    "rel",
    [
        "mapa/en-mapa-test.jsonl",
        "eval/datasets/tab-echr/x.jsonl",
        "data/datasets/raw/dump.jsonl",
        "data/mining/pool.jsonl",
        "real/notes.jsonl",
        *{Path(p).name for ds in REGISTRY.values() if not ds.synthetic for p in ds.fixture_paths()},
    ],
)
def test_refuses_real_text_paths_even_when_marked_synthetic(
    sync: types.ModuleType, root: Path, no_network: None, rel: str
) -> None:
    _corpus(root, {"d/en-distill-train.jsonl": DOC, rel: DOC}, {"synthetic": True})
    with pytest.raises(sync.SyncRefused):
        sync.push("c1")


def test_registry_has_real_sets_for_the_name_check() -> None:
    assert any(not ds.synthetic for ds in REGISTRY.values())


def test_include_and_exclude(sync: types.ModuleType, root: Path) -> None:
    corpus = _corpus(
        root,
        {
            "court/en-distill-train.jsonl": DOC,
            "cache/ab/abc.json": "{}",
            "hf/third-party/x.jsonl": DOC,
            "court/stats.json": "{}",
            "court.log": "log",
        },
        {"synthetic": True, "include": ["court/*", "cache/*"], "exclude": ["*/stats.json"]},
    )
    assert sync.corpus_files(corpus) == [
        "cache/ab/abc.json",
        "court/en-distill-train.jsonl",
        "manifest.json",
    ]


def test_write_manifest_marks_synthetic_and_keeps_runs(sync: types.ModuleType, root: Path) -> None:
    corpus = root / "c2"
    sync.write_manifest(corpus, generated_by={"script": "a", "seed": 1})
    m = sync.write_manifest(corpus, generated_by={"script": "b", "seed": 2}, license="x")
    assert m["synthetic"] is True and m["corpus"] == "c2" and m["license"] == "x"
    assert [r["script"] for r in m["generated_by"]] == ["a", "b"]
    assert json.loads((corpus / "manifest.json").read_text(encoding="utf-8")) == m


def test_push_after_run_skips_outside_the_root_and_when_disabled(
    sync: types.ModuleType, root: Path, no_network: None, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("worktree") / "eval" / "generated" / "x"
    assert sync.push_after_run(outside, enabled=True, what="t") is None
    assert sync.push_after_run(root / "c1" / "d", enabled=False, what="t") is None
    # A corpus without a manifest is reported, not raised: the run's files are already written.
    _corpus(root, {"d/en-distill-train.jsonl": DOC}, None)
    assert sync.push_after_run(root / "c1" / "d", enabled=True, what="t") is None
