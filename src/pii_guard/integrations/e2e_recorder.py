"""Scripted coding-agent upstream stand-in and request recorder for E2E runs."""

from __future__ import annotations

import json
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from pii_guard.vault.placeholders import PLACEHOLDER_RE

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
