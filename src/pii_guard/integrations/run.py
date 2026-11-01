"""``pii-guard run <client>``: start a local on-device gateway and launch a coding agent.

```
pii-guard run opencode [--upstream meta|openai|fireworks|openrouter] [--model ID]
                       [--dashboard URL|local|off] [--dashboard-key KEY] [--endpoint ID]
                       [--telemetry-level masked|stats] [-- <agent_args>...]
pii-guard run codex|claude-code|pi|muse-code|muse [options] [-- <agent_args>...]
```

All PII detection and masking run locally in-process on ``127.0.0.1`` and the masked prompt goes
straight from the local machine to the upstream LLM provider. Telemetry can stay in memory
(``--dashboard off``), be served by the bundled web UI on the local gateway port
(``--dashboard local``), or be shipped as scrubbed ``masked`` or ``stats`` events to a hosted
(``https://guard.watt-mind.com``) or self-hosted dashboard via ``PII_GUARD_REMOTE_URL`` /
``PII_GUARD_REMOTE_KEY`` / ``PII_GUARD_REMOTE_LEVEL``, configured by ``pii-guard login`` (a saved
telemetry-only key) or by flags.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import SecretStr

from pii_guard.app_bundle import MockServer, Status, create_bundle_app
from pii_guard.config import Settings, get_settings
from pii_guard.gateway import GatewayConfig, Mode
from pii_guard.gateway.config import cli_mode
from pii_guard.integrations import muse_code, pi, snippets
from pii_guard.integrations.common import ConnectError, fetch_models
from pii_guard.integrations.login import (
    CliProfile,
    TelemetryLevel,
    dashboard_origin,
    load_cli_profile,
    run_browser_login,
    save_cli_profile,
)
from pii_guard.observability import resolve_ingest_url
from pii_guard.upstreams import PRESETS, Upstream, by_url

__all__ = [
    "AUTO_UPSTREAM_ORDER",
    "CLIENT_ALIASES",
    "DEFAULT_DASHBOARD_URL",
    "RUNNABLE_CLIENTS",
    "DashboardTarget",
    "ResolvedUpstream",
    "build_agent_invocation",
    "build_parser",
    "child_base_env",
    "main",
    "prompt_first_run_dashboard",
    "resolve_dashboard",
    "resolve_upstream",
    "run_agent",
    "split_agent_argv",
]

RUNNABLE_CLIENTS = ("opencode", "codex", "claude-code", "pi", "muse-code")
#: Short binary-name aliases accepted for ``client`` (e.g. ``pii-guard run muse``).
CLIENT_ALIASES: dict[str, str] = {"muse": "muse-code", "claude": "claude-code"}
AUTO_UPSTREAM_ORDER = ("meta", "openai", "openrouter", "fireworks")
DEFAULT_DASHBOARD_URL = "https://guard.watt-mind.com"
ANTHROPIC_UPSTREAM_URL = "https://api.anthropic.com/v1"
ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-5"
MOCK_DEFAULT_MODEL = "pii-guard-mock"
_ENDPOINT_ID_RE = re.compile(r"^(?:/)?(?:e/)?([A-Za-z0-9_-]{1,64})(?:/v1(?:/traffic)?)?/?$")


@dataclass(frozen=True)
class ResolvedUpstream:
    """The upstream provider URL, API key value, and optional preset."""

    base_url: str
    api_key: str
    label: str
    preset: Upstream | None = None
    mock: bool = False


@dataclass(frozen=True)
class DashboardTarget:
    """Resolved remote or local dashboard ingestion settings and display URL."""

    remote_url: str | None
    remote_key: str | None
    remote_level: str
    display_url: str | None
    local_ui: bool = False
    project_name: str | None = None


def split_agent_argv(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split ``argv`` at ``--`` into ``(run_args, agent_args)``."""
    items = list(argv)
    if "--" in items:
        idx = items.index("--")
        return items[:idx], items[idx + 1 :]
    return items, []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pii-guard run",
        description=(
            "Start a local on-device PII Guard gateway and launch a coding agent "
            "(opencode, codex, claude-code/claude, pi, muse-code/muse) with optional remote or "
            "local dashboard telemetry."
        ),
    )
    parser.add_argument(
        "client",
        type=lambda v: CLIENT_ALIASES.get(v, v),
        choices=RUNNABLE_CLIENTS,
        help="coding agent to launch (opencode, codex, claude-code/claude, pi, muse-code/muse)",
    )
    parser.add_argument(
        "--upstream",
        choices=sorted(PRESETS),
        default=None,
        help="upstream provider preset: "
        + ", ".join(f"{p.id} ({p.label}, key in ${p.key_env})" for p in PRESETS.values()),
    )
    parser.add_argument(
        "--upstream-url",
        default=None,
        help="OpenAI-compatible or Anthropic upstream base URL (env: PII_GUARD_UPSTREAM_BASE_URL)",
    )
    parser.add_argument(
        "--api-key-env",
        default=None,
        metavar="VAR",
        help="environment variable holding the upstream API key, e.g. OPENAI_API_KEY",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="use the offline mock model even if an upstream key is set",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="ID",
        help="model ID to pass to the coding agent (default: discovered from GET /v1/models)",
    )
    parser.add_argument(
        "--mode",
        type=lambda v: cli_mode(v, "pii-guard run"),
        choices=("fast", "audit"),
        default="fast",
        help="gateway masking mode (default: fast, local rules + NER)",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="default language pack for detection (default: en)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="loopback port for the local gateway on 127.0.0.1 (default: 0, ephemeral free port)",
    )
    parser.add_argument(
        "--traffic-log",
        choices=("off", "masked", "full"),
        default="masked",
        help="local traffic log level (default: masked)",
    )
    parser.add_argument(
        "--dashboard",
        default=None,
        metavar="URL",
        help=(
            "dashboard for telemetry: a remote https URL (env: PII_GUARD_DASHBOARD_URL or "
            f"PII_GUARD_REMOTE_URL; default: {DEFAULT_DASHBOARD_URL} when a key is set, else "
            "the `pii-guard login` profile), 'local' to serve the web UI on the local gateway "
            "port, or 'off'"
        ),
    )
    parser.add_argument(
        "--dashboard-key",
        default=None,
        metavar="KEY",
        help=(
            "remote dashboard API token or pg_ep_ endpoint key; discouraged, since argv shows "
            "in ps and shell history: prefer PII_GUARD_DASHBOARD_KEY or --dashboard-key-env"
        ),
    )
    parser.add_argument(
        "--dashboard-key-env",
        default=None,
        metavar="VAR",
        help="environment variable holding the remote dashboard / endpoint key",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        metavar="ID",
        help="project endpoint ID (e.g. ep_abc123) on the remote dashboard",
    )
    parser.add_argument(
        "--telemetry-level",
        choices=("masked", "stats"),
        default=None,
        help="remote telemetry detail level: masked (default) or stats (counts/timings only)",
    )
    parser.add_argument(
        "--agent-bin",
        default=None,
        metavar="PATH",
        help="override the coding agent executable path or name",
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
        "--print-env",
        action="store_true",
        help="print the resolved gateway URL, environment, and command without running the agent",
    )
    return parser


