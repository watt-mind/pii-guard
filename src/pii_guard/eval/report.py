"""The scorecard: a JSON document and its Markdown rendering.

Layout (``schema_version`` 1)::

    {"schema_version": 1,
     "meta": {"commit", "dirty", "pii_guard_version", "generated_at", "detectors",
              "skipped_detectors", "languages", "fixtures": [{"path", "sha256", "documents"}]},
     "overall": <block>,
     "languages": {"hu": <block>, "en": <block>}}

A ``<block>`` is :func:`pii_guard.eval.scorer.summarize`'s output. Nothing in the scorecard
contains a labeled value or a document text: only ids, types, counts and ratios.
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pii_guard import __version__
from pii_guard.eval.fixtures import file_sha256
from pii_guard.eval.scorer import DocumentResult, summarize
from pii_guard.eval.stats import fmt_ms, fmt_pct

__all__ = ["SCHEMA_VERSION", "build_scorecard", "git_commit", "render_markdown"]

SCHEMA_VERSION = 1


def git_commit(cwd: str | Path | None = None) -> tuple[str, bool]:
    """``(commit hash, dirty)`` of the working tree, or ``("unknown", False)``."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607 - git from PATH is intended
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],  # noqa: S607
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "unknown", False
    return head or "unknown", bool(status.strip())


def build_scorecard(
    results: Sequence[DocumentResult],
    *,
    detectors: Sequence[str],
    skipped_detectors: Sequence[tuple[str, str]] = (),
    fixture_paths: Sequence[str | Path] = (),
    languages: Sequence[str] | None = None,
    commit: tuple[str, bool] | None = None,
) -> dict[str, Any]:
    """The JSON scorecard: metadata, an overall block and one block per language."""
    commit_hash, dirty = commit if commit is not None else git_commit()
    by_language: dict[str, list[DocumentResult]] = defaultdict(list)
    for r in results:
        by_language[r.document.language].append(r)
    fixtures = []
    for path in fixture_paths:
        path = Path(path)
        fixtures.append({"path": str(path), "sha256": file_sha256(path)})
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "commit": commit_hash,
            "dirty": dirty,
            "pii_guard_version": __version__,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "detectors": list(detectors),
            "skipped_detectors": [{"name": n, "reason": why} for n, why in skipped_detectors],
            "languages": sorted(languages) if languages else None,
            "fixtures": fixtures,
        },
        "overall": summarize(results),
        "languages": {lang: summarize(by_language[lang]) for lang in sorted(by_language)},
    }


# --- Markdown ----------------------------------------------------------------------------


def _summary_row(name: str, block: dict[str, Any]) -> str:
    ex = block["detection"]["exact"]["micro"]
    ov = block["detection"]["overlap"]["micro"]
    leak, over = block["leak"], block["over_masking"]
    cells = [
        name,
        str(block["documents"]),
        str(block["gold_spans"]),
        str(block["predicted_spans"]),
        fmt_pct(ex["precision"]),
        fmt_pct(ex["recall"]),
        fmt_pct(ex["f1"]),
        fmt_pct(ov["precision"]),
        fmt_pct(ov["recall"]),
        fmt_pct(ov["f1"]),
        fmt_pct(block["detection"]["overlap"]["macro"]["f1"]),
        fmt_pct(leak["rate"]),
        fmt_pct(leak["partial_rate"]),
        fmt_pct(over["rate"]),
        fmt_pct(block["roundtrip"]["rate"]),
        fmt_pct((block.get("consistency") or {}).get("rate")),
        fmt_ms(block["latency_ms"]["detect"]["p50"], 2),
        fmt_ms(block["latency_ms"]["detect"]["p95"], 2),
    ]
    return "| " + " | ".join(cells) + " |"


def _type_rows(block: dict[str, Any]) -> list[str]:
    exact = block["detection"]["exact"]["per_type"]
    overlap = block["detection"]["overlap"]["per_type"]
    leaks = block["leak"]["per_type"]
    rows = []
    for name in exact:
        ex, ov = exact[name], overlap[name]
        leak = leaks.get(name)
        cells = [
            f"`{name}`",
            str(ex["gold"]),
            str(ex["pred"]),
            fmt_pct(ex["precision"]),
            fmt_pct(ex["recall"]),
            fmt_pct(ex["f1"]),
            fmt_pct(ov["precision"]),
            fmt_pct(ov["recall"]),
            fmt_pct(ov["f1"]),
            fmt_pct(leak["rate"]) if leak else "keep",
            fmt_pct(leak["partial_rate"]) if leak else "keep",
        ]
        rows.append("| " + " | ".join(cells) + " |")
    micro_ex = block["detection"]["exact"]["micro"]
    micro_ov = block["detection"]["overlap"]["micro"]
    rows.append(
        "| **all (micro)** | "
        + " | ".join(
            [
                str(micro_ex["gold"]),
                str(micro_ex["pred"]),
                fmt_pct(micro_ex["precision"]),
                fmt_pct(micro_ex["recall"]),
                fmt_pct(micro_ex["f1"]),
                fmt_pct(micro_ov["precision"]),
                fmt_pct(micro_ov["recall"]),
                fmt_pct(micro_ov["f1"]),
                fmt_pct(block["leak"]["rate"]),
                fmt_pct(block["leak"]["partial_rate"]),
            ]
        )
        + " |"
    )
    return rows


def render_markdown(scorecard: dict[str, Any]) -> str:
    """The scorecard as Markdown: a summary per language and overall, then per entity type."""
    meta = scorecard["meta"]
    commit = meta["commit"][:12] + (" (dirty)" if meta["dirty"] else "")
    lines = [
        "# pii-guard evaluation",
        "",
        f"- commit: `{commit}`, pii-guard {meta['pii_guard_version']}",
        f"- detectors: {', '.join(f'`{d}`' for d in meta['detectors']) or 'none'}",
    ]
    for skipped in meta["skipped_detectors"]:
        lines.append(f"- skipped detector `{skipped['name']}`: {skipped['reason']}")
    for fixture in meta["fixtures"]:
        lines.append(f"- fixtures: `{fixture['path']}` sha256 `{fixture['sha256'][:16]}`")
    if meta["languages"]:
        lines.append(f"- language filter: {', '.join(meta['languages'])}")
    lines += [
        "",
        "All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types "
        "(overlap match). Leak = labeled values of mask-policy types surviving the masked "
        "text in any surface form; partial = an identifying token survives. Consistency = "
        "gold entities whose occurrences (all surface forms) are masked by one placeholder.",
        "",
        "| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap "
        "| R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking "
        "| Round trip | Consistency | Detect p50 ms | Detect p95 ms |",
        "|---|" + "---:|" * 17,
    ]
    for lang, block in scorecard["languages"].items():
        lines.append(_summary_row(f"`{lang}`", block))
    lines.append(_summary_row("**overall**", scorecard["overall"]))
    sections = [*scorecard["languages"].items()]
    if len(sections) > 1:
        sections.append(("overall", scorecard["overall"]))
    for name, block in sections:
        lines += [
            "",
            f"## Per entity type: {name if name == 'overall' else f'`{name}`'}",
            "",
            "| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap "
            "| R overlap | F1 overlap | Leak | Partial leak |",
            "|---|" + "---:|" * 10,
            *_type_rows(block),
        ]
    return "\n".join(lines) + "\n"
