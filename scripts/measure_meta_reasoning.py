"""Measure how a reasoning upstream spends its output budget (LAB-1372 AC6, LAB-1334).

Sends short synthetic prompts (the hosted demo samples, as the gateway would send them
masked, plus two chat-length ones) straight to an OpenAI-compatible endpoint, sweeping
``max_completion_tokens``. Records only counts: usage tokens (prompt, completion, reasoning
when reported), finish reason, whether ``message.content`` was empty, its length in
characters, and latency. No answer text and no credential is written anywhere.

    set -a; . ./.env; set +a     # provides META_API_KEY; never pass it in argv
    uv run --no-sync python scripts/measure_meta_reasoning.py \
        --out eval/results/<date>-lab-1372-meta-reasoning/measurements.json

Keep it small: every call is billed to the key's owner.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# Synthetic only: fictional names, reserved example domains, placeholders as the gateway
# sends them (the demo samples in pii_guard.hosted.routes after masking).
PROMPTS: dict[str, str] = {
    "demo-en": (
        "Please write a short reply to this support request: I am [[PERSON_1a2b]], "
        "my email is [[EMAIL_3c4d]]. I would like to change the delivery date."
    ),
    "demo-hu": (
        "Kérlek, írj rövid választ erre az ügyfélszolgálati kérésre: [[PERSON_1a2b]] vagyok, "
        "az e-mail-címem [[EMAIL_3c4d]]. Szeretném módosítani a szállítás időpontját."
    ),
    "chat-en": (
        "You are a helpful assistant for an online shop. A customer, [[PERSON_5e6f]], wrote: "
        "'Hello, I ordered a blue kettle last Tuesday (order [[ORDER_7a8b]]) and it arrived "
        "with a cracked lid. I would like either a replacement lid or a refund for the lid "
        "only, since the kettle itself works. I can send photos. My phone is [[PHONE_9c0d]] "
        "if a call is easier, but email to [[EMAIL_1e2f]] is better during work hours.' "
        "Draft a friendly reply in three or four sentences that apologises, offers both "
        "options, and explains the next step."
    ),
    "chat-de": (
        "Fasse diese Nachricht in zwei Sätzen zusammen und nenne die gewünschte Aktion: "
        "'Guten Tag, mein Name ist [[PERSON_3a4b]]. Ich bin am 3. März umgezogen und meine "
        "neue Adresse lautet [[ADDRESS_5c6d]]. Bitte ändern Sie die Lieferadresse für mein "
        "Abonnement ab der nächsten Lieferung und bestätigen Sie die Änderung per E-Mail an "
        "[[EMAIL_7e8f]]. Die Rechnungsadresse bleibt gleich. Vielen Dank.'"
    ),
}


def call(client: httpx.Client, model: str, prompt: str, budget: int, effort: str | None) -> dict:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": budget,
    }
    if effort:
        body["reasoning_effort"] = effort
    start = time.monotonic()
    try:
        response = client.post("/chat/completions", json=body)
    except httpx.HTTPError as exc:
        return {"error": type(exc).__name__, "latency_s": round(time.monotonic() - start, 2)}
    latency = round(time.monotonic() - start, 2)
    if response.status_code != 200:
        return {"status": response.status_code, "latency_s": latency}
    data = response.json()
    choice = (data.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content")
    usage = data.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    return {
        "status": 200,
        "latency_s": latency,
        "finish_reason": choice.get("finish_reason"),
        "empty": not (isinstance(content, str) and content.strip()),
        "content_chars": len(content) if isinstance(content, str) else 0,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
    }


def summarise(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        groups.setdefault((row["effort"] or "default", row["budget"]), []).append(row)
    out = []
    for (effort, budget), items in sorted(groups.items()):
        ok = [r for r in items if r.get("status") == 200]
        out.append(
            {
                "reasoning_effort": effort,
                "max_completion_tokens": budget,
                "calls": len(items),
                "empty": sum(1 for r in ok if r["empty"]) + (len(items) - len(ok)),
                "finish_length": sum(1 for r in ok if r["finish_reason"] == "length"),
                "completion_tokens_median": statistics.median(r["completion_tokens"] for r in ok)
                if ok
                else None,
                "reasoning_tokens_max": max((r["reasoning_tokens"] or 0) for r in ok)
                if ok
                else None,
                "completion_tokens_max_answered": max(
                    (r["completion_tokens"] for r in ok if not r["empty"]), default=None
                ),
                "latency_s_median": statistics.median(r["latency_s"] for r in items),
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="https://api.meta.ai/v1")
    parser.add_argument("--model", default="muse-spark-1.3")
    parser.add_argument("--budgets", default="128,256,512,1024,2048,4096")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--effort", action="append", default=[], help="extra reasoning_effort")
    parser.add_argument("--effort-budget", type=int, default=512)
    parser.add_argument("--max-calls", type=int, default=60)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    key = os.environ.get("META_API_KEY")
    if not key:
        print("META_API_KEY is not set", file=sys.stderr)
        return 2
    plan = [
        (name, int(budget), None)
        for budget in args.budgets.split(",")
        for name in PROMPTS
        for _ in range(args.repeats if int(budget) > 128 else 1)
    ]
    plan += [(name, args.effort_budget, effort) for effort in args.effort for name in PROMPTS]
    if len(plan) > args.max_calls:
        print(f"plan has {len(plan)} calls, above --max-calls", file=sys.stderr)
        return 2
    rows = []
    with httpx.Client(
        base_url=args.base_url, headers={"Authorization": f"Bearer {key}"}, timeout=180
    ) as client:
        for name, budget, effort in plan:
            row = {"prompt": name, "budget": budget, "effort": effort}
            row.update(call(client, args.model, PROMPTS[name], budget, effort))
            rows.append(row)
            print(json.dumps(row), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "base_url": args.base_url,
                "model": args.model,
                "measured_at": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()),
                "calls": len(rows),
                "summary": summarise(rows),
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