def _env_or_dotenv(name: str) -> str | None:
    """Read ``name`` from ``os.environ`` or ``./.env``."""
    val = os.environ.get(name)
    if val:
        return val
    try:
        from dotenv import dotenv_values
    except ImportError:  # pragma: no cover
        return None
    raw = dotenv_values(".env").get(name)
    return raw if raw else None


def _env(name: str) -> str | None:
    """Read ``name`` from the real environment only.

    Where traffic goes (upstream and dashboard URLs, endpoint, telemetry level) is never taken
    from a project's ``./.env``: a cloned repo must not be able to redirect the upstream or
    switch on monitoring (LAB-1705). Keys may still come from ``./.env``.
    """
    return os.environ.get(name) or None


def _resolve_preset_upstream(args: argparse.Namespace) -> ResolvedUpstream:
    if args.upstream_url:
        raise ConnectError("pass --upstream or --upstream-url, not both")
    preset = PRESETS[args.upstream]
    key_env = args.api_key_env or preset.key_env
    key = _env_or_dotenv(key_env)
    if not key:
        raise ConnectError(
            f"--upstream {preset.id} needs the {preset.label} key in ${key_env}: "
            f"export {key_env}=<your-key> (or put it in .env)"
        )
    return ResolvedUpstream(
        base_url=preset.base_url,
        api_key=key,
        label=f"{preset.id} ({preset.base_url})",
        preset=preset,
    )


