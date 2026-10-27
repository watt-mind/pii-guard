"""``make demo-traffic``: send the scripted fictional requests through a running gateway.

Hungarian, English and German chats, streaming, tool definitions, pre-loaded known values and
an inline image (refused, fail closed, unless SAM is configured). Watch them arrive in the
traffic log (``/v1/traffic``) or the UI.

    uv run python scripts/demo_traffic.py [--url http://127.0.0.1:8787] [--model NAME]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo_stack import MOCK_MODEL

from pii_guard.bench.scenarios import SCENARIOS, Outcome, run


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
    return (
        f"  {o.scenario.name:<16} turn {o.turn}  {o.scenario.language}  {kind:<13} "
        f"{status:<28} {restored:<17} {o.elapsed_ms:7.1f} ms  {o.request_id or ''}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--url", default=os.environ.get("PII_GUARD_DEMO_URL", "http://127.0.0.1:8787")
    )
    parser.add_argument("--model", default=os.environ.get("PII_GUARD_DEMO_MODEL", MOCK_MODEL))
    args = parser.parse_args(argv)
    print(f"sending {len(SCENARIOS)} scenarios to {args.url}/v1/chat/completions")
    outcomes = run(args.url, model=args.model, on_outcome=lambda o: print(describe(o), flush=True))
    failed = [o for o in outcomes if o.status >= 400 and o.scenario.expect != "refused_or_echo"]
    print(f"done: {len(outcomes)} requests, see {args.url}/v1/traffic")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
