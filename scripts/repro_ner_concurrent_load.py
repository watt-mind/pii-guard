"""Manual repro for LAB-1274: concurrent first requests against a fresh API with NER on.

Starts the mock upstream and a fresh pii-guard API with ``PII_GUARD_DETECTORS=rules,ner``,
fires ``--concurrency`` requests at once (``/v1/analyze`` and ``/v1/chat/completions``
alternating, so the REST analyzer and the gateway both use NER first), and checks that the
API is still alive. Repeats for ``--runs`` cold starts. Exit 1 if any start crashed.

Before the fix, two NerDetector instances loaded and ran the model concurrently and the API
died with signal 11 on Apple MPS. Needs the ``ner`` extra and a local NER checkpoint; slow
(each cold start loads the model). Fictional text only.

    uv run --no-sync python scripts/repro_ner_concurrent_load.py \\
        --model ~/models/pii-guard-ner/pii-guard-ner-xlmr-base [--device mps] [--runs 20]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from demo_stack import Stack, plan

TEXT = "Kovács Teszt Elek a Minta Kft. ügyintézője, címe 1234 Próbafalva, Fő utca 12."


def fire(api: str, model: str, index: int) -> str:
    try:
        if index % 2:
            r = httpx.post(
                api + "/v1/chat/completions",
                json={"model": model, "messages": [{"role": "user", "content": TEXT}]},
                timeout=120,
            )
        else:
            r = httpx.post(api + "/v1/analyze", json={"text": TEXT, "language": "hu"}, timeout=120)
    except httpx.HTTPError as exc:
        return type(exc).__name__
    return str(r.status_code)


def one_run(args: argparse.Namespace) -> tuple[int | None, list[str], float]:
    p = plan(
        force_mock=True,
        ui=False,
        traffic_log="masked",
        api_port=args.api_port,
        mock_port=args.mock_port,
    )
    p.env["PII_GUARD_DETECTORS"] = "rules,ner"
    if args.device:
        p.env["PII_GUARD_NER_DEVICE"] = args.device
    start = time.monotonic()
    with Stack(p, quiet=not args.verbose) as stack:
        api = next(proc for name, proc in stack.procs if name == "api")
        with ThreadPoolExecutor(args.concurrency) as pool:
            results = list(pool.map(lambda i: fire(p.api_url, p.model, i), range(args.concurrency)))
        time.sleep(0.5)
        code = api.poll()
    return code, results, time.monotonic() - start


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=os.environ.get("PII_GUARD_NER_MODEL"))
    parser.add_argument("--device", help="PII_GUARD_NER_DEVICE (default: auto)")
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--api-port", type=int, default=28787)
    parser.add_argument("--mock-port", type=int, default=28790)
    parser.add_argument("--verbose", action="store_true", help="show the server output")
    args = parser.parse_args()
    if not args.model:
        parser.error("--model (or PII_GUARD_NER_MODEL) is required")
    os.environ["PII_GUARD_NER_MODEL"] = str(Path(args.model).expanduser())
    crashes = 0
    for run in range(1, args.runs + 1):
        try:
            code, results, seconds = one_run(args)
        except RuntimeError as exc:  # exited during startup
            code, results, seconds = -1, [str(exc)], 0.0
        alive = code is None
        crashes += not alive
        status = "alive" if alive else f"exited with {code}"
        print(f"run {run:2d}: {status:>16}  {seconds:5.1f}s  {' '.join(results)}", flush=True)
    print(f"{crashes} crash(es) in {args.runs} cold starts")
    return 1 if crashes else 0


if __name__ == "__main__":
    sys.exit(main())
