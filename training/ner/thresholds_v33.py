"""Path 4 of LAB-1512: per-language, per-type NER decision thresholds for v2.0, from dev data.

Calibration reads **development data only** (s11 hu/en dev, OpenPII hu/en/de dev, the v3.3
add-on dev split), never agent-traffic-dev or a test set. For every global threshold in
:data:`GRID` it runs fast mode (rules + the published v2.0) over those documents and counts the
gold values that survive masking, per language and type. Candidate H takes, for each language
(hu, en, de) and NER type, the highest threshold whose leak count is no higher than at 0.5
(the current default for every type)::

    PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/thresholds_v33.py \\
        --json eval/results/2026-10-29-ner-v33/thresholds-h.json

``eval_v3.py score --thresholds <json>`` scores the table. The output holds counts and
thresholds only, never a text or a value.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

GRID = (0.5, 0.6, 0.7, 0.8, 0.9)
LANGUAGES = ("hu", "en", "de")
DEV = (
    "eval/generated/v31-final/s11/hu-distill-dev.jsonl",
    "eval/generated/v31-final/s11/en-distill-dev.jsonl",
    "eval/generated/v31-final/openpii/hu-openpii-dev.jsonl",
    "eval/generated/v31-final/openpii/en-openpii-dev.jsonl",
    "eval/generated/v31-final/openpii/de-openpii-dev.jsonl",
    *(
        f"eval/generated/v33-addon/{lang}-v33-{part}-dev.jsonl"
        for part, lang in (
            ("names", "hu"),
            ("names", "de"),
            ("payload", "hu"),
            ("payload", "en"),
            ("payload", "de"),
            ("agent", "hu"),
            ("agent", "en"),
            ("agent", "de"),
        )
    ),
)


def apply(table: dict[str, dict[str, float]]) -> None:
    """Make ``table`` the NER detector's default thresholds in this process."""
    from pii_guard.detect import ner
    from pii_guard.types import EntityType

    base = {t: 0.5 for t in sorted(ner.NER_ENTITY_TYPES)}
    ner.DEFAULT_THRESHOLDS.clear()
    ner.DEFAULT_THRESHOLDS["default"] = dict(base)
    for lang, values in table.items():
        ner.DEFAULT_THRESHOLDS[lang] = {**base, **{EntityType(k): v for k, v in values.items()}}


def leaks(threshold: float, docs: Sequence[Any]) -> Counter[tuple[str, str]]:
    """Gold values left in the masked text, by (language, type), at one global threshold."""
    from pii_guard.detect import ner
    from pii_guard.eval.scorer import DetectorAnalyzer, run_documents

    apply({lang: dict.fromkeys((t.value for t in ner.NER_ENTITY_TYPES), threshold)
           for lang in LANGUAGES})  # fmt: skip
    analyzer = DetectorAnalyzer(["rules", "ner"])
    counts: Counter[tuple[str, str]] = Counter()
    for result in run_documents(docs, analyzer):
        doc = result.document
        for span in doc.spans:
            if span.text in result.masked_text:
                counts[(doc.language, span.entity_type.value)] += 1
    return counts


def calibrate(paths: Sequence[str] = DEV) -> dict[str, Any]:
    from pii_guard.detect import ner
    from pii_guard.eval.fixtures import load_fixtures

    docs = load_fixtures([p for p in paths if Path(p).is_file()])
    by_t = {t: leaks(t, docs) for t in GRID}
    types = sorted(t.value for t in ner.NER_ENTITY_TYPES)
    table: dict[str, dict[str, float]] = {}
    for lang in LANGUAGES:
        row: dict[str, float] = {}
        for typ in types:
            ref = by_t[0.5][(lang, typ)]
            ok = [t for t in GRID if by_t[t][(lang, typ)] <= ref]
            best = max(ok)
            if best != 0.5:
                row[typ] = best
        if row:
            table[lang] = row
    return {
        "grid": list(GRID),
        "dev_files": [p for p in paths if Path(p).is_file()],
        "dev_documents": len(docs),
        "leaked_by_threshold": {
            str(t): {
                f"{lang}/{typ}": c[(lang, typ)]
                for lang in LANGUAGES
                for typ in types
                if c[(lang, typ)]
            }
            for t, c in by_t.items()
        },
        "thresholds": table,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args(argv)
    report = calibrate()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["thresholds"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
