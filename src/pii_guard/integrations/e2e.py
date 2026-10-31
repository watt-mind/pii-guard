"""End-to-end run: a real coding agent (pinned) works on the fictional mini-repo through the
gateway. Four clients: **pi** and **OpenCode** (Chat Completions), **Muse Code** and **Codex**
(Responses API).

```
uv run python -m pii_guard.integrations.e2e                       # pi, scripted mock (CI)
uv run python -m pii_guard.integrations.e2e --client muse-code    # Muse Code, scripted mock
uv run python -m pii_guard.integrations.e2e --client codex        # Codex, scripted mock
uv run python -m pii_guard.integrations.e2e --client opencode     # OpenCode, scripted mock
uv run python -m pii_guard.integrations.e2e --client muse-code --session per-request  # before
uv run python -m pii_guard.integrations.e2e --client muse-code --upstream https://api.meta.ai/v1 \\
    --model muse-spark-1.3 --key-env META_API_KEY --record examples/coding-agents/runs/<name>.json
```

What runs, all on loopback, in throwaway directories (``HOME`` and the client's config too):

1. The client is installed: pi ``PI_VERSION`` with npm into a temp prefix (or ``--pi-prefix``);
   Muse Code with its official installer (``MUSE_INSTALLER``) into a throwaway ``HOME`` (or
   ``--muse-home``), and only version ``MUSE_VERSION`` is run (``--muse-version`` runs another;
   an installer that serves a different version stops the run with :class:`MuseVersionError`).
2. A **recorder** stands in for the upstream: it keeps every request body it gets, then either
   answers like a scripted coding model (read the letter, read the CSV, read ``.env``, write
   ``reply.md`` with the placeholders it saw, finish), as Chat Completions chunks or as
   ``response.*`` events, or forwards to a real upstream (``--upstream``) with the key from
   ``--key-env``. The gateway and the client never hold that key.
3. The gateway (``create_app``) forwards to the recorder; ``pii-guard connect`` configures the
   client (pi's ``models.json``; Muse's ``settings.json``, ``endpoint_transport``). Muse can't
   send ``X-PII-Guard-Mode``, so its gateway runs in fast mode (``PII_GUARD_GATEWAY_MODE``).
4. The client runs headless (``pi --print``, ``muse exec``) on a copy of
   ``examples/coding-agents/mini-repo``. Codex and OpenCode need no config file: they run the
   Connect page's paste-and-run block (:mod:`pii_guard.integrations.snippets`) with
   ``exec`` / ``run`` appended, so the e2e covers the text users paste.

The result (:class:`RunResult`) says whether any gold value (``examples/coding-agents/gold.json``)
reached the upstream, whether the gateway refused a request, and what the agent wrote: the files
hold the real values again, because tool-call arguments come back restored. Values pii-guard
does not cover yet (names inside CSV rows) are counted separately as known gaps.

Sticky sessions (LAB-1286): ``--session`` picks how the client lands in a vault session.
``path`` (default) is what ``pii-guard connect`` writes, a ``/s/<session>/v1`` base URL;
``auto`` is the plain URL (the gateway uses the ``prompt_cache_key``, else the client's default
session); ``per-request`` gives every request a new session, the behaviour before LAB-1286. The
result counts the sessions and their sources (``X-PII-Guard-Session-Source``) and, from the
gateway's vault, how many gold values were masked under more than one placeholder
(``gold_unstable``: 0 means the same value had the same placeholder in every turn).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response

from pii_guard.integrations import snippets
from pii_guard.integrations.e2e_recorder import (
    _READS,
    SCRIPTED_MODEL,
    Recorder,
    _call_outputs,
    _chunk,
    _codex_turn,
    _function_names,
    _last_input_text,
    _pieces,
    _reply,
    _response_stream,
    _ResponseEvents,
    _scripted_turn,
    _seen,
    _tool_texts,
)
from pii_guard.integrations.e2e_recorder import (
    RunResult as RunResult,
)
from pii_guard.integrations.e2e_recorder import (
    _by_type as _by_type,
)
from pii_guard.integrations.e2e_recorder import (
    _ner_available as _ner_available,
)
from pii_guard.integrations.e2e_recorder import (
    _partial as _partial,
)
from pii_guard.integrations.e2e_recorder import (
    _request_keys as _request_keys,
)
from pii_guard.integrations.e2e_recorder import (
    _result as _result,
)
from pii_guard.integrations.e2e_recorder import (
    _stability as _stability,
)
from pii_guard.integrations.e2e_recorder import (
    _written as _written,
)
from pii_guard.integrations.muse_code import MUSE_VERSION_CHECKED
from pii_guard.integrations.snippets import CODEX_VERSION, OPENCODE_VERSION, PI_VERSION

__all__ = [
    "CODEX_VERSION",
    "EXAMPLE_DIR",
    "MUSE_INSTALLER",
    "MUSE_VERSION",
    "OPENCODE_VERSION",
    "PI_PACKAGE",
    "PI_VERSION",
    "PROMPT",
    "SCRIPTED_MODEL",
    "_READS",
    "MuseVersionError",
    "Recorder",
    "RunResult",
    "_ResponseEvents",
    "_call_outputs",
    "_chunk",
    "_codex_turn",
    "_function_names",
    "_last_input_text",
    "_pieces",
    "_reply",
    "_response_stream",
    "_scripted_turn",
    "_seen",
    "_tool_texts",
    "install_codex",
    "install_muse",
    "install_opencode",
    "install_pi",
    "load_gold",
    "main",
    "run",
    "run_codex",
    "run_muse",
    "run_opencode",
]

PI_PACKAGE = "@earendil-works/pi-coding-agent"
CODEX_PACKAGE = "@openai/codex"
OPENCODE_PACKAGE = "opencode-ai"
MUSE_VERSION = MUSE_VERSION_CHECKED
MUSE_INSTALLER = "https://dev.meta.ai/install.sh"
EXAMPLE_DIR = Path(__file__).resolve().parents[3] / "examples" / "coding-agents"
#: The key Muse Code sends the gateway in a run; the gateway replaces it with its own.
MUSE_RUN_KEY = "pii-guard-e2e-not-a-key"
PROMPT = (
    "Read client-letter.md, customers.csv and .env in this directory. Then write reply.md: a "
    "short reply to the author of the letter that confirms the refund to the IBAN they gave and "
    "repeats their email address and phone number, followed by a list of every customer's "
    "email address from customers.csv. Personal data in these files reaches you as placeholders "
    "such as [[EMAIL_1a2b3c]]: copy them into reply.md exactly as written, they are turned back "
    "into the real values on this machine. Do not change any other file. Answer with one "
    "sentence when you are done."
)


def load_gold(example_dir: Path = EXAMPLE_DIR) -> dict[str, Any]:
    return json.loads((example_dir / "gold.json").read_text(encoding="utf-8"))


# --- the clients -------------------------------------------------------------------------


def install_pi(prefix: Path, version: str = PI_VERSION) -> Path:
    """``pi`` from npm into ``prefix`` (skipped when that version is already there)."""
    binary = prefix / "node_modules" / ".bin" / "pi"
    package_json = prefix / "node_modules" / "@earendil-works" / "pi-coding-agent" / "package.json"
    installed = package_json.exists() and json.loads(package_json.read_text()).get("version")
    if binary.exists() and installed == version:
        return binary
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm is not installed")
    prefix.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603 - npm from PATH, a pinned package
        [
            npm,
            "install",
            "--prefix",
            str(prefix),
            f"{PI_PACKAGE}@{version}",
            "--no-fund",
            "--no-audit",
            "--loglevel=error",
        ],
        check=True,
        capture_output=True,
        timeout=600,
    )
    return binary


def _install_npm(prefix: Path, package: str, version: str, command: str) -> Path:
    """``command`` of ``package@version`` from npm into ``prefix`` (reused when it's there)."""
    binary = prefix / "node_modules" / ".bin" / command
    package_json = prefix / "node_modules" / Path(*package.split("/")) / "package.json"
    installed = package_json.exists() and json.loads(package_json.read_text()).get("version")
    if binary.exists() and installed == version:
        return binary
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm is not installed")
    prefix.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603 - npm from PATH, a pinned package
        [
            npm,
            "install",
            "--prefix",
            str(prefix),
            f"{package}@{version}",
            "--no-fund",
            "--no-audit",
            "--loglevel=error",
        ],
        check=True,
        capture_output=True,
        timeout=600,
    )
    if not binary.exists():
        raise RuntimeError(f"npm installed no {command} binary for {package}@{version}")
    return binary


