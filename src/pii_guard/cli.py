"""The ``pii-guard`` command line."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from pii_guard import __version__
from pii_guard.upstreams import PRESETS

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pii-guard",
        description="PII Guard, a privacy firewall for AI agents: reversible PII masking.",
    )
    parser.add_argument("--version", action="version", version=f"pii-guard {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    up = sub.add_parser(
        "up",
        help="start here: API, gateway and web UI on one port (8787), offline mock model",
        description="Start everything in one process: the REST API, the OpenAI-compatible "
        "gateway and the bundled web UI at /. The gateway masks in fast mode (local rules, plus "
        "the on-device NER, installed by default; no LLM call). Without --upstream or "
        "--upstream-url "
        "(or PII_GUARD_UPSTREAM_BASE_URL) an offline mock model answers by echoing what it "
        "receives. --upstream meta: the Meta Model API with the key in $META_API_KEY.",
    )
    up.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    up.add_argument("--port", type=int, default=8787, help="port (default 8787)")
    up.add_argument("--no-browser", action="store_true", help="don't open the browser")
    up.add_argument(
        "--upstream",
        choices=sorted(PRESETS),
        default=None,
        help="a real model provider by name: "
        + ", ".join(f"{p.id} ({p.label}, key in ${p.key_env})" for p in PRESETS.values()),
    )
    up.add_argument(
        "--upstream-url",
        default=None,
        help="OpenAI-compatible upstream base URL (env: PII_GUARD_UPSTREAM_BASE_URL)",
    )
    up.add_argument(
        "--api-key-env",
        default=None,
        metavar="VAR",
        help="name of the environment variable holding the upstream key, e.g. OPENAI_API_KEY",
    )
    up.add_argument(
        "--mock", action="store_true", help="use the offline mock model even if an upstream is set"
    )
    up.add_argument(
        "--traffic-log",
        choices=["masked", "full"],
        default=None,
        help="live traffic log: masked (default, placeholders only) or full (also the original "
        "personal data; loopback binds only)",
    )

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

    connect = sub.add_parser(
        "connect",
        help="put a coding agent (Muse Code, pi, Codex, OpenCode) behind the gateway "
        "(docs/integrations/)",
        add_help=False,
    )
    connect.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)

    run = sub.add_parser(
        "run",
        help="start a local gateway and launch a coding agent (opencode, codex, claude-code, "
        "pi, muse-code)",
        add_help=False,
    )
    run.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)

    login = sub.add_parser(
        "login",
        help="authorize the CLI to send scrubbed telemetry to a hosted or self-hosted dashboard",
        add_help=False,
    )
    login.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)

    logout = sub.add_parser(
        "logout",
        help="revoke the CLI telemetry key and remove ~/.config/pii-guard/cli.json",
        add_help=False,
    )
    logout.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)

    baselines = sub.add_parser(
        "baselines", help="set up the comparison baselines (docs/evaluation.md)"
    )
    baselines_sub = baselines.add_subparsers(dest="baselines_command", metavar="<command>")
    baselines_sub.add_parser(
        "download",
        help="fetch, verify and unpack the pinned huSpaCy model once (needs --extra baselines)",
    )
    models = sub.add_parser("models", help="fetch the pinned on-device models (YuNet faces)")
    models_sub = models.add_subparsers(dest="models_command", metavar="<command>")
    fetch = models_sub.add_parser("fetch", help="download a pinned model (SHA-256 checked)")
    fetch.add_argument("model", nargs="?", default="yunet", choices=["yunet"])
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
        # Raw URL paths can contain bearer session handles and query values. LoggedRoute
        # records safe route templates instead; this also applies to reload workers.
        access_log=False,
    )
    return 0


def _dotenv_value(name: str) -> str | None:
    """``name`` from ``./.env`` (where the settings read theirs), or ``None``."""
    try:
        from dotenv import dotenv_values
    except ImportError:  # pragma: no cover - a pydantic-settings dependency
        return None
    return dotenv_values(".env").get(name) or None


def _preset(args: argparse.Namespace) -> tuple[str | None, str | None] | int:
    """``(upstream_url, api_key_env)`` for ``up``, from ``--upstream`` or the plain flags.

    A preset's key variable may also live in ``./.env``; it is then exported for this process.
    Only the variable's name is ever printed, never its value.
    """
    if args.upstream is None:
        return args.upstream_url, args.api_key_env
    if args.upstream_url:
        print("pii-guard up: pass --upstream or --upstream-url, not both", file=sys.stderr)
        return 2
    preset = PRESETS[args.upstream]
    key_env = args.api_key_env or preset.key_env
    if not os.environ.get(key_env):
        value = _dotenv_value(key_env)
        if value is None:
            print(
                f"pii-guard up: --upstream {preset.id} needs the {preset.label} key in "
                f"${key_env}: export {key_env}=<your-key> (or put it in .env)",
                file=sys.stderr,
            )
            return 2
        os.environ[key_env] = value
    return preset.base_url, key_env


def _up(args: argparse.Namespace) -> int:
    from pii_guard.app_bundle import UpOptions, run_up

    resolved = _preset(args)
    if isinstance(resolved, int):
        return resolved
    upstream_url, api_key_env = resolved
    return run_up(
        UpOptions(
            host=args.host,
            port=args.port,
            browser=not args.no_browser,
            upstream_url=upstream_url,
            api_key_env=api_key_env,
            mock=args.mock,
            traffic_log=args.traffic_log,
        )
    )


def _eval(args: argparse.Namespace) -> int:
    from pii_guard.eval.cli import main as eval_main

    return eval_main(args.args)


def _lang(args: argparse.Namespace) -> int:
    from pii_guard.languages.cli import main as lang_main

    return lang_main(args.args)


def _bench(args: argparse.Namespace) -> int:
    from pii_guard.bench.cli import main as bench_main

    return bench_main(args.args)


def _connect(args: argparse.Namespace) -> int:
    from pii_guard.integrations.cli import main as connect_main

    return connect_main(args.args)


def _run(args: argparse.Namespace) -> int:
    from pii_guard.integrations.run import main as run_main

    return run_main(args.args)


def _login(args: argparse.Namespace) -> int:
    from pii_guard.integrations.login import login_main

    return login_main(args.args)


def _logout(args: argparse.Namespace) -> int:
    from pii_guard.integrations.login import logout_main

    return logout_main(args.args)


def _models(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.models_command != "fetch":
        parser.parse_args(["models", "--help"])
        return 2  # pragma: no cover - --help exits
    from pii_guard.visual.segment import YUNET, fetch_model

    if args.model != "yunet":
        print(f"pii-guard models fetch: unknown model {args.model!r}", file=sys.stderr)
        return 2
    try:
        path = fetch_model()
    except Exception as exc:  # network or SHA-256 mismatch: message carries no image content
        print(f"pii-guard models fetch yunet: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"{path} ({YUNET.licence}, SHA-256 verified)")
    return 0


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


_PASSTHROUGH_COMMANDS = {
    "bench": _bench,
    "eval": _eval,
    "connect": _connect,
    "run": _run,
    "login": _login,
    "logout": _logout,
    "lang": _lang,
}


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in _PASSTHROUGH_COMMANDS:
        return _PASSTHROUGH_COMMANDS[argv[0]](argparse.Namespace(args=argv[1:]))
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        return _serve(args)
    if args.command == "up":
        return _up(args)
    if args.command == "baselines":
        return _baselines(args, parser)
    if args.command == "models":
        return _models(args, parser)
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
