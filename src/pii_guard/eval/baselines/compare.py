"""Side-by-side comparison of pii-guard and the baselines, from one or more scorecards.

```
python -m pii_guard.eval.baselines.compare CARD.json [CARD.json ...] [--out FILE.md]
```

Scorecards are grouped by fixture set (file names and SHA-256; a scorecard on a subset of a
set's files, such as one language, joins it): each group gets a summary table
per language and a per-entity-type recall table, with one row per system. A system is a
pii-guard detector combination (``pii-guard rules``, ``pii-guard rules+llm``) or a baseline;
the first scorecard that has it wins.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval.stats import fmt_ms, fmt_pct
from pii_guard.types import EntityType

__all__ = ["main", "render_comparison", "systems"]


def systems(scorecard: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """``(system name, section)`` for pii-guard and every baseline in one scorecard.

    A section has ``overall`` and ``languages`` blocks, plus ``reversible`` for baselines.
    """
    detectors = scorecard["meta"]["detectors"]
    out: list[tuple[str, dict[str, Any]]] = [
        (f"pii-guard {'+'.join(detectors)}", {**scorecard, "reversible": True})
    ]
    for name, section in scorecard.get("baselines", {}).items():
        out.append((name, section))
    return out


def _fixture_key(scorecard: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple((Path(f["path"]).name, f["sha256"]) for f in scorecard["meta"]["fixtures"])


def _summary_table(rows: list[tuple[str, dict[str, Any], bool]]) -> list[str]:
    lines = [
        "| System | Docs | P overlap | R overlap | F1 overlap | F1 exact | Leak "
        "| Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |",
        "|---|" + "---:|" * 11,
    ]
    for name, block, reversible in rows:
        ov = block["detection"]["overlap"]["micro"]
        ex = block["detection"]["exact"]["micro"]
        cells = [
            name,
            str(block["documents"]),
            fmt_pct(ov["precision"]),
            fmt_pct(ov["recall"]),
            fmt_pct(ov["f1"]),
            fmt_pct(ex["f1"]),
            fmt_pct(block["leak"]["rate"]),
            fmt_pct(block["leak"]["partial_rate"]),
            fmt_pct(block["over_masking"]["rate"]),
            fmt_pct(block["roundtrip"]["rate"]) if reversible else "n/a",
            fmt_ms(block["latency_ms"]["detect"]["p50"]),
            fmt_ms(block["latency_ms"]["detect"]["p95"]),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _type_table(rows: list[tuple[str, dict[str, Any], bool]]) -> list[str]:
    present: set[str] = set()
    for _, block, _ in rows:
        present |= {
            t for t, c in block["detection"]["overlap"]["per_type"].items() if c["gold"] > 0
        }
    types = [t.value for t in EntityType if t.value in present]
    if not types:
        return []
    gold = {}
    for _, block, _ in rows:
        for t in types:
            gold.setdefault(t, block["detection"]["overlap"]["per_type"].get(t, {}).get("gold"))
    lines = [
        "| Entity type | Gold | " + " | ".join(name for name, _, _ in rows) + " |",
        "|---|---:|" + "---:|" * len(rows),
    ]
    for t in types:
        cells = [f"`{t}`", str(gold.get(t) or 0)]
        for _, block, _ in rows:
            counts = block["detection"]["overlap"]["per_type"].get(t)
            recall = fmt_pct(counts["recall"]) if counts else "0.0"
            leak = block["leak"]["per_type"].get(t)
            cells.append(recall + (f" / {fmt_pct(leak['rate'])}" if leak else ""))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _configs(scorecards: Sequence[dict[str, Any]]) -> list[str]:
    seen: dict[str, dict[str, Any]] = {}
    for card in scorecards:
        for name, section in card.get("baselines", {}).items():
            seen.setdefault(name, section)
    if not seen:
        return []
    lines = ["", "### Baseline configurations", ""]
    for name, section in seen.items():
        info = section.get("info", {})
        versions = ", ".join(f"{k} {v}" for k, v in info.get("versions", {}).items())
        lines.append(f"- **{name}**: {versions}")
        for model in info.get("models", []):
            lines.append(f"  - model: `{model}`")
        unmapped = section.get("unmapped_labels") or {}
        if unmapped:
            listed = ", ".join(f"`{k}` x{v}" for k, v in unmapped.items())
            lines.append(f"  - unmapped labels (masked, not scored for P/R): {listed}")
    host = next(
        (s.get("info", {}).get("host") for s in seen.values() if s.get("info", {}).get("host")),
        None,
    )
    if host:
        lines += [
            "",
            f"Latency measured on {host.get('machine')} ({host.get('platform')}, "
            f"{host.get('cpu_count')} CPUs), CPU only, single process, after one warm-up call.",
        ]
    return lines


def render_comparison(scorecards: Sequence[dict[str, Any]]) -> str:
    """The comparison as Markdown (see the module docstring)."""
    # A card run on a subset of a group's fixtures (one language, say) joins that group.
    groups: dict[tuple[tuple[str, str], ...], list[dict[str, Any]]] = {}
    for card in sorted(scorecards, key=lambda c: -len(_fixture_key(c))):
        key = _fixture_key(card)
        home = next((k for k in groups if set(key) <= set(k)), key)
        groups.setdefault(home, []).append(card)
    lines = [
        "# pii-guard vs open-source baselines",
        "",
        "All ratios in %. P/R/F1 are span-level micro averages over pii-guard's entity "
        "types (tool labels mapped as in docs/evaluation.md). Leak = labelled values of "
        "mask-policy types surviving the text each system would send upstream (its own "
        "masking). Latency is detection only.",
    ]
    for key, cards in groups.items():
        # Per language, the first card that scored a system on it supplies its row.
        by_language: dict[str, dict[str, tuple[dict[str, Any], bool]]] = {}
        for card in cards:
            for name, section in systems(card):
                for lang, block in section["languages"].items():
                    reversible = bool(section.get("reversible", True))
                    by_language.setdefault(lang, {}).setdefault(name, (block, reversible))
        commits = sorted(
            {c["meta"]["commit"][:12] + (" (dirty)" if c["meta"]["dirty"] else "") for c in cards}
        )
        lines += [
            "",
            f"## Fixtures: {', '.join(f'`{n}`' for n, _ in key)}",
            "",
            "- fixture sha256: " + ", ".join(f"`{n}` `{sha[:16]}`" for n, sha in key),
            f"- commit: {', '.join(f'`{c}`' for c in commits)}",
        ]
        for lang in sorted(by_language):
            rows = [(name, block, rev) for name, (block, rev) in by_language[lang].items()]
            lines += ["", f"### `{lang}`", "", *_summary_table(rows)]
            type_lines = _type_table(rows)
            if type_lines:
                lines += [
                    "",
                    f"Per entity type, `{lang}`: overlap recall / leak rate "
                    "(leak only for mask-policy types).",
                    "",
                    *type_lines,
                ]
    lines += _configs(scorecards)
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pii_guard.eval.baselines.compare",
        description="Render the pii-guard vs baselines comparison from scorecard JSON files.",
    )
    parser.add_argument("scorecards", nargs="+", type=Path, metavar="CARD.json")
    parser.add_argument("--out", type=Path, metavar="FILE.md", help="also write it here")
    args = parser.parse_args(argv)
    cards = [json.loads(p.read_text(encoding="utf-8")) for p in args.scorecards]
    markdown = render_comparison(cards)
    sys.stdout.write(markdown)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