def install_codex(prefix: Path, version: str = CODEX_VERSION) -> Path:
    """Codex (``@openai/codex``, with its platform binary) from npm into ``prefix``."""
    return _install_npm(prefix, CODEX_PACKAGE, version, "codex")


def install_opencode(prefix: Path, version: str = OPENCODE_VERSION) -> Path:
    """OpenCode (``opencode-ai``, with its platform binary) from npm into ``prefix``."""
    return _install_npm(prefix, OPENCODE_PACKAGE, version, "opencode")


class MuseVersionError(RuntimeError):
    """The official installer served another Muse Code version than the pinned one.

    Not a reason to skip: the e2e then no longer covers what users install. Re-run the protocol
    capture (docs/integrations/muse-code.md) and bump ``MUSE_VERSION_CHECKED``, or run the
    served version anyway with ``--muse-version`` (``PII_GUARD_MUSE_VERSION`` for the tests).
    """

    def __init__(self, served: str, pinned: str) -> None:
        self.served = served
        self.pinned = pinned
        super().__init__(
            f"the official Muse Code installer serves {served}, but this harness is pinned to "
            f"{pinned}. Re-run the protocol capture in docs/integrations/muse-code.md and bump "
            f"MUSE_VERSION_CHECKED (src/pii_guard/integrations/muse_code.py), or run {served} "
            f"anyway with --muse-version {served} (PII_GUARD_MUSE_VERSION={served} for pytest)"
        )


