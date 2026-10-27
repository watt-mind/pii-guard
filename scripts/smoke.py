"""``make smoke``: start the stack on the mock upstream, send the demo traffic, check it.

Fails (exit 1) if any answer is not restored exactly, a request fails unexpectedly, a gold
value reached the upstream (the mock records what it receives), or the traffic log is missing
an event, holds a key or a raw session id. Offline and free; runs in CI.

Rules only (the default): every scenario's values must be masked, names through session known
values. The one scenario labelled "needs fast mode (NER)" is an expected miss, printed but not
a failure; with ``PII_GUARD_NER_MODEL`` set its name must be masked too.
"""

from __future__ import annotations

import json
import sys

import httpx
from demo_stack import Stack, plan

from pii_guard.bench.scenarios import check, expected_misses, run

API_PORT, MOCK_PORT = 18787, 18790


def main() -> int:
    p = plan(
        force_mock=True, ui=False, traffic_log="masked", api_port=API_PORT, mock_port=MOCK_PORT
    )
    detectors = {"ner"} if p.ner else set()
    failures: list[str] = []
    misses: list = []
    try:
        with Stack(p, quiet=True):
            outcomes = run(p.api_url)
            received = httpx.get(f"{p.mock_url}/_mock/received?limit=1000", timeout=10).json()
            failures += check(outcomes, received["requests"], detectors=detectors)
            misses = expected_misses(outcomes, received["requests"], detectors=detectors)
            traffic = httpx.get(f"{p.api_url}/v1/traffic?limit=1000", timeout=10).json()
            failures += check_traffic(traffic["events"], outcomes)
    except RuntimeError as exc:
        print(f"smoke: {exc}", file=sys.stderr)
        return 1
    for o in outcomes:
        state = "ok" if o.status < 400 else f"refused ({o.error})"
        print(f"  {o.scenario.name:<16} turn {o.turn}  {state:<28} {o.elapsed_ms:7.1f} ms")
    print(f"  upstream received {received['count']} requests")
    for scenario, values in misses:
        print(
            f"  {scenario.name:<16} expected miss ({scenario.label}): "
            f"{len(values)} name(s) sent as written, not a failure in rules-only mode"
        )
    if failures:
        print("smoke: FAILED", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    mode = "rules + NER" if p.ner else "rules only"
    print(f"smoke: OK ({len(outcomes)} requests, {mode}, no gold value reached the upstream)")
    return 0


def check_traffic(events: list[dict], outcomes: list) -> list[str]:
    failures = []
    by_id = {e["id"]: e for e in events}
    sessions = {o.session for o in outcomes if o.session}
    raw = json.dumps(events, ensure_ascii=False)
    for o in outcomes:
        if o.request_id and o.request_id not in by_id:
            failures.append(f"{o.scenario.name}: no traffic event for {o.request_id}")
    for event in events:
        timing = event.get("timing") or {}
        if timing.get("overhead_ms") is None or "stages_ms" not in timing:
            failures.append(f"traffic event {event.get('id')} has no timing breakdown")
    for session in sessions:
        if session in raw:
            failures.append("a raw session id appears in the traffic log")
    if "Bearer " in raw or "authorization" in raw.lower():
        failures.append("credentials appear in the traffic log")
    return failures


if __name__ == "__main__":
    sys.exit(main())
