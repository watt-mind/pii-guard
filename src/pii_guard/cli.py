"""The ``pii-guard`` command line."""

from __future__ import annotations

import argparse
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
    return parser


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from pii_guard.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "pii_guard.api.app:create_app",
        factory=True,
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=args.reload,
        log_level=settings.log_level,
    )
    return 0


def _eval(args: argparse.Namespace) -> int:
    from pii_guard.eval.cli import main as eval_main

    return eval_main(args.args)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "eval":
        # Hand everything after "eval" to the eval CLI untouched (it owns its own flags).
        return _eval(argparse.Namespace(args=argv[1:]))
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        return _serve(args)
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