def install_muse(home: Path, version: str = MUSE_VERSION) -> Path:
    """Muse Code's binary, from the official installer into the throwaway ``home``.

    The installer always fetches the current release; only ``version`` is run (the protocol
    capture and these tests are for it). Another version raises :class:`MuseVersionError`:
    re-run the capture (docs/integrations/muse-code.md) and update ``MUSE_VERSION_CHECKED``, or
    pass the served version as ``version`` (``--muse-version``) to run it anyway.
    """
    bin_dir = home / ".local" / "bin"
    binary = bin_dir / f"muse-bin-{version}"
    if binary.exists():
        return binary
    bash = shutil.which("bash")
    if bash is None:
        raise RuntimeError("bash is not installed")
    home.mkdir(parents=True, exist_ok=True)
    script = home / "muse-install.sh"
    response = httpx.get(MUSE_INSTALLER, follow_redirects=True, timeout=60)
    response.raise_for_status()
    script.write_bytes(response.content)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "MUSE_NO_MODIFY_PATH": "1",
    }
    subprocess.run(  # noqa: S603 - the official installer, into a throwaway HOME
        [bash, str(script)], env=env, check=True, capture_output=True, timeout=900
    )
    if not binary.exists():
        # The launcher records the version it installed in .muse-version.
        state = bin_dir / ".muse-version"
        served = state.read_text(encoding="utf-8").strip() if state.exists() else ""
        if not served:
            found = sorted(p.name.removeprefix("muse-bin-") for p in bin_dir.glob("muse-bin-*"))
            if not found:
                raise RuntimeError("the Muse Code installer installed no muse-bin-* binary")
            served = found[-1]
        raise MuseVersionError(served, version)
    return binary


# --- servers -----------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def serve(app: Any, port: int | None = None) -> Iterator[str]:
    """Run an ASGI app with uvicorn in a thread; yields ``http://127.0.0.1:<port>``."""
    import uvicorn

    port = port or free_port()
    # lifespan "auto": the gateway's shutdown closes its pooled upstream client (LAB-1176).
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="auto")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


_COUNTED = ("/v1/chat/completions", "/v1/responses")
SESSIONS = ("path", "auto", "per-request")


