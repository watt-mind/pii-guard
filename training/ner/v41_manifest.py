"""The NER v4.1 data manifest (LAB-1539): every source, its license, counts and file hashes.

Rows are never committed. ``training/ner/v41-data-manifest.json`` records, per source and file,
the documents, gold spans and the SHA-256 of each file in the data directory (outside every
git worktree, so a merge cleanup cannot delete it), so a rebuild can be checked byte for byte.
Every source is synthetic or fictional (ADR 0005) and marked ``"synthetic": true``, so the Modal
upload allowlist (``training/distill/modal_upload.py``, LAB-1527) may carry it. The Hugging Face
sources' row ids and label maps are in ``training/ner/v41-hf-manifest.json`` (``hf_v41.py``)::

    uv run --no-sync python training/ner/v41_manifest.py \\
        --data ~/Develop/.worktrees/pii-guard/data-eu/v41
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import load_fixtures

OUT = Path("training/ner/v41-data-manifest.json")
HF_MANIFEST = "training/ner/v41-hf-manifest.json"
MUSE = "Apache-2.0 (pii-guard generator; writer Muse Spark, Meta Model API contributor tier)"
TEACHER = "Apache-2.0 (teacher: Muse Glimmer 30B, open weights)"

SOURCES: dict[str, dict[str, Any]] = {
    "court-v41": {
        "dir": "court",
        "what": "fictional judgment and opinion-style documents, 24 languages, planted gold "
        "with standalone and declined surnames (court_eu.py court, seed 1539)",
        "license": MUSE,
    },
    "court-v41-labelled": {
        "dir": "court/labelled",
        "what": "court-v41 after the Muse Glimmer teacher pass (fireworks_label.py)",
        "license": TEACHER,
    },
    "variants-v41": {
        "dir": "variants",
        "what": "fictional variants per mined v2.0 error pattern (court_eu.py variants, "
        "seed 1539; patterns in eval/results/2026-10-29-lab-1539-v41-data/patterns.json)",
        "license": MUSE,
    },
    "variants-v41-labelled": {
        "dir": "variants/labelled",
        "what": "variants-v41 after the Muse Glimmer teacher pass",
        "license": TEACHER,
    },
    "kiji": {
        "dir": "hf-mapped/kiji",
        "what": "DataikuNLP/kiji-pii-training-data train, mapped (hf_v41.py)",
        "license": "Apache-2.0",
        "manifest": HF_MANIFEST,
    },
    "nym": {
        "dir": "hf-mapped/nym",
        "what": "Wismut/nym-pii-multilingual-data train, language-identified and mapped",
        "license": "MIT",
        "manifest": HF_MANIFEST,
    },
    "e3": {
        "dir": "hf-mapped/e3",
        "what": "E3-JSI/synthetic-multi-pii-ner-v1, non-health rows, mapped",
        "license": "MIT",
        "manifest": HF_MANIFEST,
    },
    "pii-anon": {
        "dir": "hf-mapped/pii-anon",
        "what": "subhash-holla/pii-anon train, synthetic rows with an ID only, <= 5 % of the mix",
        "license": "CC0-1.0",
        "manifest": HF_MANIFEST,
    },
}


def file_block(path: Path) -> dict[str, Any]:
    docs = load_fixtures([path])
    gold = Counter(s.entity_type.value for d in docs for s in d.spans)
    return {
        "documents": len(docs),
        "gold_spans": dict(sorted(gold.items())),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


RESULTS = Path("eval/results/2026-10-29-lab-1539-v41-data")

#: Mined pattern keys (``mine_v41.py``) grouped into the variant kinds that target them.
PATTERN_GROUPS: dict[str, tuple[str, ...]] = {
    "variant-dates-not-birth": ("overmask:date_of_birth:", "overmask:id_document:other"),
    "variant-honorific": ("overmask:person:honorific", "overmask:address:honorific"),
    "variant-standalone-declined": ("leak:person:single-token",),
    "variant-reference-numbers": (
        "overmask:id_document:digits", "overmask:address:lowercase-word",
        "overmask:address:with-digits", "leak:id_document:", "overmask:bank_account:",
    ),
    "variant-person-like-company": ("overmask:person:multi-word",),
    "negative-capitalized-words": (
        "overmask:person:single-capitalized-word", "overmask:person:sentence-initial-word",
        "overmask:address:single-capitalized-word",
        "overmask:address:all-caps-word", "overmask:address:multi-word",
    ),
}  # fmt: skip


def pattern_report(data: Path) -> dict[str, Any]:
    """Mined counts per pattern, the variant kind that targets it, and variants written."""
    mining = json.loads((RESULTS / "mining.json").read_text(encoding="utf-8"))
    patterns: dict[str, int] = mining["patterns"]
    variant_counts: Counter[str] = Counter()
    for path in sorted((data / "variants").glob("*-distill-*.jsonl")):
        for doc in load_fixtures([path]):
            variant_counts[str(doc.meta["kind"])] += 1
    groups: dict[str, Any] = {}
    covered: set[str] = set()
    for kind, prefixes in PATTERN_GROUPS.items():
        members = {p: n for p, n in patterns.items() if p.startswith(prefixes)}
        covered |= set(members)
        groups[kind] = {
            "mined_misses": sum(members.values()),
            "patterns": members,
            "variants_written": variant_counts.get(kind, 0),
        }
    return {
        "ticket": "LAB-1539",
        "model": mining["model"],
        "pools": {k: v["documents"] for k, v in mining["pools"].items()},
        "groups": dict(sorted(groups.items(), key=lambda kv: -kv[1]["mined_misses"])),
        "not_targeted": {p: n for p, n in patterns.items() if p not in covered},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args(argv)
    out: dict[str, Any] = {
        "ticket": "LAB-1539",
        "synthetic": True,
        "rows_committed": False,
        "data_dir": "~/Develop/.worktrees/pii-guard/data-eu/v41 (outside every worktree)",
        "policy": "ADR 0005: synthetic or fictional only; no MAPA/TAB or other real text "
        "(LAB-1419); no GDPR special categories",
        "sources": {},
    }
    for name, src in SOURCES.items():
        base = args.data / src["dir"]
        files = sorted(base.glob("*.jsonl")) if base.is_dir() else []
        files = [p for p in files if p.name != "teacher-cache.jsonl"]
        entry = {k: v for k, v in src.items() if k != "dir"}
        entry["synthetic"] = True
        entry["path"] = f"data-eu/v41/{src['dir']}"
        entry["files"] = {p.name: file_block(p) for p in files}
        entry["documents"] = sum(f["documents"] for f in entry["files"].values())
        out["sources"][name] = entry
        print(f"manifest: {name}: {len(files)} files", file=sys.stderr)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"manifest -> {OUT}", file=sys.stderr)
    report = pattern_report(args.data)
    target = RESULTS / "patterns.json"
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"patterns -> {target}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
