"""Teacher agreement check (LAB-1539): Muse Spark Open (Baseten) vs Muse Glimmer vs planted gold.

Evidence only: Spark Open's spans are never trained on and never mixed into the v4.1 labelled
set. A stratified sample of the court-style corpus (``spark-check/<lang>-distill-sample.jsonl``,
8-9 documents per language, all 24) was labelled by Spark Open through ``training/distill/
label.py`` (same request path as audit mode, ``reasoning_effort`` low). This compares the raw
teacher spans (each teacher's ``teacher-cache.jsonl``) of the four NER types the teacher pass
uses (PERSON, ORGANIZATION, ADDRESS, DATE_OF_BIRTH), per language and per type:

- **vs gold**: recall of the planted gold spans (exact boundaries and any overlap of the same
  type) and the share of teacher spans that match gold exactly (teacher spans outside gold are
  often names the writer added, so this is not a precision);
- **Spark vs Glimmer**: exact-match F1 between the two teachers (same type, same boundaries)
  and overlap agreement (same type, any overlap).

Writes counts and ratios only (no text)::

    uv run --no-sync python training/ner/teacher_agreement.py --data <data>/v41 \\
        --json eval/results/2026-10-29-lab-1539-v41-data/teacher-agreement.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import load_fixtures

TYPES = ("PERSON", "ORGANIZATION", "ADDRESS", "DATE_OF_BIRTH")
#: Baseten Model APIs price for Muse Spark Open (docs/models.md, 2026-10-27), USD per M tokens.
BASETEN = {"input": 1.25, "cached": 0.15, "output": 4.25}

Span = tuple[int, int, str]


def load_cache(path: Path) -> dict[str, list[Span]]:
    out: dict[str, list[Span]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[row["id"]] = [(s, e, t) for s, e, t in row["spans"] if t in TYPES]
    return out


def _overlap(a: Span, bs: list[Span]) -> bool:
    return any(a[2] == b[2] and a[0] < b[1] and b[0] < a[1] for b in bs)


def _ratio(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def compare(docs: list[Any], spark: dict[str, list[Span]], glimmer: dict[str, list[Span]]):
    c: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for doc in docs:
        if doc.id not in spark or doc.id not in glimmer:
            c[(doc.language, "*")]["missing_teacher"] += 1
            continue
        gold = [(s.start, s.end, s.entity_type.value) for s in doc.spans]
        gold = [g for g in gold if g[2] in TYPES]
        sp, gl = spark[doc.id], glimmer[doc.id]
        for key in ((doc.language, "*"),):
            c[key]["documents"] += 1
        for t in TYPES:
            g_t = [x for x in gold if x[2] == t]
            s_t = [x for x in sp if x[2] == t]
            l_t = [x for x in gl if x[2] == t]
            for scope in ((doc.language, t), ("*", t)):
                k = c[scope]
                k["gold"] += len(g_t)
                k["spark"] += len(s_t)
                k["glimmer"] += len(l_t)
                k["spark_gold_exact"] += len(set(s_t) & set(g_t))
                k["glimmer_gold_exact"] += len(set(l_t) & set(g_t))
                k["gold_found_spark"] += sum(_overlap(g, s_t) for g in g_t)
                k["gold_found_glimmer"] += sum(_overlap(g, l_t) for g in g_t)
                k["spark_glimmer_exact"] += len(set(s_t) & set(l_t))
                k["spark_in_glimmer_overlap"] += sum(_overlap(s, l_t) for s in s_t)
                k["glimmer_in_spark_overlap"] += sum(_overlap(g, s_t) for g in l_t)
    return c


def summarize(k: Counter[str]) -> dict[str, Any]:
    exact = k["spark_glimmer_exact"]
    return {
        **dict(sorted(k.items())),
        "gold_recall_exact_spark": _ratio(k["spark_gold_exact"], k["gold"]),
        "gold_recall_exact_glimmer": _ratio(k["glimmer_gold_exact"], k["gold"]),
        "gold_recall_overlap_spark": _ratio(k["gold_found_spark"], k["gold"]),
        "gold_recall_overlap_glimmer": _ratio(k["gold_found_glimmer"], k["gold"]),
        "spark_spans_matching_gold": _ratio(k["spark_gold_exact"], k["spark"]),
        "glimmer_spans_matching_gold": _ratio(k["glimmer_gold_exact"], k["glimmer"]),
        "spark_vs_glimmer_exact_f1": _ratio(2 * exact, k["spark"] + k["glimmer"]),
        "spark_vs_glimmer_overlap_agreement": _ratio(
            k["spark_in_glimmer_overlap"] + k["glimmer_in_spark_overlap"],
            k["spark"] + k["glimmer"],
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data", type=Path, required=True, help="the v41 corpus folder")
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument(
        "--usage", type=Path, nargs="*", default=[], help="label.py logs of the Spark runs"
    )
    args = parser.parse_args(argv)
    docs = load_fixtures(sorted((args.data / "spark-check").glob("*-distill-sample.jsonl")))
    spark = load_cache(args.data / "spark-check" / "teacher-cache.jsonl")
    glimmer = load_cache(args.data / "court" / "teacher-cache.jsonl")
    c = compare(docs, spark, glimmer)
    usage: Counter[str] = Counter()
    for log in args.usage:
        last = log.read_text(encoding="utf-8").strip().splitlines()[-1]
        usage.update(json.loads(last).get("usage", {}))
    uncached = usage["prompt_tokens"] - usage["cached_tokens"]
    cost = (
        uncached * BASETEN["input"]
        + usage["cached_tokens"] * BASETEN["cached"]
        + usage["completion_tokens"] * BASETEN["output"]
    ) / 1e6
    report = {
        "ticket": "LAB-1539",
        "purpose": "agreement evidence only; Spark Open labels are not used for training",
        "spark": "meta-models/muse-spark-open-1026 on Baseten Model APIs, reasoning_effort low",
        "glimmer": "Muse Glimmer 30B on a Fireworks on-demand H200, reasoning_effort low",
        "sample_documents": len(docs),
        "languages": sorted({d.language for d in docs}),
        "by_type": {t: summarize(c[("*", t)]) for t in TYPES},
        "by_language": {
            lang: {
                "documents": c[(lang, "*")]["documents"],
                "missing_teacher": c[(lang, "*")]["missing_teacher"],
                **{t: summarize(c[(lang, t)]) for t in TYPES},
            }
            for lang in sorted({d.language for d in docs})
        },
        "spark_usage": dict(usage),
        "spark_cost_usd_estimate": round(cost, 4),
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["by_type"], indent=1)[:3000], file=sys.stderr)
    print(f"spark cost ~${cost:.3f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