def gateway_app(
    upstream_url: str,
    statuses: list[int],
    *,
    mode: str | None = None,
    calls: list[tuple[str, str]] | None = None,
    per_request_sessions: bool = False,
) -> FastAPI:
    """The gateway in front of ``upstream_url``; ``mode`` sets its default mode (Muse Code
    can't send ``X-PII-Guard-Mode``). ``calls`` collects ``(session, session source)`` per
    counted call; ``per_request_sessions`` sends every call to a new session (the gateway
    before LAB-1286)."""
    from pydantic import SecretStr

    from pii_guard.api.app import create_app
    from pii_guard.config import Settings
    from pii_guard.gateway import GatewayConfig, Mode

    settings = Settings(
        tenant_key=SecretStr(secrets.token_hex(32)),
        upstream_base_url=upstream_url,
        upstream_api_key=SecretStr("recorder-holds-the-real-key"),
    )
    app = create_app(settings)
    if mode is not None:
        app.state.gateway_config = GatewayConfig(mode=Mode(mode))

    @app.middleware("http")
    async def count(request: Request, call_next: Any) -> Response:
        # The path before SessionPathMiddleware: /s/<session>/v1/... counts too (LAB-1286).
        counted = re.sub(r"^/s/[^/]+", "", request.url.path) in _COUNTED
        if counted and per_request_sessions:
            path = f"/s/e2e_{secrets.token_hex(8)}{request.scope['path']}"
            request.scope["path"], request.scope["raw_path"] = path, path.encode()
        response = await call_next(request)
        if counted:
            statuses.append(response.status_code)
            if calls is not None:
                calls.append(
                    (
                        response.headers.get("x-pii-guard-session", ""),
                        response.headers.get("x-pii-guard-session-source", ""),
                    )
                )
        return response

    return app


# --- the run -----------------------------------------------------------------------------


@contextmanager
def _workspace(example_dir: Path, prefix: str) -> Iterator[tuple[Path, Path, set[Path]]]:
    """``(root, work, files before)``: a copy of the mini-repo in a throwaway directory."""
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        root = Path(tmp)
        work = root / "work"
        shutil.copytree(example_dir / "mini-repo", work)
        # Kept as env.fake in the repo (a tracked .env would be ignored by git, or loaded by
        # tools that read .env); the agent sees it under its usual name.
        (work / "env.fake").rename(work / ".env")
        yield root, work, {p.relative_to(work) for p in work.rglob("*") if p.is_file()}


