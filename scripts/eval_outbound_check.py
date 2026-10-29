"""Replay the standard evaluation sets through the gateway and count outbound re-check blocks.

LAB-1500. Every document goes through the real in-process gateway in fast mode (rules + the
published NER, the production path) against a mock upstream, and the re-check either passes
the masked request or refuses it with ``422 outbound_check_failed``. On these sets every
value is synthetic and every request is one the gateway should forward, so each block is a
false block: the rate should be 0.

```
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/eval_outbound_check.py \\
    --out eval/results/2026-10-29-lab-1500-outbound-check
```

- ``agent-traffic-dev`` documents are Chat Completions bodies (tool definitions, tool calls,
  tool results): sent as they are. Every other document is the content of one user message.
- ``per-document``: each document opens its own session, as a new conversation would.
- ``shared session``: every document of one set and language goes into one session, in
  order, so each request is re-checked against every value of the documents before it. This
  is the stress case for short and common values (a name found in one document, a word in
  the next).
- ``latency``: the latency corpus of ``pii-guard bench latency``
  (:data:`pii_guard.bench.latency.CORPUS`), each text in a new session, ``--repeat`` times;
  the re-check's own time per request (``outbound_check.ms`` of the traffic event).

Writes ``<set>.json`` per set and ``latency.json`` to ``--out``: counts, rates and
percentiles only, never a value or a text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import secrets
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

SETS: dict[str, tuple[str, ...]] = {
    "agent-traffic-dev": (
        "eval/synthetic/dev/hu-agent-traffic-dev.jsonl",
        "eval/synthetic/dev/en-agent-traffic-dev.jsonl",
        "eval/synthetic/dev/de-agent-traffic-dev.jsonl",
    ),
    "smoke": (
        "eval/fixtures/hu-smoke.jsonl",
        "eval/fixtures/en-smoke.jsonl",
        "eval/fixtures/de-smoke.jsonl",
    ),
    "agent-text": (
        "eval/fixtures/agent-text/de-agent-text.jsonl",
        "eval/fixtures/agent-text/en-agent-text.jsonl",
        "eval/fixtures/agent-text/hu-agent-text.jsonl",
    ),
    "synth-sample": (
        "eval/fixtures/hu-synth-sample.jsonl",
        "eval/fixtures/en-synth-sample.jsonl",
    ),
}


def _answer(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-eval",
            "object": "chat.completion",
            "created": 0,
            "model": body.get("model", "mock"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "OK."},
                    "finish_reason": "stop",
                }
            ],
        },
    )


def _gateway() -> Any:
    from pii_guard.config import Settings
    from pii_guard.gateway import Gateway, GatewayConfig, Mode
    from pii_guard.vault import Vault

    settings = Settings(
        _env_file=None,
        tenant_key=secrets.token_hex(32),
        upstream_base_url="https://upstream.invalid/v1",
        upstream_api_key="eval-mock-key",
    )
    return Gateway(
        settings=settings,
        vault=Vault.from_settings(settings),
        config=GatewayConfig(mode=Mode.FAST),
        transport=httpx.MockTransport(_answer),
    )


def _body(text: str) -> dict[str, Any]:
    try:
        body = json.loads(text)
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("messages"), list):
        body.setdefault("model", "mock")
        body.pop("stream", None)
        return body
    return {"model": "mock", "messages": [{"role": "user", "content": text}]}


async def _send(gateway: Any, body: dict[str, Any], language: str, session: str) -> tuple[str, Any]:
    from pii_guard.gateway.outbound import OutboundCheckFailedError
    from pii_guard.types import PiiGuardError

    headers = {"X-PII-Guard-Mode": "fast", "X-PII-Guard-Language": language}
    try:
        response, stats = await gateway.chat_completions(body, headers, path_session=session)
    except OutboundCheckFailedError as exc:
        return "blocked", exc.counts
    except PiiGuardError as exc:
        return f"refused:{exc.code}", None
    if response.status_code != 200:
        return f"status:{response.status_code}", None
    return "passed", stats.outbound


def _load(paths: tuple[str, ...]) -> list[dict[str, Any]]:
    docs = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            docs += [json.loads(line) for line in fh if line.strip()]
    return docs


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(q * (len(ordered) - 1))))
    return round(ordered[k], 3)


def _summary(outcomes: list[tuple[str, Any]]) -> dict[str, Any]:
    kinds = Counter(kind for kind, _ in outcomes)
    hits: Counter[str] = Counter()
    for kind, detail in outcomes:
        if kind == "blocked":
            hits.update(detail)
    checks = [d for k, d in outcomes if k == "passed" and d is not None]
    ms = [c.ms for c in checks]
    checked = kinds["passed"] + kinds["blocked"]
    return {
        "requests": len(outcomes),
        "checked": checked,
        "passed": kinds["passed"],
        "blocked": kinds["blocked"],
        "false_block_rate": round(kinds["blocked"] / checked, 6) if checked else None,
        "blocked_types": dict(sorted(hits.items())),
        "short_occurrences": sum(c.short for c in checks),
        "refused_before_the_check": {
            k: n for k, n in sorted(kinds.items()) if k not in ("passed", "blocked")
        },
        "texts_per_request": {"p50": _pct([c.texts for c in checks], 0.5)},
        "check_ms": {"p50": _pct(ms, 0.5), "p95": _pct(ms, 0.95), "max": _pct(ms, 1.0)},
    }


async def _run_set(gateway: Any, name: str, docs: list[dict[str, Any]]) -> dict[str, Any]:
    per_doc = []
    for i, doc in enumerate(docs):
        per_doc.append(await _send(gateway, _body(doc["text"]), doc["language"], f"ev{i}_{name}"))
    shared = []
    for doc in docs:
        session = f"shared_{name}_{doc['language']}"
        shared.append(await _send(gateway, _body(doc["text"]), doc["language"], session))
    return {
        "set": name,
        "documents": len(docs),
        "languages": dict(sorted(Counter(d["language"] for d in docs).items())),
        "per_document": _summary(per_doc),
        "shared_session": _summary(shared),
    }


async def _latency(gateway: Any, repeat: int) -> dict[str, Any]:
    from pii_guard.bench.latency import CORPUS

    outcomes = []
    for r in range(repeat):
        for i, (language, text) in enumerate(CORPUS):
            body = {"model": "mock", "messages": [{"role": "user", "content": text}]}
            outcomes.append(await _send(gateway, body, language, f"lat{r}_{i}"))
    return {
        "set": "latency-corpus",
        "documents": len(CORPUS),
        "repeat": repeat,
        **_summary(outcomes),
    }


def _commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sets", default=",".join(SETS))
    parser.add_argument("--repeat", type=int, default=25, help="latency corpus repetitions")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    gateway = _gateway()
    meta = {
        "ticket": "LAB-1500",
        "commit": _commit(),
        "mode": "fast (rules + NER)",
        "ner": "watt-mind/pii-guard-ner-xlmr-base",
        "hardware": f"{platform.platform()}, python {platform.python_version()}",
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    async def run() -> None:
        # Warm the NER up on one text first, so the first request isn't the model load.
        await _send(gateway, _body("Warm-up text."), "en", "warmup")
        for name in args.sets.split(","):
            result = await _run_set(gateway, name, _load(SETS[name]))
            (args.out / f"{name}.json").write_text(
                json.dumps({**meta, **result}, indent=2) + "\n", encoding="utf-8"
            )
            pd, sh = result["per_document"], result["shared_session"]
            print(
                f"{name}: {pd['blocked']}/{pd['checked']} blocked per document, "
                f"{sh['blocked']}/{sh['checked']} shared; check p50 {pd['check_ms']['p50']} ms",
                file=sys.stderr,
            )
        result = await _latency(gateway, args.repeat)
        (args.out / "latency.json").write_text(
            json.dumps({**meta, **result}, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"latency corpus: check p50 {result['check_ms']['p50']} ms, "
            f"p95 {result['check_ms']['p95']} ms, {result['blocked']} blocked",
            file=sys.stderr,
        )

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
