"""p50/p95 latency of the ``ner`` detector per ~400-character message, per device.

Messages are cut from fictional fixture documents at whitespace (about 400 characters each).
The model is loaded and warmed up first; the timed call is ``NerDetector.detect`` (tokenise,
forward pass, decode, thresholds).

::

    uv run --extra ner python training/ner/bench_latency.py --devices cpu,mps \
        --model models/ner/pii-guard-ner-xlmr-base --json eval/results/ner-latency.json
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

import torch

from pii_guard.detect.ner import NerDetector
from pii_guard.eval.fixtures import load_fixtures


def messages(paths: list[str], size: int, limit: int) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for doc in load_fixtures(paths):
        text = doc.text
        start = 0
        while start < len(text) and len(out) < limit:
            end = min(len(text), start + size)
            if end < len(text):
                cut = text.rfind(" ", start + size // 2, end)
                end = cut if cut > start else end
            chunk = text[start:end].strip()
            if len(chunk) >= size // 2:
                out.append((doc.language, chunk))
            start = end
    return out[:limit]


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def bench(
    model: str | None,
    device: str,
    msgs: list[tuple[str, str]],
    threads: int | None,
    backend: str = "transformers",
) -> dict:
    if threads:
        torch.set_num_threads(threads)
    if backend == "gliner":
        from pii_guard.detect.ner_gliner import GlinerDetector

        detector: NerDetector = GlinerDetector(model=model, device=device, preload=True)
    else:
        detector = NerDetector(model=model, device=device, preload=True)
    for language, text in msgs[:5]:
        detector.detect(text, language)
    times: list[float] = []
    for language, text in msgs:
        started = time.perf_counter()
        detector.detect(text, language)
        if device == "mps":
            torch.mps.synchronize()
        times.append((time.perf_counter() - started) * 1000)
    return {
        "device": device,
        "torch_threads": torch.get_num_threads(),
        "messages": len(times),
        "mean_chars": round(statistics.mean(len(t) for _, t in msgs), 1),
        "p50_ms": round(percentile(times, 0.50), 1),
        "p95_ms": round(percentile(times, 0.95), 1),
        "mean_ms": round(statistics.mean(times), 1),
        "load_average": [round(x, 2) for x in os.getloadavg()],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", help="hub id or directory (default: the detector default)")
    parser.add_argument("--devices", default="cpu", help="comma-separated: cpu,mps,cuda")
    parser.add_argument(
        "--fixtures",
        action="append",
        default=None,
        help="fixture files (default: the hu/en synth samples)",
    )
    parser.add_argument("--chars", type=int, default=400)
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--threads", type=int, help="torch CPU threads (default: torch's)")
    parser.add_argument(
        "--backend",
        choices=("transformers", "gliner"),
        default="transformers",
        help="gliner: a GLiNER hub id or directory (LAB-1150)",
    )
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    paths = args.fixtures or [
        "eval/fixtures/hu-synth-sample.jsonl",
        "eval/fixtures/en-synth-sample.jsonl",
    ]
    msgs = messages(paths, args.chars, args.n)
    results = [
        bench(args.model, d.strip(), msgs, args.threads, args.backend)
        for d in args.devices.split(",")
    ]
    report = {
        "model": args.model or "default",
        "machine": f"{platform.machine()} {platform.platform()}",
        "processor": platform.processor(),
        "torch": torch.__version__,
        "fixtures": paths,
        "results": results,
    }
    print(json.dumps(report, indent=2))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