def _resolve_explicit_url_upstream(args: argparse.Namespace, url: str) -> ResolvedUpstream:
    preset = by_url(url)
    key = ""
    if args.api_key_env:
        found = _env_or_dotenv(args.api_key_env)
        if not found:
            raise ConnectError("the variable named by --api-key-env is not set")
        key = found
    else:
        key = (
            _env_or_dotenv("PII_GUARD_UPSTREAM_API_KEY")
            or (preset and _env_or_dotenv(preset.key_env))
            or ""
        )
    return ResolvedUpstream(base_url=url, api_key=key, label=url, preset=preset)


def resolve_upstream(args: argparse.Namespace) -> ResolvedUpstream:
    """Resolve the upstream LLM provider from CLI flags or environment variables."""
    if args.mock:
        return ResolvedUpstream(base_url="mock", api_key="", label="mock", mock=True)
    if args.upstream is not None:
        return _resolve_preset_upstream(args)
    explicit_url = args.upstream_url or _env("PII_GUARD_UPSTREAM_BASE_URL")
    if explicit_url:
        return _resolve_explicit_url_upstream(args, explicit_url)
    if args.client == "claude-code":
        key_env = args.api_key_env or "ANTHROPIC_API_KEY"
        key = _env_or_dotenv(key_env)
        if key:
            return ResolvedUpstream(
                base_url=ANTHROPIC_UPSTREAM_URL,
                api_key=key,
                label=f"anthropic ({ANTHROPIC_UPSTREAM_URL})",
            )
        raise ConnectError(
            f"claude-code needs ${key_env} set (or pass --upstream-url / --mock): "
            f"export {key_env}=<your-key>"
        )
    for preset_id in AUTO_UPSTREAM_ORDER:
        preset = PRESETS[preset_id]
        key = _env_or_dotenv(preset.key_env)
        if key:
            return ResolvedUpstream(
                base_url=preset.base_url,
                api_key=key,
                label=f"{preset.id} ({preset.base_url})",
                preset=preset,
            )
    envs = ", ".join(f"${PRESETS[p].key_env}" for p in AUTO_UPSTREAM_ORDER)
    raise ConnectError(
        f"no upstream provider configured; export one of {envs}, pass --upstream <name>, "
        "or pass --mock for the offline mock model"
    )


def _normalize_endpoint_id(endpoint: str) -> str:
    match = _ENDPOINT_ID_RE.fullmatch(endpoint.strip())
    if match is None:
        raise ConnectError(f"--endpoint {endpoint!r} is not a valid endpoint id")
    return match.group(1)


def _display_dashboard_url(remote_url: str) -> str:
    parts = urlsplit(remote_url)
    origin = f"{parts.scheme}://{parts.hostname or ''}" + (f":{parts.port}" if parts.port else "")
    return f"{origin}/#traffic"


def _off(level: str) -> DashboardTarget:
    return DashboardTarget(remote_url=None, remote_key=None, remote_level=level, display_url=None)


def _validated_remote_url(remote_url: str, what: str) -> str:
    try:
        resolve_ingest_url(remote_url)  # https only (http for loopback), no credentials
    except ValueError as exc:
        raise ConnectError(f"{what}: {exc}") from None
    return remote_url


def _target_from_profile(profile: CliProfile, level_override: str | None) -> DashboardTarget:
    """Turn a saved login profile into a dashboard target, validating it like a flag."""
    level = level_override or profile.telemetry_level
    if profile.mode == "local":
        return _off(level)
    if not profile.dashboard_url or not profile.endpoint_id or not profile.endpoint_key:
        raise ConnectError(
            "the saved login profile has no dashboard, endpoint or key; "
            "run `pii-guard login` again (or `pii-guard logout`)"
        )
    try:
        origin = dashboard_origin(profile.dashboard_url)
    except ConnectError as exc:
        raise ConnectError(f"saved login profile: {exc}") from None
    remote_url = _validated_remote_url(
        f"{origin}/e/{_normalize_endpoint_id(profile.endpoint_id)}/v1", "saved login profile"
    )
    return DashboardTarget(
        remote_url=remote_url,
        remote_key=profile.endpoint_key,
        remote_level=level,
        display_url=_display_dashboard_url(remote_url),
        project_name=profile.project_name or profile.project_id,
    )


def _login_and_save(
    login_fn: Callable[..., CliProfile], url: str, level: str, stderr: Any
) -> CliProfile:
    profile = login_fn(url, telemetry_level="stats" if level == "stats" else None, stderr=stderr)
    _target_from_profile(profile, None)  # refuse to save anything run would refuse to use
    save_cli_profile(profile)
    return profile


