"""What the Modal NER training image may carry from ``eval/`` and ``data/`` (LAB-1527).

An allowlist, not a directory upload. ``modal_train.py`` used to add ``eval/datasets`` and
``data/datasets/fixtures`` wholesale, so whatever a worktree held there (the rebuilt MAPA
EUR-Lex fixtures, for one) went to Modal with the image. Policy LAB-1419: MAPA and TAB court
text, and any other real text, never leaves the machine.

The image gets exactly what the decontamination gate (``training/ner/decontam.py``, LAB-1392)
reads, minus real text:

- the fixture files of every registry set marked ``synthetic`` (wherever they live, so the
  rebuilt ``gretel-finance-corrected`` under ``data/datasets/fixtures`` still goes);
- every registry manifest, real sets included: a manifest holds uids and SHA-256 hashes of the
  texts, never the texts;
- every ``*.jsonl`` under ``eval/fixtures/`` except ``visual/`` (committed, synthetic only).

**How the gate handles the real sets on Modal.** Their fixture files are absent there, so
``eval_corpus`` lists them under ``missing`` and compares training documents with them by the
manifest's exact text hashes only, not by near-duplicate (Jaccard) text. That is the gate's
documented fetch-only behaviour and the simplest correct option: the training corpora are
generated, fictional text, so a near-copy of a court judgment can only get in by an exact
copy, which the hashes catch. To check near-duplicates against MAPA/TAB too, run the gate
locally first (``uv run --no-sync python training/ner/decontam.py --config <toml>``).

Pure and Modal-free so the test can call it (``tests/training/test_modal_upload.py``).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from pii_guard.eval.datasets import REGISTRY

__all__ = ["REAL_TEXT_MARKERS", "RealTextError", "check_payload", "eval_upload_files"]

#: Path fragments that mark real (non-synthetic) text. Belt and braces on top of the registry's
#: ``synthetic`` flag: any path containing one is refused unless it is a registry manifest.
REAL_TEXT_MARKERS: tuple[str, ...] = (
    "mapa",
    "tab-echr",
    "data/datasets/raw",  # dataset downloads
    "data/mining",  # error-mining pools (MAPA validation split, LAB-1512)
    "real-data",
    "/real/",
    "/private/",
)
_FIXTURES = Path("eval/fixtures")
_FIXTURES_SKIP = ("visual",)


class RealTextError(ValueError):
    """A path that could hold real text was about to be sent to Modal."""


def _manifests() -> set[str]:
    return {PurePosixPath(ds.manifest_path).as_posix() for ds in REGISTRY.values()}


def _real_fixture_paths() -> set[str]:
    return {
        PurePosixPath(p).as_posix()
        for ds in REGISTRY.values()
        if not ds.synthetic
        for p in ds.fixture_paths()
    }


def check_payload(paths: Iterable[str | Path]) -> list[str]:
    """``paths`` (repo-relative) as POSIX strings; raises :class:`RealTextError` on real text."""
    manifests, real = _manifests(), _real_fixture_paths()
    out: list[str] = []
    for p in paths:
        rel = PurePosixPath(Path(p)).as_posix()
        if rel.startswith("/") or ".." in PurePosixPath(rel).parts:
            raise RealTextError(f"{rel}: not a repository-relative path")
        if rel in manifests:  # hashes and counts, no text
            out.append(rel)
            continue
        probe = f"/{rel.lower()}"
        if rel in real or any(m in probe for m in REAL_TEXT_MARKERS):
            raise RealTextError(f"{rel}: real text must not leave the machine (LAB-1419)")
        out.append(rel)
    return out


def eval_upload_files(root: Path) -> list[str]:
    """The repo-relative evaluation files the Modal image carries, given the repo ``root``.

    Only files that exist under ``root`` are listed; the result has passed :func:`check_payload`.
    """
    wanted: set[str] = set()
    for ds in REGISTRY.values():
        wanted.add(PurePosixPath(ds.manifest_path).as_posix())
        if ds.synthetic:
            wanted.update(PurePosixPath(p).as_posix() for p in ds.fixture_paths())
    fixtures = root / _FIXTURES
    if fixtures.is_dir():
        for full in fixtures.rglob("*.jsonl"):
            rel = full.relative_to(root)
            if rel.relative_to(_FIXTURES).parts[0] in _FIXTURES_SKIP:
                continue
            wanted.add(rel.as_posix())
    present = sorted(rel for rel in wanted if (root / rel).is_file())
    return check_payload(present)
