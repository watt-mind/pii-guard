"""``POST /v1/messages``: mask an Anthropic Messages API request, forward it natively, restore
the answer and the event stream (LAB-1605). Fictional values only (ADR 0005).

The request bodies have the shape Claude Code 2.1.312 sends (captured against a scratch
recording upstream): ``system`` text blocks with ``cache_control``, user text blocks,
``thinking``, ``context_management``, ``metadata.user_id`` and client tools with
``input_schema`` (one with ``defer_loading``), plus a tool-use turn.
"""

from __future__ import annotations

import base64
import io
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway_helpers import (
    NAMES,
    PHONES,
    TEST_TENANT_KEY,
    UPSTREAM_KEY,
    UPSTREAM_URL,
    FakeLlm,
    leaked_values,
    make_app,
)
from PIL import Image
from test_image_parts import FACE, TAJ_BOX, TAJ_VALUE, FakeOcr, Sam, filled, png

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway import Gateway, GatewayConfig, Mode, build_mode_detectors
from pii_guard.gateway.messages import messages_url
from pii_guard.gateway.messages_request import collect_message_texts
from pii_guard.gateway.messages_restore import MessagesSseRestorer
from pii_guard.gateway.placeholder_note import PLACEHOLDER_NOTE
from pii_guard.gateway.sessions import client_identity
from pii_guard.gateway.tool_names import model_words
from pii_guard.vault import PLACEHOLDER_RE, Vault
from pii_guard.visual import SamClient

SIGNATURE = "EqQBCkYIBxgCKkB-opaque-signature-0000"
CLIENT_KEY = "0" * 32


def claude_code_body(**extra: Any) -> dict[str, Any]:
    return {
        "model": "claude-test-model",
        "max_tokens": 32000,
        "stream": False,
        "system": [
            {"type": "text", "text": "You are Claude Code."},
            {
                "type": "text",
                "text": "The repo owner is Teszt Elek (teszt.elek@example.com).",
                "cache_control": {"type": "ephemeral"},
            },
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "<system-reminder>Support: +36 30 123 4567"},
                    {
                        "type": "text",
                        "text": "Write to Jane Placeholder at jane.placeholder@example.net.",
                        "cache_control": {"type": "ephemeral"},
                    },
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "Mail Minta Mária too.",
                        "signature": SIGNATURE,
                    },
                    {"type": "text", "text": "Reading the file."},
                    {
                        "type": "tool_use",
                        "id": "toolu_01",
                        "name": "Bash",
                        "input": {"command": "grep -n 'Minta Mária' notes.md"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_01",
                        "content": "3: Minta Mária, minta.maria@example.org",
                    },
                    {"type": "text", "text": "Go on."},
                ],
            },
        ],
        "tools": [
            {
                "name": "Bash",
                "description": "Run a shell command.",
                "input_schema": {
                    "type": "object",
                    "properties": {"command": {"type": "string", "description": "The command"}},
                    "required": ["command"],
                },
            },
            {
                "name": "DeferredToolPlaceholder",
                "description": "Deferred.",
                "input_schema": {"type": "object", "properties": {}},
                "defer_loading": True,
            },
        ],
        "thinking": {"type": "enabled", "budget_tokens": 31999, "display": "omitted"},
        "context_management": {"edits": [{"type": "clear_thinking_20251015", "keep": "all"}]},
        "metadata": {"user_id": '{"session_id":"00000000-0000-0000-0000-000000000000"}'},
        **extra,
    }


def placeholders_in(body: dict[str, Any]) -> list[str]:
    text = json.dumps(body, ensure_ascii=False)
    return list(dict.fromkeys(f"[[{t}_{i}]]" for t, i in PLACEHOLDER_RE.findall(text)))


