"""Prompt-injection red team: leak rate per attack class, with fail-closed accounting.

``pii-guard eval injection`` runs fixtures whose documents carry ``meta.attack`` (see
``eval/fixtures/build_injection.py``) through the same detect-mask-unmask path as
``pii-guard eval``, one document at a time. Unlike the plain scorecard, a detector failure on
one document does not abort the run: the document is counted as **blocked** (the gateway
would have refused the request, ADR 0006), which is the safe outcome, and the run goes on.

```
pii-guard eval injection [--fixtures PATH ...] [--detectors rules,llm] [--language hu]
                         [--json OUT] [--markdown OUT]
```

For every attack class the report gives the documents, the blocked documents, the labelled
values of ``mask``-policy types, how many survived the masked text (leaked / partially
leaked), and how many documents leaked at least one value. The JSON adds the full
:func:`~pii_guard.eval.scorer.summarize` block per class and the LLM detector's usage counters
(requests, tokens, invalid outputs, refusals). Nothing in it contains a value or a text.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import Document, FixtureError, load_fixtures
from pii_guard.eval.scorer import DocumentResult, leak_report, run_documents, summarize
from pii_guard.eval.stats import fmt_pct
from pii_guard.types import DetectionError

__all__ = [
    "DEFAULT_INJECTION_FIXTURES",
    "UNTAGGED",
    "attack_breakdown",
    "attack_of",
    "render_attack_table",
    "run_injection",
]

DEFAULT_INJECTION_FIXTURES = (
    "eval/fixtures/hu-injection.jsonl",
    "eval/fixtures/en-injection.jsonl",
)
#: Attack class of documents without ``meta.attack``.
UNTAGGED = "(none)"


def attack_of(doc: Document) -> str:
    attack = doc.meta.get("attack")
    return attack if isinstance(attack, str) and attack else UNTAGGED


def run_injection(
    documents: Sequence[Document], analyzer: Any
) -> tuple[list[DocumentResult], list[tuple[Document, str]]]:
    """Run each document on its own. Returns the results and the blocked ``(doc, code)`` pairs.

    Only :class:`DetectionError` (the fail-closed signal) counts as blocked; anything else
    propagates.
    """
    results: list[DocumentResult] = []
    blocked: list[tuple[Document, str]] = []
    for doc in documents:
        try:
            results.extend(run_documents([doc], analyzer))
        except DetectionError as exc:
            blocked.append((doc, exc.message))
    return results, blocked


def attack_breakdown(
    results: Sequence[DocumentResult],
    blocked: Sequence[tuple[Document, str]] = (),
    *,
    order: Sequence[str] = (),
) -> dict[str, dict[str, Any]]:
    """Per attack class: counts, leak rates and the :func:`summarize` block."""
    by_attack: dict[str, list[DocumentResult]] = defaultdict(list)
    blocked_by: dict[str, list[tuple[Document, str]]] = defaultdict(list)
    for r in results:
        by_attack[attack_of(r.document)].append(r)
    for doc, code in blocked:
        blocked_by[attack_of(doc)].append((doc, code))
    names = [*order, *sorted((set(by_attack) | set(blocked_by)) - set(order))]
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        rs, bl = by_attack.get(name, []), blocked_by.get(name, [])
        if not rs and not bl:
            continue
        values = leaked = partial = docs_leaked = 0
        for r in rs:
            report = leak_report(r.document, r.masked_text)
            values += len(report)
            leaked += sum(v.leaked for v in report)
            partial += sum(v.partial for v in report)
            docs_leaked += any(v.leaked for v in report)
        out[name] = {
            "documents": len(rs) + len(bl),
            "blocked": len(bl),
            "blocked_ids": [d.id for d, _ in bl],
            "values": values,
            "leaked": leaked,
            "partial": partial,
            "leak_rate": leaked / values if values else None,
            "partial_rate": partial / values if values else None,
            "documents_leaked": docs_leaked,
            "leaked_ids": [
                r.document.id
                for r in rs
                if any(v.leaked for v in leak_report(r.document, r.masked_text))
            ],
            "summary": summarize(rs) if rs else None,
        }
    return out


def render_attack_table(breakdown: dict[str, dict[str, Any]]) -> str:
    """Markdown: one row per attack class plus a total row."""
    lines = [
        "| Attack | Docs | Blocked | Values | Leaked | Leak % | Partial % | Docs leaked |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    total: defaultdict[str, int] = defaultdict(int)
    for name, row in breakdown.items():
        lines.append(
            f"| `{name}` | {row['documents']} | {row['blocked']} | {row['values']} | "
            f"{row['leaked']} | {fmt_pct(row['leak_rate'])} | {fmt_pct(row['partial_rate'])} | "
            f"{row['documents_leaked']} |"
        )
        for key in ("documents", "blocked", "values", "leaked", "partial", "documents_leaked"):
            total[key] += row[key]
    v = total["values"]
    lines.append(
        f"| **all** | {total['documents']} | {total['blocked']} | {v} | {total['leaked']} | "
        f"{fmt_pct(total['leaked'] / v if v else None)} | "
        f"{fmt_pct(total['partial'] / v if v else None)} | {total['documents_leaked']} |"
    )
    return "\n".join(lines) + "\n"


def _usage(analyzer: Any) -> dict[str, dict[str, int]]:
    """The ``usage`` counters of every detector that keeps them (the LLM detector)."""
    out: dict[str, dict[str, int]] = {}
    for detector in getattr(analyzer, "detectors", ()):
        usage = getattr(detector, "usage", None)
        if isinstance(usage, dict):
            out[detector.name] = dict(usage)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    from pii_guard.eval.report import build_scorecard
    from pii_guard.eval.scorer import DetectorAnalyzer

    parser = argparse.ArgumentParser(
        prog="pii-guard eval injection",
        description="Leak rate per prompt-injection attack class (fixtures with meta.attack).",
    )
    parser.add_argument("--fixtures", action="append", metavar="PATH")
    parser.add_argument("--detectors", default="rules", metavar="NAMES")
    parser.add_argument("--language", action="append", metavar="LANG")
    parser.add_argument("--json", type=Path, metavar="OUT")
    parser.add_argument("--markdown", type=Path, metavar="OUT")
    args = parser.parse_args(list(argv) if argv is not None else None)

    paths = [Path(p) for p in (args.fixtures or DEFAULT_INJECTION_FIXTURES)]
    try:
        documents = load_fixtures(paths)
    except (FixtureError, OSError) as exc:
        print(f"pii-guard eval injection: {exc}", file=sys.stderr)
        return 2
    if args.language:
        wanted = {lang for item in args.language for lang in item.split(",")}
        documents = [d for d in documents if d.language in wanted]
    if not documents:
        print("pii-guard eval injection: no fixture documents selected", file=sys.stderr)
        return 2
    names = [n.strip() for n in args.detectors.split(",") if n.strip()]
    analyzer = DetectorAnalyzer(names)
    for name, reason in analyzer.skipped:
        print(f"pii-guard eval injection: warning: skipping {name!r}: {reason}", file=sys.stderr)
    if not analyzer.detectors:
        print("pii-guard eval injection: no detector could be loaded", file=sys.stderr)
        return 2

    results, blocked = run_injection(documents, analyzer)
    order = list(dict.fromkeys(attack_of(d) for d in documents))
    breakdown = attack_breakdown(results, blocked, order=order)
    scorecard = build_scorecard(
        results, detectors=analyzer.loaded, skipped_detectors=analyzer.skipped, fixture_paths=paths
    )
    scorecard["attacks"] = breakdown
    scorecard["blocked"] = [{"id": d.id, "attack": attack_of(d), "error": c} for d, c in blocked]
    scorecard["usage"] = _usage(analyzer)

    meta = scorecard["meta"]
    commit = meta["commit"][:12] + (" (dirty)" if meta["dirty"] else "")
    markdown = "\n".join(
        [
            "# pii-guard prompt-injection red team",
            "",
            f"- commit: `{commit}`, detectors: {', '.join(f'`{d}`' for d in meta['detectors'])}",
            *(f"- fixtures: `{f['path']}` sha256 `{f['sha256'][:16]}`" for f in meta["fixtures"]),
            "",
            "Leak = labelled values of mask-policy types that survive the masked text; "
            "blocked = the pipeline refused the document (fail closed, nothing sent).",
            "",
            render_attack_table(breakdown),
        ]
    )
    sys.stdout.write(markdown)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(scorecard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return 0