def prompt_first_run_dashboard(
    *,
    telemetry_level: TelemetryLevel = "masked",
    input_fn: Callable[[str], str] = input,
    login_fn: Callable[..., CliProfile] = run_browser_login,
    stderr: Any = None,
) -> CliProfile:
    """Interactive first-run prompt when no CLI profile or ``--dashboard`` flag is configured."""
    err = stderr or sys.stderr
    print(
        "Where should PII Guard send scrubbed session telemetry?\n"
        f"  [1] Hosted dashboard ({DEFAULT_DASHBOARD_URL}, sign in with the browser)\n"
        "  [2] Local only (keep all metrics on this machine)\n"
        "  [3] Self-hosted dashboard URL",
        file=err,
    )
    choice = input_fn("Select [1/2/3] (default: 2): ").strip() or "2"
    if choice == "1":
        return _login_and_save(login_fn, DEFAULT_DASHBOARD_URL, telemetry_level, err)
    if choice == "3":
        custom_url = input_fn("Self-hosted dashboard URL: ").strip()
        return _login_and_save(login_fn, custom_url, telemetry_level, err)
    profile = CliProfile(mode="local", telemetry_level=telemetry_level)
    save_cli_profile(profile)
    return profile


def _resolve_dashboard_key(args: argparse.Namespace) -> str | None:
    if args.dashboard_key_env:
        key = _env_or_dotenv(args.dashboard_key_env)
        if not key:
            raise ConnectError("the variable named by --dashboard-key-env is not set")
        return key
    return (
        args.dashboard_key
        or _env("PII_GUARD_DASHBOARD_KEY")
        or _env("PII_GUARD_REMOTE_KEY")
        or _env("PII_GUARD_ENDPOINT_KEY")
    )


def _resolve_implicit_dashboard(
    args: argparse.Namespace,
    level: str,
    *,
    profile: CliProfile | None,
    interactive: bool,
    input_fn: Callable[[str], str],
    login_fn: Callable[..., CliProfile],
    stderr: Any,
) -> DashboardTarget:
    saved = profile if profile is not None else load_cli_profile()
    if saved is not None:
        return _target_from_profile(saved, args.telemetry_level)
    if interactive:
        chosen = prompt_first_run_dashboard(
            telemetry_level="stats" if level == "stats" else "masked",
            input_fn=input_fn,
            login_fn=login_fn,
            stderr=stderr,
        )
        return _target_from_profile(chosen, args.telemetry_level)
    return _off(level)


def resolve_dashboard(
    args: argparse.Namespace,
    *,
    profile: CliProfile | None = None,
    interactive: bool = False,
    input_fn: Callable[[str], str] = input,
    login_fn: Callable[..., CliProfile] = run_browser_login,
    stderr: Any = None,
) -> DashboardTarget:
    """Resolve dashboard telemetry from flags, the real environment, or the login profile.

    Flags and environment win; with none set, the saved ``pii-guard login`` profile is used, and
    an interactive first run asks where telemetry should go.
    """
    level = (
        args.telemetry_level
        or _env("PII_GUARD_REMOTE_LEVEL")
        or _env("PII_GUARD_TELEMETRY_LEVEL")
        or "masked"
    )
    raw_url = args.dashboard or _env("PII_GUARD_DASHBOARD_URL") or _env("PII_GUARD_REMOTE_URL")
    if raw_url and raw_url.strip().lower() in ("off", "none", "false", "0"):
        return _off(level)
    if raw_url and raw_url.strip().lower() == "local":
        return DashboardTarget(
            remote_url=None, remote_key=None, remote_level=level, display_url=None, local_ui=True
        )
    key = _resolve_dashboard_key(args)
    endpoint = args.endpoint or _env("PII_GUARD_ENDPOINT_ID")
    if not raw_url and not key and not endpoint:
        return _resolve_implicit_dashboard(
            args,
            level,
            profile=profile,
            interactive=interactive,
            input_fn=input_fn,
            login_fn=login_fn,
            stderr=stderr,
        )
    base = (raw_url or DEFAULT_DASHBOARD_URL).strip().rstrip("/")
    parts = urlsplit(base)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConnectError(f"--dashboard {base!r} must be an http:// or https:// URL")
    if not key and not endpoint and "/e/" not in parts.path:
        # A bare dashboard URL: use the login profile for it, or log in to it.
        origin = dashboard_origin(base)
        saved = profile if profile is not None else load_cli_profile()
        if saved and saved.mode == "remote" and saved.dashboard_url:
            with suppress(ConnectError):
                if dashboard_origin(saved.dashboard_url) == origin:
                    return _target_from_profile(saved, args.telemetry_level)
        if interactive:
            logged_in = _login_and_save(login_fn, origin, level, stderr)
            return _target_from_profile(logged_in, args.telemetry_level)
    if endpoint and "/e/" not in parts.path:
        ep_id = _normalize_endpoint_id(endpoint)
        remote_url = f"{base}/e/{ep_id}/v1"
    else:
        remote_url = base
    _validated_remote_url(remote_url, "--dashboard")
    return DashboardTarget(
        remote_url=remote_url,
        remote_key=key,
        remote_level=level,
        display_url=_display_dashboard_url(remote_url),
    )