@dataclass
class MessagesUpstream:
    """An Anthropic-compatible upstream: echoes every placeholder it received as the answer
    (streamed in ``chunk``-sized deltas); a ``tool_use`` answer when ``tool`` is set."""

    chunk: int = 5
    status: int = 200
    error_body: dict[str, Any] | None = None
    tool: bool = False
    events: Callable[[str], list[dict[str, Any]]] | None = None
    requests: list[httpx.Request] = field(default_factory=list)

    @property
    def raw_bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]

    def answer(self, body: dict[str, Any]) -> str:
        own = {k: v for k, v in body.items() if k != "system"}
        return "Done: " + ", ".join(placeholders_in(own)) + "."

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status >= 400:
            return httpx.Response(self.status, json=self.error_body or {"type": "error"})
        body = json.loads(request.content)
        if request.url.path.endswith("/count_tokens"):
            return httpx.Response(200, json={"input_tokens": 123, "extra": "dropped"})
        text = self.answer(body)
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        if self.tool:
            content.append(
                {
                    "type": "tool_use",
                    "id": "toolu_02",
                    "name": "Bash",
                    "input": {"command": f"echo {placeholders_in(body)[0]}", "n": 1},
                }
            )
        message = {
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "model": body["model"],
            "content": content,
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        if not body.get("stream"):
            return httpx.Response(200, json=message)
        events = self.events(text) if self.events else self.stream(text, message)
        raw = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
        return httpx.Response(
            200, content=raw.encode(), headers={"content-type": "text/event-stream"}
        )

    def stream(self, text: str, message: dict[str, Any]) -> list[dict[str, Any]]:
        start = {**message, "content": [], "stop_reason": None}
        out: list[dict[str, Any]] = [
            {"type": "message_start", "message": start},
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ]
        for i in range(0, len(text), self.chunk):
            out.append(
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": text[i : i + self.chunk]},
                }
            )
        out.append({"type": "content_block_stop", "index": 0})
        if self.tool:
            args = json.dumps(message["content"][1]["input"])
            out.append(
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_02",
                        "name": "Bash",
                        "input": {},
                    },
                }
            )
            for i in range(0, len(args), self.chunk):
                piece = args[i : i + self.chunk]
                out.append(
                    {
                        "type": "content_block_delta",
                        "index": 1,
                        "delta": {"type": "input_json_delta", "partial_json": piece},
                    }
                )
            out.append({"type": "content_block_stop", "index": 1})
        out += [
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 12},
            },
            {"type": "message_stop"},
        ]
        return out

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def post(
    upstream: MessagesUpstream,
    body: dict[str, Any],
    *,
    path: str = "/v1/messages",
    headers: dict[str, str] | None = None,
    **settings: Any,
) -> httpx.Response:
    app = make_app(upstream, llm=FakeLlm(), **settings)  # type: ignore[arg-type]
    with TestClient(app) as http:
        return http.post(path, json=body, headers=headers or {})


