"""Where generated training data lives, and its backup on a private Hugging Face dataset (LAB-1542).

LLM-written corpora, their response caches and the Glimmer teacher labels cost model credits
and GPU hours, and a rerun with new completions gives a different corpus. They used to live in
a worktree's git-ignored ``eval/generated/`` and went with the worktree (LAB-1535). Now:

- **Data root.** ``PII_GUARD_DATA_DIR`` (default ``~/Develop/.worktrees/pii-guard/data-eu``),
  outside every worktree. A *corpus* is one top-level folder there (``phase1b``, ``v41``): the
  labelled files, the response cache and a ``manifest.json``. Training configs name files in it
  as ``data:<corpus>/<path>`` (:func:`resolve`); plain repo-relative paths such as
  ``eval/generated/...`` still work as before.
- **Backup.** ``push <corpus>`` uploads one corpus folder to the PRIVATE dataset
  ``watt-mind/pii-guard-ner-train`` as one commit and prints the revision; ``pull <corpus>
  --revision <sha>`` restores it into the data root. The generators push at the end of a
  successful run (``--no-push`` to skip).
- **Modal.** ``volume <corpus> --revision <sha>`` copies that revision to the Modal volume
  ``pii-guard-ner-runs`` under ``data/<corpus>@<rev>``, which ``modal_train.py --data`` mounts.

**Only synthetic data.** A push is refused unless the corpus ``manifest.json`` says
``"synthetic": true``, and every path goes through the LAB-1527 allowlist
(``training/distill/modal_upload.check_payload``: no MAPA, TAB, dataset downloads or mining
pools, LAB-1419) plus a file-name check against every real registry fixture::

    set -a; source .env; set +a   # HF_TOKEN with write access to the watt-mind org
    uv run --no-sync --with huggingface-hub python training/ner/data_sync.py push phase1b
    uv run --no-sync --with huggingface-hub python training/ner/data_sync.py pull phase1b \\
        --revision <sha>
    uv run --no-sync --with huggingface-hub --with modal python training/ner/data_sync.py \\
        volume phase1b --revision <sha>

The token is read by ``huggingface_hub`` from ``HF_TOKEN`` or the local login, never printed.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.append(str(_REPO_ROOT / "src"))  # pii_guard, when the venv has not installed it

DATA_DIR_ENV = "PII_GUARD_DATA_DIR"
DEFAULT_DATA_DIR = Path("~/Develop/.worktrees/pii-guard/data-eu")
REPO_ENV = "PII_GUARD_DATA_REPO"
DEFAULT_REPO = "watt-mind/pii-guard-ner-train"
VOLUME = "pii-guard-ner-runs"
MANIFEST = "manifest.json"
#: Config paths with this prefix are read from the data root (:func:`resolve`).
DATA_PREFIX = "data:"
#: Never uploaded, whatever the manifest includes.
ALWAYS_EXCLUDE = ("*.log", ".DS_Store", "*/.DS_Store", "*/__pycache__/*", ".cache/*")

__all__ = [
    "DATA_DIR_ENV",
    "SyncRefused",
    "corpus_files",
    "corpus_of",
    "data_root",
    "push",
    "resolve",
    "write_manifest",
]

#: The dataset card (``README.md`` of the dataset repo), pushed by ``data_sync.py card``.
CARD = Path(__file__).resolve().with_name("data-card.md")


class SyncRefused(ValueError):
    """A corpus that is not marked synthetic, or a path that could hold real text."""


def data_root() -> Path:
    """The stable local data root: ``$PII_GUARD_DATA_DIR`` or the default, outside worktrees."""
    return Path(os.environ.get(DATA_DIR_ENV) or DEFAULT_DATA_DIR).expanduser()


def resolve(path: str | Path) -> Path:
    """A config path: ``data:<corpus>/<file>`` is under the data root, anything else as given."""
    text = str(path)
    if text.startswith(DATA_PREFIX):
        return data_root() / text[len(DATA_PREFIX) :]
    return Path(text)


def corpus_of(path: Path) -> str | None:
    """The corpus (top-level data-root folder) ``path`` lies in, or ``None`` outside the root."""
    try:
        rel = path.expanduser().resolve().relative_to(data_root().resolve())
    except ValueError:
        return None
    return rel.parts[0] if rel.parts else None


def corpus_dir(corpus: str | Path) -> Path:
    """A corpus name under the data root, or an existing directory given as a path."""
    p = Path(corpus).expanduser()
    if p.is_absolute() or (p.is_dir() and len(p.parts) > 1):
        return p
    return data_root() / str(corpus)


def load_manifest(directory: Path) -> dict[str, Any]:
    path = directory / MANIFEST
    if not path.is_file():
        raise SyncRefused(f"{directory}: no {MANIFEST}; write one marking the data synthetic")
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return manifest


def write_manifest(directory: Path, **fields: Any) -> dict[str, Any]:
    """Create or update ``<corpus>/manifest.json`` (``synthetic: true``); returns it.

    ``generated_by`` entries accumulate (one per generator run), other fields are replaced.
    """
    path = directory / MANIFEST
    manifest: dict[str, Any] = (
        json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    )
    manifest.setdefault("corpus", directory.name)
    manifest["synthetic"] = True
    runs = manifest.setdefault("generated_by", [])
    run = fields.pop("generated_by", None)
    if run is not None and run not in runs:
        runs.append(run)
    manifest.update(fields)
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def _real_basenames() -> set[str]:
    from pii_guard.eval.datasets import REGISTRY

    return {
        PurePosixPath(p).name
        for ds in REGISTRY.values()
        if not ds.synthetic
        for p in ds.fixture_paths()
    }


def _check_payload(paths: list[str]) -> list[str]:
    sys.path.insert(0, str(_REPO_ROOT / "training" / "distill"))
    from modal_upload import check_payload

    return check_payload(paths)


def _matches(rel: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(rel, pat) for pat in patterns)


def corpus_files(directory: Path) -> list[str]:
    """The corpus-relative POSIX paths a push uploads; raises :class:`SyncRefused`.

    The manifest must say ``"synthetic": true``. ``include`` / ``exclude`` (glob lists, on
    the corpus-relative path) narrow the folder; ``manifest.json`` itself always goes.
    """
    manifest = load_manifest(directory)
    if manifest.get("synthetic") is not True:
        raise SyncRefused(f'{directory.name}: {MANIFEST} does not say "synthetic": true')
    include = manifest.get("include") or ["*"]
    exclude = [*ALWAYS_EXCLUDE, *manifest.get("exclude", [])]
    rels = sorted(p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file())
    picked = [
        r for r in rels if r == MANIFEST or (_matches(r, include) and not _matches(r, exclude))
    ]
    real = _real_basenames()
    for rel in picked:
        if PurePosixPath(rel).name in real:
            raise SyncRefused(f"{rel}: named like a real-text fixture (LAB-1419)")
    try:
        _check_payload([f"corpora/{directory.name}/{r}" for r in picked])
    except ValueError as exc:  # modal_upload.RealTextError
        raise SyncRefused(str(exc)) from exc
    return picked


def _api() -> Any:
    from huggingface_hub import HfApi

    return HfApi()  # HF_TOKEN or the local login; never handled here


def _repo() -> str:
    return os.environ.get(REPO_ENV) or DEFAULT_REPO


def ensure_private(api: Any, repo: str) -> None:
    api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
    if not api.dataset_info(repo).private:
        raise SyncRefused(f"{repo} is public; this data stays private for now")


def push(corpus: str | Path, *, repo: str | None = None, message: str | None = None) -> str:
    """Upload one corpus folder as one commit; returns the revision (commit sha)."""
    directory = corpus_dir(corpus)
    files = corpus_files(directory)  # refuses before anything leaves the machine
    from huggingface_hub import CommitOperationAdd

    repo = repo or _repo()
    api = _api()
    ensure_private(api, repo)
    ops = [
        CommitOperationAdd(path_in_repo=f"{directory.name}/{rel}", path_or_fileobj=directory / rel)
        for rel in files
    ]
    info = api.create_commit(
        repo_id=repo,
        repo_type="dataset",
        operations=ops,
        commit_message=message or f"{directory.name}: {len(files)} files",
    )
    return str(info.oid)


def pull(corpus: str, revision: str, *, repo: str | None = None, dest: Path | None = None) -> Path:
    """Download ``<corpus>/`` at ``revision`` into ``dest`` (the data root); returns its folder."""
    from huggingface_hub import snapshot_download

    dest = dest or data_root()
    snapshot_download(
        repo_id=repo or _repo(),
        repo_type="dataset",
        revision=revision,
        allow_patterns=[f"{corpus}/*"],
        local_dir=dest,
    )
    return dest / corpus


def push_card(*, repo: str | None = None) -> str:
    """Upload the dataset card (``README.md``); returns the revision."""
    repo = repo or _repo()
    api = _api()
    ensure_private(api, repo)
    info = api.upload_file(
        path_or_fileobj=CARD.read_bytes(),
        path_in_repo="README.md",
        repo_id=repo,
        repo_type="dataset",
        commit_message="Dataset card: synthetic data only, sources and licenses, private",
    )
    return str(getattr(info, "oid", info))


def volume_path(corpus: str, revision: str) -> str:
    return f"data/{corpus}@{revision}"


def to_volume(corpus: str, revision: str, *, repo: str | None = None) -> str:
    """Copy ``<corpus>`` at ``revision`` to the Modal volume; returns the volume path."""
    target = volume_path(corpus, revision)
    with tempfile.TemporaryDirectory() as tmp:
        local = pull(corpus, revision, repo=repo, dest=Path(tmp))
        subprocess.run(  # noqa: S603 - fixed argument list
            ["modal", "volume", "put", VOLUME, str(local), f"/{target}"],  # noqa: S607
            check=True,
        )
    return target


def push_after_run(path: Path, *, enabled: bool, what: str) -> str | None:
    """The generators' end-of-run push: the corpus ``path`` lies in, unless disabled."""
    if not enabled:
        return None
    corpus = corpus_of(path)
    if corpus is None:
        print(
            f"{what}: {path} is outside the data root ({data_root()}); not pushed "
            "(data_sync.py push <dir> to back it up)",
            file=sys.stderr,
        )
        return None
    try:
        rev = push(corpus, message=f"{corpus}: {what}")
    except SyncRefused as exc:
        print(f"{what}: not pushed: {exc}", file=sys.stderr)
        return None
    print(f"{what}: pushed {corpus} to {_repo()} at revision {rev}", file=sys.stderr)
    return rev


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_push = sub.add_parser("push", help="upload one corpus folder as one commit")
    p_push.add_argument("corpus", help="a folder name under the data root, or a path")
    p_push.add_argument("--message")
    p_pull = sub.add_parser("pull", help="restore a corpus at a revision into the data root")
    p_pull.add_argument("corpus")
    p_pull.add_argument("--revision", required=True)
    p_pull.add_argument("--dest", type=Path, help="default: the data root")
    p_vol = sub.add_parser("volume", help=f"copy a corpus revision to Modal volume {VOLUME}")
    p_vol.add_argument("corpus")
    p_vol.add_argument("--revision", required=True)
    sub.add_parser("card", help="upload the dataset card (README.md)")
    sub.add_parser("check", help="list what a push would upload, upload nothing").add_argument(
        "corpus"
    )
    args = parser.parse_args(argv)
    try:
        if args.cmd == "push":
            print(push(args.corpus, message=args.message))
        elif args.cmd == "pull":
            print(pull(args.corpus, args.revision, dest=args.dest))
        elif args.cmd == "card":
            print(push_card())
        elif args.cmd == "volume":
            print(to_volume(args.corpus, args.revision))
        else:
            files = corpus_files(corpus_dir(args.corpus))
            print(f"{len(files)} files would be pushed", file=sys.stderr)
            print("\n".join(files))
    except SyncRefused as exc:
        print(f"data_sync: refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
