"""``pii-guard connect``: put a coding agent behind the gateway.

```
pii-guard connect pi [--gateway URL] [--model ID ...] [--mode fast|audit] [--language en]
                     [--api-key VALUE] [--agent-dir DIR] [--no-session-path]
                     [--dry-run | --check]
pii-guard connect muse-code [--gateway URL] [--muse-dir DIR] [--model ID] [--no-session-path]
                            [--dry-run | --check]
pii-guard connect <tool> --print [--gateway URL] [--model ID]
                     # tool: muse-code, pi, codex, opencode, curl, python, claude-code
pii-guard connect codex|opencode --check [--gateway URL] [--model ID]
```

- ``--print`` prints the tool's paste-and-run block, the same text the web UI's Connect page
  shows: both read ``GET /v1/connect/snippets`` (:mod:`pii_guard.integrations.snippets`). For
  ``codex``, ``opencode``, ``curl``, ``python`` and ``claude-code`` printing is all ``connect``
  does (they need no config file), so ``--print`` is implied. When the gateway can't be asked,
  the block is built locally (with ``--model``, or a ``<model-id>`` to fill in).

- Both write a gateway base URL with a stable vault session in its path,
  ``http://127.0.0.1:8787/s/<session>/v1`` (LAB-1286): neither client can send
  ``X-PII-Guard-Session``, and with the session in the URL the same value gets the same
  placeholder in every turn and every conversation. The session already in the client's config
  is kept (``connect`` stays idempotent); a new one is random. ``--no-session-path`` writes the
  plain URL: the gateway then uses one session per ``prompt_cache_key`` (Muse sends one per
  conversation), else one per client key. A project endpoint URL (``/e/<endpoint>/v1``) is
  always written as given: endpoints have no ``/s/<session>`` form (LAB-1614).

- ``connect pi`` merges a ``pii-guard`` provider into pi's ``models.json`` (a backup of the old
  file first; nothing is written when it's already up to date). For a project endpoint URL the
  provider has no ``X-PII-Guard-Mode`` / ``-Language`` headers: the endpoint's policy sets
  both and refuses a request that names others (LAB-1651). ``--dry-run`` prints the diff
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

- ``connect codex --check`` and ``connect opencode --check`` write nothing (those tools take
  the block's flags or variable, no config file): they send the canary the way the block's
  client does, to a fresh path session on ``--gateway``. Codex: a non-streamed
  ``POST <base_url>/responses``; OpenCode: ``POST <base_url>/chat/completions`` without
  ``X-PII-Guard-*`` headers (so the gateway's default mode and language). The model is
  ``--model`` or the one the Connect page suggests.

Exit codes: 0 done, 1 the check failed, 2 bad arguments or a problem to fix.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

import httpx

from pii_guard.gateway.config import cli_mode
from pii_guard.integrations import muse_code, pi, snippets
from pii_guard.integrations.common import (
    DASHBOARD_URL,
    ConnectError,
    _without_session,
    default_gateway_url,
    fetch_models,
    is_endpoint_url,
    json_diff,
    run_check,
    session_of,
    session_url,
    write_json,
)

__all__ = ["build_parser", "main"]

#: Clients ``connect`` writes a config file for (and can ``--check``).
CONFIGURED = ("pi", "muse-code")
#: Tools without a config file that ``--check`` still covers: the canary goes the way their
#: block sends requests (LAB-1469). Codex: ``POST /responses``; OpenCode: ``/chat/completions``
#: without pii-guard headers.
BLOCK_CHECKED = ("codex", "opencode")
#: Every tool with a quickstart block (``--print``).
CLIENTS = snippets.TOOL_IDS


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
        help="X-PII-Guard-Mode the client sends (default: fast, rules + NER); not written "
        "for a project endpoint URL, whose policy sets the mode",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="X-PII-Guard-Language the client sends (default: en); not written for a project "
        "endpoint URL, whose policy sets the language",
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
    action.add_argument(
        "--print",
        action="store_true",
        dest="print_snippet",
        help="print the paste-and-run block the web UI's Connect page shows; write nothing",
    )
    return parser


def _token() -> str | None:
    from pii_guard.config import get_settings

    token = get_settings().api_token
    return token.get_secret_value() if token is not None else None


def _gateway(args: argparse.Namespace, existing: object) -> str:
    """The base URL to write: ``--gateway`` or the default, with the config's session kept."""
    gateway = (args.gateway or default_gateway_url()).rstrip("/")
    if not args.session_path or is_endpoint_url(gateway):
        return gateway
    return session_url(gateway, existing if isinstance(existing, str) else None)


