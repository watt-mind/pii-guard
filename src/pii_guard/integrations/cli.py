"""``pii-guard connect``: put a coding agent behind the gateway.

```
pii-guard connect pi [--gateway URL] [--model ID ...] [--mode fast|audit] [--language en]
                     [--api-key VALUE] [--agent-dir DIR] [--dry-run | --check]
pii-guard connect muse-code
```

- ``connect pi`` merges a ``pii-guard`` provider into pi's ``models.json`` (a backup of the old
  file first; nothing is written when it's already up to date). ``--dry-run`` prints the diff
  and writes nothing; it works without a running gateway (the model list is then empty unless
  ``--model`` gives it).
- ``connect pi --check`` sends one fictional canary request the way pi would (the provider's
  ``baseUrl``, headers and first model from ``models.json``) and prints what was sent, what the
  model saw (masked) and what came back (restored). With the traffic log on, the call shows
  up on the Live traffic tab.
- ``connect muse-code`` prints why Muse Code can't be connected yet (docs/integrations/).

Exit codes: 0 done, 1 the check failed (or Muse Code), 2 bad arguments or a problem to fix.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

import httpx

from pii_guard.gateway.config import cli_mode
from pii_guard.integrations import muse_code, pi
from pii_guard.integrations.common import (
    DASHBOARD_URL,
    ConnectError,
    default_gateway_url,
    fetch_models,
    json_diff,
    run_check,
    write_json,
)

__all__ = ["build_parser", "main"]

CLIENTS = ("pi", "muse-code")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pii-guard connect",
        description="Put a coding agent behind the pii-guard gateway (docs/integrations/).",
    )
    parser.add_argument("client", choices=CLIENTS, help="the client to configure")
    parser.add_argument(
        "--gateway",
        default=None,
        help="the gateway's OpenAI base URL (default: http://127.0.0.1:<PII_GUARD_PORT>/v1)",
    )
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        metavar="ID",
        help="a model id to offer (repeatable; default: the gateway's GET /v1/models)",
    )
    parser.add_argument(
        "--mode",
        type=lambda v: cli_mode(v, "pii-guard connect"),
        choices=("fast", "audit"),
        default="fast",
        help="X-PII-Guard-Mode the client sends (default: fast, rules + NER)",
    )
    parser.add_argument(
        "--language", default="en", help="X-PII-Guard-Language the client sends (default: en)"
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="the key the client sends to the gateway, e.g. '$MY_KEY' (default: "
        "$PII_GUARD_API_TOKEN when the gateway needs a token, else a placeholder)",
    )
    parser.add_argument(
        "--agent-dir",
        default=None,
        help="pi's agent dir (default: $PI_CODING_AGENT_DIR or ~/.pi/agent)",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", action="store_true", help="print the diff, write nothing")
    action.add_argument(
        "--check", action="store_true", help="send one fictional canary through the client path"
    )
    return parser


def _token() -> str | None:
    from pii_guard.config import get_settings

    token = get_settings().api_token
    return token.get_secret_value() if token is not None else None


def _pi(args: argparse.Namespace, out: list[str]) -> int:
    path = pi.config_path(args.agent_dir)
    if args.check:
        return _pi_check(path, args, out)
    gateway = (args.gateway or default_gateway_url()).rstrip("/")
    token = _token()
    models = list(dict.fromkeys(args.model or []))
    if not models:
        try:
            models = fetch_models(gateway, token=token)
        except ConnectError as exc:
            if not args.dry_run:
                raise
            print(f"warning: {exc}; the diff below lists no models", file=sys.stderr)
    if not models and not args.dry_run:
        raise ConnectError(f"the gateway at {gateway} lists no models; pass --model")
    api_key = args.api_key or ("$PII_GUARD_API_TOKEN" if token else None)
    entry = pi.provider_entry(
        gateway, models, mode=args.mode, language=args.language, api_key=api_key
    )
    existing, old = pi.load(path)
    new = pi.render(existing, old, entry)
    diff = json_diff(path, old, new)
    if args.dry_run:
        out.append(diff or f"{path} is already up to date")
        return 0
    backup = write_json(path, new)
    if old == new:
        out.append(f"{path} is already up to date (provider {pi.PROVIDER_ID!r})")
    else:
        out.append(diff)
        if backup is not None:
            out.append(f"backup: {backup}")
        out.append(f"wrote {path}: provider {pi.PROVIDER_ID!r}, {len(models)} model(s)")
    out.append(
        f"next: pi --provider {pi.PROVIDER_ID} --model {models[0]}   "
        "(check it: pii-guard connect pi --check)"
    )
    return 0


def _pi_check(path: os.PathLike[str], args: argparse.Namespace, out: list[str]) -> int:
    existing, _ = pi.load(path)  # type: ignore[arg-type]
    entry = (existing.get("providers") or {}).get(pi.PROVIDER_ID)
    if not isinstance(entry, dict):
        raise ConnectError(f"{path} has no {pi.PROVIDER_ID!r} provider; run `pii-guard connect pi`")
    base_url = args.gateway or entry.get("baseUrl")
    models = [m.get("id") for m in entry.get("models") or [] if isinstance(m, dict)]
    model = (args.model or [None])[0] or next((m for m in models if isinstance(m, str)), None)
    if not isinstance(base_url, str) or not model:
        raise ConnectError(f"{path}: the {pi.PROVIDER_ID!r} provider needs baseUrl and a model")
    headers = {
        str(k): v
        for k, raw in (entry.get("headers") or {}).items()
        if isinstance(raw, str) and (v := pi.resolve_value(raw)) is not None
    }
    result = run_check(
        base_url, model, headers=headers, token=pi.resolve_value(entry.get("apiKey"))
    )
    out.append(f"client config: {path} (provider {pi.PROVIDER_ID!r})")
    out.extend(result.lines())
    out.append(f"dashboard    : {DASHBOARD_URL} (with PII_GUARD_TRAFFIC_LOG=masked or full)")
    return 0 if result.ok else 1


def main(argv: Sequence[str] | None = None, *, stdout=None) -> int:  # type: ignore[no-untyped-def]
    stdout = stdout or sys.stdout
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    out: list[str] = []
    try:
        if args.client == "muse-code":
            out.append(muse_code.FINDING.rstrip("\n"))
            code = 1
        else:
            code = _pi(args, out)
    except ConnectError as exc:
        for line in out:
            print(line, file=stdout)
        print(f"pii-guard connect: {exc}", file=sys.stderr)
        return 2
    except httpx.HTTPError as exc:  # pragma: no cover - fetch/check catch their own
        print(f"pii-guard connect: {type(exc).__name__}", file=sys.stderr)
        return 2
    for line in out:
        print(line.rstrip("\n"), file=stdout)
    return code