def _resolve_binary(client: str, override: str | None) -> str:
    if override:
        found = shutil.which(override)
        if found:
            return found
        if Path(override).is_file():
            return str(Path(override).resolve())
        raise ConnectError(f"executable {override!r} was not found")
    candidates = {
        "opencode": ("opencode",),
        "codex": ("codex",),
        "claude-code": ("claude", "claude-code"),
        "pi": ("pi",),
        "muse-code": ("muse",),
    }[client]
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found
    raise ConnectError(
        f"{client} executable ({candidates[0]!r}) was not found on PATH; install it or pass "
        "--agent-bin"
    )


def _opencode_config_json(
    session_url: str, model: str, existing_raw: str | None, *, token_env: str | None
) -> str:
    base: dict[str, Any] = {}
    if existing_raw:
        try:
            loaded = json.loads(existing_raw)
            if isinstance(loaded, dict):
                base = dict(loaded)
        except ValueError:
            base = {}
    raw_providers = base.get("provider")
    providers = dict(raw_providers) if isinstance(raw_providers, dict) else {}
    options: dict[str, Any] = {"baseURL": session_url}
    if token_env:
        options["apiKey"] = "{env:" + token_env + "}"
    providers["pii-guard"] = {
        "npm": "@ai-sdk/openai-compatible",
        "name": "pii-guard",
        "options": options,
        "models": {model: dict(snippets.OPENCODE_MODEL_CAPABILITIES)},
    }
    base["provider"] = providers
    base["model"] = f"pii-guard/{model}"
    return json.dumps(base, separators=(",", ":"))


# The gateway token the agents authenticate with; every other PII Guard variable stays private.
_KEEP_PII_GUARD = frozenset({snippets.TOKEN_ENV})


