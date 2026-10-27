"""One summary table for a comparison run: every system on every fixture, from scorecards.

```
python -m pii_guard.eval.baselines.table CARD.json [CARD.json ...] [--out FILE.md]
```

Rows are (fixture, system): pii-guard systems come from each scorecard's detectors (or its
``run.system`` when :mod:`pii_guard.eval.baselines.suite` wrote it), baselines from its
``baselines`` block. Columns: overlap P/R/F1, exact F1, leak, partial leak, over-masking, round
trip, detection p50/p95 and, when a ``run.llm`` block exists, the cost per 1,000 messages. A
fixture group is the set of fixture files a scorecard was run on.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

__all__ = ["main", "render_table", "rows"]

_NAMES = {
    "pii-guard rules": "pii-guard rules",
    "pii-guard rules+ner": "pii-guard fast",
    "pii-guard rules+ner+llm": "pii-guard audit",
}
ORDER = [
    "pii-guard rules",
    "pii-guard fast",
    "pii-guard audit",
    "presidio",
    "llm-guard",
    "privaite",
]


def _pct(value: object) -> str:
    return "-" if value is None else f"{float(value) * 100:.1f}"  # type: ignore[arg-type]


def _ms(value: object) -> str:
    if value is None:
        return "-"
    v = float(value)  # type: ignore[arg-type]
    return f"{v:,.0f}" if v >= 100 else f"{v:.1f}"


def rows(cards: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flat rows: fixture, system, documents, the metrics and $/1k (or None)."""
    out: list[dict[str, Any]] = []
    for card in cards:
        fixture = ", ".join(Path(f["path"]).stem for f in card["meta"]["fixtures"])
        own = "pii-guard " + "+".join(card["meta"]["detectors"])
        run = card.get("run") or {}
        systems: list[tuple[str, dict[str, Any], bool, float | None]] = [
            (
                _NAMES.get(own, own),
                card["overall"],
                True,
                (run.get("llm") or {}).get("usd_per_1k_messages"),
            )
        ]
        for name, section in card.get("baselines", {}).items():
            systems.append((name, section["overall"], bool(section.get("reversible")), None))
        for name, block, reversible, usd in systems:
            ov = block["detection"]["overlap"]["micro"]
            out.append(
                {
                    "fixture": fixture,
                    "system": name,
                    "documents": block["documents"],
                    "precision": ov["precision"],
                    "recall": ov["recall"],
                    "f1": ov["f1"],
                    "f1_exact": block["detection"]["exact"]["micro"]["f1"],
                    "leak": block["leak"]["rate"],
                    "partial_leak": block["leak"]["partial_rate"],
                    "over_masking": block["over_masking"]["rate"],
                    "roundtrip": block["roundtrip"]["rate"] if reversible else None,
                    "reversible": reversible,
                    "p50_ms": block["latency_ms"]["detect"]["p50"],
                    "p95_ms": block["latency_ms"]["detect"]["p95"],
                    "usd_per_1k": usd,
                }
            )
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for row in out:  # the first card with a (fixture, system) wins
        seen.setdefault((row["fixture"], row["system"]), row)
    fixtures = list(dict.fromkeys(r["fixture"] for r in out))
    rank = {name: i for i, name in enumerate(ORDER)}
    return sorted(
        seen.values(),
        key=lambda r: (fixtures.index(r["fixture"]), rank.get(r["system"], len(ORDER))),
    )


def render_table(cards: Sequence[dict[str, Any]]) -> str:
    lines = [
        "| Fixture | System | Docs | P | R | F1 | F1 exact | Leak | Partial leak "
        "| Over-masking | Round trip | p50 ms | p95 ms | $ / 1k msgs |",
        "|---|---|---:|" + "---:|" * 11,
    ]
    for r in rows(cards):
        rt = _pct(r["roundtrip"]) if r["reversible"] else "n/a"
        usd = "-" if r["usd_per_1k"] is None else f"{r['usd_per_1k']:.2f}"
        cells = [
            f"`{r['fixture']}`",
            r["system"],
            str(r["documents"]),
            _pct(r["precision"]),
            _pct(r["recall"]),
            _pct(r["f1"]),
            _pct(r["f1_exact"]),
            _pct(r["leak"]),
            _pct(r["partial_leak"]),
            _pct(r["over_masking"]),
            rt,
            _ms(r["p50_ms"]),
            _ms(r["p95_ms"]),
            usd,
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pii_guard.eval.baselines.table",
        description="One table of every system on every fixture, from scorecard JSON files.",
    )
    parser.add_argument("scorecards", nargs="+", type=Path, metavar="CARD.json")
    parser.add_argument("--out", type=Path, metavar="FILE.md")
    args = parser.parse_args(argv)
    cards = [json.loads(p.read_text(encoding="utf-8")) for p in args.scorecards]
    table = render_table(cards)
    sys.stdout.write(table)
    if args.out:
        args.out.write_text(table, encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
