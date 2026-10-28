"""Score the Muse Glimmer LoRA (or the base model) on a Fireworks on-demand deployment (LAB-1109).

The same harness as ``pii-guard eval --detectors llm`` and ``--detectors rules,llm``
(:class:`~pii_guard.eval.scorer.run_documents` + :func:`~pii_guard.eval.report.build_scorecard`),
with three additions the CLI does not report:

- per-document **completion tokens** and request counts, from each response's ``usage``;
- a **reasoning check** per response: a ``reasoning_content`` field, a ``to=self`` turn left in
  the content, or content that does not start with JSON;
- Fireworks ignores ``chat_template_kwargs``: ``reasoning_strength`` reaches Glimmer's chat
  template only as ``reasoning_effort`` (the served prompt then equals the training renderer's
  ``reasoning_strength=low`` render byte for byte; checked with ``raw_output``);
- the LLM's answer for each document is computed **once**: the ``rules,llm`` scorecard reuses
  the ``llm`` pass's answers (the pipeline is deterministic given them), so the second system
  costs no GPU time. Its latency is the ``llm`` latency plus the rules (milliseconds).

With ``--workers N > 1`` the answers are fetched in parallel first (to fill the cache) and the
latency columns are **not** a per-document latency; they are dropped from the output.

Writes ``<out>/<name>-llm.json``, ``<out>/<name>-rules-llm.json`` (scorecards, no text, no
values) and ``<out>/<name>-docs.json`` (per document: id, language, latency, tokens, flags).

```
FIREWORKS_MODEL='accounts/<acct>/models/<lora>#accounts/<acct>/deployments/<dep>' \\
  uv run --no-sync python training/llm/eval_fireworks.py --name lora-smoke \\
  --fixtures eval/fixtures/hu-smoke.jsonl --fixtures eval/fixtures/en-smoke.jsonl
```

The key is read from ``FIREWORKS_API_KEY`` (or ``.env``) at run time and never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from pii_guard.detect.llm import LlmDetector
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.detect.rules import RuleDetector
from pii_guard.eval.fixtures import Document, load_fixtures
from pii_guard.eval.report import build_scorecard
from pii_guard.eval.scorer import run_documents
from pii_guard.policy import PolicySet

FIREWORKS_URL = "https://api.fireworks.ai/inference/v1"
_local = threading.local()


def _key() -> str:
    key = os.environ.get("FIREWORKS_API_KEY", "")
    if not key and Path(".env").exists():
        for line in Path(".env").read_text().splitlines():
            if line.startswith("FIREWORKS_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("'\"")
    if not key:
        raise SystemExit("FIREWORKS_API_KEY is not set")
    return key


def response_flags(data: dict[str, Any]) -> dict[str, Any]:
    """Counts and reasoning flags of one chat completion; never its text."""
    usage = data.get("usage") or {}
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
    details = usage.get("completion_tokens_details") or {}
    return {
        "prompt_tokens": usage.get("prompt_tokens") or 0,
        "completion_tokens": usage.get("completion_tokens") or 0,
        "reasoning_tokens": details.get("reasoning_tokens") or 0,
        "reasoning_chars": len(reasoning),
        "self_turn": "to=self" in content,
        "json_first": content.lstrip()[:1] in ("{", "["),
        "finish_reason": choice.get("finish_reason"),
    }


class RecordingTransport(httpx.HTTPTransport):
    """Records :func:`response_flags` of every completion into the current thread's list."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = super().handle_request(request)
        body = response.read()
        calls = getattr(_local, "calls", None)
        if calls is not None:
            try:
                calls.append(response_flags(json.loads(body)) | {"status": response.status_code})
            except ValueError:
                calls.append({"status": response.status_code, "malformed": True})
        return httpx.Response(
            response.status_code, headers=response.headers, content=body, request=request
        )


class CachedLlm(LlmDetector):
    """:class:`LlmDetector` that answers each ``(text, language)`` once.

    The pipeline may call it on parts of a document (structured shapes), so the per-request
    records are collected per *document* by :class:`_Analyzer`, not per call."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.cache: dict[tuple[str, str], list[Any]] = {}
        self.collector: list[dict[str, Any]] | None = None
        self._lock = threading.Lock()

    def detect(self, text: str, language: str = "hu") -> list[Any]:
        key = (text, language)
        if key not in self.cache:
            _local.calls = []
            self.cache[key] = super().detect(text, language)
            with self._lock:
                if self.collector is not None:
                    self.collector.extend(_local.calls)
            _local.calls = None
        return list(self.cache[key])


class _Analyzer:
    """:class:`~pii_guard.eval.scorer.Analyzer` over a pipeline (as ``DetectorAnalyzer``);
    with ``llm`` set, records each document's LLM requests and wall time."""

    def __init__(self, pipeline: DetectionPipeline, llm: CachedLlm | None = None) -> None:
        self.pipeline = pipeline
        self.llm = llm
        self.per_doc: dict[tuple[str, str], dict[str, Any]] = {}

    def analyze(self, text: str, language: str) -> list[Any]:
        if self.llm is None:
            return self.pipeline.detect(text, language)
        self.llm.collector = calls = []
        started = time.perf_counter()
        try:
            return self.pipeline.detect(text, language)
        finally:
            self.per_doc[(text, language)] = {
                "calls": calls,
                "wall_ms": (time.perf_counter() - started) * 1000,
            }
            self.llm.collector = None