def child_base_env(
    environ: dict[str, str] | None = None, *, extra_secret_envs: Sequence[str | None] = ()
) -> dict[str, str]:
    """The environment the agent starts from: no provider key, dashboard key or gateway setting.

    The agent must only ever reach the model through the local gateway. A provider key left in
    its environment would let it (or a built-in provider it supports) go around the filter, and
    any shell tool could print it into a transcript (LAB-1705).
    """
    source = dict(os.environ if environ is None else environ)
    secret_envs = {p.key_env for p in PRESETS.values()}
    secret_envs |= {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY"}
    secret_envs |= {e for e in extra_secret_envs if e}
    return {
        k: v
        for k, v in source.items()
        if k not in secret_envs and (not k.startswith("PII_GUARD_") or k in _KEEP_PII_GUARD)
    }


def build_agent_invocation(
    client: str,
    binary: str,
    session_url: str,
    model: str,
    agent_args: Sequence[str],
    *,
    base_env: dict[str, str] | None = None,
    token: str | None = None,
    agent_dir: str | None = None,
    muse_dir: str | None = None,
    configure: bool = True,
) -> tuple[list[str], dict[str, str]]:
    """Build ``(command_argv, child_env)`` to launch ``client`` behind ``session_url``.

    ``base_env`` defaults to :func:`child_base_env`. ``configure=False`` skips writing pi's and
    Muse Code's config files (``--print-env``).
    """
    client = CLIENT_ALIASES.get(client, client)
    env = child_base_env() if base_env is None else dict(base_env)
    extra = list(agent_args)
    if client == "opencode":
        token_env = snippets.TOKEN_ENV if token else None
        env["OPENCODE_CONFIG_CONTENT"] = _opencode_config_json(
            session_url, model, env.get("OPENCODE_CONFIG_CONTENT"), token_env=token_env
        )
        return [binary, *extra], env
    if client == "codex":
        provider = f'name="pii-guard", base_url="{session_url}", wire_api="responses"'
        if token:
            provider += f', env_key="{snippets.TOKEN_ENV}"'
        cmd = [
            binary,
            "-m",
            model,
            "-c",
            "model_provider=pii-guard",
            "-c",
            f"model_providers.pii-guard={{{provider}}}",
            "-c",
            "web_search=disabled",
            *extra,
        ]
        return cmd, env
    if client == "claude-code":
        base = session_url[: -len("/v1")] if session_url.endswith("/v1") else session_url
        env["ANTHROPIC_BASE_URL"] = base
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        if token:
            env["ANTHROPIC_AUTH_TOKEN"] = token
        else:
            env["ANTHROPIC_API_KEY"] = "unused"
        return [binary, "--model", model, *extra], env
    if client == "pi":
        from pii_guard.integrations.cli import main as connect_main

        c_args = ["pi", "--gateway", session_url, "--model", model]
        if agent_dir:
            c_args += ["--agent-dir", agent_dir]
        if configure and connect_main(c_args, stdout=io.StringIO()) != 0:
            raise ConnectError("failed to configure pi models.json")
        return [binary, "--provider", "pii-guard", "--model", model, *extra], env
    from pii_guard.integrations.cli import main as connect_main

    c_args = ["muse-code", "--gateway", session_url, "--model", model]
    if muse_dir:
        c_args += ["--muse-dir", muse_dir]
    if configure and connect_main(c_args, stdout=io.StringIO()) != 0:
        raise ConnectError("failed to configure Muse Code settings.json")
    # Always the placeholder: Muse Code sends it as its bearer to the local gateway.
    env["META_API_KEY"] = "pii-guard-local"
    return [binary, *extra], env


def _discover_model(
    args: argparse.Namespace,
    upstream: ResolvedUpstream,
    gateway_base_url: str,
    token: str | None,
) -> str:
    if args.model:
        if snippets.safe_model(args.model) is None:
            raise ConnectError(f"--model {args.model!r} is not a valid model id")
        return str(args.model)
    if args.client == "claude-code":
        return ANTHROPIC_DEFAULT_MODEL
    if upstream.mock:
        return MOCK_DEFAULT_MODEL
    try:
        models = fetch_models(gateway_base_url, token=token)
    except ConnectError:
        models = []
    if models:
        return snippets.pick_model(models, upstream.preset, mock_model=None)
    if upstream.preset and upstream.preset.default_model:
        return upstream.preset.default_model
    return snippets.FALLBACK_MODEL


def _config_files(args: argparse.Namespace) -> list[Path]:
    """The agent config files ``run`` writes for this client (restored afterwards)."""
    if args.client == "pi":
        return [Path(pi.config_path(args.agent_dir))]
    if args.client == "muse-code":
        return [Path(muse_code.config_path(args.muse_dir))]
    return []


@contextmanager
def _restored_files(paths: Sequence[Path]) -> Iterator[None]:
    """Put ``paths`` back as they were, and drop the backups written meanwhile.

    ``run`` points pi and Muse Code at a throwaway port; left behind, a plain ``muse`` would
    send its bearer to whatever takes that port next (LAB-1705).
    """
    saved = {p: p.read_bytes() if p.exists() else None for p in paths}
    backups = {p: set(p.parent.glob(f"{p.name}.pii-guard-backup-*")) for p in paths}
    try:
        yield
    finally:
        for p, old in saved.items():
            if old is None:
                p.unlink(missing_ok=True)
            else:
                p.write_bytes(old)
            for new_backup in set(p.parent.glob(f"{p.name}.pii-guard-backup-*")) - backups[p]:
                new_backup.unlink(missing_ok=True)


def run_agent(cmd: Sequence[str], env: dict[str, str]) -> int:
    """Run the agent to completion and return its exit status (``128 + n`` for signal ``n``).

    Ctrl-C reaches the agent from the terminal (same process group) and means "cancel this
    turn" to interactive agents, so this process ignores SIGINT while waiting instead of
    killing the agent. SIGTERM and SIGHUP sent to this process are forwarded to the agent, so
    it never outlives its gateway.
    """
    proc = subprocess.Popen(list(cmd), env=env)  # noqa: S603

    def forward(signum: int, _frame: object) -> None:
        with suppress(ProcessLookupError):
            proc.send_signal(signum)

    handlers: dict[int, Any] = {}
    if threading.current_thread() is threading.main_thread():
        handlers[signal.SIGINT] = signal.signal(signal.SIGINT, signal.SIG_IGN)
        for name in ("SIGTERM", "SIGHUP"):
            signum = getattr(signal, name, None)
            if signum is not None:
                handlers[signum] = signal.signal(signum, forward)
    try:
        code = proc.wait()
    finally:
        for signum, previous in handlers.items():
            signal.signal(signum, previous)
    return 128 - code if code < 0 else code


@contextmanager
def _TemporaryEnv(overrides: dict[str, str | None]) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in overrides}
    try:
        for k, v in overrides.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()
        yield
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
        get_settings.cache_clear()


