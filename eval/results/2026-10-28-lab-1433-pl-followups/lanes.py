"""Leak and over-masking per ``meta.lane``, with a count-only attribution of each over-masked
span to its detector and type. No document text is printed.

    PII_GUARD_NER_DEVICE=cpu uv run --no-sync python \\
        eval/results/2026-10-28-lab-1433-pl-followups/lanes.py FIXTURES rules,ner
"""

from __future__ import annotations

import collections
import sys

from pii_guard.eval.fixtures import load_fixtures
from pii_guard.eval.scorer import (
    DetectorAnalyzer,
    DocumentResult,
    over_masked,
    run_documents,
    summarize,
    unscored,
)


def line(name: str, results: list[DocumentResult]) -> str:
    summary = summarize(results)
    leak, over = summary["leak"], summary["over_masking"]
    attribution: collections.Counter[str] = collections.Counter()
    for r in results:
        masked = [s for s in r.masked_spans if not unscored(r.document, s)]
        for span in over_masked(r.document, masked):
            attribution[f"{span.detector}:{span.entity_type.value}"] += 1
    return (
        f"{name:12} leak {leak['leaked']}/{leak['values']}  "  # type: ignore[index]
        f"over-masked {over['over_masked']}/{over['masked']}  {dict(attribution)}"  # type: ignore[index]
    )


def main(path: str, detectors: str) -> None:
    results = run_documents(load_fixtures(path), DetectorAnalyzer(detectors.split(",")))
    lanes: dict[str, list[DocumentResult]] = collections.defaultdict(list)
    for r in results:
        lanes[str(r.document.meta.get("lane", "-"))].append(r)
    for lane, rs in sorted(lanes.items()):
        print(line(lane, rs))
    print(line("all", results))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
