"""One pii-guard configuration over one fixture file, with what a comparison run needs to record.

```
python -m pii_guard.eval.baselines.suite --system fast --fixtures eval/fixtures/hu-smoke.jsonl \\
    --json OUT.json [--markdown OUT.md]
```

``pii-guard eval`` scores detectors; this wraps the same scorer for a named *system*
(:data:`SYSTEMS`: ``rules``, ``fast`` = rules + NER, ``escalate`` = fast + the LLM on uncertain
spans only, ``audit`` = rules + NER + LLM, as the gateway's modes are built) and adds a ``run``
block to the scorecard:

- one warm-up call before timing (as the baselines get), so a model load isn't a p95 outlier;
- the NER checkpoint's identity (``PII_GUARD_NER_MODEL`` and the SHA-256 of its
  ``model.safetensors``) and the LLM endpoint, model and reasoning effort (never the key);
- the LLM detector's token usage, the cost at :data:`BASETEN_PRICE_USD_PER_1M` and the cost
  per 1,000 messages (one fixture document = one message);
- for ``escalate``: the escalation rate (documents sent to the LLM), windows and characters
  sent, fail-closed calls, and the latency escalation adds per document (p50/p95, all documents
  and escalated ones only), with the gateway's default ``escalate_*`` settings;
- wall time and the host's load average at start and end, since latency depends on it;
- documents a detector failed on (the pipeline fails closed, so the gateway would have
  refused that request): counted in ``run.blocked``, left out of the scores.

Nothing in the output contains a document text or a labelled value.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from pii_guard.eval.baselines.base import host_info
from pii_guard.eval.fixtures import FixtureError, load_fixtures
from pii_guard.eval.injection import run_injection
from pii_guard.eval.report import build_scorecard, render_markdown
from pii_guard.eval.scorer import DetectorAnalyzer
from pii_guard.eval.stats import sha256_file
from pii_guard.gateway.config import cli_mode
from pii_guard.types import PiiGuardError

__all__ = [
    "BASETEN_PRICE_USD_PER_1M",
    "SYSTEMS",
    "EscalateAnalyzer",
    "cost_usd",
    "main",
    "ner_identity",
]

SYSTEMS: dict[str, list[str]] = {
    "rules": ["rules"],
    "fast": ["rules", "ner"],
    "escalate": ["rules", "ner", "llm"],
    "audit": ["rules", "ner", "llm"],
}

#: Baseten Model APIs, Muse Spark Open (baseten.co/pricing, 2026-10-27); reasoning = output.
BASETEN_PRICE_USD_PER_1M = {"input": 1.25, "cached_input": 0.15, "output": 4.25}

_WARMUP = ("Warm-up text without personal data.", "en")


def cost_usd(
    usage: Mapping[str, int], price: Mapping[str, float] = BASETEN_PRICE_USD_PER_1M
) -> float:
    """Cost of ``usage`` (the LLM detector's counters) at ``price`` per million tokens."""
    prompt = usage.get("prompt_tokens", 0)
    cached = usage.get("cached_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    return (
        (prompt - cached) * price["input"]
        + cached * price["cached_input"]
        + completion * price["output"]
    ) / 1_000_000


def ner_identity() -> dict[str, Any]:
    """Which NER model ran: the configured path or hub id and, for a directory, weight hashes."""
    model = os.environ.get("PII_GUARD_NER_MODEL")
    out: dict[str, Any] = {"model": model or "default (see docs/models.md)"}
    if model and Path(model).is_dir():
        out["model"] = Path(model).name  # a local directory: its name, not the user's path
        weights = sorted(Path(model).glob("*.safetensors"))
        out["safetensors_sha256"] = {w.name: sha256_file(w) for w in weights}
        meta = Path(model) / "training_meta.json"
        if meta.is_file():
            out["training_meta_sha256"] = sha256_file(meta)
    device = os.environ.get("PII_GUARD_NER_DEVICE")
    out["device"] = device or "auto"
    return out


class EscalateAnalyzer:
    """Escalate mode as the gateway builds it (LAB-1766), behind :class:`DetectorAnalyzer`'s
    interface: the fast pipeline with raw-span recording, an
    :class:`~pii_guard.detect.escalate.EscalatingDetector` with the default ``escalate_*``
    settings and an :class:`~pii_guard.detect.llm.LlmDetector` from the environment.

    ``added_ms`` holds the time escalation added to each analysed text (0 when nothing was
    uncertain), for the added-latency percentiles.
    """

    def __init__(self, names: Sequence[str] = ("rules", "ner"), llm: Any = None) -> None:
        from pii_guard.config import get_settings
        from pii_guard.detect.escalate import EscalatingDetector, RawRecorder
        from pii_guard.detect.pipeline import DetectionPipeline
        from pii_guard.gateway.config import GatewayConfig
        from pii_guard.policy import PolicySet

        self.policies = PolicySet()
        base = DetectorAnalyzer([n for n in names if n != "llm"], policies=self.policies)
        self.skipped = list(base.skipped)
        self.loaded = [*base.loaded, "llm"]
        config = GatewayConfig()
        if llm is None:
            from pii_guard.detect.llm import LlmDetector

            llm = LlmDetector(
                settings=get_settings(),
                reasoning_effort=config.llm_reasoning_effort,
                timeout=config.escalate_timeout,
                challenge_empty=False,
            )
            reason = llm.unavailable_reason
            if reason:
                self.skipped.append(("llm", reason))
        self.llm = llm
        self.config = config
        self._last_ms = 0.0
        self.added_ms: list[float] = []
        fast = DetectionPipeline(
            [RawRecorder(d) for d in base.detectors], keep_types=self.policies.keep_types
        )
        self.escalate = EscalatingDetector(
            fast,
            llm,
            radius=config.escalate_window,
            max_windows=config.escalate_max_windows,
            low_score=config.escalate_low_score,
            timeout=config.escalate_timeout,
            on_failure=config.escalate_on_failure,
            on_llm_ms=self._record,
        )
        self.detectors = [*base.detectors, llm]

    def _record(self, ms: float) -> None:
        self._last_ms += ms

    def analyze(self, text: str, language: str) -> list[Any]:
        self._last_ms = 0.0
        spans = self.escalate.detect(text, language)
        self.added_ms.append(self._last_ms)
        return spans


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = q * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (rank - low), 1)