def _create_gateway_app(
    settings: Settings, *, local_ui: bool, mode: str, upstream_label: str
) -> Any:
    from pii_guard.api.app import create_app

    app = (
        create_bundle_app(Status(upstream=upstream_label), settings)
        if local_ui
        else create_app(settings)
    )
    app.state.gateway_config = GatewayConfig(mode=Mode(mode))
    return app


@contextmanager
def _local_gateway(
    args: argparse.Namespace,
    upstream: ResolvedUpstream,
    dashboard: DashboardTarget,
) -> Iterator[tuple[str, Any]]:
    import uvicorn

    mock_server: MockServer | None = None
    # No SO_REUSEADDR: on macOS it can let 127.0.0.1:<port> bind while another server holds
    # 0.0.0.0:<port>, hiding a collision with a running `pii-guard up`.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", args.port))
    except OSError as exc:
        sock.close()
        raise ConnectError(f"port {args.port} on 127.0.0.1 is in use ({exc})") from exc
    actual_port = int(sock.getsockname()[1])

    if upstream.mock:
        mock_server = MockServer()
        mock_server.start()
        upstream_url = mock_server.base_url
    else:
        upstream_url = upstream.base_url

    tenant_key = _env_or_dotenv("PII_GUARD_TENANT_KEY") or secrets.token_hex(32)
    meta_key = (
        upstream.api_key
        if (upstream.preset and upstream.preset.id == "meta" and upstream.api_key)
        else _env_or_dotenv("META_API_KEY")
    )
    env_overrides: dict[str, str | None] = {
        "PII_GUARD_HOST": "127.0.0.1",
        "PII_GUARD_PORT": str(actual_port),
        "PII_GUARD_GATEWAY_MODE": args.mode,
        "PII_GUARD_TRAFFIC_LOG": args.traffic_log,
        "PII_GUARD_REMOTE_URL": dashboard.remote_url,
        "PII_GUARD_REMOTE_KEY": dashboard.remote_key,
        "PII_GUARD_REMOTE_LEVEL": dashboard.remote_level if dashboard.remote_url else None,
    }
    stack_logger = logging.getLogger("pii_guard.gateway.detection")
    prev_stack_level = stack_logger.level
    if args.mode == "fast":
        stack_logger.setLevel(logging.ERROR)
    with _TemporaryEnv(env_overrides):
        try:
            settings = Settings(
                host="127.0.0.1",
                port=actual_port,
                tenant_key=SecretStr(tenant_key),
                upstream_base_url=upstream_url,
                upstream_api_key=SecretStr(upstream.api_key) if upstream.api_key else None,
                meta_api_key=SecretStr(meta_key) if meta_key else None,
                default_language=args.language,
            )
            app = _create_gateway_app(
                settings,
                local_ui=dashboard.local_ui,
                mode=args.mode,
                upstream_label="mock" if upstream.mock else upstream.label,
            )
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=actual_port,
                log_level="warning",
                lifespan="auto",
                timeout_graceful_shutdown=2,
            )
            server = uvicorn.Server(config)
            thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
            thread.start()
            deadline = time.monotonic() + 15.0
            while not server.started:
                if time.monotonic() > deadline or not thread.is_alive():
                    server.should_exit = True
                    sock.close()
                    if mock_server is not None:
                        mock_server.stop()
                    raise ConnectError("local gateway did not start")
                time.sleep(0.02)
            try:
                yield f"http://127.0.0.1:{actual_port}", app
            finally:
                obs = getattr(app.state, "observability", None)
                flush = getattr(obs, "flush", None)
                if callable(flush):
                    flush()
                server.should_exit = True
                thread.join(timeout=5.0)
                sock.close()
                if mock_server is not None:
                    mock_server.stop()
        finally:
            stack_logger.setLevel(prev_stack_level)


