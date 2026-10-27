"""A tiny OpenAI-compatible upstream for the demo, the smoke test and the latency benchmark.

It answers ``POST /v1/chat/completions`` without any model: the reply echoes the last user
message (``Echo: <text>``), so after the gateway restores it the client must get back exactly
what it sent; with ``tools`` in the request it calls the first tool with
``{"text": <last user message>}`` instead. Streams are cut into small chunks, so placeholders
are split across chunks. A fixed ``delay_ms`` before the answer (before the first chunk when
streaming) stands in for model latency, so the benchmark isolates pii-guard's own overhead.

It keeps the last requests it received in memory (``GET /_mock/received``, ``DELETE`` to
reset): the smoke test asserts that no fictional gold value ever reached it. It never calls
anything; run it with ``pii-guard bench mock-upstream`` (binds 127.0.0.1:8790).
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

__all__ = ["DEFAULT_PORT", "MockUpstream", "create_mock_upstream", "last_user_text"]

DEFAULT_PORT = 8790
MODEL = "pii-guard-mock"


def last_user_text(body: dict[str, Any]) -> str:
    """The text of the last ``user`` message (text parts joined by newlines)."""
    for message in reversed(body.get("messages") or []):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
    return ""


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


class MockUpstream:
    """State of one mock upstream: settings and the requests it received."""

    def __init__(self, *, delay_ms: float = 0.0, chunk_chars: int = 7, keep: int = 1000) -> None:
        self.delay_ms = delay_ms
        self.chunk_chars = max(1, chunk_chars)
        self.received: deque[str] = deque(maxlen=keep)
        self.count = 0
        self._lock = threading.Lock()

    def record(self, raw: bytes) -> None:
        with self._lock:
            self.received.append(raw.decode("utf-8", errors="replace"))
            self.count += 1

    def reply(self, body: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]] | None]:
        """``(content, tool_calls)`` for a request."""
        text = last_user_text(body)
        tools = body.get("tools")
        if isinstance(tools, list) and tools and body.get("tool_choice") != "none":
            function = tools[0].get("function", {}) if isinstance(tools[0], dict) else {}
            call = {
                "id": "call_mock_1",
                "type": "function",
                "function": {
                    "name": str(function.get("name") or "tool"),
                    "arguments": json.dumps({"text": text}, ensure_ascii=False),
                },
            }
            return None, [call]
        return f"Echo: {text}", None


def create_mock_upstream(
    *, delay_ms: float = 0.0, chunk_chars: int = 7, state: MockUpstream | None = None
) -> FastAPI:
    """The mock upstream app; its :class:`MockUpstream` is ``app.state.mock``."""
    mock = state or MockUpstream(delay_ms=delay_ms, chunk_chars=chunk_chars)
    app = FastAPI(title="pii-guard mock upstream", docs_url=None, redoc_url=None)
    app.state.mock = mock

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "model": MODEL, "delay_ms": mock.delay_ms}

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        return {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "mock"}]}

    @app.get("/_mock/received")
    def received(limit: int = 100) -> dict[str, Any]:
        with mock._lock:
            items = list(mock.received)[-limit:] if limit > 0 else []
            count = mock.count
        return {"count": count, "requests": items}

    @app.delete("/_mock/received")
    def reset() -> dict[str, Any]:
        with mock._lock:
            mock.received.clear()
            mock.count = 0
        return {"count": 0}

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Any:
        raw = await request.body()
        mock.record(raw)
        try:
            body = json.loads(raw)
        except ValueError:
            return JSONResponse({"error": {"type": "invalid_request", "code": "bad_json"}}, 400)
        if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
            return JSONResponse({"error": {"type": "invalid_request", "code": "no_messages"}}, 400)
        content, tool_calls = mock.reply(body)
        model = str(body.get("model") or MODEL)
        prompt_tokens = _tokens(json.dumps(body["messages"], ensure_ascii=False))
        completion_tokens = _tokens(content or json.dumps(tool_calls, ensure_ascii=False))
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        created = int(time.time())
        if body.get("stream"):
            include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
            return StreamingResponse(
                _stream(
                    mock, model, created, content, tool_calls, usage if include_usage else None
                ),
                media_type="text/event-stream",
            )
        if mock.delay_ms:
            await asyncio.sleep(mock.delay_ms / 1000)
        message: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "tool_calls" if tool_calls else "stop",
                }
            ],
            "usage": usage,
        }

    return app


async def _stream(
    mock: MockUpstream,
    model: str,
    created: int,
    content: str | None,
    tool_calls: list[dict[str, Any]] | None,
    usage: dict[str, int] | None,
) -> AsyncIterator[bytes]:
    def event(delta: dict[str, Any], finish: str | None = None) -> bytes:
        chunk = {
            "id": "chatcmpl-mock",
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode()

    if mock.delay_ms:
        await asyncio.sleep(mock.delay_ms / 1000)
    n = mock.chunk_chars
    yield event({"role": "assistant", "content": "" if content is not None else None})
    if content is not None:
        for i in range(0, len(content), n):
            yield event({"content": content[i : i + n]})
    for call in tool_calls or []:
        args = call["function"]["arguments"]
        head = {"index": 0, "id": call["id"], "type": "function"}
        yield event({"tool_calls": [{**head, "function": {"name": call["function"]["name"]}}]})
        for i in range(0, len(args), n):
            yield event({"tool_calls": [{"index": 0, "function": {"arguments": args[i : i + n]}}]})
    yield event({}, finish="tool_calls" if tool_calls else "stop")
    if usage is not None:
        chunk = {
            "id": "chatcmpl-mock",
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [],
            "usage": usage,
        }
        yield f"data: {json.dumps(chunk)}\n\n".encode()
    yield b"data: [DONE]\n\n"