def _check_url(args: argparse.Namespace, configured: object) -> object:
    """The URL ``--check`` sends the canary to: the client's configured base URL.

    ``--gateway`` without a session that names the same gateway as the config keeps the
    config's session (LAB-1469): ``pii-guard up`` prints ``connect <client> --gateway URL
    --check``, and that check went to the gateway's default session, not the path session
    the client actually uses. A different gateway, or one with its own session, wins.
    """
    if not args.gateway:
        return configured
    gateway = str(args.gateway).rstrip("/")
    if (
        isinstance(configured, str)
        and session_of(gateway) is None
        and session_of(configured) is not None
        and _without_session(configured) == gateway
    ):
        return configured.rstrip("/")
    return gateway


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


def _pi_check(path: Path, args: argparse.Namespace, out: list[str]) -> int:
    existing, _ = pi.load(path)
    entry = (existing.get("providers") or {}).get(pi.PROVIDER_ID)
    if not isinstance(entry, dict):
        raise ConnectError(f"{path} has no {pi.PROVIDER_ID!r} provider; run `pii-guard connect pi`")
    base_url = _check_url(args, entry.get("baseUrl"))
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
    base_url = _check_url(args, transport.get("base_url") if isinstance(transport, dict) else None)
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


def _snippets_document(root: str, session: str, model: str | None) -> dict[str, object]:
    """The gateway's ``GET /v1/connect/snippets``."""
    params = {"session": session, **({"model": model} if model else {})}
    token = _token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = httpx.get(
        root + "/v1/connect/snippets",
        params=params,
        headers=headers,
        timeout=httpx.Timeout(20.0, connect=3.0),
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("not a snippets document")
    return data


def _snippets_from_gateway(root: str, session: str, model: str | None) -> list[object]:
    """The ``tools`` of the gateway's ``GET /v1/connect/snippets``."""
    tools = _snippets_document(root, session, model).get("tools")
    if not isinstance(tools, list):
        raise ValueError("not a snippets document")
    return tools


def _print(args: argparse.Namespace, out: list[str]) -> int:
    """The tool's quickstart block: from the gateway when it answers, else built locally."""
    gateway = (args.gateway or default_gateway_url()).rstrip("/")
    session = session_of(gateway) or session_of(session_url(gateway))
    root = _without_session(gateway)
    root = root[: -len("/v1")] if root.endswith("/v1") else root
    model = (args.model or [None])[0]
    if model is not None and snippets.safe_model(model) is None:
        raise ConnectError(f"--model {model!r} is not a model id")
    tool: dict[str, object] | None = None
    try:
        tools = _snippets_from_gateway(root, str(session), model)
        tool = next((t for t in tools if isinstance(t, dict) and t.get("id") == args.client), None)
    except (httpx.HTTPError, ValueError) as exc:
        print(
            f"note: the gateway at {root} didn't answer ({type(exc).__name__}); "
            "built locally" + ("" if model else ", fill in <model-id>"),
            file=sys.stderr,
        )
    if tool is None:
        url = f"{root}/s/{session}/v1"
        tool = snippets.tool_snippet(args.client, url, model, token=_token() is not None)
    if tool.get("code"):
        out.append(snippets.printable(tool))
    print(f"# {tool.get('note')}", file=sys.stderr)
    return 0 if tool.get("supported") else 1


def _block_check(args: argparse.Namespace, out: list[str]) -> int:
    """``connect codex|opencode --check``: the canary the way the tool's block sends it."""
    gateway = (args.gateway or default_gateway_url()).rstrip("/")
    base_url = gateway
    if args.session_path and session_of(gateway) is None and not is_endpoint_url(gateway):
        base_url = session_url(gateway)
    token = _token()
    model = (args.model or [None])[0]
    if model is None:
        root = _without_session(gateway)
        root = root[: -len("/v1")] if root.endswith("/v1") else root
        try:  # the model the Connect page puts in the block
            suggested = _snippets_document(root, str(session_of(base_url)), None).get("model")
            model = suggested if isinstance(suggested, str) else None
        except (httpx.HTTPError, ValueError):
            model = None
        model = model or fetch_models(gateway, token=token)[0]
    if args.client == "codex":
        result, mode = muse_code.run_check(base_url, model, token=token)
    else:
        result, mode = run_check(base_url, model, token=token), ""
    out.append(f"client       : {args.client} (no config file: the Connect block's base URL)")
    out.extend(result.lines())
    if mode:
        out.append(f"gateway mode : {mode}")
    out.append(f"dashboard    : {DASHBOARD_URL} (with PII_GUARD_TRAFFIC_LOG=masked or full)")
    return 0 if result.ok else 1


def main(argv: Sequence[str] | None = None, *, stdout: TextIO | None = None) -> int:
    stdout = stdout or sys.stdout
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    out: list[str] = []
    try:
        if args.check and not args.print_snippet and args.client in BLOCK_CHECKED:
            code = _block_check(args, out)
        elif args.print_snippet or args.client not in CONFIGURED:
            if args.dry_run or args.check:
                checked = ", ".join((*CONFIGURED, *BLOCK_CHECKED))
                raise ConnectError(
                    f"--dry-run is for {' and '.join(CONFIGURED)}; --check for {checked}"
                )
            code = _print(args, out)
        else:
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