def sse_events(text: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def test_claude_code_request_is_masked_everywhere_and_the_answer_restored() -> None:
    upstream = MessagesUpstream()
    r = post(upstream, claude_code_body())
    assert r.status_code == 200, r.text
    (request,) = upstream.requests
    assert request.url == "https://upstream.test/v1/messages"
    assert leaked_values(request.content) == []
    sent = json.loads(request.content)
    # The note goes in front of the system blocks; the client's cache marks stay.
    assert sent["system"][0] == {"type": "text", "text": PLACEHOLDER_NOTE}
    assert sent["system"][2]["cache_control"] == {"type": "ephemeral"}
    assistant = sent["messages"][1]["content"]
    assert assistant[0]["signature"] == SIGNATURE  # opaque, untouched
    assert "[[PERSON_" in assistant[0]["thinking"]
    assert "[[PERSON_" in assistant[2]["input"]["command"]
    assert sent["messages"][2]["content"][0]["tool_use_id"] == "toolu_01"
    assert sent["tools"][1]["defer_loading"] is True
    assert sent["thinking"]["budget_tokens"] == 31999
    answer = r.json()
    text = answer["content"][0]["text"]
    for value in ("Jane Placeholder", "jane.placeholder@example.net", "Minta Mária"):
        assert value in text
    assert not PLACEHOLDER_RE.search(text)
    assert r.headers["X-PII-Guard-Unresolved"] == "0"
    assert r.headers["X-PII-Guard-Request-Id"]


def test_upstream_auth_is_anthropic_style() -> None:
    upstream = MessagesUpstream()
    post(
        upstream,
        claude_code_body(),
        headers={
            "x-api-key": CLIENT_KEY,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "claude-code-20250219, bad value!,interleaved-thinking-2025-05-14",
        },
    )
    headers = upstream.requests[0].headers
    # The configured key wins, as x-api-key; the client's key never goes upstream.
    assert headers["x-api-key"] == UPSTREAM_KEY
    assert "authorization" not in headers
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["anthropic-beta"] == "claude-code-20250219,interleaved-thinking-2025-05-14"


def test_without_a_configured_key_the_clients_key_is_passed_through() -> None:
    upstream = MessagesUpstream()
    settings = Settings(tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL)
    post(upstream, claude_code_body(), headers={"x-api-key": CLIENT_KEY}, settings=settings)
    headers = upstream.requests[0].headers
    assert headers["x-api-key"] == CLIENT_KEY
    assert headers["anthropic-version"] == "2023-06-01"


@pytest.mark.parametrize("tool", [False, True])
def test_stream_is_restored_across_split_placeholders(tool: bool) -> None:
    upstream = MessagesUpstream(chunk=3, tool=tool)
    r = post(upstream, claude_code_body(stream=True))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    events = sse_events(r.text)
    text = "".join(
        e["delta"]["text"]
        for e in events
        if e["type"] == "content_block_delta" and e["delta"]["type"] == "text_delta"
    )
    for value in ("Jane Placeholder", "jane.placeholder@example.net", "Minta Mária"):
        assert value in text
    assert not PLACEHOLDER_RE.search(r.text)
    # Each block's deltas end before its stop event.
    stops = [i for i, e in enumerate(events) if e["type"] == "content_block_stop"]
    last_text = max(
        i
        for i, e in enumerate(events)
        if e.get("index") == 0 and e["type"] == "content_block_delta"
    )
    assert last_text < stops[0]
    assert events[-1]["type"] == "message_stop"
    if tool:
        args = "".join(
            e["delta"]["partial_json"]
            for e in events
            if e["type"] == "content_block_delta" and e["delta"]["type"] == "input_json_delta"
        )
        command = json.loads(args)["command"]
        assert command.startswith("echo ")
        assert not PLACEHOLDER_RE.search(command)
        assert json.loads(args)["n"] == 1


def test_whole_tool_use_input_is_restored_as_json() -> None:
    upstream = MessagesUpstream(tool=True)
    r = post(upstream, claude_code_body())
    tool_use = r.json()["content"][1]
    assert tool_use["type"] == "tool_use"
    assert not PLACEHOLDER_RE.search(tool_use["input"]["command"])
    assert tool_use["input"]["n"] == 1


def test_upstream_error_events_are_replaced() -> None:
    def events(_: str) -> list[dict[str, Any]]:
        return [
            {
                "type": "error",
                "error": {"type": "overloaded_error", "message": "quote: [[PERSON_000000]]"},
            }
        ]

    upstream = MessagesUpstream(events=events)
    r = post(upstream, claude_code_body(stream=True))
    (event,) = sse_events(r.text)
    assert event == {
        "type": "error",
        "error": {"type": "api_error", "message": "upstream stream error"},
    }


def test_upstream_without_messages_api_is_unsupported_api() -> None:
    upstream = MessagesUpstream(status=404)
    r = post(upstream, claude_code_body())
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unsupported_api"
    assert r.headers["x-should-retry"] == "false"
    assert "Jane" not in r.text


def test_upstream_error_keeps_only_its_type() -> None:
    body = {"type": "error", "error": {"type": "overloaded_error", "message": "Jane Placeholder"}}
    upstream = MessagesUpstream(status=529, error_body=body)
    r = post(upstream, claude_code_body())
    assert r.status_code == 529
    assert r.json()["error"]["type"] == "overloaded_error"
    assert "Jane" not in r.text


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"mcp_servers": [{"type": "url", "url": "https://mcp.test"}]}, "mcp_servers"),
        ({"tools": [{"type": "web_search_20250305", "name": "web_search"}]}, "server tools"),
        ({"surprise": 1}, "surprise"),
        (
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "document", "source": {"type": "text", "data": "x"}}],
                    }
                ]
            },
            "document",
        ),
        (
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "url", "url": "https://x.test"}}
                        ],
                    }
                ]
            },
            "never fetched",
        ),
        (
            {"messages": [{"role": "user", "content": [{"type": "text", "text": "a", "x": 1}]}]},
            "messages.0.content.0.x",
        ),
    ],
)
def test_unsupported_fields_fail_closed(change: dict[str, Any], fragment: str) -> None:
    upstream = MessagesUpstream()
    r = post(upstream, claude_code_body(**change))
    assert r.status_code == 400, r.text
    assert fragment in r.json()["error"]["message"]
    assert upstream.requests == []


