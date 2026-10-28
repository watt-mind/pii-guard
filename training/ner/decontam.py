"""Decontamination gate: drop training documents that are near-copies of any evaluation text.

Exact-uid and exact-hash filtering (``openpii.py``, ``tests/eval/test_datasets_disjoint.py``)
miss what synthetic generators produce most: the same template with a few values swapped, or a
later release of a dataset that "extends" an earlier one. This gate compares every training
document with **every** evaluation text pii-guard reports on (LAB-1392):

- every ``test`` set of the dataset registry (``pii_guard.eval.datasets``): Ai4Privacy OpenPII
  validation, Nemotron-PII test, Gretel finance test, CEE-PII-Bench, TAB, agent traffic,
  pl-pii-bench and MAPA EUR-Lex. Fetch-only sets (TAB, MAPA) are compared by text when their
  fixture files have been rebuilt locally, and by their manifest's document hashes always;
- every fixture file under ``eval/fixtures/`` (the smoke sets, inflection, injection, brand
  names, uncued numbers, known values, secrets), which the rules are tuned against.

**Method.** Text is NFKC-normalised, case-folded and split into word tokens; a document's
shingles are its word 5-grams (a document shorter than five words is one shingle). A 128-hash
MinHash signature per document goes into an LSH index of 32 bands of 4 rows, which finds every
pair with Jaccard similarity 0.8 with probability above 0.999. Each candidate pair is then
checked with the exact Jaccard similarity of the two shingle sets, so the threshold is exact:
a training document is dropped when it shares a SHA-256 of its whitespace-folded text with an
evaluation document or its Jaccard similarity to one is at least :data:`THRESHOLD`. The
signatures use NumPy when it is installed (it comes with the ``ner`` extra) and pure Python
otherwise; both give the same bits.

``train.py`` runs the gate on its train and dev files by default (``decontam = false`` in a
config, or ``--no-decontam``, turns it off) and records the counts in ``training_meta.json``.
On its own it reports, and with ``--out`` writes the cleaned files::

    uv run --no-sync python training/ner/decontam.py --config training/ner/v2-base-hn.toml
    uv run --no-sync python training/ner/decontam.py eval/generated/x/hu-x-train.jsonl --json r.json

Reports carry document ids, set names, counts and similarities; never text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import tomllib
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pii_guard.eval.datasets import test_datasets
from pii_guard.eval.datasets._common import text_sha256
from pii_guard.eval.fixtures import Document, FixtureError, load_fixtures

__all__ = [
    "BANDS",
    "NGRAM",
    "NUM_PERM",
    "THRESHOLD",
    "EvalIndex",
    "Match",
    "Report",
    "eval_corpus",
    "gate",
    "jaccard",
    "load_training_docs",
    "shingles",
    "signature",
]

NGRAM = 5
THRESHOLD = 0.8
NUM_PERM = 128
BANDS = 32
ROWS = NUM_PERM // BANDS
_MASK = (1 << 64) - 1
_SEED = 1392
_rng = random.Random(_SEED)  # noqa: S311 (fixed hash parameters, not a secret)
#: The MinHash family: h_i(x) = (a_i * x + b_i) mod 2^64, a_i odd.
_A = [_rng.getrandbits(64) | 1 for _ in range(NUM_PERM)]
_B = [_rng.getrandbits(64) for _ in range(NUM_PERM)]
_WORD = re.compile(r"\w+")
#: Fixture files under eval/fixtures that are not documents of a scored set.
_FIXTURE_ROOT = Path("eval/fixtures")


def tokens(text: str) -> list[str]:
    return _WORD.findall(unicodedata.normalize("NFKC", text).casefold())


def _h64(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big")


def shingles(text: str, n: int = NGRAM) -> frozenset[int]:
    """The 64-bit hashes of the word ``n``-grams of ``text`` (one shingle if it is shorter)."""
    words = tokens(text)
    if not words:
        return frozenset()
    if len(words) <= n:
        return frozenset({_h64(" ".join(words))})
    return frozenset(_h64(" ".join(words[i : i + n])) for i in range(len(words) - n + 1))


def jaccard(a: frozenset[int], b: frozenset[int]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


try:  # NumPy is in the `ner` extra; the gate works without it, only slower.
    import numpy as _np

    _NA = _np.array(_A, dtype=_np.uint64)[:, None]
    _NB = _np.array(_B, dtype=_np.uint64)[:, None]
except ImportError:  # pragma: no cover - CI has no ner extra; exercised by the parity test
    _np = None  # type: ignore[assignment]


def _signature_py(sh: Iterable[int]) -> tuple[int, ...]:
    xs = list(sh)
    return tuple(min((a * x + b) & _MASK for x in xs) for a, b in zip(_A, _B, strict=True))


def _signature_np(sh: Iterable[int]) -> tuple[int, ...]:
    assert _np is not None  # noqa: S101
    xs = _np.fromiter(sh, dtype=_np.uint64)
    out: list[int] = []
    for start in range(0, len(xs), 4096):  # bounded memory on 70,000-character documents
        chunk = (_NA * xs[None, start : start + 4096] + _NB).min(axis=1)
        part = chunk.tolist()
        out = part if not out else [min(p, q) for p, q in zip(out, part, strict=True)]
    return tuple(int(v) for v in out)


def signature(sh: frozenset[int]) -> tuple[int, ...]:
    """The MinHash signature of a non-empty shingle set (:data:`NUM_PERM` values)."""
    if _np is not None and len(sh) > 8:
        return _signature_np(sh)
    return _signature_py(sh)


def _bands(sig: Sequence[int]) -> list[tuple[int, tuple[int, ...]]]:
    return [(i, tuple(sig[i * ROWS : (i + 1) * ROWS])) for i in range(BANDS)]


@dataclass(frozen=True, slots=True)
class Match:
    """A training document that duplicates an evaluation document. No text."""

    train_id: str
    eval_set: str
    eval_id: str
    jaccard: float
    exact: bool


@dataclass
class EvalIndex:
    """Every evaluation text, as hashes and an LSH index over MinHash signatures."""

    threshold: float = THRESHOLD
    hashes: dict[str, tuple[str, str]] = field(default_factory=dict)
    sets: list[tuple[str, str, frozenset[int]]] = field(default_factory=list)
    buckets: dict[tuple[int, tuple[int, ...]], list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    sources: Counter[str] = field(default_factory=Counter)
    missing: list[str] = field(default_factory=list)

    def add_hash(self, digest: str, eval_set: str, eval_id: str) -> None:
        self.hashes.setdefault(digest, (eval_set, eval_id))

    def add(self, eval_set: str, doc: Document) -> None:
        self.add_hash(text_sha256(doc.text), eval_set, doc.id)
        sh = shingles(doc.text)
        self.sources[eval_set] += 1
        if not sh:
            return
        index = len(self.sets)
        self.sets.append((eval_set, doc.id, sh))
        for key in _bands(signature(sh)):
            self.buckets[key].append(index)

    def __len__(self) -> int:
        return len(self.hashes)

    def match(self, doc: Document) -> Match | None:
        hit = self.hashes.get(text_sha256(doc.text))
        if hit is not None:
            return Match(doc.id, hit[0], hit[1], 1.0, True)
        sh = shingles(doc.text)
        if not sh:
            return None
        candidates: set[int] = set()
        for key in _bands(signature(sh)):
            candidates.update(self.buckets.get(key, ()))
        best: Match | None = None
        for i in sorted(candidates):
            eval_set, eval_id, other = self.sets[i]
            # J <= min size / max size: skip pairs whose sizes alone rule them out.
            if min(len(sh), len(other)) < self.threshold * max(len(sh), len(other)):
                continue
            j = jaccard(sh, other)
            if j >= self.threshold and (best is None or j > best.jaccard):
                best = Match(doc.id, eval_set, eval_id, round(j, 4), False)
        return best


def _fixture_set_name(path: Path) -> str:
    stem = path.stem
    lang, _, rest = stem.partition("-")
    return f"fixtures/{rest or stem}" if len(lang) == 2 else f"fixtures/{stem}"


def eval_corpus(root: Path = Path(), *, threshold: float = THRESHOLD) -> EvalIndex:
    """Index every evaluation text reachable from ``root`` (the repository root)."""
    index = EvalIndex(threshold=threshold)
    seen: set[Path] = set()
    for ds in test_datasets():
        manifest_path = root / ds.manifest_path
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for block in manifest.get("languages", {}).values():
                for uid, digest in zip(
                    block.get("uids", []), block.get("text_sha256", []), strict=False
                ):
                    index.add_hash(digest, ds.name, f"{ds.name}-{uid}")
        else:
            index.missing.append(str(ds.manifest_path))
        for path in ds.fixture_paths():
            full = root / path
            if not full.is_file():
                index.missing.append(str(path))
                continue
            seen.add(full.resolve())
            for doc in load_fixtures([full]):
                index.add(ds.name, doc)
    for full in sorted((root / _FIXTURE_ROOT).rglob("*.jsonl")):
        if full.resolve() in seen:
            continue
        try:
            docs = load_fixtures([full])
        except FixtureError:  # not a document fixture
            continue
        name = _fixture_set_name(full)
        for doc in docs:
            index.add(name, doc)
    return index


@dataclass
class Report:
    """What the gate dropped, per input file and per evaluation set. Ids and counts only."""

    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    matches: list[Match] = field(default_factory=list)

    def add(self, name: str, kept: int, dropped: Sequence[Match]) -> None:
        self.files[name] = {
            "documents": kept + len(dropped),
            "kept": kept,
            "dropped_exact": sum(m.exact for m in dropped),
            "dropped_near": sum(not m.exact for m in dropped),
            "by_eval_set": dict(sorted(Counter(m.eval_set for m in dropped).items())),
        }
        self.matches.extend(dropped)

    @property
    def dropped(self) -> int:
        return len(self.matches)

    def to_dict(self, *, index: EvalIndex | None = None, examples: int = 20) -> dict[str, Any]:
        out: dict[str, Any] = {
            "method": {
                "shingles": f"word {NGRAM}-grams of NFKC case-folded text",
                "minhash": f"{NUM_PERM} hashes, LSH {BANDS} bands x {ROWS} rows",
                "threshold": f"exact Jaccard >= {index.threshold if index else THRESHOLD}",
                "exact": "SHA-256 of the whitespace-folded text",
            },
            "documents": sum(f["documents"] for f in self.files.values()),
            "dropped": self.dropped,
            "dropped_exact": sum(m.exact for m in self.matches),
            "dropped_near": sum(not m.exact for m in self.matches),
            "by_eval_set": dict(sorted(Counter(m.eval_set for m in self.matches).items())),
            "files": self.files,
            "examples": [
                {
                    "train_id": m.train_id,
                    "eval_set": m.eval_set,
                    "eval_id": m.eval_id,
                    "jaccard": m.jaccard,
                }
                for m in sorted(self.matches, key=lambda m: (m.eval_set, m.train_id))[:examples]
            ],
        }
        if index is not None:
            out["eval_index"] = {
                "documents_by_set": dict(sorted(index.sources.items())),
                "hashes": len(index.hashes),
                "missing": index.missing,
            }
        return out


def gate(
    docs: Sequence[Document], index: EvalIndex, *, name: str, report: Report
) -> list[Document]:
    """``docs`` without the ones that duplicate an evaluation text; counts go to ``report``."""
    kept: list[Document] = []
    dropped: list[Match] = []
    for doc in docs:
        m = index.match(doc)
        if m is None:
            kept.append(doc)
        else:
            dropped.append(m)
    report.add(name, len(kept), dropped)
    return kept


def load_training_docs(
    paths: Sequence[Path], index: EvalIndex | None, report: Report
) -> list[Document]:
    """Load ``paths`` and, unless ``index`` is ``None``, drop evaluation duplicates.

    ``train.py`` loads its train and dev files through this, so the gate runs by default.
    Fails closed: an index with no evaluation text (run from the wrong directory, say) is
    refused rather than silently letting everything through.
    """
    if index is not None and not index.sets:
        raise RuntimeError(
            "decontam: no evaluation text found (run from the repository root, or turn the "
            "gate off explicitly with --no-decontam)"
        )
    out: list[Document] = []
    for path in paths:
        docs = load_fixtures([path])
        out.extend(docs if index is None else gate(docs, index, name=str(path), report=report))
    return out


def summary_line(report: Report) -> str:
    by_set = ", ".join(f"{k} {v}" for k, v in report.to_dict()["by_eval_set"].items())
    total = sum(f["documents"] for f in report.files.values())
    return f"decontam: dropped {report.dropped} of {total} documents" + (
        f" ({by_set})" if by_set else ""
    )


def _paths_from(config: Path, include_dev: bool) -> list[Path]:
    cfg = tomllib.loads(config.read_text(encoding="utf-8"))
    return [Path(p) for p in [*cfg.get("train", []), *(cfg.get("dev", []) if include_dev else [])]]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="*", type=Path, help="training JSONL files")
    parser.add_argument("--config", type=Path, help="a train.py TOML: check its train+dev files")
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    parser.add_argument("--json", type=Path, help="write the report here")
    parser.add_argument("--out", type=Path, help="write the cleaned files into this directory")
    parser.add_argument(
        "--allow-missing", action="store_true", help="skip input files that don't exist"
    )
    args = parser.parse_args(argv)
    paths = list(args.files)
    if args.config:
        paths += _paths_from(args.config, include_dev=True)
    if not paths:
        parser.error("name training files or --config")
    index = eval_corpus(threshold=args.threshold)
    report = Report()
    absent = []
    for path in paths:
        if not path.is_file():
            if args.allow_missing:
                absent.append(str(path))
                continue
            parser.error(f"{path}: not found (use --allow-missing to skip it)")
        kept = gate(load_fixtures([path]), index, name=str(path), report=report)
        if args.out:
            from pii_guard.eval.fixtures import write_fixtures

            args.out.mkdir(parents=True, exist_ok=True)
            write_fixtures(args.out / path.name, kept)
    data = report.to_dict(index=index)
    data["absent_inputs"] = absent
    for name, f in report.files.items():
        print(
            f"{name}: {f['documents']} docs, dropped {f['dropped_exact']} exact + "
            f"{f['dropped_near']} near {f['by_eval_set'] or ''}",
            file=sys.stderr,
        )
    print(summary_line(report), file=sys.stderr)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
