"""End-to-end run: a real pi (pinned) works on the fictional mini-repo through the gateway.

```
uv run python -m pii_guard.integrations.e2e                 # scripted mock upstream (CI)
uv run python -m pii_guard.integrations.e2e --upstream https://api.meta.ai/v1 \\
    --model muse-spark-1.3 --key-env META_API_KEY --record examples/coding-agents/runs/<name>.json
```

What runs, all on loopback, in throwaway directories (``HOME`` and pi's agent dir too):

1. pi ``PI_VERSION`` is installed with npm into a temp prefix (or ``--pi-prefix``; reused).
2. A **recorder** stands in for the upstream: it keeps every request body it gets, then either
   answers like a scripted coding model (read the letter, read the CSV, read ``.env``, write
   ``reply.md`` with the placeholders it saw, finish) or forwards to a real OpenAI-compatible
   upstream (``--upstream``) with the key from ``--key-env``. The gateway never holds that key.
3. The gateway (``create_app``) forwards to the recorder; ``pii-guard connect pi`` writes pi's
   ``models.json`` from the gateway's ``GET /v1/models``.
4. pi runs headless (``--print``) on a copy of ``examples/coding-agents/mini-repo``.

The result (:class:`RunResult`) says whether any gold value (``examples/coding-agents/gold.json``)
reached the upstream, whether the gateway refused a request, and what pi wrote: the files hold
the real values again, because tool-call arguments come back restored. Values pii-guard does not
cover yet (API keys, names inside CSV rows) are counted separately as known gaps.
"""

from __future__ import annotations

import argparse
import json
import os
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

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from pii_guard.vault.placeholders import PLACEHOLDER_RE

__all__ = [
    "EXAMPLE_DIR",
    "PI_PACKAGE",
    "PI_VERSION",
    "PROMPT",
    "Recorder",
    "RunResult",
    "install_pi",
    "load_gold",
    "main",
    "run",
]

PI_PACKAGE = "@earendil-works/pi-coding-agent"
PI_VERSION = "1.4.0"
EXAMPLE_DIR = Path(__file__).resolve().parents[3] / "examples" / "coding-agents"
SCRIPTED_MODEL = "pii-guard-mock-coder"
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


# --- pi ----------------------------------------------------------------------------------


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