def test_personal_data_in_a_tool_name_is_refused() -> None:
    body = claude_code_body()
    body["tools"][0]["name"] = "teszt.elek@example.com"
    upstream = MessagesUpstream()
    r = post(upstream, body)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unsupported_content"
    assert upstream.requests == []


def test_count_tokens_is_masked_and_answers_input_tokens_only() -> None:
    upstream = MessagesUpstream()
    body = claude_code_body()
    del body["max_tokens"], body["stream"]
    r = post(upstream, body, path="/v1/messages/count_tokens")
    assert r.status_code == 200, r.text
    assert r.json() == {"input_tokens": 123}
    (request,) = upstream.requests
    assert request.url == "https://upstream.test/v1/messages/count_tokens"
    assert leaked_values(request.content) == []


def test_session_header_keeps_placeholders_across_turns() -> None:
    upstream = MessagesUpstream()
    app = make_app(upstream, llm=FakeLlm())  # type: ignore[arg-type]
    simple = {
        "model": "claude-test-model",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "Mail Jane Placeholder."}],
    }
    with TestClient(app) as http:
        first = http.post("/v1/messages", json=simple)
        session = first.headers["X-PII-Guard-Session"]
        http.post("/v1/messages", json=simple, headers={"X-PII-Guard-Session": session})
    one, two = (placeholders_in(b) for b in upstream.raw_bodies)
    assert one == two and one


def test_echo_shows_the_masked_boundary_and_refuses_streams() -> None:
    upstream = MessagesUpstream()
    r = post(upstream, claude_code_body(), headers={"X-PII-Guard-Echo": "masked"})
    echo = r.json()["pii_guard"]
    assert echo["masked_input"][0]["role"] == "system"
    assert "Jane" not in json.dumps(echo)
    assert "[[PERSON_" in echo["masked_output"]
    r = post(upstream, claude_code_body(stream=True), headers={"X-PII-Guard-Echo": "masked"})
    assert r.status_code == 400


def test_string_system_and_content() -> None:
    upstream = MessagesUpstream()
    body = {
        "model": "claude-test-model",
        "max_tokens": 64,
        "system": "Owner: Teszt Elek.",
        "stop_sequences": ["Minta Mária"],
        "messages": [{"role": "user", "content": "Call +44 20 7946 0958."}],
    }
    r = post(upstream, body)
    assert r.status_code == 200, r.text
    sent = upstream.raw_bodies[0]
    assert sent["system"].startswith(PLACEHOLDER_NOTE)
    assert leaked_values(upstream.requests[0].content) == []
    assert PHONES[1] in r.json()["content"][0]["text"]


def test_x_api_key_gives_each_key_its_own_identity() -> None:
    anonymous = client_identity({})
    one = client_identity({"x-api-key": "0" * 32})
    two = client_identity({"x-api-key": "1" * 32})
    assert len({anonymous, one, two}) == 3
    # Authorization still wins when both are sent.
    both = {"authorization": "Bearer " + "0" * 32, "x-api-key": "1" * 32}
    assert client_identity(both) == client_identity({"authorization": "Bearer " + "0" * 32})


