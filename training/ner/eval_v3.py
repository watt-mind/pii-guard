"""Score NER v3 candidates against v2.0 (LAB-1393): fast mode on every set, and CPU latency.

``score`` runs pii-guard fast mode (rules + NER) with one candidate checkpoint over the whole
fast-mode suite (the LAB-1386 sets) plus pl-pii-bench and MAPA EUR-Lex (LAB-1392), and writes
one run record per set, ``eval/results/runs/<date>-lab-1393-<set>-<candidate>.json``. Run it
once per candidate, each in its own process (the NER backend is shared per process)::

    PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/eval_v3.py score \\
        --candidate v20 --record
    PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/eval_v3.py score \\
        --candidate xlmr-v3 --model models/ner/pii-guard-ner-xlmr-base-v3 --record

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
}
LABELS = {
    "v20": "pii-guard fast, NER v2.0 (published hdkiller/pii-guard-ner-xlmr-base, LAB-1306)",
    "xlmr-v3": "pii-guard fast, NER v3 candidate: XLM-R base on the v3 mix (LAB-1393)",
    "mmbert-v3": "pii-guard fast, NER v3 candidate: mmBERT-base on the v3 mix (LAB-1393)",
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
            "model_ref": f"hdkiller/pii-guard-ner-xlmr-base v2.0, revision {pub.revision[:12]}",
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
            "LAB-1393: NER v3 candidates vs v2.0, fast mode (rules + NER), CPU "
            "(PII_GUARD_NER_DEVICE=cpu), one commit.",
            f"Wall time {wall:.1f} s, load average at end {os.getloadavg()[0]:.1f}.",
        ]
        if name == "ai4privacy":
            notes.append("Every candidate trained on OpenPII train rows: in distribution here.")
        if name == "agent-traffic-dev":
            notes.append(
                "The v3 mix holds train-only agent-traffic documents from the same generator "
                "(seed 1393, near-copies removed by decontam.py): closer to distribution than "
                "for v2.0."
            )
        records = build_records(
            card,
            slug=f"lab-1393-{name}-{args.candidate}",
            detectors=detectors,
            hardware=host_info(),
            extra={"system": {"label": LABELS.get(args.candidate, args.candidate)}},
            notes=notes,
        )[:1]
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
    score.add_argument("--record", action="store_true")
    score.add_argument("--runs-dir", type=Path, default=Path("eval/results/runs"))
    score.add_argument("--scorecards", type=Path)
    score.add_argument("--summary", type=Path)
    lat = sub.add_parser("latency")
    lat.add_argument("--model", action="append", required=True, help="name=dir (empty: v2.0)")
    lat.add_argument("--n", type=int, default=150)
    lat.add_argument("--threads", type=int, default=8)
    lat.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    return _score(args) if args.command == "score" else _latency(args)


if __name__ == "__main__":
    sys.exit(main())
