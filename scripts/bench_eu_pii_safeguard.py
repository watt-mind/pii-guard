"""Benchmark ``tabularisai/eu-pii-safeguard`` against pii-guard's NER v2.0 (LAB-1386).

Evaluation only: scores four configurations on the same sets and commit, fast mode, CPU.

- ``ner-v20``: pii-guard's NER alone, the published ``watt-mind/pii-guard-ner-xlmr-base`` v2.0;
- ``fast-v20``: rules + that NER (pii-guard fast mode);
- ``eu-pii-safeguard``: the comparison model alone;
- ``fast-eu-pii-safeguard``: rules + the comparison model in place of pii-guard's NER.

Both models run through pii-guard's NER post-processing, resolver and vault
(:mod:`pii_guard.eval.baselines.eu_pii_safeguard`), and are scored by the same scorer as
``pii-guard eval``. ``score`` writes one run record per set and configuration,
``eval/results/runs/<date>-lab-1386-<set>-<config>.json`` (with ``--record``), and the labels
the comparison model emitted that have no pii-guard type. ``latency`` times both models on
the same ~400-character messages, alternating per message, and reports load time and size.
Nothing written contains a document text or a labelled value::

    PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/bench_eu_pii_safeguard.py \
        score --record --summary eval/results/2026-10-28-eu-pii-safeguard/unmapped.json
    PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/bench_eu_pii_safeguard.py \
        latency --json eval/results/2026-10-28-eu-pii-safeguard/latency-cpu.json
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

from pii_guard.detect import ner_resolve
from pii_guard.eval.baselines import eu_pii_safeguard as eu
from pii_guard.eval.fixtures import load_fixtures
from pii_guard.eval.record import build_records, host_info, write_records
from pii_guard.eval.report import build_scorecard
from pii_guard.eval.scorer import DetectorAnalyzer, run_documents

SETS: dict[str, list[str]] = {
    "smoke": [
        "eval/fixtures/hu-smoke.jsonl",
        "eval/fixtures/en-smoke.jsonl",
        "eval/fixtures/de-smoke.jsonl",
    ],
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
}

_OURS = ner_resolve.PUBLISHED
_OURS_DETECTOR = {
    "name": "ner",
    "model": "xlmr-base-v2-hn",
    "model_ref": (
        f"watt-mind/pii-guard-ner-xlmr-base v2.0 (LAB-1306), revision {_OURS.revision[:12]}; "
        "the LAB-1150 checkpoint pii-guard-ner-xlmr-base-v2-hn"
    ),
    "revision": f"sha256:{_OURS.weights_sha256}",
    "settings": {},
    "serving": "local PyTorch, CPU",
}
_THEIRS_DETECTOR = {
    "name": "ner",
    "model": "eu-pii-safeguard",
    "model_ref": (
        f"{eu.MODEL.repo_id} revision {eu.MODEL.revision}, XLM-R large, 42 labels, label adapter "
        f"pii_guard.eval.baselines.eu_pii_safeguard (LAB-1386); licence {eu.MODEL.licence}"
    ),
    "revision": f"sha256:{eu.MODEL.weights_sha256}",
    "settings": {},
    "serving": "local PyTorch, CPU",
}
_RULES = {"name": "rules"}

#: config -> (registry names, detectors for the record, label)
CONFIGS: dict[str, tuple[list[str], list[dict[str, Any]], str]] = {
    "ner-v20": (["ner"], [_OURS_DETECTOR], "pii-guard NER v2.0 alone (no rules)"),
    "fast-v20": (
        ["rules", "ner"],
        [_RULES, _OURS_DETECTOR],
        "pii-guard fast, NER v2 base + hard negatives (LAB-1150)",
    ),
    "eu-pii-safeguard": (
        [eu.DETECTOR_NAME],
        [_THEIRS_DETECTOR],
        "tabularisai/eu-pii-safeguard alone (comparison, LAB-1386)",
    ),
    "fast-eu-pii-safeguard": (
        ["rules", eu.DETECTOR_NAME],
        [_RULES, _THEIRS_DETECTOR],
        "rules + tabularisai/eu-pii-safeguard in place of pii-guard NER (comparison, LAB-1386)",
    ),
}

_NOTE = (
    "LAB-1386: tabularisai/eu-pii-safeguard benchmarked against pii-guard NER v2.0 on one "
    "commit, CPU (PII_GUARD_NER_DEVICE=cpu), both models through pii-guard's NER "
    "post-processing; labels without a pii-guard type are dropped before scoring "
    "(docs/evaluation.md, 'eu-pii-safeguard')."
)
_AI4PRIVACY_NOTE = (
    "pii-guard NER v2 trained on OpenPII train rows: in distribution here. The comparison "
    "model's training data is not disclosed."
)


def _score(args: argparse.Namespace) -> int:
    eu.register()
    unmapped: dict[str, dict[str, int]] = {}
    for config in args.configs:
        names, detectors, label = CONFIGS[config]
        analyzer = DetectorAnalyzer(names)
        if analyzer.skipped:
            print(f"{config}: detector unavailable: {analyzer.skipped}", file=sys.stderr)
            return 2
        analyzer.analyze("Warm-up text without personal data.", "en")
        theirs = next(
            (d for d in analyzer.detectors if isinstance(d, eu.EuPiiSafeguardDetector)), None
        )
        for name in args.sets:
            paths = SETS[name]
            if theirs is not None:
                theirs.unmapped.clear()
            started = time.perf_counter()
            results = run_documents(load_fixtures(paths), analyzer)
            wall = time.perf_counter() - started
            card = build_scorecard(results, detectors=analyzer.loaded, fixture_paths=paths)
            notes = [
                _NOTE,
                f"Wall time {wall:.1f} s, load average at end {os.getloadavg()[0]:.1f}.",
            ]
            if name == "ai4privacy":
                notes.append(_AI4PRIVACY_NOTE)
            if theirs is not None:
                counts = dict(sorted(theirs.unmapped.items()))
                unmapped.setdefault(name, {}).update(
                    {f"{config}:{k}": v for k, v in counts.items()}
                )
                if counts:
                    notes.append(
                        "comparison-model labels dropped (no pii-guard type): "
                        + ", ".join(f"{k} {v}" for k, v in counts.items())
                    )
            records = build_records(
                card,
                slug=f"lab-1386-{name}-{config}",
                detectors=detectors,
                hardware=host_info(),
                extra={"system": {"label": label}},
                notes=notes,
            )[:1]
            overall = records[0]["metrics"]["overall"]
            print(
                f"{config:24s} {name:18s} docs={overall['documents']:4d} "
                f"leak={overall['leak']['rate']:.4f} f1={overall['overlap']['f1']:.4f} "
                f"over={overall['over_masking']['rate']:.4f} wall={wall:.0f}s",
                file=sys.stderr,
                flush=True,
            )
            if args.scorecards:
                args.scorecards.mkdir(parents=True, exist_ok=True)
                out = args.scorecards / f"{name}--{config}.json"
                out.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n")
            if args.record:
                for path in write_records(records, args.runs_dir):
                    print(f"wrote {path}", file=sys.stderr)
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(unmapped, indent=2, sort_keys=True) + "\n")
    return 0


def _messages(paths: list[str], size: int, limit: int) -> list[tuple[str, str]]:
    """~``size``-character messages cut at whitespace (as ``training/ner/bench_latency.py``)."""
    out: list[tuple[str, str]] = []
    for doc in load_fixtures(paths):
        text, start = doc.text, 0
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


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _latency(args: argparse.Namespace) -> int:
    import torch
    import transformers  # imported before timing, so neither load pays for it

    from pii_guard.detect.ner import NerDetector

    transformers.AutoModelForTokenClassification  # noqa: B018 - resolve the lazy import
    transformers.AutoTokenizer  # noqa: B018

    msgs = _messages(args.fixtures, args.chars, args.n)
    models: dict[str, Any] = {}
    info: dict[str, dict[str, Any]] = {}
    for key, factory, pinned in (
        ("pii-guard-ner-v2.0", lambda: NerDetector(device="cpu"), _OURS),
        ("eu-pii-safeguard", lambda: eu.EuPiiSafeguardDetector(device="cpu"), eu.MODEL),
    ):
        started = time.perf_counter()
        detector = factory()
        load_s = time.perf_counter() - started
        backend = detector.load()
        params = sum(p.numel() for p in backend.model.parameters())  # type: ignore[attr-defined]
        weights = pinned.local_dir() / "model.safetensors"
        info[key] = {
            "model": f"{pinned.repo_id}@{pinned.revision}",
            "licence": pinned.licence,
            "parameters": params,
            "weights_bytes": weights.stat().st_size,
            "load_s": round(load_s, 2),
        }
        models[key] = detector
    times: dict[str, list[float]] = {k: [] for k in models}
    for language, text in msgs[:5]:  # warm-up
        for detector in models.values():
            detector.detect(text, language)
    for language, text in msgs:  # alternate, so load changes hit both models alike
        for key, detector in models.items():
            started = time.perf_counter()
            detector.detect(text, language)
            times[key].append((time.perf_counter() - started) * 1000)
    for key, values in times.items():
        info[key].update(
            {
                "p50_ms": round(_pct(values, 0.50), 1),
                "p95_ms": round(_pct(values, 0.95), 1),
                "mean_ms": round(statistics.mean(values), 1),
            }
        )
    report = {
        "device": "cpu",
        "torch": torch.__version__,
        "torch_threads": torch.get_num_threads(),
        "machine": f"{platform.machine()} {platform.platform()}",
        "fixtures": args.fixtures,
        "messages": len(msgs),
        "mean_chars": round(statistics.mean(len(t) for _, t in msgs), 1),
        "load_average_end": [round(x, 2) for x in os.getloadavg()],
        "note": (
            "load_s: detector construction and warm-up forward in one process, torch and "
            "transformers already imported; weights may be in the OS page cache"
        ),
        "models": info,
    }
    print(json.dumps(report, indent=2))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score", help="score the configurations on the sets")
    score.add_argument("--configs", nargs="+", choices=list(CONFIGS), default=list(CONFIGS))
    score.add_argument("--sets", nargs="+", choices=list(SETS), default=list(SETS))
    score.add_argument("--record", action="store_true", help="write run records")
    score.add_argument("--runs-dir", type=Path, default=Path("eval/results/runs"))
    score.add_argument("--scorecards", type=Path, help="also write each scorecard here")
    score.add_argument("--summary", type=Path, help="dropped comparison-model labels (JSON)")
    latency = sub.add_parser("latency", help="CPU latency, load time and size of both models")
    latency.add_argument(
        "--fixtures",
        nargs="+",
        default=["eval/fixtures/hu-synth-sample.jsonl", "eval/fixtures/en-synth-sample.jsonl"],
    )
    latency.add_argument("--chars", type=int, default=400)
    latency.add_argument("--n", type=int, default=200)
    latency.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    return _score(args) if args.command == "score" else _latency(args)


if __name__ == "__main__":
    sys.exit(main())
