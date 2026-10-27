"""The LAB-1150 results table: candidates x fixtures (leak, F1, over-masking, p50/p95).

Reads ``<dir>/<fixture>--<candidate>.json`` scorecards and prints Markdown: one row per
fixture and candidate (overlap F1, leak, over-masking in %, detection p50/p95 in ms), then the
**pooled ai4privacy leak** per candidate (leaked values / values over hu + en + de) and the
smoke-set maximum leak and over-masking, the numbers the acceptance criteria name::

    uv run --no-sync python training/ner/table.py eval/results/2026-10-27-ner-v2/scorecards \\
        --out eval/results/2026-10-27-ner-v2/table.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ORDER = (
    "xlmr-large-v1",
    "xlmr-base-v2",
    "xlmr-large-v2",
    "xlmr-large-v2-no-ai4privacy",
    "xlmr-base-v2-no-ai4privacy",
    "xlmr-base-v2-openpii-1k",
    "xlmr-large-v2-openpii-1k",
    "xlmr-base-v2-hn",
    "xlmr-large-v2-hn",
    "davlan-xlmr-base-zero-shot",
    "gliner-multi-zero-shot",
    "gliner-multi-v2",
    "xlmr-base-v2-hn-gliner-union",
)
SMOKE = ("hu-smoke", "en-smoke", "de-smoke")
PUBLIC = ("hu-ai4privacy", "en-ai4privacy", "de-ai4privacy")


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{100 * x:.1f}"


def _ms(x: float | None) -> str:
    return "-" if x is None else (f"{x:.0f}" if x >= 100 else f"{x:.1f}")


def load(directory: Path) -> dict[str, dict[str, dict[str, Any]]]:
    cards: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for path in sorted(directory.glob("*--*.json")):
        fixture, _, candidate = path.stem.partition("--")
        cards[candidate][fixture] = json.loads(path.read_text(encoding="utf-8"))["overall"]
    return cards


def render(cards: dict[str, dict[str, dict[str, Any]]]) -> str:
    candidates = [c for c in ORDER if c in cards] + sorted(set(cards) - set(ORDER))
    fixtures: list[str] = []
    for c in candidates:
        fixtures += [f for f in cards[c] if f not in fixtures]
    lines = [
        "| Fixture | Candidate | F1 | Leak | Over-masking | p50 ms | p95 ms |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for f in fixtures:
        for c in candidates:
            o = cards[c].get(f)
            if o is None:
                continue
            lat = o.get("latency_ms", {}).get("detect", o.get("latency_ms", {}))
            lines.append(
                f"| `{f}` | {c} | {_pct(o['detection']['overlap']['micro']['f1'])} | "
                f"{_pct(o['leak']['rate'])} | {_pct(o['over_masking']['rate'])} | "
                f"{_ms(lat.get('p50'))} | {_ms(lat.get('p95'))} |"
            )
    lines += [
        "",
        "| Candidate | ai4privacy leak, pooled | ai4privacy F1 (mean) | smoke leak, max | "
        "smoke over-masking, max |",
        "|---|---:|---:|---:|---:|",
    ]
    for c in candidates:
        pub = [cards[c][f] for f in PUBLIC if f in cards[c]]
        smoke = [cards[c][f] for f in SMOKE if f in cards[c]]
        pooled = (
            sum(o["leak"]["leaked"] for o in pub) / sum(o["leak"]["values"] for o in pub)
            if len(pub) == len(PUBLIC)
            else None
        )
        f1 = sum(o["detection"]["overlap"]["micro"]["f1"] for o in pub) / len(pub) if pub else None
        lines.append(
            f"| {c} | {_pct(pooled)} | {_pct(f1)} | "
            f"{_pct(max((o['leak']['rate'] for o in smoke), default=None))} | "
            f"{_pct(max((o['over_masking']['rate'] for o in smoke), default=None))} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    text = render(load(args.directory))
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
