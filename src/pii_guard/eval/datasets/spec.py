"""What a dataset declares, and the generic fetch / check of a seeded sample.

A :class:`Dataset` names its source (URL, pinned revision, the files and their SHA-256), its
licence, languages and label mapping, and its **split policy**:

- ``test``: held out. Never used to write or tune rules, to train or select an NER model, or
  to pick a threshold. Every headline number comes from a ``test`` split.
- ``dev``: may be looked at and tuned on. Never reported as a headline.

``tests/eval/test_datasets_disjoint.py`` checks that no ``test`` document (by
:func:`~pii_guard.eval.datasets._common.text_sha256`) appears in a training or tuning input.

Rows are committed only when the licence allows redistribution **and** the text is synthetic
(``commit_rows``); otherwise only the manifest (sample ids and document hashes) is committed
and ``fetch`` rebuilds the fixture files in the git-ignored cache.
"""

from __future__ import annotations

import json
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pii_guard.eval.datasets._common import (
    CACHE_DIR,
    Converted,
    LabelMap,
    Row,
    convert,
    download,
    dump_json,
    sample,
    text_sha256,
)
from pii_guard.eval.fixtures import Document, write_fixtures

__all__ = ["DATASETS_DIR", "Dataset", "SourceFile", "Split", "build", "check", "fetch"]

Split = Literal["dev", "test"]

#: Committed manifests (and, where allowed, the sampled fixture files).
DATASETS_DIR = Path("eval/datasets")
#: Fixture files that may not be committed are rebuilt here.
LOCAL_FIXTURES_DIR = Path("data/datasets/fixtures")


@dataclass(frozen=True, slots=True)
class SourceFile:
    """One pinned source file: where it is in the source repository, its URL and SHA-256."""

    path: str
    url: str
    sha256: str


@dataclass(frozen=True, slots=True)
class Dataset:
    name: str
    title: str
    homepage: str
    revision: str
    license: str
    license_url: str
    attribution: str
    languages: tuple[str, ...]
    source_split: str
    split: Split
    synthetic: bool
    commit_rows: bool
    description: str
    files: tuple[SourceFile, ...] = ()
    sample: Mapping[str, int] = field(default_factory=dict)
    seed: int = 2026
    labels: LabelMap | None = None
    #: Source rows from the downloaded files (in ``files`` order).
    read: Callable[[Sequence[Path]], Iterable[Row]] | None = None
    notes: tuple[str, ...] = ()
    #: Fixture files that live elsewhere (the Ai4Privacy sample, the synthetic generator).
    external: tuple[str, ...] = ()
    #: A rebuild that isn't the generic one (the synthetic generator).
    builder: Callable[[], dict[str, list[Document]]] | None = None
    #: A manifest kept elsewhere (the Ai4Privacy sample's own).
    manifest_file: str | None = None
    #: A corrected-label variant: the set it is built from and its corrections file
    #: (:mod:`pii_guard.eval.datasets.corrections`, LAB-1497).
    derived_from: str | None = None
    corrections: str | None = None

    @property
    def kind(self) -> str:
        return f"public-{self.name}" if not self.external and self.builder is None else self.name

    @property
    def manifest_path(self) -> Path:
        if self.manifest_file:
            return Path(self.manifest_file)
        return DATASETS_DIR / self.name / "manifest.json"

    @property
    def fixtures_dir(self) -> Path:
        return (DATASETS_DIR if self.commit_rows else LOCAL_FIXTURES_DIR) / self.name

    def fixture_paths(self) -> list[Path]:
        """Where the fixture files are (committed or rebuilt by ``fetch``), one per language."""
        if self.external:
            return [Path(p) for p in self.external]
        return [self.fixtures_dir / f"{lang}-{self.name}.jsonl" for lang in self.languages]

    def to_document(self, row: Row) -> Converted:
        assert self.labels is not None  # noqa: S101 (generic datasets always have labels)
        return convert(row, self.labels, prefix=self.name, kind=self.kind, source=self.homepage)


def build(
    ds: Dataset, *, cache: Path = CACHE_DIR
) -> tuple[dict[str, list[Converted]], Counter[str]]:
    """Download (or reuse) the pinned files and draw the seeded sample."""
    if ds.read is None:
        raise ValueError(f"{ds.name}: not a downloadable dataset")
    paths = [download(f.url, f.sha256, cache / ds.name / Path(f.path).name) for f in ds.files]
    return sample(ds.read(paths), ds.sample, ds.seed, ds.to_document)


