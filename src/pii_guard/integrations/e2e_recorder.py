"""Scripted coding-agent upstream stand-in and request recorder for E2E runs."""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from pii_guard.vault import PLACEHOLDER_RE, SessionNotFoundError, normalize_value

__all__ = [
    "SCRIPTED_MODEL",
    "_READS",
    "Recorder",
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
]

SCRIPTED_MODEL = "pii-guard-mock-coder"
_READS = ("client-letter.md", "customers.csv", ".env")


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
    if "exec_command" in names:  # Codex: one shell tool
        return _codex_turn(names["exec_command"][0], _call_outputs(body))
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


def _codex_turn(name: str, outputs: list[str]) -> tuple[str, Any]:
    """Codex's turns: read the three files with one ``cat``, write ``reply.md`` with a quoted
    heredoc (the placeholders it saw: the gateway restores them in the arguments), finish."""
    if not outputs:
        return "call", (name, {"cmd": "cat " + " ".join(_READS)})
    if len(outputs) == 1:
        reply = _reply(_seen(outputs))
        return "call", (name, {"cmd": f"cat > reply.md <<'PII_GUARD_EOF'\n{reply}PII_GUARD_EOF"})
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
        #: The client's workspace, for tools that want absolute paths (OpenCode).
        self.workdir: Path | None = None
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

    def _path_arg(self, body: dict[str, Any], tool: str, name: str) -> dict[str, str]:
        """``{"path": name}`` (pi) or ``{"filePath": <absolute>}`` (OpenCode's ``read`` and
        ``write`` take an absolute ``filePath``), from the tool's own schema."""
        for entry in body.get("tools") or []:
            function = entry.get("function") if isinstance(entry, dict) else None
            if not isinstance(function, dict) or function.get("name") != tool:
                continue
            properties = (function.get("parameters") or {}).get("properties") or {}
            if "filePath" in properties:
                base = self.workdir or Path.cwd()
                return {"filePath": str(base / name)}
        return {"path": name}

    def _scripted(self, body: dict[str, Any]) -> AsyncIterator[str]:
        tools = _tool_texts(body)
        step = len(tools)
        has_tools = bool(body.get("tools"))

        async def events() -> AsyncIterator[str]:
            yield _chunk({"role": "assistant", "content": ""})
            if not has_tools:  # a side call without tools (OpenCode's session title)
                call = None
            elif step < len(_READS):
                call = ("read", self._path_arg(body, "read", _READS[step]))
            elif step == len(_READS):
                content = {"content": _reply(_seen(tools))}
                call = ("write", {**self._path_arg(body, "write", "reply.md"), **content})
            else:
                call = None
            if call is None:
                for piece in _pieces("Done: wrote reply.md." if has_tools else "Client reply"):
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
    gateway: Any = getattr(app.state, "gateway", None)
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
