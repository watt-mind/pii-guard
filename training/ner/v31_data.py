"""The NER v3.1 mixes (LAB-1410): the v3 mix without the agent-traffic generator split.

Fictional / synthetic data only (ADR 0005). v3 (LAB-1393) trained on 1,800 documents from the
agent-traffic generator (a seed of its own, the same templates), so agent-traffic-dev stopped
being an unseen selection set. Every v3.1 mix leaves that split out entirely; the configs
``training/ner/v31-{a,b,c}.toml`` name the files and ``tests/training/test_v31_data.py``
asserts that none of them is a generator-family file.

The three candidates (fixed in the ticket before any scoring):

- **A**: the v3 mix minus the agent-traffic split: the selection fix on its own.
- **B**: A with more Hungarian and agent-style gold and less Privy: OpenPII hu 10,000 rows
  (twice v3's 5,000; the seeded order makes them a superset of v3's rows, **new** rows, not
  repeats), the s11 distillation train files oversampled x1.5 (every document once, plus a
  seeded half of them a second time) and Privy halved to 6,000 (the first 6,000 of v3's
  seeded order, so the same rows the sampler would pick for 6,000, teacher regions included).
- **C**: B without Wismut.

Steps::

    modal run training/ner/modal_v3.py --profile v31          # prepare(): download + convert,
                                                              # then the Horizon teacher audit
    modal volume get pii-guard-ner-runs v31-data <raw>
    uv run --no-sync python training/ner/v31_data.py derive --raw <raw> \\
        --json eval/results/<date>-ner-v31/decontam-gate.json
    uv run --no-sync python training/ner/v31_data.py manifest   # token shares per candidate

``derive`` writes ``eval/generated/v31-final`` (git-ignored) through the decontamination gate
(``decontam.py``); ``train.py`` runs the gate again when it loads them. Rows are never
committed; ``training/ner/v31-data-manifest.json`` records counts and id hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import Document, load_fixtures, write_fixtures

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decontam
import v3_data

SEED = 1410
RAW = Path("eval/generated/v31-raw")
FINAL = Path("eval/generated/v31-final")
RAW_MANIFEST = Path("training/ner/v31-raw-data-manifest.json")
OPENPII_MANIFEST = Path("training/ner/v31-openpii-train-manifest.json")
MANIFEST = Path("training/ner/v31-data-manifest.json")
CANDIDATES = ("a", "b", "c")
CONFIGS = {c: Path(f"training/ner/v31-{c}.toml") for c in CANDIDATES}

#: v3's OpenPII sample with twice the Hungarian train rows (candidates B and C).
OPENPII_TRAIN = {**v3_data.OPENPII_TRAIN, "hu": 10_000}
#: v3's Hungarian OpenPII train rows, the first of the seeded order (candidate A).
OPENPII_HU_V3 = v3_data.OPENPII_TRAIN["hu"]
PRIVY_HALF = 6_000
S11_FACTOR = 1.5
#: Every v3 source except ``agent`` (the agent-traffic generator split).
SOURCES = ("openpii", "privy", "wismut", "nemotron", "gretel", "s11", "negatives")
#: Path fragments of the generator family that must never be in a v3.1 train file.
GENERATOR_MARKERS = ("agent-traffic",)


def prepare(
    cache: Path,
    out: Path = RAW,
    *,
    only: Sequence[str] | None = None,
    tokenizer_name: str | None = None,
) -> dict[str, Any]:
    """Download, convert and sample the v3.1 sources (``v3_data.build`` without ``agent``)."""
    chosen = [s for s in (only or SOURCES) if s in SOURCES]
    return v3_data.build(
        cache,
        out,
        only=chosen,
        tokenizer_name=tokenizer_name,
        openpii_train=OPENPII_TRAIN,
        openpii_manifest=OPENPII_MANIFEST,
        ticket="LAB-1410",
    )


# --- derived files -----------------------------------------------------------------------


def ids_sha(docs: Sequence[Document]) -> str:
    return hashlib.sha256("\n".join(sorted(d.id for d in docs)).encode()).hexdigest()


def head(docs: Sequence[Document], n: int) -> list[Document]:
    """The first ``n`` documents: the files are written in the sampler's seeded order."""
    if n > len(docs):
        raise ValueError(f"asked for {n} documents, the file has {len(docs)}")
    return list(docs[:n])


