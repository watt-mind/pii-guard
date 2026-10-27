"""The ``pii-guard`` command line."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from pii_guard import __version__

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pii-guard",
        description="Privacy firewall for AI agents: reversible PII masking.",
    )
    parser.add_argument("--version", action="version", version=f"pii-guard {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    serve = sub.add_parser("serve", help="run the REST API (default port 8787)")
    serve.add_argument("--host", default=None, help="bind address (env: PII_GUARD_HOST)")
    serve.add_argument("--port", type=int, default=None, help="port (env: PII_GUARD_PORT)")
    serve.add_argument("--reload", action="store_true", help="auto-reload on code changes")

    ev = sub.add_parser(
        "eval",
        help="run the evaluation set and print the scorecard",
        add_help=False,
    )
    ev.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)

    lang = sub.add_parser(
        "lang",
        help="list, check and scaffold language packs (docs/languages.md)",
        add_help=False,
    )
    lang.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)

    bench = sub.add_parser(
        "bench",
        help="gateway latency benchmark and the mock upstream (docs/operations.md)",
        add_help=False,
    )
    bench.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)

    baselines = sub.add_parser(
        "baselines", help="set up the comparison baselines (docs/evaluation.md)"
    )
    baselines_sub = baselines.add_subparsers(dest="baselines_command", metavar="<command>")
    baselines_sub.add_parser(
        "download",
        help="fetch, verify and unpack the pinned huSpaCy model once (needs --extra baselines)",
    )
    return parser


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from pii_guard.config import get_settings
    from pii_guard.observability import ObservabilitySettings, TrafficLogConfigError, check_bind

    settings = get_settings()
    host = args.host or settings.host
    try:
        check_bind(ObservabilitySettings().traffic_log, host)
    except TrafficLogConfigError as exc:
        print(f"pii-guard serve: {exc}", file=sys.stderr)
        return 2
    # The app checks the bind it is told about: hand it the real one, not just the env value
    # (PII_GUARD_HOST=0.0.0.0 with --host 127.0.0.1 is a loopback server). The env is inherited
    # by the --reload worker, which builds its own app.
    os.environ["PII_GUARD_HOST"] = host
    get_settings.cache_clear()
    uvicorn.run(
        "pii_guard.api.app:create_app",
        factory=True,
        host=host,
        port=args.port or settings.port,
        reload=args.reload,
        log_level=settings.log_level,
    )
    return 0


def _eval(args: argparse.Namespace) -> int:
    from pii_guard.eval.cli import main as eval_main

    return eval_main(args.args)


def _lang(args: argparse.Namespace) -> int:
    from pii_guard.languages.cli import main as lang_main

    return lang_main(args.args)


def _bench(args: argparse.Namespace) -> int:
    from pii_guard.bench.cli import main as bench_main

    return bench_main(args.args)


def _baselines(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.baselines_command != "download":
        parser.parse_args(["baselines", "--help"])
        return 2  # pragma: no cover - --help exits
    from pii_guard.eval.baselines.base import BaselineUnavailable
    from pii_guard.eval.baselines.models import HU_CORE_NEWS_LG, download

    try:
        data_dir = download(HU_CORE_NEWS_LG)
    except BaselineUnavailable as exc:
        print(f"pii-guard baselines download: {exc}", file=sys.stderr)
        return 1
    print(f"{HU_CORE_NEWS_LG.label}: {data_dir}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "bench":
        return _bench(argparse.Namespace(args=argv[1:]))
    if argv and argv[0] == "eval":
        # Hand everything after "eval" to the eval CLI untouched (it owns its own flags).
        return _eval(argparse.Namespace(args=argv[1:]))
    if argv and argv[0] == "lang":
        return _lang(argparse.Namespace(args=argv[1:]))
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        return _serve(args)
    if args.command == "baselines":
        return _baselines(args, parser)
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