def manifest(
    ds: Dataset, chosen: Mapping[str, Sequence[Converted]], seen: Mapping[str, int]
) -> dict[str, Any]:
    languages: dict[str, Any] = {}
    for lang, items in chosen.items():
        gold: Counter[str] = Counter()
        dropped: Counter[str] = Counter()
        unknown: Counter[str] = Counter()
        for c in items:
            gold.update(s.entity_type.value for s in c.document.spans)
            dropped.update(c.dropped)
            unknown.update(c.unknown)
        languages[lang] = {
            "requested": ds.sample.get(lang),
            "documents": len(items),
            "rows_in_split": seen.get(f"rows_{lang}", 0),
            "skipped_unconvertible": seen.get(f"skipped_{lang}", 0),
            "gold_spans": dict(sorted(gold.items())),
            "policy_excluded": dict(sorted(dropped.items())),
            "unknown_labels": dict(sorted(unknown.items())),
            "uids": [c.document.meta["uid"] for c in items],
            "text_sha256": [text_sha256(c.document.text) for c in items],
        }
    return {
        "dataset": ds.name,
        "title": ds.title,
        "url": ds.homepage,
        "revision": ds.revision,
        "files": [{"path": f.path, "sha256": f.sha256} for f in ds.files],
        "license": ds.license,
        "license_url": ds.license_url,
        "attribution": ds.attribution,
        "synthetic": ds.synthetic,
        "rows_committed": ds.commit_rows,
        "source_split": ds.source_split,
        "split": ds.split,
        "seed": ds.seed,
        "sample_rule": "per language, rows ordered by sha256('<seed>:<uid>'), first n convertible",
        "label_mapping": ds.labels.table() if ds.labels else [],
        "merge_rule": "adjacent spans of one mapped type separated by <= 3 spaces/tabs/commas",
        "notes": list(ds.notes),
        "languages": languages,
    }


def fetch(ds: Dataset, *, cache: Path = CACHE_DIR, out: Path | None = None) -> list[Path]:
    """Build the sample and write its fixture files and manifest. Returns the paths written."""
    chosen, seen = build(ds, cache=cache)
    out_dir = out or ds.fixtures_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for lang, items in chosen.items():
        path = out_dir / f"{lang}-{ds.name}.jsonl"
        write_fixtures(path, [c.document for c in items])
        written.append(path)
    ds.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    ds.manifest_path.write_text(dump_json(manifest(ds, chosen, seen)), encoding="utf-8")
    written.append(ds.manifest_path)
    return written


def check(ds: Dataset, *, cache: Path = CACHE_DIR) -> list[str]:
    """Differences between a rebuild and the committed manifest (and committed rows)."""
    chosen, seen = build(ds, cache=cache)
    mine = manifest(ds, chosen, seen)
    try:
        committed = json.loads(ds.manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{ds.manifest_path}: unreadable ({exc.__class__.__name__})"]
    problems = [
        f"{ds.manifest_path}: {key!r} differs"
        for key in sorted(set(mine) | set(committed))
        if key != "languages" and mine.get(key) != committed.get(key)
    ]
    for lang in sorted(set(mine["languages"]) | set(committed.get("languages", {}))):
        a, b = mine["languages"].get(lang), committed.get("languages", {}).get(lang)
        if a is None or b is None:
            problems.append(f"{ds.manifest_path}: language {lang!r} is only on one side")
            continue
        problems.extend(
            f"{ds.manifest_path}: languages.{lang}.{key} differs"
            for key in sorted(set(a) | set(b))
            if a.get(key) != b.get(key)
        )
    if ds.commit_rows:
        with tempfile.TemporaryDirectory() as tmp:
            for lang, items in chosen.items():
                rebuilt = Path(tmp) / f"{lang}-{ds.name}.jsonl"
                write_fixtures(rebuilt, [c.document for c in items])
                path = ds.fixtures_dir / rebuilt.name
                if not path.is_file():
                    problems.append(f"{path}: missing")
                elif path.read_bytes() != rebuilt.read_bytes():
                    problems.append(f"{path}: differs from the rebuilt sample")
    return problems
