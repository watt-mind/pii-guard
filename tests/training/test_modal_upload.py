"""The Modal training image never carries real text (LAB-1527, policy LAB-1419)."""

from __future__ import annotations

import re
import types
from pathlib import Path

import pytest

from pii_guard.eval.datasets import REGISTRY

from .conftest import ROOT, load_script

REAL = [ds for ds in REGISTRY.values() if not ds.synthetic]
SYNTHETIC = [ds for ds in REGISTRY.values() if ds.synthetic]


@pytest.fixture(scope="module")
def upload() -> types.ModuleType:
    return load_script("training/distill/modal_upload.py", "modal_upload")


def _touch(root: Path, rel: str | Path, text: str = '{"id": "x", "text": "t", "spans": []}\n'):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _assert_no_real_text(files: list[str]) -> None:
    manifests = {Path(ds.manifest_path).as_posix() for ds in REGISTRY.values()}
    real = {Path(p).as_posix() for ds in REAL for p in ds.fixture_paths()}
    for rel in files:
        assert rel not in real, rel
        if rel not in manifests:
            assert not re.search(r"mapa|tab-echr|data/datasets/raw|data/mining", rel), rel


def test_registry_still_has_the_real_sets() -> None:
    # If MAPA or TAB were relabelled synthetic, the allowlist would start shipping them.
    assert {"mapa-eur-lex", "tab-echr"} <= {ds.name for ds in REAL}


def test_real_text_is_never_listed_even_when_present(upload, tmp_path: Path) -> None:
    for ds in REAL:  # rebuilt fetch-only fixtures, as in the LAB-1512 worktree
        for p in ds.fixture_paths():
            _touch(tmp_path, p)
        _touch(tmp_path, ds.manifest_path, "{}")
        _touch(tmp_path, Path(ds.manifest_path).parent / "stray.jsonl")
    for ds in SYNTHETIC:
        for p in ds.fixture_paths():
            _touch(tmp_path, p)
    _touch(tmp_path, "data/datasets/raw/mapa/en.jsonl")
    _touch(tmp_path, "data/mining/raw/mapa-validation.jsonl")
    _touch(tmp_path, "eval/fixtures/en-smoke.jsonl")
    _touch(tmp_path, "eval/fixtures/visual/en-visual.jsonl")

    files = upload.eval_upload_files(tmp_path)
    _assert_no_real_text(files)
    # The gate keeps every synthetic text (wherever it lives) and every manifest (hashes only).
    for ds in SYNTHETIC:
        assert {Path(p).as_posix() for p in ds.fixture_paths()} <= set(files), ds.name
    assert {Path(ds.manifest_path).as_posix() for ds in REAL} <= set(files)
    assert "eval/fixtures/en-smoke.jsonl" in files
    assert "eval/fixtures/visual/en-visual.jsonl" not in files
    assert not any(f.startswith("data/") and "gretel-finance-corrected" not in f for f in files)


def test_real_text_is_never_listed_from_this_checkout(upload) -> None:
    _assert_no_real_text(upload.eval_upload_files(ROOT))


@pytest.mark.parametrize(
    "path",
    [
        "data/datasets/fixtures/mapa-eur-lex/en-mapa-eur-lex.jsonl",
        "data/datasets/fixtures/tab-echr/en-tab-echr.jsonl",
        "eval/datasets/mapa-eur-lex/en.jsonl",
        "data/datasets/raw/tab/echr.json",
        "data/mining/raw/mapa-validation.jsonl",
        "eval/generated/real-data/x.jsonl",
        "../outside.jsonl",
    ],
)
def test_check_payload_refuses_real_text(upload, path: str) -> None:
    with pytest.raises(upload.RealTextError):
        upload.check_payload([path])


def test_check_payload_passes_generated_training_files(upload) -> None:
    ok = [
        "eval/generated/v33-replay/openpii/en-train.jsonl",
        "eval/datasets/tab-echr/manifest.json",
    ]
    assert upload.check_payload(ok) == ok


def test_modal_train_uploads_no_eval_or_data_directory() -> None:
    source = (ROOT / "training/distill/modal_train.py").read_text(encoding="utf-8")
    for call in re.findall(r"add_local_dir\(([^)]*)\)", source):
        assert '"eval"' not in call and '"data"' not in call, call
    assert "eval_upload_files(ROOT)" in source and "check_payload(" in source