def oversample(docs: Sequence[Document], factor: float, seed: int = SEED) -> list[Document]:
    """Every document once, then a seeded ``factor - 1`` share of them again (``~rep`` ids)."""
    if factor < 1:
        raise ValueError("factor must be at least 1")
    whole, part = int(factor), factor - int(factor)
    out = list(docs)
    for r in range(1, whole):
        out.extend(_copy(d, r) for d in docs)
    rng = random.Random(seed)  # noqa: S311 - a reproducible sample, not a secret
    extra = rng.sample(range(len(docs)), round(part * len(docs)))
    out.extend(_copy(docs[i], whole) for i in sorted(extra))
    return out


def _copy(doc: Document, r: int) -> Document:
    return Document(f"{doc.id}~rep{r}", doc.language, doc.text, doc.spans, dict(doc.meta))


def is_generator_file(path: str | Path) -> bool:
    return any(m in str(path) for m in GENERATOR_MARKERS)


def derive(
    raw: Path,
    out: Path = FINAL,
    *,
    s11: Path = Path("eval/generated/distill-s11/labelled"),
    index: decontam.EvalIndex | None = None,
) -> dict[str, Any]:
    """Assemble ``out`` from the fetched ``v31-data`` volume dir, through the decontam gate.

    ``raw`` holds ``eval/generated/v31-raw/<source>/*.jsonl`` and ``audited/*.jsonl`` (the
    teacher-audited Privy, Wismut, Nemotron and Gretel train files). Returns the gate report.
    """
    built = raw / RAW
    audited = raw / "audited"
    files: dict[Path, list[Document]] = {}

    for p in sorted((built / "openpii").glob("*-openpii-*.jsonl")):
        files[out / "openpii" / p.name] = load_fixtures([p])
    hu = files.pop(out / "openpii" / "hu-openpii-train.jsonl")
    files[out / "openpii" / "hu-openpii-train-10k.jsonl"] = hu
    files[out / "openpii" / "hu-openpii-train.jsonl"] = head(hu, OPENPII_HU_V3)

    for name in ("privy", "wismut", "nemotron", "gretel"):
        for p in sorted((built / name).glob("*-train.jsonl")):
            files[out / name / p.name] = load_fixtures([audited / p.name])
    privy = files[out / "privy" / "en-privy-train.jsonl"]
    files[out / "privy" / "en-privy-train-6k.jsonl"] = head(privy, PRIVY_HALF)

    for p in sorted((built / "negatives").glob("*-negatives-train.jsonl")):
        files[out / "negatives" / p.name] = load_fixtures([p])

    for p in sorted(s11.glob("*-distill-*.jsonl")):
        docs = load_fixtures([p])
        files[out / "s11" / p.name] = docs
        if p.name.endswith("-train.jsonl"):
            name = p.name.replace("-train.jsonl", "-train-x1.5.jsonl")
            files[out / "s11" / name] = oversample(docs, S11_FACTOR)

    index = index if index is not None else decontam.eval_corpus()
    report = decontam.Report()
    if out.exists():
        shutil.rmtree(out)
    for path, docs in sorted(files.items()):
        if is_generator_file(path):
            raise RuntimeError(f"{path}: a generator-family file in the v3.1 mix")
        kept = decontam.gate(docs, index, name=str(path), report=report)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_fixtures(path, kept)
    return report.to_dict(index=index)


# --- configs and manifest ----------------------------------------------------------------


def config_paths(config: Path) -> dict[str, list[str]]:
    cfg = tomllib.loads(config.read_text(encoding="utf-8"))
    return {"train": list(cfg["train"]), "dev": list(cfg["dev"])}


def source_of(path: str) -> str:
    return Path(path).parent.name


