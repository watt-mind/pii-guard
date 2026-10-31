"""``pii-guard bench``: the latency benchmark and the mock upstream.

```
pii-guard bench latency [--modes fast,audit] [--requests 200] [--record SLUG]
pii-guard bench mock-upstream [--port 8790] [--delay-ms 0]
```
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pii_guard.bench.mock_upstream import DEFAULT_PORT
from pii_guard.gateway.config import cli_mode

__all__ = ["main"]


def _ints(value: str) -> list[int]:
    try:
        out = [int(v) for v in value.split(",") if v.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected comma-separated integers, got {value!r}"
        ) from None
    if not out or any(v < 1 for v in out):
        raise argparse.ArgumentTypeError("values must be >= 1")
    return out


def _names(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pii-guard bench", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    lat = sub.add_parser("latency", help="measure the gateway's overhead per stage and mode")
    lat.add_argument("--modes", type=_names, default=["fast"], help="fast,audit (default fast)")
    lat.add_argument("--concurrency", type=_ints, default=[1, 8], help="default 1,8")
    lat.add_argument(
        "--stream", choices=["both", "off", "on"], default="both", help="streamed requests"
    )
    lat.add_argument("--requests", type=int, default=200, help="requests per cell (default 200)")
    lat.add_argument(
        "--audit-requests",
        type=int,
        default=12,
        help="requests per audit-mode cell (each calls the LLM detector; default 12)",
    )
    # Deprecated spelling of --audit-requests (the mode was called strict).
    lat.add_argument("--strict-requests", type=int, dest="strict_requests", help=argparse.SUPPRESS)
    lat.add_argument("--warmup", type=int, default=5, help="unrecorded requests per cell")
    lat.add_argument(
        "--upstream-delay-ms", type=float, default=50.0, help="mock upstream delay (default 50)"
    )
    lat.add_argument("--record", metavar="SLUG", help="write run records <date>-<SLUG>-<mode>")
    lat.add_argument("--runs-dir", type=Path, default=Path("eval/results/runs"))
    lat.add_argument("--overwrite", action="store_true", help="replace existing records")
    lat.add_argument(
        "--detector-info",
        type=Path,
        help="JSON {detector: {model, model_ref, serving, device, settings}} for the record",
    )
    lat.add_argument("--note", action="append", default=[], help="a note for the record")
    lat.add_argument("--json", type=Path, help="also write the cell summaries here")

    mock = sub.add_parser("mock-upstream", help="run the offline OpenAI-compatible mock upstream")
    mock.add_argument("--host", default="127.0.0.1")
    mock.add_argument("--port", type=int, default=DEFAULT_PORT)
    mock.add_argument("--delay-ms", type=float, default=0.0, help="delay before each answer")
    mock.add_argument("--chunk-chars", type=int, default=7, help="characters per stream chunk")
    return parser


def _fmt(p: dict[str, float] | None, key: str) -> str:
    return "-" if not p else f"{p[key]:.2f}"


def _latency(args: argparse.Namespace) -> int:
    from pii_guard.bench.latency import CellResult, build_records, run_benchmark

    streams = {"both": [False, True], "off": [False], "on": [True]}[args.stream]
    args.modes = [cli_mode(m, "pii-guard bench latency") for m in args.modes]
    if args.strict_requests is not None:
        print(
            "pii-guard bench latency: --strict-requests is deprecated, use --audit-requests",
            file=sys.stderr,
        )
        args.audit_requests = args.strict_requests
    for mode in args.modes:
        if mode not in ("fast", "audit"):
            print(f"pii-guard bench latency: unknown mode {mode!r}", file=sys.stderr)
            return 2

    def progress(cell: CellResult) -> None:
        s = cell.summary()
        print(
            f"{s['mode']:<6} c={s['concurrency']:<2} stream={'on ' if s['stream'] else 'off'} "
            f"n={s['requests']:<4} err={s['errors']:<3} "
            f"overhead p50={_fmt(s['overhead_ms'], 'p50')}"
            f" p95={_fmt(s['overhead_ms'], 'p95')} p99={_fmt(s['overhead_ms'], 'p99')} ms"
            + (f"  added TTFT p50={_fmt(s['added_ttft_ms'], 'p50')} ms" if s["stream"] else "")
            + f"  [{', '.join(cell.detectors) or '-'}]",
            flush=True,
        )

    cells = run_benchmark(
        modes=args.modes,
        concurrency=args.concurrency,
        streams=streams,
        requests=args.requests,
        mode_requests={"audit": args.audit_requests},
        warmup=args.warmup,
        delay_ms=args.upstream_delay_ms,
        progress=progress,
    )
    if args.json:
        args.json.write_text(
            json.dumps([c.summary() for c in cells], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if any(c.errors for c in cells):
        print("pii-guard bench latency: some requests failed (see err=)", file=sys.stderr)
    if args.record:
        from pii_guard.eval.record import RecordError, write_records

        info = json.loads(args.detector_info.read_text("utf-8")) if args.detector_info else None
        records = build_records(
            cells,
            slug=args.record,
            delay_ms=args.upstream_delay_ms,
            detector_info=info,
            notes=args.note,
        )
        try:
            paths = write_records(records, args.runs_dir, overwrite=args.overwrite)
        except RecordError as exc:
            print(f"pii-guard bench latency: {exc}", file=sys.stderr)
            return 2
        for path in paths:
            print(f"wrote {path}")
        print("regenerate the report: uv run pii-guard eval report")
    return 1 if any(c.errors == c.requests for c in cells) else 0


def _mock(args: argparse.Namespace) -> int:
    import uvicorn

    from pii_guard.bench.mock_upstream import create_mock_upstream

    app = create_mock_upstream(delay_ms=args.delay_ms, chunk_chars=args.chunk_chars)
    print(f"mock upstream on http://{args.host}:{args.port}/v1 (delay {args.delay_ms:g} ms)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "latency":
        return _latency(args)
    if args.command == "mock-upstream":
        return _mock(args)
    parser.print_help()
    return 0
