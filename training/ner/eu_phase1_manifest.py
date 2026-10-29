"""The phase-1 multilingual data manifest (LAB-1525): every source, its licence, counts, hashes.

Rows are never committed. ``training/ner/eu-phase1-data-manifest.json`` records, per source and
language, the documents, gold spans, the SHA-256 of each git-ignored file under
``eval/generated/`` (so a rebuild can be checked byte for byte) and the licence. Every source
is synthetic or fictional (ADR 0005), marked ``"synthetic": true``, so the Modal upload
allowlist (``training/distill/modal_upload.py``, LAB-1527) may carry it. A source whose
directory is absent on this machine keeps its recorded entry (phase 1b, LAB-1534, added
sources without rebuilding phase 1's)::

    uv run --no-sync python training/ner/eu_phase1_manifest.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import load_fixtures

OUT = Path("training/ner/eu-phase1-data-manifest.json")

SOURCES: dict[str, dict[str, Any]] = {
    "openpii-eu": {
        "dir": "eval/generated/openpii-eu",
        "glob": "*-openpii-*.jsonl",
        "what": "Ai4Privacy OpenPII-1M train split, 19 languages, seed 1525 (openpii_eu.py)",
        "license": "CC-BY-4.0",
        "attribution": "Ai4Privacy / Ai Suisse SA",
        "manifest": "training/ner/eu-openpii-train-manifest.json",
    },
    "muse-eu": {
        "dir": "eval/generated/distill-eu-s1525",
        "glob": "*-distill-*.jsonl",
        "what": "fictional documents written by Muse Spark (Meta Model API), planted gold "
        "with declined names (eu_corpus.py)",
        "license": "Apache-2.0 (pii-guard generator, as the v2.0 s11/s13 corpora)",
    },
    "muse-eu-labelled": {
        "dir": "eval/generated/distill-eu-s1525/labelled",
        "glob": "*-distill-*.jsonl",
        "what": "muse-eu after the Muse Glimmer teacher pass (training/distill/label.py)",
        "license": "Apache-2.0 (teacher: Muse Glimmer, open weights, Apache-2.0)",
    },
    "muse-eu-1b": {
        "dir": "eval/generated/distill-eu-1b-s1525",
        "glob": "*-distill-*.jsonl",
        "what": "phase 1b (LAB-1534): the muse-eu pipeline for fr, es, it, nl, ro, ga, mt "
        "(eu_corpus.py)",
        "license": "Apache-2.0 (pii-guard generator, as the v2.0 s11/s13 corpora)",
    },
    "muse-eu-1b-labelled": {
        "dir": "eval/generated/distill-eu-1b-s1525/labelled",
        "glob": "*-distill-*.jsonl",
        "what": "muse-eu-1b after the Muse Glimmer teacher pass (training/distill/label.py)",
        "license": "Apache-2.0 (teacher: Muse Glimmer, open weights, Apache-2.0)",
    },
    "negatives-eu": {
        "dir": "eval/generated/negatives-eu",
        "glob": "*-negatives-train.jsonl",
        "what": "template hard negatives, no gold spans, seed 1525 (negatives_eu.py)",
        "license": "Apache-2.0",
    },
    "court-en": {
        "dir": "eval/generated/court-en",
        "glob": "en-court-*.jsonl",
        "what": "template English court-style text, standalone surnames (court_surnames_en.py)",
        "license": "Apache-2.0",
    },
    "gates-eu": {
        "dir": "eval/fixtures/eu",
        "glob": "*.jsonl",
        "what": "hand-written fictional smoke and inflection gate sets (committed; "
        "eval/fixtures/build_eu_gates.py). Evaluation only, never training",
        "license": "Apache-2.0",
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


def main() -> int:
    out: dict[str, Any] = {
        "ticket": "LAB-1525",
        "tickets": ["LAB-1525", "LAB-1534"],
        "synthetic": True,
        "rows_committed": False,
        "policy": "ADR 0005: synthetic or fictional only; no MAPA/TAB or other real text "
        "(LAB-1419); no GDPR special categories",
        "sources": {},
    }
    previous = json.loads(OUT.read_text(encoding="utf-8"))["sources"] if OUT.exists() else {}
    for name, src in SOURCES.items():
        base = Path(src["dir"])
        if not base.is_dir() and name in previous:
            # Not rebuilt on this machine: keep the recorded counts and hashes.
            out["sources"][name] = previous[name]
            print(f"manifest: {name}: kept (no {base} here)", file=sys.stderr)
            continue
        files = sorted(base.glob(src["glob"])) if base.is_dir() else []
        entry = {k: v for k, v in src.items() if k not in {"dir", "glob"}}
        entry["synthetic"] = True
        entry["files"] = {p.name: file_block(p) for p in files}
        out["sources"][name] = entry
        print(f"manifest: {name}: {len(files)} files", file=sys.stderr)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"manifest -> {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