class Recorder:
    """Keeps every request; answers as a scripted coder or forwards to a real upstream."""

    def __init__(self, upstream: str | None = None, key: str | None = None) -> None:
        self.upstream = upstream.rstrip("/") if upstream else None
        self.key = key
        self.bodies: list[str] = []
        self._lock = threading.Lock()
        self.app = FastAPI()
        self.app.add_api_route("/v1/models", self.models, methods=["GET"])
        self.app.add_api_route("/v1/chat/completions", self.chat, methods=["POST"])

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        return headers

    async def models(self) -> Response:
        if self.upstream is None:
            return JSONResponse({"object": "list", "data": [{"id": SCRIPTED_MODEL}]})
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(self.upstream + "/models", headers=self._headers())
        return Response(response.content, response.status_code, media_type="application/json")

    async def chat(self, request: Request) -> Response:
        raw = await request.body()
        with self._lock:
            self.bodies.append(raw.decode("utf-8", errors="replace"))
        body = json.loads(raw)
        if self.upstream is not None:
            return await self._forward(raw, bool(body.get("stream")))
        if not body.get("stream"):
            return JSONResponse(self._scripted_completion(body))
        return StreamingResponse(self._scripted(body), media_type="text/event-stream")

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

    async def _forward(self, raw: bytes, stream: bool) -> Response:
        client = httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10))
        request = client.build_request(
            "POST", self.upstream + "/chat/completions", content=raw, headers=self._headers()
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
        reads = ("client-letter.md", "customers.csv", ".env")

        async def events() -> AsyncIterator[str]:
            yield _chunk({"role": "assistant", "content": ""})
            if step < len(reads):
                call = ("read", {"path": reads[step]})
            elif step == len(reads):
                seen = list(
                    dict.fromkeys(m.group(0) for m in PLACEHOLDER_RE.finditer("\n".join(tools)))
                )
                content = "Reply to the client\n\n" + "\n".join(f"- {p}" for p in seen) + "\n"
                call = ("write", {"path": "reply.md", "content": content})
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
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
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


def gateway_app(upstream_url: str, statuses: list[int]) -> FastAPI:
    from pii_guard.api.app import create_app
    from pii_guard.config import Settings

    settings = Settings(
        tenant_key=secrets.token_hex(32),
        upstream_base_url=upstream_url,
        upstream_api_key="recorder-holds-the-real-key",
    )
    app = create_app(settings)

    @app.middleware("http")
    async def count(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        if request.url.path == "/v1/chat/completions":
            statuses.append(response.status_code)
        return response

    return app


# --- the run -----------------------------------------------------------------------------


@dataclass
class RunResult:
    pi_version: str
    upstream: str
    model: str
    ner: bool
    pi_exit: int
    pi_output: str
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

    @property
    def ok(self) -> bool:
        return (
            self.pi_exit == 0
            and self.refused == 0
            and not self.gold_upstream
            and self.placeholders_upstream > 0
            and self.placeholders_in_files == 0
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
    top: set[str] = set()
    message: set[str] = set()
    roles: set[str] = set()
    for raw in bodies:
        body = json.loads(raw)
        top |= set(body)
        for m in body.get("messages") or []:
            message |= set(m)
            roles.add(str(m.get("role")))
    return {"top_level": sorted(top), "message": sorted(message), "roles": sorted(roles)}


def run(
    *,
    pi_bin: Path,
    upstream: str | None = None,
    key: str | None = None,
    model: str | None = None,
    example_dir: Path = EXAMPLE_DIR,
    prompt: str = PROMPT,
    timeout: float = 900,
) -> RunResult:
    gold = load_gold(example_dir)
    ner = _ner_available()
    checked = list(gold["rules"]) + (list(gold["ner"]) if ner else [])
    gaps = {kind: list(values) for kind, values in gold["known_gaps"].items()}
    started = time.monotonic()
    recorder = Recorder(upstream, key)
    statuses: list[int] = []
    with tempfile.TemporaryDirectory(prefix="pii-guard-pi-e2e-") as tmp:
        root = Path(tmp)
        work = root / "work"
        shutil.copytree(example_dir / "mini-repo", work)
        # Kept as env.fake in the repo (a tracked .env would be ignored by git, or loaded by
        # tools that read .env); the agent sees it under its usual name.
        (work / "env.fake").rename(work / ".env")
        before = {p.relative_to(work) for p in work.rglob("*") if p.is_file()}
        agent_dir = root / "agent"
        with (
            serve(recorder.app) as recorder_url,
            serve(gateway_app(recorder_url + "/v1", statuses)) as gateway_url,
        ):
            from pii_guard.integrations.cli import main as connect

            args = ["pi", "--gateway", gateway_url + "/v1", "--agent-dir", str(agent_dir)]
            if model:
                args += ["--model", model]
            with open(os.devnull, "w") as quiet:
                if connect(args, stdout=quiet) != 0:
                    raise RuntimeError("pii-guard connect pi failed")
            chosen = model or SCRIPTED_MODEL
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(root / "home"),
                "PI_CODING_AGENT_DIR": str(agent_dir),
                "PI_OFFLINE": "1",
                "PI_SKIP_VERSION_CHECK": "1",
                "PI_TELEMETRY": "0",
            }
            try:
                proc = subprocess.run(  # noqa: S603 - the pinned pi this harness installed
                    [
                        str(pi_bin),
                        "--print",
                        "--no-session",
                        "--provider",
                        "pii-guard",
                        "--model",
                        chosen,
                        prompt,
                    ],
                    cwd=work,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                out = exc.stdout or b""
                out = out.decode(errors="replace") if isinstance(out, bytes) else out
                proc = subprocess.CompletedProcess(exc.cmd, -1, out, "timed out")
        after = {p.relative_to(work) for p in work.rglob("*") if p.is_file()}
        written = sorted(str(p) for p in after - before)
        texts = "\n".join(
            (work / p).read_text(encoding="utf-8", errors="replace") for p in sorted(after - before)
        )

    upstream_text = "\n".join(
        json.dumps(json.loads(b), ensure_ascii=False) for b in recorder.bodies
    )
    upstream_text += "\n" + "\n".join(recorder.bodies)
    return RunResult(
        pi_version=PI_VERSION,
        upstream=upstream or "scripted mock",
        model=model or SCRIPTED_MODEL,
        ner=ner,
        pi_exit=proc.returncode,
        pi_output=(proc.stdout + proc.stderr).strip()[-2000:],
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
    )


def record(result: RunResult, path: Path) -> None:
    """A run record for ``examples/coding-agents/runs/``: counts, never the values.

    Not ``eval/results/runs/``: every record there follows the eval record schema.
    """
    data = asdict(result)
    data.pop("pi_output")
    gold_upstream = data.pop("gold_upstream")
    restored = data.pop("restored_in_files")
    checked = data.pop("gold_checked")
    data.update(
        {
            "kind": "coding-agent-e2e",
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "client": "pi",
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
    parser.add_argument("--upstream", default=None, help="a real OpenAI-compatible base URL")
    parser.add_argument("--model", default=None, help="model id (required with --upstream)")
    parser.add_argument("--key-env", default=None, help="env var (or .env key) with its API key")
    parser.add_argument("--pi-prefix", default=None, help="npm prefix for pi (default: temp)")
    parser.add_argument("--record", default=None, help="write a run record JSON here")
    parser.add_argument("--timeout", type=float, default=900, help="pi's time limit (s)")
    args = parser.parse_args(argv)
    if args.upstream and not args.model:
        parser.error("--upstream needs --model")
    key = None
    if args.key_env:
        key = os.environ.get(args.key_env) or _dotenv(args.key_env)
        if not key:
            parser.error(f"{args.key_env} is not set")
    prefix = (
        Path(args.pi_prefix) if args.pi_prefix else Path(tempfile.gettempdir()) / "pii-guard-pi"
    )
    pi_bin = install_pi(prefix)
    result = run(
        pi_bin=pi_bin, upstream=args.upstream, key=key, model=args.model, timeout=args.timeout
    )
    summary = asdict(result)
    summary["gold_upstream"] = len(result.gold_upstream)  # counts only: never print values
    summary["restored_in_files"] = len(result.restored_in_files)
    summary["gold_checked"] = len(result.gold_checked)
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
