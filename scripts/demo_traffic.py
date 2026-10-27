"""``make demo-traffic``: send the scripted fictional requests through a running gateway.

Hungarian, English and German chats, streaming, tool definitions, names pre-loaded as known
values (with Hungarian inflected forms) and an inline image (refused, fail closed, unless SAM is
configured). Watch them arrive in the traffic log (``/v1/traffic``) or the UI. In rules-only
mode nothing leaks except the one scenario labelled "needs fast mode (NER)": an expected miss.

    uv run python scripts/demo_traffic.py [--url http://127.0.0.1:8787] [--model NAME]
    uv run python scripts/demo_traffic.py --export-ui   # rewrite the UI's copy of the scenarios
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo_stack import MOCK_MODEL

from pii_guard.bench.scenarios import SCENARIOS, Outcome, run, ui_export

UI_SCENARIOS = Path(__file__).resolve().parent.parent / "ui/src/content/demoScenarios.json"


def describe(o: Outcome) -> str:
    kind = "stream" if o.scenario.stream else "chat"
    if o.scenario.tools:
        kind += "+tools"
    if o.scenario.image:
        kind += "+image"
    status = "ok" if o.status < 400 and not o.error else f"refused ({o.error})"
    restored = ""
    if o.status < 400 and not o.error:
        if o.scenario.expect == "tool":
            restored = "tool call"
        else:
            restored = "restored exactly" if o.content == o.expected else "restored"
    label = f"  [{o.scenario.label}]" if o.scenario.label else ""
    return (
        f"  {o.scenario.name:<16} turn {o.turn}  {o.scenario.language}  {kind:<13} "
        f"{status:<28} {restored:<17} {o.elapsed_ms:7.1f} ms  {o.request_id or ''}{label}"
    )


def detectors_of(url: str, outcomes: list[Outcome]) -> dict[str, list[str]]:
    """Request id -> detectors that ran, from the traffic log (empty when it is off)."""
    try:
        events = httpx.get(f"{url}/v1/traffic?limit=1000", timeout=10).json()["events"]
    except (httpx.HTTPError, ValueError, KeyError):
        return {}
    ids = {o.request_id for o in outcomes}
    return {e["id"]: e.get("detectors") or [] for e in events if e.get("id") in ids}


def labelled_summary(url: str, outcomes: list[Outcome]) -> list[str]:
    ran = detectors_of(url, outcomes)
    lines = []
    for o in outcomes:
        if not o.scenario.requires or not o.request_id:
            continue
        detectors = ran.get(o.request_id)
        if detectors is None:
            verdict = "see the Live traffic tab"
        elif set(o.scenario.requires) <= set(detectors) or "llm" in detectors:
            verdict = "the NER ran, so the name was masked"
        else:
            verdict = (
                "this call ran rules only, so its free-text name reached the model as written: "
                "an expected miss (set PII_GUARD_NER_MODEL for fast mode with the NER)"
            )
        lines.append(f"  {o.scenario.name}: {o.scenario.label}; {verdict}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--url", default=os.environ.get("PII_GUARD_DEMO_URL", "http://127.0.0.1:8787")
    )
    parser.add_argument("--model", default=os.environ.get("PII_GUARD_DEMO_MODEL", MOCK_MODEL))
    parser.add_argument(
        "--export-ui",
        action="store_true",
        help=f"write the scenarios to {UI_SCENARIOS.relative_to(UI_SCENARIOS.parents[3])}",
    )
    args = parser.parse_args(argv)
    if args.export_ui:
        text = json.dumps(ui_export(), ensure_ascii=False, indent=2) + "\n"
        UI_SCENARIOS.write_text(text, encoding="utf-8")
        print(f"wrote {UI_SCENARIOS}")
        return 0
    print(f"sending {len(SCENARIOS)} scenarios to {args.url}/v1/chat/completions")
    outcomes = run(args.url, model=args.model, on_outcome=lambda o: print(describe(o), flush=True))
    failed = [o for o in outcomes if o.status >= 400 and o.scenario.expect != "refused_or_echo"]
    for line in labelled_summary(args.url, outcomes):
        print(line)
    print(f"done: {len(outcomes)} requests, see {args.url}/v1/traffic")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