def _print_banner(
    client: str,
    gateway_root: str,
    model: str,
    mode: str,
    traffic_log: str,
    upstream: ResolvedUpstream,
    dashboard: DashboardTarget,
    *,
    stderr: Any,
) -> None:
    print(
        f"pii-guard run {client}: gateway {gateway_root}/v1 "
        f"(mode={mode}, model={model}, upstream={upstream.label})",
        file=stderr,
    )
    if mode == "fast":
        from pii_guard.detect.stack import default_detector_names, ner_choice

        settings = get_settings()
        if "ner" in default_detector_names(settings) and not ner_choice(settings).ready:
            print(
                f"pii-guard run {client}: first run, the NER model downloads in the background; "
                "the first requests wait for it",
                file=stderr,
            )
    if dashboard.local_ui:
        from pii_guard.app_bundle import ui_available

        where = f"{gateway_root}/#traffic" if ui_available() else f"{gateway_root}/v1/traffic"
        print(
            f"pii-guard run {client}: local dashboard {where} (traffic log={traffic_log})",
            file=stderr,
        )
    elif dashboard.display_url:
        project = f"project={dashboard.project_name!r}, " if dashboard.project_name else ""
        print(
            f"pii-guard run {client}: remote dashboard {dashboard.display_url} "
            f"({project}telemetry={dashboard.remote_level})",
            file=stderr,
        )


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: Any = None,
    stderr: Any = None,
    interactive: bool | None = None,
    input_fn: Callable[[str], str] = input,
    login_fn: Callable[..., CliProfile] = run_browser_login,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    own_argv, agent_args = split_agent_argv(raw_argv)
    parser = build_parser()
    args, trailing = parser.parse_known_args(own_argv)
    if trailing:
        if trailing[0].startswith("-"):
            parser.error(
                f"unrecognized arguments: {' '.join(trailing)} (pass '--' before agent flags)"
            )
        agent_args = [*trailing, *agent_args]

    is_tty = (
        not args.print_env and hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        if interactive is None
        else interactive
    )
    try:
        upstream = resolve_upstream(args)
        dashboard = resolve_dashboard(
            args, interactive=is_tty, input_fn=input_fn, login_fn=login_fn, stderr=stderr
        )
        # Taken before the gateway's overrides go into os.environ, minus every secret.
        base_env = child_base_env(extra_secret_envs=(args.api_key_env, args.dashboard_key_env))
        binary = "dry-run" if args.print_env else _resolve_binary(args.client, args.agent_bin)
        with _local_gateway(args, upstream, dashboard) as (gateway_root, _app):
            session_id = f"c_{secrets.token_hex(16)}"
            session_url = f"{gateway_root}/s/{session_id}/v1"
            token_secret = get_settings().api_token
            token = token_secret.get_secret_value() if token_secret is not None else None
            model = _discover_model(args, upstream, f"{gateway_root}/v1", token)
            restore = _restored_files([] if args.print_env else _config_files(args))
            with restore:
                cmd, child_env = build_agent_invocation(
                    args.client,
                    binary,
                    session_url,
                    model,
                    agent_args,
                    base_env=base_env,
                    token=token,
                    agent_dir=args.agent_dir,
                    muse_dir=args.muse_dir,
                    configure=not args.print_env,
                )
                if not args.print_env:
                    _print_banner(
                        args.client,
                        gateway_root,
                        model,
                        args.mode,
                        args.traffic_log,
                        upstream,
                        dashboard,
                        stderr=stderr,
                    )
                    return run_agent(cmd, child_env)
            info = {
                "client": args.client,
                "gateway_url": f"{gateway_root}/v1",
                "session_url": session_url,
                "upstream": upstream.base_url,
                "model": model,
                "mode": args.mode,
                "remote_url": dashboard.remote_url,
                "remote_level": dashboard.remote_level if dashboard.remote_url else None,
                "dashboard_url": (
                    f"{gateway_root}/#traffic" if dashboard.local_ui else dashboard.display_url
                ),
                "local_ui": dashboard.local_ui,
                "command": cmd,
            }
            print(json.dumps(info, indent=2), file=stdout)
            return 0
    except ConnectError as exc:
        print(f"pii-guard run: {exc}", file=stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        # Ctrl-C at the first-run prompt or while waiting for the browser login.
        print("\npii-guard run: cancelled", file=stderr)
        return 130