def _client_run(cmd: list[str], cwd: Path, env: dict[str, str], timeout: float) -> Any:
    try:
        return subprocess.run(  # noqa: S603 - the pinned client this harness installed
            cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or b""
        text = partial.decode(errors="replace") if isinstance(partial, bytes) else partial
        return subprocess.CompletedProcess(exc.cmd, -1, text, "timed out")


def _connect(args: list[str]) -> None:
    from pii_guard.integrations.cli import main as connect

    with Path(os.devnull).open("w") as quiet:
        if connect(args, stdout=quiet) != 0:
            raise RuntimeError(f"pii-guard connect {args[0]} failed")


def run(
    *,
    pi_bin: Path,
    upstream: str | None = None,
    key: str | None = None,
    model: str | None = None,
    example_dir: Path = EXAMPLE_DIR,
    prompt: str = PROMPT,
    timeout: float = 900,
    session: str = "path",
) -> RunResult:
    """pi through the gateway (Chat Completions)."""
    gold = load_gold(example_dir)
    ner = _ner_available()
    started = time.monotonic()
    recorder = Recorder(upstream, key)
    statuses: list[int] = []
    calls: list[tuple[str, str]] = []
    with _workspace(example_dir, "pii-guard-pi-e2e-") as (root, work, before):
        agent_dir = root / "agent"
        fresh = session == "per-request"
        with (
            serve(recorder.app) as recorder_url,
            serve(
                app := gateway_app(
                    recorder_url + "/v1", statuses, calls=calls, per_request_sessions=fresh
                )
            ) as gateway_url,
        ):
            args = ["pi", "--gateway", gateway_url + "/v1", "--agent-dir", str(agent_dir)]
            args += [] if session == "path" else ["--no-session-path"]
            _connect(args + (["--model", model] if model else []))
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(root / "home"),
                "PI_CODING_AGENT_DIR": str(agent_dir),
                "PI_OFFLINE": "1",
                "PI_SKIP_VERSION_CHECK": "1",
                "PI_TELEMETRY": "0",
            }
            cmd = [str(pi_bin), "--print", "--no-session", "--provider", "pii-guard"]
            cmd += ["--model", model or SCRIPTED_MODEL, prompt]
            proc = _client_run(cmd, work, env, timeout)
        written, texts = _written(work, before)
    return _result(
        client="pi",
        version=PI_VERSION,
        upstream=upstream,
        model=model,
        proc=proc,
        output=proc.stdout + proc.stderr,
        recorder=recorder,
        statuses=statuses,
        written=written,
        texts=texts,
        gold=gold,
        ner=ner,
        started=started,
        app=app,
        calls=calls,
        session=session,
    )


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def run_muse(
    *,
    muse_bin: Path,
    upstream: str | None = None,
    key: str | None = None,
    model: str | None = None,
    example_dir: Path = EXAMPLE_DIR,
    prompt: str = PROMPT,
    timeout: float = 900,
    reasoning_effort: str = "low",
    session: str = "path",
    version: str = MUSE_VERSION,
) -> RunResult:
    """Muse Code through the gateway (Responses API), the gateway in fast mode. ``version`` is
    the one ``muse_bin`` is (recorded in the result)."""
    gold = load_gold(example_dir)
    ner = _ner_available()
    started = time.monotonic()
    recorder = Recorder(upstream, key)
    statuses: list[int] = []
    calls: list[tuple[str, str]] = []
    with _workspace(example_dir, "pii-guard-muse-e2e-") as (root, work, before):
        home = root / "home"
        config = home / ".config"
        fresh = session == "per-request"
        with (
            serve(recorder.app) as recorder_url,
            serve(
                app := gateway_app(
                    recorder_url + "/v1",
                    statuses,
                    mode="fast",
                    calls=calls,
                    per_request_sessions=fresh,
                )
            ) as gateway_url,
        ):
            muse_dir = str(config / "muse")  # Muse reads $XDG_CONFIG_HOME/muse/settings.json
            args = ["muse-code", "--gateway", gateway_url + "/v1", "--muse-dir", muse_dir]
            _connect(args + ([] if session == "path" else ["--no-session-path"]))
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(config),
                "META_API_KEY": MUSE_RUN_KEY,  # the gateway replaces it with its own key
                "MUSE_NO_AUTO_UPDATE": "1",
                "NO_COLOR": "1",
            }
            cmd = [str(muse_bin), "exec", "--model", model or SCRIPTED_MODEL]
            cmd += ["--reasoning-effort", reasoning_effort, "--workspace", str(work), prompt]
            proc = _client_run(cmd, work, env, timeout)
        written, texts = _written(work, before)
    return _result(
        client="muse-code",
        version=version,
        upstream=upstream,
        model=model,
        proc=proc,
        output=_ANSI_RE.sub("", proc.stdout + proc.stderr),
        recorder=recorder,
        statuses=statuses,
        written=written,
        texts=texts,
        gold=gold,
        ner=ner,
        started=started,
        app=app,
        calls=calls,
        session=session,
    )


def _snippet_command(tool: str, binary: Path, url: str, model: str, tail: str) -> list[str]:
    """The Connect page's block for ``tool`` (what a user pastes), run with ``binary`` and
    ``tail`` in place of the bare command at its end: the e2e covers the published text."""
    code = str(snippets.tool_snippet(tool, url, model, token=False)["code"])
    lines = code.split("\n")
    if tool == "codex":
        # The block is one command: `codex -m ... -c ...`; the run adds `exec ... "$PROMPT"`.
        code = code.replace("codex ", f"{shlex.quote(str(binary))} ", 1) + " " + tail
    else:
        # The block's last line starts the tool: `opencode`.
        code = "\n".join([*lines[:-1], f"{shlex.quote(str(binary))} {tail}"])
    bash = shutil.which("bash") or "/bin/bash"
    return [bash, "-c", code]