def test_messages_url() -> None:
    assert messages_url("https://api.anthropic.com/v1") == "https://api.anthropic.com/v1/messages"
    assert messages_url("https://x.test/v1/chat/completions/") == "https://x.test/v1/messages"
    assert (
        messages_url("https://x.test/v1", "/messages/count_tokens")
        == "https://x.test/v1/messages/count_tokens"
    )


def test_sse_restorer_flushes_a_held_back_placeholder_at_stream_end() -> None:
    vault = Vault.from_settings(Settings(tenant_key=TEST_TENANT_KEY))
    session, _ = vault.session_or_create("test-session")
    restorer = MessagesSseRestorer(session)
    delta = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta"}}
    delta["delta"]["text"] = "Hi [[PER"
    ((name, data),) = restorer.process(None, json.dumps(delta))
    assert name == "content_block_delta"
    assert json.loads(data)["delta"]["text"] == "Hi "
    ((_, rest),) = restorer.finish()
    assert json.loads(rest)["delta"] == {"type": "text_delta", "text": "[[PER"}
    assert restorer.finish() == []


def test_sse_restorer_passes_signatures_and_unknown_events() -> None:
    vault = Vault.from_settings(Settings(tenant_key=TEST_TENANT_KEY))
    restorer = MessagesSseRestorer(vault.session_or_create("test-session")[0])
    signature = {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "signature_delta", "signature": SIGNATURE},
    }
    ((_, data),) = restorer.process(None, json.dumps(signature))
    assert json.loads(data) == signature
    assert restorer.process("ping", "not json") == [("ping", "not json")]


def image_app(upstream: MessagesUpstream, sam: Sam) -> FastAPI:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
        image_render="opaque",
    )
    config = GatewayConfig(mode=Mode.AUDIT)
    app = create_app(settings)
    app.state.gateway = Gateway(
        settings=settings,
        vault=Vault.from_settings(settings),
        config=config,
        detectors=build_mode_detectors(settings, config, llm_detector=FakeLlm()),
        transport=upstream.transport(),
        sam=SamClient(api_key="test-key", transport=httpx.MockTransport(sam), max_retries=0),
        ocr=FakeOcr(),  # type: ignore[arg-type]
    )
    return app


def image_block(data: bytes, media: str = "image/png") -> dict[str, Any]:
    source = {"type": "base64", "media_type": media, "data": base64.b64encode(data).decode()}
    return {"type": "image", "source": source}


def test_inline_image_blocks_are_masked_before_forwarding() -> None:
    upstream, sam = MessagesUpstream(), Sam()
    body = claude_code_body()
    body["messages"][0]["content"].insert(0, image_block(png()))
    # A screenshot in a tool result too (Claude Code's Read tool on an image file).
    body["messages"][2]["content"][0]["content"] = [image_block(png())]
    with TestClient(image_app(upstream, sam)) as http:
        r = http.post("/v1/messages", json=body)
    assert r.status_code == 200, r.text
    sent = upstream.raw_bodies[0]
    for block in (
        sent["messages"][0]["content"][0],
        sent["messages"][2]["content"][0]["content"][0],
    ):
        assert block["type"] == "image"
        assert block["source"]["media_type"] == "image/png"
        img = Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))).convert("RGB")
        assert filled(img, FACE) and filled(img, TAJ_BOX)
    assert TAJ_VALUE not in upstream.requests[0].content.decode()
    assert leaked_values(upstream.requests[0].content) == []
    assert r.headers["X-PII-Guard-Images"] == "2"


# --- Claude Code's own vocabulary under fast-mode false positives (found live, LAB-1605) ---


def test_model_words_keep_the_model_id_when_the_prompt_names_the_assistant() -> None:
    """Claude Code says "You are Claude"; a detector reading "Claude" as a PERSON made the
    vault's sweep rewrite ``claude-test-model`` and refused every request. The model id goes
    as sent; the prose occurrence is still masked."""
    upstream = MessagesUpstream()
    body = {
        "model": "claude-test-model",
        "max_tokens": 64,
        "system": "You are Claude, a coding agent.",
        "messages": [{"role": "user", "content": "Mail Jane Placeholder."}],
    }
    app = make_app(upstream, llm=FakeLlm(names=("Claude", "Jane Placeholder")))  # type: ignore[arg-type]
    with TestClient(app) as http:
        r = http.post("/v1/messages", json=body)
    assert r.status_code == 200, r.text
    sent = upstream.raw_bodies[0]
    assert sent["model"] == "claude-test-model"
    assert "Claude" not in sent["system"]


