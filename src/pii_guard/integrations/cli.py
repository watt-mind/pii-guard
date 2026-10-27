"""``pii-guard connect``: put a coding agent behind the gateway.

```
pii-guard connect pi [--gateway URL] [--model ID ...] [--mode fast|strict] [--language en]
                     [--api-key VALUE] [--agent-dir DIR] [--no-session-path]
                     [--dry-run | --check]
pii-guard connect muse-code [--gateway URL] [--muse-dir DIR] [--model ID] [--no-session-path]
                            [--dry-run | --check]
```

- Both write a gateway base URL with a stable vault session in its path,
  ``http://127.0.0.1:8787/s/<session>/v1`` (LAB-1286): neither client can send
  ``X-PII-Guard-Session``, and with the session in the URL the same value gets the same
  placeholder in every turn and every conversation. The session already in the client's config
  is kept (``connect`` stays idempotent); a new one is random. ``--no-session-path`` writes the
  plain URL: the gateway then uses one session per ``prompt_cache_key`` (Muse sends one per
  conversation), else one per client key.

- ``connect pi`` merges a ``pii-guard`` provider into pi's ``models.json`` (a backup of the old
  file first; nothing is written when it's already up to date). ``--dry-run`` prints the diff
  and writes nothing; it works without a running gateway (the model list is then empty unless
  ``--model`` gives it).
- ``connect pi --check`` sends one fictional canary request the way pi would (the provider's
  ``baseUrl``, headers and first model from ``models.json``) and prints what was sent, what the
  model saw (masked) and what came back (restored). With the traffic log on, the call shows
  up on the Live traffic tab.
- ``connect muse-code`` points Muse Code's ``settings.json`` (``$XDG_CONFIG_HOME/muse``,
  default ``~/.config/muse``) at the gateway: ``endpoint_transport.base_url`` and
  ``endpoint_transport.auth: "bearer"``, keeping every other setting (backup first, idempotent,
  ``--dry-run``). Muse then reads ``/muse-code/models`` and sends ``/v1/responses`` through
  pii-guard. ``--check`` sends the canary the way Muse does (``POST <base_url>/responses``, with
  ``$META_API_KEY`` as Muse sends it) and prints what the model saw and what came back.

Exit codes: 0 done, 1 the check failed, 2 bad arguments or a problem to fix.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

import httpx

from pii_guard.integrations import muse_code, pi
from pii_guard.integrations.common import (
    DASHBOARD_URL,
    ConnectError,
    default_gateway_url,
    fetch_models,
    json_diff,
    run_check,
    session_url,
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
        choices=("fast", "strict"),
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
    parser.add_argument(
        "--muse-dir",
        default=None,
        help="Muse Code's config dir (default: $XDG_CONFIG_HOME/muse or ~/.config/muse)",
    )
    parser.add_argument(
        "--session-path",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="put a stable vault session in the base URL, /s/<session>/v1 (default: on)",
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


def _gateway(args: argparse.Namespace, existing: object) -> str:
    """The base URL to write: ``--gateway`` or the default, with the config's session kept."""
    gateway = (args.gateway or default_gateway_url()).rstrip("/")
    if not args.session_path:
        return gateway
    return session_url(gateway, existing if isinstance(existing, str) else None)


def _pi(args: argparse.Namespace, out: list[str]) -> int:
    path = pi.config_path(args.agent_dir)
    if args.check:
        return _pi_check(path, args, out)
    existing, old = pi.load(path)
    ours = (existing.get("providers") or {}).get(pi.PROVIDER_ID)
    gateway = _gateway(args, ours.get("baseUrl") if isinstance(ours, dict) else None)
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
    out.append(f"gateway: {gateway}")
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


def _muse(args: argparse.Namespace, out: list[str]) -> int:
    path = muse_code.config_path(args.muse_dir)
    existing, old = muse_code.load(path)
    if args.check:
        return _muse_check(path, existing, args, out)
    transport = existing.get("endpoint_transport")
    gateway = _gateway(args, transport.get("base_url") if isinstance(transport, dict) else None)
    new = muse_code.render(existing, old, gateway)
    diff = json_diff(path, old, new)
    if args.dry_run:
        out.append(diff or f"{path} is already up to date")
        return 0
    backup = write_json(path, new)
    if old == new:
        out.append(f"{path} is already up to date (endpoint_transport -> {gateway})")
    else:
        out.append(diff)
        if backup is not None:
            out.append(f"backup: {backup}")
        out.append(f"wrote {path}: endpoint_transport.base_url = {gateway}, auth = bearer")
    out.append(f"note: {muse_code.MODE_NOTE}")
    out.append("next: muse   (check it: pii-guard connect muse-code --check)")
    return 0


def _muse_check(
    path: os.PathLike[str], existing: dict[str, object], args: argparse.Namespace, out: list[str]
) -> int:
    transport = existing.get("endpoint_transport")
    base_url = args.gateway or (transport.get("base_url") if isinstance(transport, dict) else None)
    if not isinstance(base_url, str) or not base_url:
        raise ConnectError(
            f"{path} has no endpoint_transport.base_url; run `pii-guard connect muse-code`"
        )
    # Muse sends $META_API_KEY (or its saved key) as the bearer token; so does the check.
    token = os.environ.get("META_API_KEY") or _token()
    model = (args.model or [None])[0] or muse_code.fetch_catalog(base_url, token=token)[0]
    result, mode = muse_code.run_check(base_url, model, token=token)
    out.append(f"client config: {path}")
    out.extend(result.lines())
    if mode:
        out.append(f"gateway mode : {mode}")
    if mode == "strict":
        out.append(f"note         : {muse_code.MODE_NOTE}")
    out.append(f"dashboard    : {DASHBOARD_URL} (with PII_GUARD_TRAFFIC_LOG=masked or full)")
    return 0 if result.ok else 1


def main(argv: Sequence[str] | None = None, *, stdout=None) -> int:  # type: ignore[no-untyped-def]
    stdout = stdout or sys.stdout
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    out: list[str] = []
    try:
        code = _muse(args, out) if args.client == "muse-code" else _pi(args, out)
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