def _run_snippet_client(
    *,
    client: str,
    version: str,
    binary: Path,
    upstream: str | None,
    key: str | None,
    model: str | None,
    example_dir: Path,
    prompt: str,
    timeout: float,
    tail: str,
    extra_env: dict[str, str],
) -> RunResult:
    """A client configured by its quickstart block alone (no config file), gateway in fast
    mode, on the session URL the Connect page hands out."""
    gold = load_gold(example_dir)
    ner = _ner_available()
    started = time.monotonic()
    recorder = Recorder(upstream, key)
    statuses: list[int] = []
    calls: list[tuple[str, str]] = []
    with _workspace(example_dir, f"pii-guard-{client}-e2e-") as (root, work, before):
        recorder.workdir = work.resolve()
        home = root / "home"
        home.mkdir()
        with (
            serve(recorder.app) as recorder_url,
            serve(
                app := gateway_app(recorder_url + "/v1", statuses, mode="fast", calls=calls)
            ) as gateway_url,
        ):
            url = f"{gateway_url}/s/e2e_{secrets.token_hex(8)}/v1"
            cmd = _snippet_command(client, binary, url, model or SCRIPTED_MODEL, tail)
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_DATA_HOME": str(home / ".local" / "share"),
                "XDG_CACHE_HOME": str(home / ".cache"),
                "XDG_STATE_HOME": str(home / ".local" / "state"),
                "NO_COLOR": "1",
                "PII_GUARD_E2E_PROMPT": prompt,
                **extra_env,
            }
            proc = _client_run(cmd, work, env, timeout)
        written, texts = _written(work, before)
    return _result(
        client=client,
        version=version,
        upstream=upstream,
        model=model,
        proc=proc,
        output=_ANSI_RE.sub("", proc.stdout + proc.stderr),
        recorder=recorder,
        statuses=statuses,
        written=written,
        texts=texts,
        gold=gold,
        ner=ner,
        started=started,
        app=app,
        calls=calls,
        session="path",
    )


def run_codex(
    *,
    codex_bin: Path,
    upstream: str | None = None,
    key: str | None = None,
    model: str | None = None,
    example_dir: Path = EXAMPLE_DIR,
    prompt: str = PROMPT,
    timeout: float = 900,
    version: str = CODEX_VERSION,
    sandbox: str | None = None,
) -> RunResult:
    """Codex through the gateway (Responses API), started with the Connect page's block plus
    ``exec``: headless, the workspace writable, nothing outside it.

    ``sandbox`` is Codex's ``--sandbox`` mode. The default is ``workspace-write``, except on
    Linux: there Codex sandboxes commands with bubblewrap, which needs unprivileged user
    namespaces that hosted CI runners (Ubuntu 24.04's AppArmor default) refuse, so every
    command would fail. The run happens in a throwaway directory either way, and the result
    still records each file the agent wrote (``files_written``)."""
    if sandbox is None:
        sandbox = "danger-full-access" if sys.platform == "linux" else "workspace-write"
    codex_home = Path(tempfile.mkdtemp(prefix="pii-guard-codex-home-"))
    try:
        tail = (
            f"exec --skip-git-repo-check --sandbox {sandbox} --color never "
            '"$PII_GUARD_E2E_PROMPT" </dev/null'
        )
        return _run_snippet_client(
            client="codex",
            version=version,
            binary=codex_bin,
            upstream=upstream,
            key=key,
            model=model,
            example_dir=example_dir,
            prompt=prompt,
            timeout=timeout,
            tail=tail,
            extra_env={"CODEX_HOME": str(codex_home)},
        )
    finally:
        shutil.rmtree(codex_home, ignore_errors=True)


def run_opencode(
    *,
    opencode_bin: Path,
    upstream: str | None = None,
    key: str | None = None,
    model: str | None = None,
    example_dir: Path = EXAMPLE_DIR,
    prompt: str = PROMPT,
    timeout: float = 900,
    version: str = OPENCODE_VERSION,
) -> RunResult:
    """OpenCode through the gateway (Chat Completions), configured by the Connect page's
    ``OPENCODE_CONFIG_CONTENT`` alone, headless with ``opencode run``."""
    return _run_snippet_client(
        client="opencode",
        version=version,
        binary=opencode_bin,
        upstream=upstream,
        key=key,
        model=model,
        example_dir=example_dir,
        prompt=prompt,
        timeout=timeout,
        # --auto: OpenCode asks before reading .env (and, headless, refuses); the task reads it
        # on purpose, in a throwaway copy of the mini-repo.
        tail='run --auto "$PII_GUARD_E2E_PROMPT" </dev/null',
        extra_env={"OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_LSP_DOWNLOAD": "1"},
    )


