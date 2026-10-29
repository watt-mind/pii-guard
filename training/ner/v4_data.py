"""Assemble the NER v4 training mixes A and B (LAB-1535) and record what went in.

Fictional / synthetic data only (ADR 0005); no MAPA, TAB or other real text (LAB-1419). Every
input is rebuilt from a committed script and seed (``docs/training-data-eu-phase1.md``,
``training/ner/v2-base-hn.toml``); this script only takes seeded prefixes and copies them into
``eval/generated/v4-mix/<mix>/`` (git-ignored), so the Modal upload (``modal_train.py``, through
the LAB-1527 allowlist) holds exactly the files the config names::

    uv run --no-sync python training/ner/v4_data.py build --json eval/results/2026-10-29-lab-1535-ner-v4/data.json

Mixes (fixed in ``eval/results/2026-10-29-lab-1535-ner-v4/README.md`` before any training):

- **a:** OpenPII-1M EU train rows, the first 2,500 per language (19 languages); EU hard
  negatives, the first 1,000 per language (the same 19; none for ga/mt, which have no positive
  rows); the Muse lv/lt/hr/sl train documents twice; the English court-style set; the v2.0
  hu/en/de replay (s11, OpenPII hu/en/de, negatives hu/en/de).
- **b:** as a, with 5,000 OpenPII rows and 2,000 negatives per language.

The JSON report holds counts, gold-span counts per type and SHA-256 per file, never text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

GEN = Path("eval/generated")
OUT = GEN / "v4-mix"
#: OpenPII-1M languages of the phase-1 data (openpii_eu.LANGUAGES); no ga, no mt.
EU_LANGS = (
    "lv", "lt", "hr", "sl", "fr", "es", "it", "nl", "ro",
    "bg", "cs", "da", "el", "et", "fi", "pl", "pt", "sk", "sv",
)  # fmt: skip
MUSE_LANGS = ("lv", "lt", "hr", "sl")
MIXES = {"a": {"openpii": 2500, "negatives": 1000}, "b": {"openpii": 5000, "negatives": 2000}}
#: The v2.0 hu/en/de replay: v2-base-hn.toml's train files minus s13 (not recoverable).
REPLAY = (
    "distill-s11/labelled/hu-distill-train.jsonl",
    "distill-s11/labelled/en-distill-train.jsonl",
    "openpii-train/hu-openpii-train.jsonl",
    "openpii-train/en-openpii-train.jsonl",
    "openpii-train/de-openpii-train.jsonl",
    "negatives/hu-negatives-train.jsonl",
    "negatives/en-negatives-train.jsonl",
    "negatives/de-negatives-train.jsonl",
)
DEV = (
    "distill-s11/labelled/hu-distill-dev.jsonl",
    "distill-s11/labelled/en-distill-dev.jsonl",
    "openpii-train/hu-openpii-dev.jsonl",
    "openpii-train/en-openpii-dev.jsonl",
    "openpii-train/de-openpii-dev.jsonl",
    *(f"openpii-eu/{lang}-openpii-dev.jsonl" for lang in EU_LANGS),
    *(f"distill-eu-s1525/{lang}-distill-dev.jsonl" for lang in MUSE_LANGS),
    "court-en/en-court-dev.jsonl",
)


def _lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _describe(path: Path) -> dict[str, Any]:
    lines = _lines(path)
    spans: Counter[str] = Counter()
    for ln in lines:
        for s in json.loads(ln).get("spans", ()):
            spans[s.get("entity_type") or s.get("type") or "?"] += 1
    return {
        "documents": len(lines),
        "gold_spans": dict(sorted(spans.items())),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _prefix(src: Path, dst: Path, n: int) -> None:
    lines = _lines(src)
    if len(lines) < n:
        raise SystemExit(f"{src}: {len(lines)} rows, {n} wanted")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(lines[:n]) + "\n", encoding="utf-8")


def build(mix: str) -> dict[str, Any]:
    """Write ``eval/generated/v4-mix/<mix>/`` and return the config's train and dev lists."""
    sizes = MIXES[mix]
    base = OUT / mix
    train: list[str] = []
    for lang in EU_LANGS:
        dst = base / f"openpii/{lang}-openpii-train-{sizes['openpii']}.jsonl"
        _prefix(GEN / f"openpii-eu/{lang}-openpii-train.jsonl", dst, sizes["openpii"])
        train.append(dst.as_posix())
    for lang in EU_LANGS:
        dst = base / f"negatives/{lang}-negatives-train-{sizes['negatives']}.jsonl"
        _prefix(GEN / f"negatives-eu/{lang}-negatives-train.jsonl", dst, sizes["negatives"])
        train.append(dst.as_posix())
    for lang in MUSE_LANGS:  # twice: about 1,080 documents a language against 2,500-5,000 rows
        rel = (GEN / f"distill-eu-s1525/{lang}-distill-train.jsonl").as_posix()
        train += [rel, rel]
    train.append((GEN / "court-en/en-court-train.jsonl").as_posix())
    train += [(GEN / rel).as_posix() for rel in REPLAY]
    dev = [(GEN / rel).as_posix() for rel in DEV]
    return {"train": train, "dev": dev}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="write both mixes and the data report")
    b.add_argument("--json", type=Path, required=True)
    args = parser.parse_args(argv)
    report: dict[str, Any] = {"ticket": "LAB-1535", "synthetic": True, "mixes": {}}
    for mix in MIXES:
        lists = build(mix)
        files: dict[str, Any] = {}
        for rel in dict.fromkeys(lists["train"] + lists["dev"]):
            files[rel] = _describe(Path(rel))
        docs = sum(files[p]["documents"] for p in lists["train"])
        report["mixes"][mix] = {
            "sizes": MIXES[mix],
            "train": lists["train"],
            "dev": lists["dev"],
            "train_documents": docs,
            "dev_documents": sum(files[p]["documents"] for p in lists["dev"]),
            "files": files,
        }
        print(f"v4-data: mix {mix}: {docs} train documents", file=sys.stderr)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
