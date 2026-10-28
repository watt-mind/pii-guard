"""Gold values masked only in part, and which detector made the mask (LAB-1367).

A placeholder that starts or ends inside a value sends the rest of it upstream: on
agent-traffic, a few digits of an identifier (``[[ID_DOCUMENT_x]]010``). This script runs the
detectors and the vault over fixture sets and prints, as JSON:

- per set, the scorer's counts: leak, partial leak (with the vault replacements, and with the
  token rule alone, as before LAB-1367), placeholder consistency, over-masking, overlap
  precision and recall;
- per set, the gold occurrences a placeholder covers only in part
  (:func:`pii_guard.eval.scorer._fully_covered`), grouped by gold type and by the detectors
  and types of the predictions over them.

No text or value is printed, only counts. ``--shapes`` also prints each partial cover as a
shape (digits ``9``, letters ``a``, masked characters ``#``) with its document id::

    uv run --no-sync python scripts/probe_partial_covers.py rules,ner \\
        agent-traffic-dev=eval/synthetic/dev/hu-agent-traffic-dev.jsonl,eval/synthetic/dev/en-agent-traffic-dev.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Sequence

from pii_guard.eval.fixtures import load_fixtures
from pii_guard.eval.scorer import (
    DEFAULT_POLICY,
    DetectorAnalyzer,
    _fully_covered,
    _gold_entities,
    leak_report,
    run_documents,
    summarize,
)

_LETTER = re.compile(r"[^\W\d_]")


def _shape(text: str) -> str:
    return _LETTER.sub("a", re.sub(r"\d", "9", text))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("detectors", help="comma-separated registry names")
    parser.add_argument("sets", nargs="+", help="NAME=path,path,...")
    parser.add_argument("--shapes", action="store_true", help="also print each partial cover")
    args = parser.parse_args(argv)

    analyzer = DetectorAnalyzer(args.detectors.split(","))
    report: dict[str, object] = {}
    for group in args.sets:
        name, _, paths = group.partition("=")
        results = run_documents(load_fixtures(paths.split(",")), analyzer)
        s = summarize(results)
        overlap = s["detection"]["overlap"]["micro"]  # type: ignore[index]
        by_source: Counter[str] = Counter()
        shapes: list[str] = []
        for r in results:
            doc = r.document
            for members in _gold_entities(doc, DEFAULT_POLICY):
                for span in members:
                    hits = [
                        (a, b, p)
                        for a, b, p in r.replacements or ()
                        if a < span.end and span.start < b
                    ]
                    if not hits or _fully_covered(span, hits, doc.language):
                        continue
                    preds = sorted(
                        {
                            f"{p.detector}:{p.entity_type.value}"
                            for p in r.predicted
                            if p.start < span.end and span.start < p.end
                        }
                    )
                    by_source[f"{span.entity_type.value} <- {' + '.join(preds)}"] += 1
                    if args.shapes:
                        vis = "".join(
                            "#" if any(a <= i < b for a, b, _ in hits) else _shape(doc.text[i])
                            for i in range(span.start, span.end)
                        )
                        shapes.append(f"{doc.id} {span.entity_type.value} {vis}")
        token_rule = sum(v.partial for r in results for v in leak_report(r.document, r.masked_text))
        entry: dict[str, object] = {
            "values": s["leak"]["values"],  # type: ignore[index]
            "leaked": s["leak"]["leaked"],  # type: ignore[index]
            "partial": s["leak"]["partial"],  # type: ignore[index]
            "partial_token_rule_only": token_rule,
            "entities": s["consistency"]["entities"],  # type: ignore[index]
            "consistent": s["consistency"]["consistent"],  # type: ignore[index]
            "masked": s["over_masking"]["masked"],  # type: ignore[index]
            "over_masked": s["over_masking"]["over_masked"],  # type: ignore[index]
            "precision_overlap": overlap["precision"],
            "recall_overlap": overlap["recall"],
            "partial_covers": sum(by_source.values()),
            "partial_covers_by_source": dict(by_source.most_common()),
        }
        if args.shapes:
            entry["shapes"] = shapes
        report[name] = entry
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