def test_model_words() -> None:
    words = model_words({"model": "claude-sonnet-4-5"})
    assert {"claude", "sonnet", "claude-sonnet", "claude-sonnet-4-5"} <= words
    assert "4-5" not in words and "4" not in words
    assert model_words({"model": 7}) == frozenset()


def test_json_schema_type_names_are_not_checked_as_personal_data() -> None:
    """The published NER reads a lone "boolean" as a PERSON; ``"type": "boolean"`` refused
    every tool with a flag (Claude Code's Agent tool)."""
    upstream = MessagesUpstream()
    body = claude_code_body()
    body["tools"][0]["input_schema"]["properties"]["background"] = {"type": "boolean"}
    app = make_app(upstream, llm=FakeLlm(names=("boolean", *NAMES)))  # type: ignore[arg-type]
    with TestClient(app) as http:
        r = http.post("/v1/messages", json=body)
    assert r.status_code == 200, r.text
    schema = upstream.raw_bodies[0]["tools"][0]["input_schema"]
    assert schema["properties"]["background"] == {"type": "boolean"}


def test_integer_limits_in_a_schema_are_not_checked_other_numbers_are() -> None:
    """zod's ``.int()`` writes +-(2**53 - 1) as bounds; the NER reads it as a bank account."""
    body = claude_code_body()
    line = {"type": "integer", "minimum": -(2**53 - 1), "maximum": 2**53 - 1}
    other = {"type": "integer", "maximum": 8123456786}
    body["tools"][0]["input_schema"]["properties"].update(line=line, other=other)
    checked = {s.text for s in collect_message_texts(body).slots if s.kind == "identifier"}
    assert str(2**53 - 1) not in checked and str(-(2**53 - 1)) not in checked
    assert "8123456786" in checked


def test_session_path_base_url_as_the_connect_block_writes_it() -> None:
    """``ANTHROPIC_BASE_URL=http://.../s/<session>``: the SDK posts ``/s/<session>/v1/messages``."""
    upstream = MessagesUpstream()
    app = make_app(upstream, llm=FakeLlm())  # type: ignore[arg-type]
    simple = {
        "model": "claude-test-model",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "Mail Jane Placeholder."}],
    }
    with TestClient(app) as http:
        r = http.post(
            "/s/c_claude_test/v1/messages", json=simple, headers={"x-api-key": CLIENT_KEY}
        )
    assert r.status_code == 200, r.text
    assert r.headers["X-PII-Guard-Session-Source"] == "path"
    assert "Jane Placeholder" in r.json()["content"][0]["text"]


def test_guard_token_in_x_api_key_is_never_forwarded_upstream() -> None:
    """With ``PII_GUARD_API_TOKEN`` set and no upstream key, an ``x-api-key`` carrying the
    token authenticates and is stripped: the BYOK pass-through never sees it (LAB-1605)."""
    token = "1" * 32
    upstream = MessagesUpstream()
    settings = Settings(tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL, api_token=token)
    app = make_app(upstream, llm=FakeLlm(), settings=settings)  # type: ignore[arg-type]
    simple = {
        "model": "claude-test-model",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "Mail Jane Placeholder."}],
    }
    with TestClient(app, base_url="http://127.0.0.1") as http:
        r = http.post("/v1/messages", json=simple, headers={"x-api-key": token})
        refused = http.post("/v1/messages", json=simple, headers={"x-api-key": "2" * 32})
    assert r.status_code == 200, r.text
    (request,) = upstream.requests
    assert "x-api-key" not in request.headers
    assert token not in str(request.headers)
    assert refused.status_code == 401
