"""The scorecard: a JSON document and its Markdown rendering.

Layout (``schema_version`` 1)::

    {"schema_version": 1,
     "meta": {"commit", "dirty", "pii_guard_version", "generated_at", "detectors",
              "skipped_detectors", "languages", "fixtures": [{"path", "sha256", "documents"}],
              "usage": {...}},  # only when a detector meters requests (the LLM detector)
     "overall": <block>,
     "languages": {"hu": <block>, "en": <block>}}

A ``<block>`` is :func:`pii_guard.eval.scorer.summarize`'s output. Nothing in the scorecard
contains a labelled value or a document text: only ids, types, counts and ratios.
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pii_guard import __version__
from pii_guard.eval.fixtures import file_sha256
from pii_guard.eval.scorer import DocumentResult, summarize
from pii_guard.eval.stats import fmt_ms, fmt_pct

__all__ = ["SCHEMA_VERSION", "build_scorecard", "git_commit", "price_usage", "render_markdown"]

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
    usage: Mapping[str, Mapping[str, int]] | None = None,
    price: Mapping[str, float | None] | None = None,
) -> dict[str, Any]:
    """The JSON scorecard: metadata, an overall block and one block per language.

    ``usage`` is :meth:`pii_guard.eval.scorer.DetectorAnalyzer.usage`; when it names a
    detector, ``meta.usage`` is added, priced with ``price`` (USD per 1M tokens: ``input``,
    ``cached``, ``output``) when that has an input or output rate.
    """
    commit_hash, dirty = commit if commit is not None else git_commit()
    by_language: dict[str, list[DocumentResult]] = defaultdict(list)
    for r in results:
        by_language[r.document.language].append(r)
    fixtures = []
    for path in fixture_paths:
        path = Path(path)
        fixtures.append({"path": str(path), "sha256": file_sha256(path)})
    card: dict[str, Any] = {
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
    if usage:
        card["meta"]["usage"] = usage_block(usage, messages=len(results), price=price)
    return card


def usage_block(
    usage: Mapping[str, Mapping[str, int]],
    *,
    messages: int,
    price: Mapping[str, float | None] | None = None,
) -> dict[str, Any]:
    """``meta.usage``: per-detector counters, their total, the refusal rate and the cost."""
    detectors = {name: dict(counters) for name, counters in usage.items()}
    total: dict[str, int] = {}
    for counters in detectors.values():
        for key, value in counters.items():
            total[key] = total.get(key, 0) + value
    requests = total.get("requests", 0)
    block: dict[str, Any] = {
        "messages": messages,
        "detectors": detectors,
        "total": total,
        "refusal_rate": total.get("refusals", 0) / requests if requests else None,
    }
    if price and (price.get("input") is not None or price.get("output") is not None):
        block["cost"] = price_usage(total, messages=messages, price=price)
    return block


def price_usage(
    total: Mapping[str, int], *, messages: int, price: Mapping[str, float | None]
) -> dict[str, Any]:
    """Dollar cost of ``total`` token counts at ``price`` (USD per 1M tokens).

    A missing ``cached`` rate falls back to the ``input`` rate; a missing rate is 0.
    """
    rate_in = float(price.get("input") or 0.0)
    cached_rate = price.get("cached")
    rate_cached = rate_in if cached_rate is None else float(cached_rate)
    rate_out = float(price.get("output") or 0.0)
    prompt = total.get("prompt_tokens", 0)
    cached = min(total.get("cached_tokens", 0), prompt)
    usd = (
        (prompt - cached) * rate_in
        + cached * rate_cached
        + total.get("completion_tokens", 0) * rate_out
    ) / 1_000_000
    return {
        "usd": usd,
        "usd_per_1k_messages": usd / messages * 1000 if messages else None,
        "prices_per_1m_tokens": {"input": rate_in, "cached": rate_cached, "output": rate_out},
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


def _usage_line(block: Mapping[str, Any]) -> str:
    total = block["total"]
    parts = [
        f"{total.get('requests', 0)} requests",
        f"{total.get('prompt_tokens', 0)} prompt tokens ({total.get('cached_tokens', 0)} cached)",
        f"{total.get('completion_tokens', 0)} completion tokens "
        f"({total.get('reasoning_tokens', 0)} reasoning)",
        f"{total.get('invalid_outputs', 0)} invalid outputs",
        f"{total.get('refusals', 0)} refusals ({fmt_pct(block.get('refusal_rate'), sign=True)})",
    ]
    cost = block.get("cost")
    if cost:
        per_1k = cost["usd_per_1k_messages"]
        parts.append(
            f"${cost['usd']:.4f} total, "
            + (f"${per_1k:.4f} per 1k messages" if per_1k is not None else "n/a per 1k messages")
        )
    return f"- LLM usage over {block['messages']} messages: " + ", ".join(parts)


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
    if meta.get("usage"):
        lines.append(_usage_line(meta["usage"]))
    lines += [
        "",
        "All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types "
        "(overlap match). Leak = labelled values of mask-policy types surviving the masked "
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