def _pct(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[q - 1]


def subset(docs: list[Document], per_language: int | None) -> list[Document]:
    """The first ``per_language`` documents of each language, in file order."""
    if not per_language:
        return docs
    seen: dict[str, int] = {}
    out = []
    for d in docs:
        if seen.get(d.language, 0) < per_language:
            out.append(d)
            seen[d.language] = seen.get(d.language, 0) + 1
    return out


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--name", required=True)
    p.add_argument("--fixtures", action="append", required=True)
    p.add_argument("--model", default=os.environ.get("FIREWORKS_MODEL"))
    p.add_argument(
        "--reasoning-effort",
        default="low",
        help="sent as reasoning_effort; Fireworks maps it to Glimmer's reasoning_strength and "
        "ignores chat_template_kwargs (checked with raw_output, 2026-10-28)",
    )
    p.add_argument("--per-language", type=int, default=None, help="first N docs per language")
    p.add_argument("--skip-per-language", type=int, default=0, help="drop the first N per lang")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--timeout", type=float, default=180.0)
    p.add_argument("--out", type=Path, default=Path("eval/results/2026-10-28-glimmer-lora"))
    args = p.parse_args(argv)
    if not args.model:
        raise SystemExit("--model or FIREWORKS_MODEL is required")

    docs = load_fixtures(args.fixtures)
    if args.skip_per_language:
        drop = {d.id for d in subset(docs, args.skip_per_language)}
        docs = [d for d in docs if d.id not in drop]
    docs = subset(docs, args.per_language)
    llm = CachedLlm(
        base_url=FIREWORKS_URL,
        api_key=_key(),
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        timeout=args.timeout,
        max_retries=2,
        transport=RecordingTransport(retries=2),
    )
    llm.detect("Warm-up text without personal data.", "en")  # first request / scale-up
    policies = PolicySet()
    if args.workers > 1:
        with ThreadPoolExecutor(args.workers) as pool:
            list(pool.map(lambda d: llm.detect(d.text, d.language), docs))

    paths = [str(Path(f)) for f in args.fixtures]
    systems = {
        "llm": _Analyzer(DetectionPipeline([llm], keep_types=policies.keep_types), llm),
        "rules-llm": _Analyzer(
            DetectionPipeline([RuleDetector(), llm], keep_types=policies.keep_types)
        ),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for label, pipeline in systems.items():
        results = run_documents(docs, pipeline)
        card = build_scorecard(results, detectors=label.split("-"), fixture_paths=paths)
        card["meta"]["model"] = args.model.split("#")[0]
        card["meta"]["serving"] = "Fireworks on-demand, 1x H200 141GB BF16 (shape dkuwotf7)"
        card["meta"]["reasoning_strength"] = args.reasoning_effort
        card["meta"]["workers"] = args.workers
        if args.workers > 1:
            card["meta"]["latency_note"] = "parallel fetch: latency columns not per-document"
        (args.out / f"{args.name}-{label}.json").write_text(
            json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        if label == "llm":
            for d, r in zip(docs, results, strict=True):
                rec = systems["llm"].per_doc.get((d.text, d.language), {})
                calls = rec.get("calls", [])
                rows.append(
                    {
                        "id": d.id,
                        "language": d.language,
                        "llm_ms": round(r.detect_ms, 1),
                        "requests": len(calls),
                        "prompt_tokens": sum(c.get("prompt_tokens", 0) for c in calls),
                        "completion_tokens": sum(c.get("completion_tokens", 0) for c in calls),
                        "reasoning_tokens": sum(c.get("reasoning_tokens", 0) for c in calls),
                        "reasoning_chars": sum(c.get("reasoning_chars", 0) for c in calls),
                        "self_turn": any(c.get("self_turn") for c in calls),
                        "non_json": sum(not c.get("json_first", True) for c in calls),
                        "truncated": sum(c.get("finish_reason") == "length" for c in calls),
                    }
                )
    lat = [r["llm_ms"] for r in rows]
    comp = [r["completion_tokens"] for r in rows]
    summary = {
        "documents": len(rows),
        "workers": args.workers,
        "p50_ms": None if args.workers > 1 else _pct(lat, 50),
        "p95_ms": None if args.workers > 1 else _pct(lat, 95),
        "completion_tokens_p50": _pct(comp, 50),
        "completion_tokens_mean": round(statistics.fmean(comp), 1) if comp else None,
        "requests": sum(r["requests"] for r in rows),
        "docs_with_reasoning": sum(
            bool(r["reasoning_tokens"] or r["reasoning_chars"] or r["self_turn"]) for r in rows
        ),
        "non_json_answers": sum(r["non_json"] for r in rows),
        "truncated": sum(r["truncated"] for r in rows),
        "usage": dict(llm.usage),
    }
    (args.out / f"{args.name}-docs.json").write_text(
        json.dumps({"summary": summary, "documents": rows}, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