def record(result: RunResult, path: Path) -> None:
    """A run record for ``examples/coding-agents/runs/``: counts, never the values.

    Not ``eval/results/runs/``: every record there follows the eval record schema.
    """
    data = asdict(result)
    data.pop("client_output")
    gold_upstream = data.pop("gold_upstream")
    restored = data.pop("restored_in_files")
    checked = data.pop("gold_checked")
    data["gold_partial_upstream"] = len(data["gold_partial_upstream"])
    data.update(
        {
            "kind": "coding-agent-e2e",
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "gateway_mode": "fast",
            "gold_checked": len(checked),
            "gold_upstream": len(gold_upstream),
            "restored_in_files": len(restored),
            "ok": result.ok,
            "data": "fictional (examples/coding-agents/mini-repo)",
        }
    )
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pii_guard.integrations.e2e")
    parser.add_argument("--client", choices=("pi", "muse-code", "codex", "opencode"), default="pi")
    parser.add_argument("--upstream", default=None, help="a real OpenAI-compatible base URL")
    parser.add_argument("--model", default=None, help="model id (required with --upstream)")
    parser.add_argument("--key-env", default=None, help="env var (or .env key) with its API key")
    parser.add_argument(
        "--pi-prefix", default=None, help="npm prefix for pi, Codex or OpenCode (default: temp)"
    )
    parser.add_argument(
        "--muse-home", default=None, help="throwaway HOME for the Muse Code install (default: temp)"
    )
    parser.add_argument(
        "--muse-version",
        default=MUSE_VERSION,
        help=f"the Muse Code version to run (default: the pinned {MUSE_VERSION}); another "
        "version than the installer serves stops with an error",
    )
    parser.add_argument(
        "--session",
        choices=SESSIONS,
        default="path",
        help="how the client reaches a vault session: the connect path URL (default), the "
        "plain URL (prompt_cache_key / default session), or a new one per request (before)",
    )
    parser.add_argument("--record", default=None, help="write a run record JSON here")
    parser.add_argument("--timeout", type=float, default=900, help="the client's time limit (s)")
    args = parser.parse_args(argv)
    if args.upstream and not args.model:
        parser.error("--upstream needs --model")
    key = None
    if args.key_env:
        key = os.environ.get(args.key_env) or _dotenv(args.key_env)
        if not key:
            parser.error(f"{args.key_env} is not set")
    if args.client in ("codex", "opencode"):
        prefix = (
            Path(args.pi_prefix)
            if args.pi_prefix
            else Path(tempfile.gettempdir()) / f"pii-guard-{args.client}"
        )
        if args.client == "codex":
            result = run_codex(
                codex_bin=install_codex(prefix),
                upstream=args.upstream,
                key=key,
                model=args.model,
                timeout=args.timeout,
            )
        else:
            result = run_opencode(
                opencode_bin=install_opencode(prefix),
                upstream=args.upstream,
                key=key,
                model=args.model,
                timeout=args.timeout,
            )
    elif args.client == "muse-code":
        home = (
            Path(args.muse_home)
            if args.muse_home
            else Path(tempfile.gettempdir()) / "pii-guard-muse"
        )
        try:
            muse_bin = install_muse(home, args.muse_version)
        except MuseVersionError as exc:
            parser.exit(2, f"error: {exc}\n")
        result = run_muse(
            muse_bin=muse_bin,
            version=args.muse_version,
            upstream=args.upstream,
            key=key,
            model=args.model,
            timeout=args.timeout,
            session=args.session,
        )
    else:
        prefix = (
            Path(args.pi_prefix) if args.pi_prefix else Path(tempfile.gettempdir()) / "pii-guard-pi"
        )
        result = run(
            pi_bin=install_pi(prefix),
            upstream=args.upstream,
            key=key,
            model=args.model,
            timeout=args.timeout,
            session=args.session,
        )
    summary = asdict(result)
    summary["gold_upstream"] = len(result.gold_upstream)  # counts only: never print values
    summary["restored_in_files"] = len(result.restored_in_files)
    summary["gold_checked"] = len(result.gold_checked)
    summary["gold_partial_upstream"] = len(result.gold_partial_upstream)
    summary["ok"] = result.ok
    print(json.dumps(summary, indent=2))
    if args.record:
        record(result, Path(args.record))
    return 0 if result.ok else 1


def _dotenv(name: str) -> str | None:
    path = Path(".env")
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