def manifest(tokenizer_name: str | None = "FacebookAI/xlm-roberta-base") -> dict[str, Any]:
    """Per candidate: every train file with its counts, and the token share per source."""
    tokenizer = None
    if tokenizer_name:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
    blocks: dict[str, dict[str, Any]] = {}
    out: dict[str, Any] = {
        "ticket": "LAB-1410",
        "rows_committed": False,
        "raw_manifest": str(RAW_MANIFEST),
        "openpii_manifest": str(OPENPII_MANIFEST),
        "tokenizer": tokenizer_name,
        "derivations": {
            "openpii/hu-openpii-train.jsonl": f"first {OPENPII_HU_V3} rows of the 10k file (v3's)",
            "openpii/hu-openpii-train-10k.jsonl": "OpenPII hu train, 10,000 rows, seed 1393",
            "privy/en-privy-train-6k.jsonl": f"first {PRIVY_HALF} rows of the audited 12k file",
            "s11/*-distill-train-x1.5.jsonl": (
                f"every s11 train document once plus a seeded half again (seed {SEED})"
            ),
        },
        "excluded": {
            "agent-traffic generator (seed 1393)": (
                "left out of every v3.1 mix so agent-traffic-dev is an unseen selection set"
            ),
            **v3_data.build.__globals__.get("_EXCLUDED_NOTE", {}),
        },
        "files": blocks,
        "candidates": {},
    }
    for c, config in CONFIGS.items():
        paths = config_paths(config)
        shares: dict[str, int] = {}
        docs_by: dict[str, int] = {}
        for rel in paths["train"] + paths["dev"]:
            if rel not in blocks:
                docs = load_fixtures([Path(rel)])
                blocks[rel] = v3_data.file_block(Path(rel), docs, tokenizer)
                blocks[rel]["ids_sha256"] = ids_sha(docs)
            if rel in paths["train"]:
                src = source_of(rel)
                shares[src] = shares.get(src, 0) + blocks[rel].get("tokens", 0)
                docs_by[src] = docs_by.get(src, 0) + blocks[rel]["documents"]
        total = sum(shares.values()) or 1
        out["candidates"][c] = {
            "config": str(config),
            "train_documents": sum(docs_by.values()),
            "train_tokens": sum(shares.values()),
            "by_source": {
                k: {"documents": docs_by[k], "tokens": v, "share": round(v / total, 3)}
                for k, v in sorted(shares.items(), key=lambda kv: -kv[1])
            },
        }
    return out


def _decontam_reports(out_dir: Path) -> dict[str, Any]:
    """The gate and the agent-traffic-dev max-J report for each candidate's train+dev files."""
    index = decontam.eval_corpus()
    dev_docs = [
        doc
        for ds in decontam._indexed_datasets()
        if ds.name == "agent-traffic-dev"
        for p in ds.fixture_paths()
        for doc in load_fixtures([p])
    ]
    summary = {}
    for c, config in CONFIGS.items():
        paths = config_paths(config)
        report = decontam.Report()
        docs: list[Document] = []
        for rel in paths["train"] + paths["dev"]:
            file_docs = load_fixtures([Path(rel)])
            decontam.gate(file_docs, index, name=rel, report=report)
            docs.extend(file_docs)
        data = report.to_dict(index=index)
        data["max_jaccard"] = {"agent-traffic-dev": decontam.max_jaccard(docs, dev_docs)}
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"decontam-v31-{c}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        summary[c] = {
            "documents": data["documents"],
            "dropped_exact": data["dropped_exact"],
            "dropped_near": data["dropped_near"],
            "max_jaccard_agent_traffic_dev": data["max_jaccard"]["agent-traffic-dev"]["jaccard"],
            "eval_sets_indexed": len(data["eval_index"]["documents_by_set"]),
        }
        print(f"decontam v31-{c}: {summary[c]}", file=sys.stderr, flush=True)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("derive", help="assemble eval/generated/v31-final from the volume copy")
    d.add_argument("--raw", type=Path, required=True)
    d.add_argument("--out", type=Path, default=FINAL)
    d.add_argument("--json", type=Path)
    m = sub.add_parser("manifest", help="write training/ner/v31-data-manifest.json")
    m.add_argument("--out", type=Path, default=MANIFEST)
    m.add_argument("--no-tokens", action="store_true")
    r = sub.add_parser("decontam", help="per-candidate decontam reports with max J")
    r.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "derive":
        report = derive(args.raw, args.out)
        print(f"decontam: {report['documents']} documents, dropped {report['dropped_exact']} "
              f"exact + {report['dropped_near']} near", file=sys.stderr)  # fmt: skip
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    elif args.command == "manifest":
        data = manifest(None if args.no_tokens else "FacebookAI/xlm-roberta-base")
        args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")
    else:
        _decontam_reports(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
