"""End-to-end run: a real coding agent (pinned) works on the fictional mini-repo through the
gateway. Two clients: **pi** (Chat Completions) and **Muse Code** (Responses API).

```
uv run python -m pii_guard.integrations.e2e                       # pi, scripted mock (CI)
uv run python -m pii_guard.integrations.e2e --client muse-code    # Muse Code, scripted mock
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
   ``examples/coding-agents/mini-repo``.

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
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from pii_guard.integrations.muse_code import MUSE_VERSION_CHECKED
from pii_guard.vault import SessionNotFoundError
from pii_guard.vault.placeholders import PLACEHOLDER_RE, normalize_value

__all__ = [
    "EXAMPLE_DIR",
    "MUSE_INSTALLER",
    "MUSE_VERSION",
    "PI_PACKAGE",
    "PI_VERSION",
    "PROMPT",
    "MuseVersionError",
    "Recorder",
    "RunResult",
    "install_muse",
    "install_pi",
    "load_gold",
    "main",
    "run",
    "run_muse",
]

PI_PACKAGE = "@earendil-works/pi-coding-agent"
PI_VERSION = "1.4.0"
MUSE_VERSION = MUSE_VERSION_CHECKED
MUSE_INSTALLER = "https://dev.meta.ai/install.sh"
EXAMPLE_DIR = Path(__file__).resolve().parents[3] / "examples" / "coding-agents"
SCRIPTED_MODEL = "pii-guard-mock-coder"
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
_READS = ("client-letter.md", "customers.csv", ".env")


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


# --- the recorder (upstream stand-in) ----------------------------------------------------


def _chunk(delta: dict[str, Any], finish: str | None = None) -> str:
    event = {
        "id": "chatcmpl-mock-coder",
        "object": "chat.completion.chunk",
        "created": 1_800_000_000,
        "model": SCRIPTED_MODEL,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _pieces(text: str, size: int = 5) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def _tool_texts(body: dict[str, Any]) -> list[str]:
    out = []
    for message in body.get("messages") or []:
        if isinstance(message, dict) and message.get("role") == "tool":
            content = message.get("content")
            if isinstance(content, list):
                content = "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
            out.append(str(content or ""))
    return out


def _seen(texts: list[str]) -> list[str]:
    return list(dict.fromkeys(m.group(0) for m in PLACEHOLDER_RE.finditer("\n".join(texts))))


def _reply(seen: list[str]) -> str:
    return "Reply to the client\n\n" + "\n".join(f"- {p}" for p in seen) + "\n"


# Responses API (Muse Code) -----------------------------------------------------------------


def _function_names(body: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    """Bare tool name -> (the name a call uses, its definition). Namespaced tools are called
    ``<namespace>.<name>`` (``muse.read_file``), as the Meta Model API does."""
    names: dict[str, tuple[str, dict[str, Any]]] = {}
    for tool in body.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "namespace":
            for sub in tool.get("tools") or []:
                if isinstance(sub, dict) and isinstance(sub.get("name"), str):
                    names[sub["name"]] = (f"{tool.get('name')}.{sub['name']}", sub)
        elif isinstance(tool.get("name"), str):
            names[tool["name"]] = (tool["name"], tool)
    return names


def _call_outputs(body: dict[str, Any]) -> list[str]:
    out = []
    for item in body.get("input") or []:
        if isinstance(item, dict) and item.get("type") == "function_call_output":
            output = item.get("output")
            if isinstance(output, list):
                output = "\n".join(str(p.get("text", "")) for p in output if isinstance(p, dict))
            out.append(str(output or ""))
    return out


def _last_input_text(body: dict[str, Any]) -> str:
    items = body.get("input")
    if isinstance(items, str):
        return items
    for item in reversed(items or []):
        if isinstance(item, dict) and item.get("role") == "user":
            content = item.get("content")
            if isinstance(content, list):
                return "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
            return str(content or "")
    return ""


def _scripted_turn(body: dict[str, Any]) -> tuple[str, Any]:
    """``("call", (name, arguments))`` or ``("text", text)`` for one Responses request."""
    names = _function_names(body)
    if "submit_reminder_decision" in names:
        # Muse's side observers (skill, goal, verify reminders): decide "none".
        name, definition = names["submit_reminder_decision"]
        required = (definition.get("parameters") or {}).get("required") or []
        arguments: dict[str, Any] = {key: None for key in required if isinstance(key, str)}
        arguments["decision"] = "none"
        return "call", (name, arguments)
    if "read_file" not in names or "write_file" not in names:
        return "text", "OK."
    outputs = _call_outputs(body)
    step = len(outputs)
    if step < len(_READS):
        return "call", (names["read_file"][0], {"path": _READS[step]})
    if step == len(_READS):
        return "call", (
            names["write_file"][0],
            {"path": "reply.md", "content": _reply(_seen(outputs))},
        )
    return "text", "Done: wrote reply.md."


class _ResponseEvents:
    """One scripted ``response.*`` stream (the shape the Meta Model API sends)."""

    def __init__(self, number: int) -> None:
        self.id = f"resp_mock_{number}"
        self.sequence = 0
        self.lines: list[str] = []

    def add(self, event_type: str, **fields: Any) -> None:
        event = {"type": event_type, **fields, "sequence_number": self.sequence}
        self.sequence += 1
        self.lines.append(f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n")

    def response(self, status: str, output: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "id": self.id,
            "object": "response",
            "created_at": 1_800_000_000,
            "status": status,
            "model": SCRIPTED_MODEL,
            "output": output,
            "store": False,
        }


def _response_stream(number: int, turn: tuple[str, Any]) -> list[str]:
    events = _ResponseEvents(number)
    events.add("response.created", response=events.response("in_progress", []))
    events.add("response.in_progress", response=events.response("in_progress", []))
    # An opaque reasoning item, as the Meta Model API sends with include=[encrypted_content].
    reasoning = {"id": f"rs_mock_{number}", "type": "reasoning", "summary": []}
    events.add("response.output_item.added", output_index=0, item={**reasoning, "status": "x"})
    reasoning = {**reasoning, "encrypted_content": f"mock-encrypted-{number}", "status": "done"}
    events.add("response.output_item.done", output_index=0, item=reasoning)
    kind, payload = turn
    if kind == "text":
        item_id = f"msg_mock_{number}"
        item: dict[str, Any] = {
            "id": item_id,
            "type": "message",
            "role": "assistant",
            "content": [],
        }
        events.add("response.output_item.added", output_index=1, item=item)
        part: dict[str, Any] = {"type": "output_text", "text": "", "annotations": []}
        where = {"item_id": item_id, "output_index": 1, "content_index": 0}
        events.add("response.content_part.added", **where, part=part)
        for piece in _pieces(payload):
            events.add("response.output_text.delta", **where, delta=piece)
        events.add("response.output_text.done", **where, text=payload)
        part = {**part, "text": payload}
        events.add("response.content_part.done", **where, part=part)
        item = {**item, "content": [part], "status": "completed"}
    else:
        name, arguments = payload
        item_id = f"fc_mock_{number}"
        item = {
            "id": item_id,
            "type": "function_call",
            "call_id": f"call_mock_{number}",
            "name": name,
            "arguments": "",
        }
        events.add("response.output_item.added", output_index=1, item=item)
        text = json.dumps(arguments, ensure_ascii=False)
        for piece in _pieces(text):
            events.add(
                "response.function_call_arguments.delta",
                item_id=item_id,
                output_index=1,
                delta=piece,
            )
        events.add(
            "response.function_call_arguments.done",
            item_id=item_id,
            output_index=1,
            name=name,
            arguments=text,
        )
        item = {**item, "arguments": text, "status": "completed"}
    events.add("response.output_item.done", output_index=1, item=item)
    completed = events.response("completed", [reasoning, item])
    completed["usage"] = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
    events.add("response.completed", response=completed)
    return [*events.lines, "data: [DONE]\n\n"]


class Recorder:
    """Keeps every request; answers as a scripted coder or forwards to a real upstream."""

    def __init__(self, upstream: str | None = None, key: str | None = None) -> None:
        self.upstream = upstream.rstrip("/") if upstream else None
        self.key = key
        self.bodies: list[str] = []
        self._lock = threading.Lock()
        self.app = FastAPI()
        self.app.add_api_route("/v1/models", self.models, methods=["GET"])
        self.app.add_api_route("/muse-code/models", self.muse_models, methods=["GET"])
        self.app.add_api_route("/v1/chat/completions", self.chat, methods=["POST"])
        self.app.add_api_route("/v1/responses", self.responses, methods=["POST"])

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        return headers

    def _record(self, raw: bytes) -> int:
        with self._lock:
            self.bodies.append(raw.decode("utf-8", errors="replace"))
            return len(self.bodies)

    async def _get(self, url: str) -> Response:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self._headers())
        return Response(response.content, response.status_code, media_type="application/json")

    async def models(self) -> Response:
        if self.upstream is None:
            return JSONResponse({"object": "list", "data": [{"id": SCRIPTED_MODEL}]})
        return await self._get(self.upstream + "/models")

    async def muse_models(self) -> Response:
        if self.upstream is None:
            model: dict[str, Any] = {
                "id": SCRIPTED_MODEL,
                "object": "model",
                "owned_by": "pii-guard",
                "metadata": {"muse-code": {"name": SCRIPTED_MODEL, "tool_call": True}},
            }
            return JSONResponse({"object": "list", "data": [model]})
        parts = urlsplit(self.upstream)
        return await self._get(f"{parts.scheme}://{parts.netloc}/muse-code/models")

    async def chat(self, request: Request) -> Response:
        raw = await request.body()
        self._record(raw)
        body = json.loads(raw)
        if self.upstream is not None:
            return await self._forward("/chat/completions", raw, bool(body.get("stream")))
        if not body.get("stream"):
            return JSONResponse(self._scripted_completion(body))
        return StreamingResponse(self._scripted(body), media_type="text/event-stream")

    async def responses(self, request: Request) -> Response:
        raw = await request.body()
        number = self._record(raw)
        body = json.loads(raw)
        if self.upstream is not None:
            return await self._forward("/responses", raw, bool(body.get("stream")))
        if not body.get("stream"):  # connect muse-code --check
            seen = list(dict.fromkeys(PLACEHOLDER_RE.findall(_last_input_text(body))))
            text = "Contact: " + ", ".join(f"[[{t}_{i}]]" for t, i in seen)
            events = _ResponseEvents(number)
            part = {"type": "output_text", "text": text, "annotations": []}
            item = {"id": "msg_check", "type": "message", "role": "assistant", "content": [part]}
            return JSONResponse(events.response("completed", [item]))

        async def stream() -> AsyncIterator[str]:
            for line in _response_stream(number, _scripted_turn(body)):
                yield line

        return StreamingResponse(stream(), media_type="text/event-stream")

    def _scripted_completion(self, body: dict[str, Any]) -> dict[str, Any]:
        """A non-streamed answer (``connect --check``): repeats the placeholders it got."""
        messages = body.get("messages") or [{}]
        last = str(messages[-1].get("content") or "")
        seen = list(dict.fromkeys(m.group(0) for m in PLACEHOLDER_RE.finditer(last)))
        return {
            "id": "chatcmpl-mock-coder",
            "object": "chat.completion",
            "created": 1_800_000_000,
            "model": SCRIPTED_MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Contact: " + ", ".join(seen)},
                    "finish_reason": "stop",
                }
            ],
        }

    async def _forward(self, path: str, raw: bytes, stream: bool) -> Response:
        if self.upstream is None:  # pragma: no cover - only called with an upstream
            raise RuntimeError("no upstream to forward to")
        client = httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10))
        request = client.build_request(
            "POST", self.upstream + path, content=raw, headers=self._headers()
        )
        response = await client.send(request, stream=True)
        if not stream or response.status_code >= 400:
            data = await response.aread()
            await response.aclose()
            await client.aclose()
            return Response(data, response.status_code, media_type="application/json")

        async def relay() -> AsyncIterator[bytes]:
            try:
                async for piece in response.aiter_raw():
                    yield piece
            finally:
                await response.aclose()
                await client.aclose()

        return StreamingResponse(relay(), media_type="text/event-stream")

    def _scripted(self, body: dict[str, Any]) -> AsyncIterator[str]:
        tools = _tool_texts(body)
        step = len(tools)

        async def events() -> AsyncIterator[str]:
            yield _chunk({"role": "assistant", "content": ""})
            if step < len(_READS):
                call = ("read", {"path": _READS[step]})
            elif step == len(_READS):
                call = ("write", {"path": "reply.md", "content": _reply(_seen(tools))})
            else:
                call = None
            if call is None:
                for piece in _pieces("Done: wrote reply.md."):
                    yield _chunk({"content": piece})
                yield _chunk({}, finish="stop")
            else:
                name, arguments = call
                yield _chunk(
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": f"call_{step}",
                                "type": "function",
                                "function": {"name": name, "arguments": ""},
                            }
                        ]
                    }
                )
                for piece in _pieces(json.dumps(arguments)):
                    yield _chunk({"tool_calls": [{"index": 0, "function": {"arguments": piece}}]})
                yield _chunk({}, finish="tool_calls")
            yield "data: [DONE]\n\n"

        return events()


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


@dataclass
class RunResult:
    client: str
    client_version: str
    upstream: str
    model: str
    ner: bool
    client_exit: int
    client_output: str
    requests: int
    gateway_statuses: list[int]
    refused: int
    placeholders_upstream: int
    gold_checked: list[str]
    gold_upstream: list[str]
    gaps_upstream: dict[str, int]
    files_written: list[str]
    restored_in_files: list[str]
    placeholders_in_files: int
    placeholders_by_type: dict[str, int] = field(default_factory=dict)
    request_keys: dict[str, list[str]] = field(default_factory=dict)
    seconds: float = 0.0
    #: Multi-word gold values (names) not upstream whole, but with a word of them upstream
    #: (a partly masked name). Reported, not part of :attr:`ok` (the whole-value check).
    gold_partial_upstream: list[str] = field(default_factory=list)
    #: How the client reached a vault session (``--session``) and what the gateway reported.
    session: str = "path"
    sessions: int = 0
    session_sources: dict[str, int] = field(default_factory=dict)
    #: Gold values the upstream saw under more than one placeholder (0: stable across turns),
    #: and the most placeholders one gold value had.
    gold_unstable: int = 0
    gold_max_placeholders: int = 0

    @property
    def ok(self) -> bool:
        return (
            self.client_exit == 0
            and self.refused == 0
            and not self.gold_upstream
            and self.placeholders_upstream > 0
            and self.placeholders_in_files == 0
            # One session from the connect path URL: one placeholder per value. The other
            # modes split a task over several sessions (Muse: one per prompt_cache_key).
            and (self.gold_unstable == 0 or self.session != "path")
        )


def _ner_available() -> bool:
    from pii_guard.gateway.detection import _ner_available as available

    return available()


def _by_type(text: str) -> dict[str, int]:
    """Distinct placeholders per entity type."""
    counts: dict[str, int] = {}
    for kind, _ in set(PLACEHOLDER_RE.findall(text)):
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))


def _request_keys(bodies: list[str]) -> dict[str, list[str]]:
    """The fields the client sent (names only): what the allow-list had to cover."""
    top: set[str] = set()
    message: set[str] = set()
    roles: set[str] = set()
    items: set[str] = set()
    for raw in bodies:
        body = json.loads(raw)
        top |= set(body)
        for m in body.get("messages") or []:
            message |= set(m)
            roles.add(str(m.get("role")))
        inputs = body.get("input")
        for item in inputs if isinstance(inputs, list) else []:
            if isinstance(item, dict):
                kind = str(item.get("type") or "message")
                items.add(kind)
                message |= {f"{kind}.{key}" for key in item}
                if "role" in item:
                    roles.add(str(item["role"]))
    out = {"top_level": sorted(top), "message": sorted(message), "roles": sorted(roles)}
    if items:
        out["input_items"] = sorted(items)
    return out


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


def _written(work: Path, before: set[Path]) -> tuple[list[str], str]:
    after = {p.relative_to(work) for p in work.rglob("*") if p.is_file()}
    new = sorted(after - before)
    texts = "\n".join((work / p).read_text(encoding="utf-8", errors="replace") for p in new)
    return [str(p) for p in new], texts


def _partial(values: list[str], upstream_text: str) -> list[str]:
    """Multi-word values whose words (3+ letters) appear upstream as words, case-sensitive."""

    def found(word: str) -> bool:
        return re.search(rf"(?<![\w.@]){re.escape(word)}(?![\w@])", upstream_text) is not None

    out = []
    for value in values:
        words = [w for w in value.split() if len(w) >= 3 and w.isalpha()]
        if len(words) > 1 and value not in upstream_text and any(found(w) for w in words):
            out.append(value)
    return out


def _result(
    *,
    client: str,
    version: str,
    upstream: str | None,
    model: str | None,
    proc: Any,
    output: str,
    recorder: Recorder,
    statuses: list[int],
    written: list[str],
    texts: str,
    gold: dict[str, Any],
    ner: bool,
    started: float,
    app: FastAPI,
    calls: list[tuple[str, str]],
    session: str,
) -> RunResult:
    checked = list(gold["rules"]) + (list(gold["ner"]) if ner else [])
    gaps = {kind: list(values) for kind, values in gold["known_gaps"].items()}
    upstream_text = "\n".join(
        json.dumps(json.loads(b), ensure_ascii=False) for b in recorder.bodies
    )
    upstream_text += "\n" + "\n".join(recorder.bodies)
    return RunResult(
        client=client,
        client_version=version,
        upstream=upstream or "scripted mock",
        model=model or SCRIPTED_MODEL,
        ner=ner,
        client_exit=proc.returncode,
        client_output=output.strip()[-2000:],
        requests=len(recorder.bodies),
        gateway_statuses=statuses,
        refused=sum(1 for s in statuses if s != 200),
        placeholders_upstream=len(set(PLACEHOLDER_RE.findall(upstream_text))),
        gold_checked=checked,
        gold_upstream=[v for v in checked if v in upstream_text],
        gaps_upstream={k: sum(1 for v in vs if v in upstream_text) for k, vs in gaps.items()},
        files_written=written,
        restored_in_files=[v for v in checked if v in texts],
        placeholders_in_files=len(PLACEHOLDER_RE.findall(texts)),
        placeholders_by_type=_by_type(upstream_text),
        request_keys=_request_keys(recorder.bodies) if recorder.bodies else {},
        seconds=round(time.monotonic() - started, 1),
        gold_partial_upstream=_partial(checked, upstream_text),
        session=session,
        **_stability(app, calls, upstream_text, checked),
    )


def _stability(
    app: FastAPI, calls: list[tuple[str, str]], upstream_text: str, checked: list[str]
) -> dict[str, Any]:
    """Sessions, their sources and per gold value the placeholders the upstream saw.

    Each placeholder is looked up in the sessions the gateway reported (only the session
    that issued it knows it), in this process; only counts leave this function.
    """
    sources: dict[str, int] = {}
    for _, source in calls:
        sources[source or "-"] = sources.get(source or "-", 0) + 1
    session_ids = sorted({sid for sid, _ in calls if sid})
    gateway = getattr(app.state, "gateway", None)
    tokens = sorted({m.group(0) for m in PLACEHOLDER_RE.finditer(upstream_text)})
    by_value: dict[str, set[str]] = {}
    for sid in session_ids if gateway is not None else []:
        try:
            session = gateway.vault.session(sid)
        except SessionNotFoundError:
            continue
        # One unmask per session: the other sessions' tokens stay as they are.
        restored = session.unmask_with_report("\n".join(tokens)).text.split("\n")
        for token, original in zip(tokens, restored, strict=True):
            if original != token:
                by_value.setdefault(normalize_value(original), set()).add(token)
    counts = [len(by_value.get(normalize_value(v), ())) for v in checked]
    return {
        "sessions": len(session_ids),
        "session_sources": dict(sorted(sources.items())),
        "gold_unstable": sum(1 for n in counts if n > 1),
        "gold_max_placeholders": max(counts, default=0),
    }


def _connect(args: list[str]) -> None:
    from pii_guard.integrations.cli import main as connect

    with open(os.devnull, "w") as quiet:
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
    parser.add_argument("--client", choices=("pi", "muse-code"), default="pi")
    parser.add_argument("--upstream", default=None, help="a real OpenAI-compatible base URL")
    parser.add_argument("--model", default=None, help="model id (required with --upstream)")
    parser.add_argument("--key-env", default=None, help="env var (or .env key) with its API key")
    parser.add_argument("--pi-prefix", default=None, help="npm prefix for pi (default: temp)")
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
    if args.client == "muse-code":
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