def _escalation_block(analyzer: EscalateAnalyzer, documents: int) -> dict[str, Any]:
    usage = dict(analyzer.escalate.usage)
    added = analyzer.added_ms[1:]  # without the warm-up call
    escalated = [ms for ms in added if ms > 0]
    config = analyzer.config
    return {
        "settings": {
            "window": config.escalate_window,
            "max_windows": config.escalate_max_windows,
            "low_score": config.escalate_low_score,
            "timeout_s": config.escalate_timeout,
            "on_failure": config.escalate_on_failure,
        },
        "usage": usage,
        "escalation_rate": round(usage.get("escalated_texts", 0) / max(documents, 1), 4),
        "added_ms": {
            "p50": _percentile(added, 0.5),
            "p95": _percentile(added, 0.95),
            "escalated_p50": _percentile(escalated, 0.5),
            "escalated_p95": _percentile(escalated, 0.95),
        },
    }


def _load() -> list[float] | None:
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except OSError:  # pragma: no cover - not on every platform
        return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pii_guard.eval.baselines.suite",
        description="Score one pii-guard system on one fixture file, recording cost and load.",
    )
    parser.add_argument(
        "--system",
        type=lambda v: cli_mode(v, "suite"),
        choices=sorted(SYSTEMS),
        required=True,
        help="rules, fast, escalate or audit (strict: deprecated alias of audit)",
    )
    parser.add_argument("--fixtures", type=Path, action="append", required=True)
    parser.add_argument("--json", type=Path, required=True, metavar="OUT")
    parser.add_argument("--markdown", type=Path, metavar="OUT")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        documents = load_fixtures(args.fixtures)
    except (FixtureError, OSError) as exc:
        print(f"suite: {exc}", file=sys.stderr)
        return 2
    names = SYSTEMS[args.system]
    analyzer: DetectorAnalyzer | EscalateAnalyzer = (
        EscalateAnalyzer(names) if args.system == "escalate" else DetectorAnalyzer(names)
    )
    if analyzer.skipped:  # a comparison row must be the configuration it claims to be
        for name, reason in analyzer.skipped:
            print(f"suite: detector {name!r} unavailable: {reason}", file=sys.stderr)
        return 2
    load_start = _load()
    started = time.perf_counter()
    try:
        analyzer.analyze(*_WARMUP)
        warm = {d.name: dict(getattr(d, "usage", {}) or {}) for d in analyzer.detectors}
        # One document at a time: a detector failure (fail closed) blocks that document only,
        # as the gateway would refuse that one request; it is counted, not scored.
        results, blocked = run_injection(documents, analyzer)
    except PiiGuardError as exc:
        print(f"suite: run failed: {exc.code}: {exc.message}", file=sys.stderr)
        return 1
    wall_s = time.perf_counter() - started

    scorecard = build_scorecard(results, detectors=analyzer.loaded, fixture_paths=args.fixtures)
    run: dict[str, Any] = {
        "system": f"pii-guard {args.system}",
        "detectors": names,
        "documents": len(documents),
        "wall_s": round(wall_s, 1),
        "load_average_start": load_start,
        "load_average_end": _load(),
        "host": host_info(),
        "warmup_calls": 1,
        "blocked": len(blocked),
        "blocked_documents": [{"id": d.id, "error": err} for d, err in blocked],
    }
    if "ner" in names:
        run["ner"] = ner_identity()
    llm = next((d for d in analyzer.detectors if d.name == "llm"), None)
    if llm is not None:
        usage: dict[str, int] = dict(getattr(llm, "usage", {}) or {})
        warm_usage = warm.get("llm", {})
        doc_usage = {k: v - warm_usage.get(k, 0) for k, v in usage.items()}
        cost = cost_usd(doc_usage)
        run["llm"] = {
            "url": getattr(llm, "url", None),
            "model": getattr(llm, "model", None),
            "reasoning_effort": getattr(llm, "reasoning_effort", None),
            "usage": doc_usage,
            "usage_incl_warmup": usage,
            "price_usd_per_1m_tokens": BASETEN_PRICE_USD_PER_1M,
            "cost_usd": round(cost, 4),
            "cost_usd_incl_warmup": round(cost_usd(usage), 4),
            "usd_per_1k_messages": round(cost / len(documents) * 1000, 2),
            "refusal_rate": doc_usage.get("refusals", 0) / max(doc_usage.get("requests", 0), 1),
            "invalid_output_rate": doc_usage.get("invalid_outputs", 0)
            / max(doc_usage.get("requests", 0), 1),
        }
    if args.system == "escalate":
        run["escalation"] = _escalation_block(cast(EscalateAnalyzer, analyzer), len(documents))
    scorecard["run"] = run
    markdown = render_markdown(scorecard)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(scorecard, indent=2, ensure_ascii=False) + "\n", "utf-8")
    if args.markdown:
        args.markdown.write_text(markdown, encoding="utf-8")
    summary = scorecard["overall"]
    print(
        f"suite: {args.system} {', '.join(p.name for p in args.fixtures)}: "
        f"F1 {summary['detection']['overlap']['micro']['f1']}, leak {summary['leak']['rate']}, "
        f"wall {wall_s:.0f}s" + (f", ${run['llm']['cost_usd']}" if "llm" in run else ""),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
