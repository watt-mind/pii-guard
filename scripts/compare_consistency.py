"""Placeholder consistency before and after LAB-1355, on one masking of each fixture set.

Before LAB-1355 an occurrence counted as masked when *any* replacement overlapped it, so
``[[PERSON_x]]inta Anna`` or ``Próba [[PERSON_x]]`` in every mention made an entity
"consistent". :func:`pii_guard.eval.scorer.consistency_report` now needs every occurrence fully
covered. This script runs the detectors and the vault once per set and scores the same
replacements with both rules, so the difference is the change of method alone, not a new run.

Only counts are printed (JSON), never a value or a document text::

    uv run --no-sync python scripts/compare_consistency.py rules,ner \\
        smoke=eval/fixtures/hu-smoke.jsonl,eval/fixtures/en-smoke.jsonl \\
        inflection=eval/fixtures/hu-inflection.jsonl
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence

from pii_guard.eval.fixtures import Document, load_fixtures
from pii_guard.eval.scorer import (
    DEFAULT_POLICY,
    DetectorAnalyzer,
    _gold_entities,
    consistency_report,
    run_documents,
)


def overlap_rule(doc: Document, replacements: Sequence[tuple[int, int, str]]) -> list[bool]:
    """The pre-LAB-1355 rule: any overlap counts as masked."""
    out = []
    for members in _gold_entities(doc, DEFAULT_POLICY):
        placeholders: set[str] = set()
        covered = True
        for span in members:
            hits = {p for s, e, p in replacements if s < span.end and span.start < e}
            covered &= bool(hits)
            placeholders |= hits
        out.append(covered and len(placeholders) == 1)
    return out


def _counts() -> dict[str, int]:
    return {"entities": 0, "consistent": 0, "multi_occurrence": 0, "multi_consistent": 0}


def main(argv: Sequence[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    analyzer = DetectorAnalyzer(argv[0].split(","))
    print(f"detectors {analyzer.loaded}, skipped {analyzer.skipped}", file=sys.stderr)
    report: dict[str, dict[str, object]] = {}
    for group in argv[1:]:
        name, _, paths = group.partition("=")
        before, after = _counts(), _counts()
        changed = 0
        for result in run_documents(load_fixtures(paths.split(",")), analyzer):
            replacements = result.replacements or ()
            old = overlap_rule(result.document, replacements)
            new = consistency_report(result.document, replacements)
            for was, entity in zip(old, new, strict=True):
                for counts, ok in ((before, was), (after, entity.consistent)):
                    counts["entities"] += 1
                    counts["consistent"] += ok
                    if entity.occurrences > 1:
                        counts["multi_occurrence"] += 1
                        counts["multi_consistent"] += ok
                changed += was != entity.consistent
        report[name] = {"before": before, "after": after, "entities_changed": changed}
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
