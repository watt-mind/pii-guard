"""Apply the NER v4 gates and selection rule (LAB-1535) to the committed run records.

Reads ``eval/results/runs/<date>-lab-1535-<set>-<candidate>.json`` (written by ``eval_v3.py
score --ticket LAB-1535 --record``) and the latency JSON of ``modal_latency.py``, and prints
the gate table the README fixed before training. Counts only, never text::

    uv run --no-sync python training/ner/gates_v4.py --date 2026-10-29 \\
        --latency eval/results/2026-10-29-lab-1535-ner-v4/latency-cpu.json \\
        --json eval/results/2026-10-29-lab-1535-ner-v4/gates.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

RUNS = Path("eval/results/runs")
CANDIDATES = ("v4-a", "v4-b", "v4-braw")  # selection order
EU_LANGS = ("lv", "lt", "hr", "sl", "fr", "es", "it", "nl", "ro", "mt", "ga")


#: The ticket whose records are read (``--ticket``; LAB-1547 reuses the LAB-1535 gates).
TICKET = "lab-1535"


def _record(date: str, name: str, cand: str) -> dict[str, Any] | None:
    path = RUNS / f"{date}-{TICKET}-{name}-{cand}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["metrics"]


def _counts(block: dict[str, Any]) -> dict[str, int]:
    return {
        "values": block["leak"]["values"],
        "leaked": block["leak"]["leaked"],
        "masked": block["over_masking"]["masked"],
        "over": block["over_masking"]["over_masked"],
    }


def _add(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    return {k: a.get(k, 0) + b[k] for k in b}


def _rates(c: dict[str, int]) -> dict[str, float]:
    return {
        "leak": round(100 * c["leaked"] / c["values"], 2) if c["values"] else 0.0,
        "over": round(100 * c["over"] / c["masked"], 2) if c["masked"] else 0.0,
        "leaked": c["leaked"],
        "values": c["values"],
    }


def metrics(date: str, cand: str) -> dict[str, Any] | None:
    sets = {
        n: _record(date, n, cand)
        for n in (
            "smoke", "inflection", "agent-traffic-dev", "eu-smoke", "eu-inflection",
            "en-court", "mapa-eur-lex",
        )
    }  # fmt: skip
    if any(sets[n] is None for n in ("smoke", "inflection", "agent-traffic-dev")):
        return None
    out: dict[str, Any] = {
        n: _rates(_counts(m["overall"])) for n, m in sets.items() if m is not None
    }
    eu: dict[str, Any] = {}
    total: dict[str, int] = {}
    for lang in EU_LANGS:
        c: dict[str, int] = {}
        for n in ("eu-smoke", "eu-inflection"):
            block = (sets[n] or {}).get("languages", {}).get(lang)
            if block:
                c = _add(c, _counts(block))
        if c:
            eu[lang] = _rates(c)
            total = _add(total, c)
    if sets["en-court"] is not None:
        c = _counts(sets["en-court"]["overall"])
        eu["en-court"] = _rates(c)
        total = _add(total, c)
    out["eu"] = eu
    out["eu-total"] = _rates(total) if total else None
    return out


def gates(base: dict[str, Any], m: dict[str, Any], p95_ratio: float | None) -> dict[str, Any]:
    g: dict[str, Any] = {
        "smoke_leak": m["smoke"]["leak"] <= base["smoke"]["leak"],
        "smoke_over": m["smoke"]["over"] <= base["smoke"]["over"] + 0.5,
        "inflection_leak": m["inflection"]["leak"] <= base["inflection"]["leak"],
        "latency": None if p95_ratio is None else p95_ratio <= 1.2,
    }
    failed_langs = [
        lang
        for lang, r in m["eu"].items()
        if lang in base["eu"]
        and (r["leak"] > base["eu"][lang]["leak"] or r["over"] > base["eu"][lang]["over"] + 2.0)
    ]
    g["eu_per_language"] = not failed_langs
    g["eu_failed_languages"] = failed_langs
    g["eu_total_lower"] = m["eu-total"]["leak"] < base["eu-total"]["leak"]
    sel, ref = m["agent-traffic-dev"], base["agent-traffic-dev"]
    g["beats_v20"] = (
        sel["leak"] <= ref["leak"]
        and sel["over"] <= ref["over"]
        and (sel["leak"] < ref["leak"] or sel["over"] < ref["over"])
    )
    g["all_gates"] = all(
        g[k] is not False
        for k in ("smoke_leak", "smoke_over", "inflection_leak", "latency", "eu_per_language")
    ) and bool(g["eu_total_lower"])
    return g


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--date", required=True)
    parser.add_argument("--latency", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--ticket", default="LAB-1535", help="record slug (LAB-1547 for v4.1)")
    parser.add_argument("--candidates", nargs="+", default=list(CANDIDATES), help="in order")
    args = parser.parse_args(argv)
    global TICKET
    TICKET = args.ticket.lower()
    base = metrics(args.date, "v20")
    if base is None:
        print("no v2.0 records", file=sys.stderr)
        return 2
    p95: dict[str, float] = {}
    if args.latency and args.latency.is_file():
        res = json.loads(args.latency.read_text(encoding="utf-8"))["results"]
        p95 = {k: v["p95_ms"] / res["v20"]["p95_ms"] for k, v in res.items()}
    report: dict[str, Any] = {"v20": {"metrics": base}}
    winners: list[tuple[float, float, int, str]] = []
    for i, cand in enumerate(args.candidates):
        m = metrics(args.date, cand)
        if m is None:
            continue
        g = gates(base, m, p95.get(cand))
        report[cand] = {"metrics": m, "gates": g, "p95_ratio": p95.get(cand)}
        if g["all_gates"] and g["beats_v20"]:
            sel = m["agent-traffic-dev"]
            winners.append((sel["leak"], sel["over"], i, cand))
    report["selected"] = min(winners)[3] if winners else "v20 (stays)"
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
