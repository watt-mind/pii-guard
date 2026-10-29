"""Score NER v3 candidates against v2.0 (LAB-1393): fast mode on every set, and CPU latency.

``score`` runs pii-guard fast mode (rules + NER) with one candidate checkpoint over the whole
fast-mode suite (the LAB-1386 sets) plus pl-pii-bench and MAPA EUR-Lex (LAB-1392), and writes
one run record per set, ``eval/results/runs/<date>-lab-1393-<set>-<candidate>.json``. Run it
once per candidate, each in its own process (the NER backend is shared per process)::

    PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/eval_v3.py score \\
        --candidate v20 --record
    PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/eval_v3.py score \\
        --candidate xlmr-v3 --model models/ner/pii-guard-ner-xlmr-base-v3 --record

``--ticket LAB-1410`` scores the v3.1 candidates (records ``<date>-lab-1410-<set>-<name>``).

``latency`` times every candidate on the same ~400-character messages (hu + en synth samples),
alternating per message so changes in machine load hit all of them alike, NER only::

    uv run --no-sync python training/ner/eval_v3.py latency --json OUT.json \\
        --model v20= --model xlmr-v3=models/ner/pii-guard-ner-xlmr-base-v3

MAPA EUR-Lex is real court text: it is read from the local, git-ignored cache only and never
leaves this machine. Nothing written contains a document text or a labelled value.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

#: Languages with an ``eval/fixtures/eu`` smoke and inflection set (LAB-1525).
EU_GATE_LANGS = ("lv", "lt", "hr", "sl", "fr", "es", "it", "nl", "ro", "mt", "ga")
SETS: dict[str, list[str]] = {
    "smoke": [f"eval/fixtures/{lang}-smoke.jsonl" for lang in ("hu", "en", "de")],
    "inflection": ["eval/fixtures/hu-inflection.jsonl"],
    "agent-traffic-dev": [
        f"eval/synthetic/dev/{lang}-agent-traffic-dev.jsonl" for lang in ("hu", "en", "de")
    ],
    "agent-traffic": [f"eval/synthetic/{lang}-agent-traffic.jsonl" for lang in ("hu", "en", "de")],
    "ai4privacy": [f"eval/fixtures/public/{lang}-ai4privacy.jsonl" for lang in ("hu", "en", "de")],
    "nemotron-pii": ["eval/datasets/nemotron-pii/en-nemotron-pii.jsonl"],
    "cee-pii": [f"eval/datasets/cee-pii/{lang}-cee-pii.jsonl" for lang in ("hu", "en")],
    "gretel-finance": [
        f"eval/datasets/gretel-finance/{lang}-gretel-finance.jsonl" for lang in ("de", "en")
    ],
    "pl-pii-bench": ["eval/datasets/pl-pii-bench/pl-pl-pii-bench.jsonl"],
    "mapa-eur-lex": ["data/datasets/fixtures/mapa-eur-lex/*-mapa-eur-lex.jsonl"],
    # LAB-1525 fictional gate sets for the new languages (LAB-1535 gates, read per language).
    "eu-smoke": [f"eval/fixtures/eu/{lang}-smoke.jsonl" for lang in EU_GATE_LANGS],
    "eu-inflection": [f"eval/fixtures/eu/{lang}-inflection.jsonl" for lang in EU_GATE_LANGS],
    "en-court": ["eval/fixtures/eu/en-court-smoke.jsonl"],
}
#: Sets whose files share a name with another set (``eu/lv-smoke.jsonl`` vs ``hu-smoke.jsonl``):
#: their records get a fixture-set name of their own, so the report never pools them.
OWN_SET_NAME = {
    "eu-smoke": "eu-smoke",
    "eu-inflection": "eu-inflection",
    "en-court": "en-court-smoke",
}
LABELS = {
    "v20": "pii-guard fast, NER v2.0 (published watt-mind/pii-guard-ner-xlmr-base, LAB-1306)",
    "xlmr-v3": "pii-guard fast, NER v3 candidate: XLM-R base on the v3 mix (LAB-1393)",
    "mmbert-v3": "pii-guard fast, NER v3 candidate: mmBERT-base on the v3 mix (LAB-1393)",
    "v31-a": "pii-guard fast, NER v3.1 candidate A: v3 mix minus agent-traffic (LAB-1410)",
    "v31-b": "pii-guard fast, NER v3.1 candidate B: A + hu/s11 gold, Privy halved (LAB-1410)",
    "v31-c": "pii-guard fast, NER v3.1 candidate C: B without Wismut (LAB-1410)",
    "v32-s30": "pii-guard fast, NER v3.2 soup S30: 0.7 v2.0 + 0.3 v3.1-B (LAB-1494)",
    "v32-s50": "pii-guard fast, NER v3.2 soup S50: 0.5 v2.0 + 0.5 v3.1-B (LAB-1494)",
    "v32-s70": "pii-guard fast, NER v3.2 soup S70: 0.3 v2.0 + 0.7 v3.1-B (LAB-1494)",
    "v32-d": "pii-guard fast, NER v3.2 candidate D: v2.0 warm start + error-mined data (LAB-1494)",
    "v32-e": "pii-guard fast, NER v3.2 candidate E: v2.0 recipe + error-mined data (LAB-1494)",
    "v33-t1": "pii-guard fast, NER v3.3 candidate T1: S30 + targeted add-on, 1 epoch (LAB-1512)",
    "v33-t2": "pii-guard fast, NER v3.3 candidate T2: S30 + targeted add-on, 2 epochs (LAB-1512)",
    "v33-h": "pii-guard fast, NER v2.0 with dev-calibrated thresholds, candidate H (LAB-1512)",
    "v4-a": "pii-guard fast, NER v4 candidate A: v2.0 + EU phase-1 data, 1 epoch (LAB-1535)",
    "v4-b": "pii-guard fast, NER v4 candidate B: 0.5 v2.0 + 0.5 B-raw soup (LAB-1535)",
    "v4-braw": "pii-guard fast, NER v4 candidate B-raw: v2.0 + EU data, 2 epochs (LAB-1535)",
    "v41-a1": "pii-guard fast, NER v4.1 candidate A1: v4-A recipe + v4.1 data, loose ADDRESS "
    "kept out of the loss (LAB-1547)",
    "v41-a2": "pii-guard fast, NER v4.1 candidate A2: v4-A recipe + v4.1 data, loose ADDRESS "
    "taught as O (LAB-1547)",
}
#: Tickets whose v2.0 runs are selection-only re-scores (LAB-1494): their records get a system
#: key and label of their own, so the report's latest-per-system pick keeps the published v2.0
#: rows (timed on a quiet machine) instead of these, timed on a loaded one.
RESCORE_TICKETS = ("LAB-1494", "LAB-1512", "LAB-1535", "LAB-1547")


def system_extra(ticket: str, candidate: str) -> dict[str, Any]:
    """The ``system`` block merged into each record: label, and a re-score key for v2.0."""
    label = LABELS.get(candidate, candidate)
    if candidate != "v20" or ticket not in RESCORE_TICKETS:
        return {"label": label}
    tag = ticket.lower()
    return {
        "key": f"rules+ner:xlmr-base-v2-hn@rescore={tag}",
        "label": f"pii-guard fast, NER v2.0 (selection-only re-score, {ticket})",
    }


#: Per ticket: the record slug prefix and what the run notes say. ``--ticket`` picks one.
TICKETS = {
    "LAB-1393": "NER v3 candidates vs v2.0",
    "LAB-1410": "NER v3.1 candidates vs v2.0 (clean selection set: agent-traffic-dev)",
    "LAB-1494": "NER v3.2 candidates (soups, error-mined data) vs v2.0, v3.1 protocol",
    "LAB-1512": "NER v3.3 candidates (S30 + targeted add-on; thresholds) vs v2.0, v3.1 protocol",
    "LAB-1535": "NER v4 multilingual candidates (v2.0 + EU phase-1 data) vs v2.0, v3.1 protocol",
    "LAB-1547": "NER v4.1 candidates (v4-A recipe, loose addresses treated, v4.1 data) vs v2.0, "
    "LAB-1535 protocol",
}


def _paths(name: str) -> list[str]:
    out: list[str] = []
    for p in SETS[name]:
        out.extend(sorted(str(x) for x in Path().glob(p)) if "*" in p else [p])
    return [p for p in out if Path(p).is_file()]


def _detector(candidate: str, model: str | None) -> dict[str, Any]:
    from pii_guard.detect import ner_resolve
    from pii_guard.eval.stats import sha256_file

    if not model:
        pub = ner_resolve.PUBLISHED
        return {
            "name": "ner",
            "model": "xlmr-base-v2-hn",
            "model_ref": f"{pub.repo_id} v2.0, revision {pub.revision[:12]}",
            "revision": f"sha256:{pub.weights_sha256}",
            "settings": {},
            "serving": "local PyTorch, CPU",
        }
    weights = Path(model) / "model.safetensors"
    return {
        "name": "ner",
        "model": Path(model).name,
        "model_ref": f"{LABELS.get(candidate, candidate)}; local checkpoint, not published",
        "revision": f"sha256:{sha256_file(weights)}" if weights.is_file() else "unknown",
        "settings": {},
        "serving": "local PyTorch, CPU",
    }


def _score(args: argparse.Namespace) -> int:
    if args.model:
        os.environ["PII_GUARD_NER_MODEL"] = args.model
    thresholds: dict[str, Any] = {}
    if args.thresholds:  # LAB-1512 path 4: a dev-calibrated table (thresholds_v33.py)
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import thresholds_v33

        thresholds = json.loads(args.thresholds.read_text(encoding="utf-8"))["thresholds"]
        thresholds_v33.apply(thresholds)
    from pii_guard.eval.fixtures import load_fixtures
    from pii_guard.eval.record import build_records, host_info, write_records
    from pii_guard.eval.report import build_scorecard
    from pii_guard.eval.scorer import DetectorAnalyzer, run_documents

    analyzer = DetectorAnalyzer(["rules", "ner"])
    if analyzer.skipped:
        print(f"detector unavailable: {analyzer.skipped}", file=sys.stderr)
        return 2
    analyzer.analyze("Warm-up text without personal data.", "en")
    detectors = [{"name": "rules"}, _detector(args.candidate, args.model)]
    if thresholds:
        from pii_guard.eval.stats import sha256_file

        detectors[1]["settings"] = {
            "thresholds_file": str(args.thresholds),
            "thresholds_sha256": sha256_file(args.thresholds),
        }
    summary: dict[str, Any] = {}
    for name in args.sets:
        paths = _paths(name)
        if not paths:
            print(f"skip {name}: no fixture files", file=sys.stderr)
            continue
        started = time.perf_counter()
        results = run_documents(load_fixtures(paths), analyzer)
        wall = time.perf_counter() - started
        card = build_scorecard(results, detectors=analyzer.loaded, fixture_paths=paths)
        notes = [
            f"{args.ticket}: {TICKETS[args.ticket]}, fast mode (rules + NER), CPU "
            "(PII_GUARD_NER_DEVICE=cpu), one commit.",
            f"Wall time {wall:.1f} s, load average at end {os.getloadavg()[0]:.1f}.",
        ]
        if name == "ai4privacy":
            notes.append("Every candidate trained on OpenPII train rows: in distribution here.")
        if name == "agent-traffic-dev" and args.ticket == "LAB-1393":
            notes.append(
                "The v3 mix holds train-only agent-traffic documents from the same generator "
                "(seed 1393, near-copies removed by decontam.py): closer to distribution than "
                "for v2.0."
            )
        if name == "agent-traffic-dev" and args.ticket in (
            "LAB-1410",
            "LAB-1494",
            "LAB-1512",
            "LAB-1535",
        ):
            notes.append(
                "Selection set. No v3.1, v3.2, v3.3 or v4 mix holds any agent-traffic generator "
                "document, so it is unseen by every candidate, as it was for v2.0."
            )
        records = build_records(
            card,
            slug=f"{args.ticket.lower()}-{name}-{args.candidate}",
            detectors=detectors,
            hardware=host_info(),
            extra={"system": system_extra(args.ticket, args.candidate)},
            notes=notes,
        )[:1]
        if name in OWN_SET_NAME:  # the eu files are named <lang>-smoke too: keep them apart
            own = OWN_SET_NAME[name]
            records[0]["fixture_set"] = own
            records[0]["title"] = records[0]["title"].rsplit(" on ", 1)[0] + f" on {own}"
            for f in records[0]["fixtures"]:
                f["set"] = own
        overall = records[0]["metrics"]["overall"]
        summary[name] = {
            "documents": overall["documents"],
            "leak": overall["leak"]["rate"],
            "over_masking": overall["over_masking"]["rate"],
            "f1": overall["overlap"]["f1"],
        }
        print(
            f"{args.candidate:10s} {name:18s} docs={overall['documents']:4d} "
            f"leak={overall['leak']['rate']:.4f} over={overall['over_masking']['rate']:.4f} "
            f"f1={overall['overlap']['f1']:.4f} wall={wall:.0f}s",
            file=sys.stderr,
            flush=True,
        )
        if args.scorecards:
            args.scorecards.mkdir(parents=True, exist_ok=True)
            out = args.scorecards / f"{name}--{args.candidate}.json"
            out.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n")
        if args.record:
            write_records(records, args.runs_dir)
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, indent=2) + "\n")
    return 0


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _latency(args: argparse.Namespace) -> int:
    import torch

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bench_latency import messages

    from pii_guard.detect.ner import NerDetector

    torch.set_num_threads(args.threads)
    msgs = messages(
        ["eval/fixtures/hu-synth-sample.jsonl", "eval/fixtures/en-synth-sample.jsonl"],
        400,
        args.n,
    )
    models: dict[str, NerDetector] = {}
    load_s: dict[str, float] = {}
    for spec in args.model:
        name, _, path = spec.partition("=")
        started = time.perf_counter()
        models[name] = NerDetector(model=path or None, device="cpu", preload=True)
        load_s[name] = round(time.perf_counter() - started, 1)
        for language, text in msgs[:5]:
            models[name].detect(text, language)
    times: dict[str, list[float]] = {name: [] for name in models}
    for language, text in msgs:
        for name, detector in models.items():
            started = time.perf_counter()
            detector.detect(text, language)
            times[name].append((time.perf_counter() - started) * 1000)
    report = {
        "machine": f"{platform.machine()} {platform.platform()}",
        "torch": torch.__version__,
        "torch_threads": torch.get_num_threads(),
        "messages": len(msgs),
        "mean_chars": round(statistics.mean(len(t) for _, t in msgs), 1),
        "load_average_end": [round(x, 2) for x in os.getloadavg()],
        "results": {
            name: {
                "p50_ms": round(percentile(t, 0.5), 1),
                "p95_ms": round(percentile(t, 0.95), 1),
                "mean_ms": round(statistics.mean(t), 1),
                "load_s": load_s[name],
            }
            for name, t in times.items()
        },
    }
    print(json.dumps(report, indent=2))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score")
    score.add_argument("--candidate", required=True)
    score.add_argument("--model", help="checkpoint directory (default: the published v2.0)")
    score.add_argument("--sets", nargs="+", default=list(SETS), choices=list(SETS))
    score.add_argument("--ticket", default="LAB-1393", choices=list(TICKETS))
    score.add_argument("--record", action="store_true")
    score.add_argument("--runs-dir", type=Path, default=Path("eval/results/runs"))
    score.add_argument("--scorecards", type=Path)
    score.add_argument("--summary", type=Path)
    score.add_argument("--thresholds", type=Path, help="thresholds_v33.py JSON (candidate H)")
    lat = sub.add_parser("latency")
    lat.add_argument("--model", action="append", required=True, help="name=dir (empty: v2.0)")
    lat.add_argument("--n", type=int, default=150)
    lat.add_argument("--threads", type=int, default=8)
    lat.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    return _score(args) if args.command == "score" else _latency(args)


if __name__ == "__main__":
    sys.exit(main())
