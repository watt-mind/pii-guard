"""End-to-End (E2E) in-process gateway scenarios filling test coverage gaps.

Tests multi-turn parallel tool calls across chunk boundaries, upstream mid-stream
disconnect/error fault injection with session recovery, multi-turn Responses API
(whole and streamed) function & custom tool calls, Anthropic Messages API multi-turn
streaming with thinking/tool_use and detection cache verification, and cross-endpoint
session continuity. All tests are strictly hermetic, offline, and in-process (ADR 0005).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway_helpers import (
    IBAN,
    NAMES,
    FakeLlm,
    Handler,
    chunk,
    leaked_values,
    make_app,
)

from pii_guard.vault import PLACEHOLDER_RE

SESSION_TOOLS = "e2e_parallel_tools_001"
SESSION_FAULT = "e2e_fault_recovery_002"
SESSION_RESP = "e2e_responses_parallel_003"
SESSION_CUSTOM = "e2e_custom_tools_004"
SESSION_RESP_STREAM = "e2e_responses_stream_005"
SESSION_MESSAGES_STREAM = "e2e_messages_stream_006"
SESSION_CROSS_ENDPOINT = "e2e_cross_endpoint_007"
SESSION_PROTOCOL_FAULT = "e2e_protocol_fault_008"


@dataclass
class E2EHarness:
    """In-process gateway harness wiring TestClient, FakeLlm, and configurable upstream."""

    app: FastAPI
    client: TestClient
    llm: FakeLlm
    _set_handler: Callable[[Handler], None]

    def use_upstream(self, handler: Handler) -> None:
        self.llm.calls = 0
        self._set_handler(handler)


@pytest.fixture
def e2e_harness() -> Iterator[E2EHarness]:
    current_handler: Handler | None = None

    def dispatch(request: httpx.Request) -> httpx.Response:
        assert current_handler is not None, "Upstream handler not configured for test"
        return current_handler(request)

    def set_handler(handler: Handler) -> None:
        nonlocal current_handler
        current_handler = handler

    llm = FakeLlm(NAMES)
    app = make_app(transport=httpx.MockTransport(dispatch), llm=llm)
    with TestClient(app) as client:
        yield E2EHarness(app=app, client=client, llm=llm, _set_handler=set_handler)


# --- Helpers for splitting chunks and parsing SSE -------------------------------------------


def _split_text(text: str, piece_size: int = 4) -> list[str]:
    """Split text into small pieces to test placeholder reconstruction across chunk boundaries."""
    return [text[i : i + piece_size] for i in range(0, len(text), piece_size)]


def _extract_placeholders(payload: Any) -> dict[str, str]:
    """Extract ``{entity_type: '[[TYPE_id]]'}`` from a JSON-serializable object or string."""
    raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return {
        entity_type: f"[[{entity_type}_{token_id}]]"
        for entity_type, token_id in PLACEHOLDER_RE.findall(raw)
    }


def _parse_named_sse(raw: str) -> list[tuple[str | None, Any]]:
    """Parse SSE blocks into ``(event_name, parsed_data_or_DONE)`` tuples."""
    out: list[tuple[str | None, Any]] = []
    for block in raw.strip().split("\n\n"):
        if not block.strip():
            continue
        event_name: str | None = None
        data_str: str | None = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                data_str = line[6:]
        assert data_str is not None, f"Missing data line in SSE block: {block!r}"
        out.append((event_name, data_str if data_str == "[DONE]" else json.loads(data_str)))
    return out


class BrokenSseStream(httpx.AsyncByteStream):
    """Simulates an upstream that sends partial SSE bytes and then fails with a network error."""

    def __init__(self, partial_chunk: bytes) -> None:
        self.partial_chunk = partial_chunk
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.partial_chunk
        raise httpx.ReadError("connection reset by peer mid-stream")

    async def aclose(self) -> None:
        self.closed = True


def _build_interleaved_tool_chunks(
    call_0_args: str, call_1_args: str, *, piece_size: int = 5
) -> bytes:
    """Build an SSE byte stream with two parallel tool calls interleaved in small chunks."""
    pieces_0 = _split_text(call_0_args, piece_size)
    pieces_1 = _split_text(call_1_args, piece_size)

    events: list[dict[str, Any]] = [
        # Initial chunk announcing both tool calls
        chunk(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_lookup_001",
                        "type": "function",
                        "function": {"name": "lookup_user", "arguments": ""},
                    },
                    {
                        "index": 1,
                        "id": "call_wire_002",
                        "type": "function",
                        "function": {"name": "wire_transfer", "arguments": ""},
                    },
                ],
            }
        )
    ]

    # Interleave argument delta chunks for index 0 and index 1
    max_len = max(len(pieces_0), len(pieces_1))
    for i in range(max_len):
        if i < len(pieces_0):
            events.append(
                chunk({"tool_calls": [{"index": 0, "function": {"arguments": pieces_0[i]}}]})
            )
        if i < len(pieces_1):
            events.append(
                chunk({"tool_calls": [{"index": 1, "function": {"arguments": pieces_1[i]}}]})
            )

    # Finish chunk
    events.append(chunk({}, finish="tool_calls"))
    raw = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
    raw += "data: [DONE]\n\n"
    return raw.encode()


# --- Scenario 1: Multi-Turn Parallel Tool Calls (Streaming & Restored) -----------------------


def test_e2e_multi_turn_parallel_tool_calls_streaming(e2e_harness: E2EHarness) -> None:
    """End-to-End: upstream streams parallel tool calls with split placeholders.

    Turn 1: User sends prompt with multiple PII entities.
            Gateway masks request (zero gold PII reaches upstream).
            Upstream streams 2 parallel tool calls in interleaved small chunks.
            Gateway restores both tool arguments with JSON-escaping intact.
    Turn 2: Client sends back tool results and follow-up prompt.
            Gateway masks Turn 2 messages using the same session placeholders.
            Upstream replies with final text referencing placeholders.
            Gateway restores final text cleanly to client.
    """
    recorded_requests: list[httpx.Request] = []
    placeholders_map: dict[str, str] = {}

    def upstream_handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        body = json.loads(request.content)
        turn = len(recorded_requests)

        if turn == 1:
            placeholders_map.update(_extract_placeholders(body["messages"][-1]["content"]))
            person_ph = placeholders_map["PERSON"]
            email_ph = placeholders_map["EMAIL"]
            bank_ph = placeholders_map["BANK_ACCOUNT"]

            args_0 = json.dumps({"name": person_ph, "email": email_ph})
            args_1 = json.dumps({"recipient": person_ph, "iban": bank_ph, "amount": 500})

            sse_bytes = _build_interleaved_tool_chunks(args_0, args_1, piece_size=4)
            return httpx.Response(
                200, content=sse_bytes, headers={"content-type": "text/event-stream"}
            )

        if turn == 2:
            person_ph = placeholders_map["PERSON"]
            bank_ph = placeholders_map["BANK_ACCOUNT"]
            reply = f"Payment of 500 EUR transferred to {bank_ph} for {person_ph}."
            events = [
                chunk({"role": "assistant", "content": ""}),
                chunk({"content": reply}),
                chunk({}, finish="stop"),
            ]
            raw = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
            raw += "data: [DONE]\n\n"
            return httpx.Response(
                200, content=raw.encode(), headers={"content-type": "text/event-stream"}
            )

        return httpx.Response(400, json={"error": "unexpected turn"})

    e2e_harness.use_upstream(upstream_handler)
    client = e2e_harness.client
    path = f"/s/{SESSION_TOOLS}/v1/chat/completions"

    # --- Turn 1 ---
    turn1_body: dict[str, Any] = {
        "model": "test-model",
        "stream": True,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Check user Teszt Elek (email: teszt.elek@example.com) and wire 500 EUR "
                    f"to {IBAN}."
                ),
            }
        ],
        "tools": [
            {"type": "function", "function": {"name": "lookup_user", "parameters": {}}},
            {"type": "function", "function": {"name": "wire_transfer", "parameters": {}}},
        ],
    }

    resp1 = client.post(path, json=turn1_body)
    assert resp1.status_code == 200
    assert resp1.headers["content-type"].startswith("text/event-stream")

    # Upstream received request: assert ZERO sensitive raw values leaked
    assert len(recorded_requests) == 1
    assert leaked_values(recorded_requests[0].content) == []

    # Parse client stream
    lines = [line for line in resp1.text.splitlines() if line.startswith("data: {")]
    assert len(lines) > 0
    deltas = [json.loads(line[6:])["choices"][0]["delta"] for line in lines]

    tool_args: dict[int, str] = {0: "", 1: ""}
    tool_names: dict[int, str] = {}
    tool_ids: dict[int, str] = {}

    for d in deltas:
        for tc in d.get("tool_calls", []):
            idx = tc["index"]
            if "id" in tc:
                tool_ids[idx] = tc["id"]
            if "function" in tc:
                fn = tc["function"]
                if "name" in fn:
                    tool_names[idx] = fn["name"]
                if "arguments" in fn:
                    tool_args[idx] += fn["arguments"]

    assert tool_names[0] == "lookup_user"
    assert tool_names[1] == "wire_transfer"
    assert tool_ids[0] == "call_lookup_001"
    assert tool_ids[1] == "call_wire_002"

    # Verify arguments are valid JSON and fully restored without placeholders
    parsed_0 = json.loads(tool_args[0])
    parsed_1 = json.loads(tool_args[1])
    assert parsed_0 == {"name": "Teszt Elek", "email": "teszt.elek@example.com"}
    assert parsed_1 == {
        "recipient": "Teszt Elek",
        "iban": IBAN,
        "amount": 500,
    }
    assert "[[" not in tool_args[0]
    assert "[[" not in tool_args[1]

    # --- Turn 2 ---
    turn2_messages = [
        turn1_body["messages"][0],
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_lookup_001",
                    "type": "function",
                    "function": {"name": "lookup_user", "arguments": tool_args[0]},
                },
                {
                    "id": "call_wire_002",
                    "type": "function",
                    "function": {"name": "wire_transfer", "arguments": tool_args[1]},
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_lookup_001",
            "content": '{"status": "found", "user": "Teszt Elek"}',
        },
        {
            "role": "tool",
            "tool_call_id": "call_wire_002",
            "content": f'{{"status": "success", "iban": "{IBAN}", "tx": "TX100"}}',
        },
        {"role": "user", "content": "Great, please confirm the payment."},
    ]

    turn2_body = {"model": "test-model", "stream": True, "messages": turn2_messages}
    resp2 = client.post(path, json=turn2_body)
    assert resp2.status_code == 200

    # Assert zero raw values leaked to upstream in Turn 2
    assert len(recorded_requests) == 2
    assert leaked_values(recorded_requests[1].content) == []

    # Parse Turn 2 restored answer
    t2_lines = [line for line in resp2.text.splitlines() if line.startswith("data: {")]
    t2_content = "".join(
        json.loads(line[6:])["choices"][0]["delta"].get("content") or "" for line in t2_lines
    )
    assert t2_content == f"Payment of 500 EUR transferred to {IBAN} for Teszt Elek."
    assert "[[" not in t2_content


# --- Scenario 2: Upstream 200 OK Mid-Stream Failure & Session Recovery -----------------------


def test_e2e_upstream_200_stream_read_error_recovery(e2e_harness: E2EHarness) -> None:
    """End-to-End: upstream 200 stream fails mid-stream with httpx.ReadError.

    Verifies that:
    1. Gateway terminates SSE stream with a sanitized error event and [DONE], and closes stream.
    2. No exception details or raw placeholders are leaked to client.
    3. The session vault is not corrupted; Turn 1's placeholder mapping is preserved and
       restored cleanly on Turn 2 of the same session.
    """
    requests_count = 0
    ph_map: dict[str, str] = {}
    broken_streams: list[BrokenSseStream] = []

    def upstream_handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests_count
        requests_count += 1
        body = json.loads(request.content)

        if requests_count == 1:
            ph_map.update(_extract_placeholders(body["messages"][-1]["content"]))
            # First request: send a partial chunk holding back an incomplete placeholder, then crash
            first_event = chunk({"role": "assistant", "content": "Starting response for [[PER"})
            raw = f"data: {json.dumps(first_event)}\n\n".encode()
            stream = BrokenSseStream(raw)
            broken_streams.append(stream)
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

        # Second request: reference Turn 1's PERSON placeholder to verify vault state survived
        person_ph = ph_map["PERSON"]
        text = f"Hello {person_ph}, your session is healthy!"
        events = [
            chunk({"role": "assistant", "content": ""}),
            chunk({"content": text}),
            chunk({}, finish="stop"),
        ]
        raw_text = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
        raw_text += "data: [DONE]\n\n"
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=raw_text.encode()
        )

    e2e_harness.use_upstream(upstream_handler)
    client = e2e_harness.client
    path = f"/s/{SESSION_FAULT}/v1/chat/completions"

    # 1. First request fails mid-stream
    req1 = {
        "model": "test-model",
        "stream": True,
        "messages": [{"role": "user", "content": "Hello from Teszt Elek!"}],
    }
    resp1 = client.post(path, json=req1)
    assert resp1.status_code == 200
    assert len(broken_streams) == 1
    assert broken_streams[0].closed is True

    # Gateway terminates with error event and [DONE]
    lines = resp1.text.splitlines()
    data_lines = [line[6:] for line in lines if line.startswith("data: ")]
    assert len(data_lines) >= 2
    assert data_lines[-1] == "[DONE]"

    # The last data payload before [DONE] must be the stream_failed error
    error_payload = json.loads(data_lines[-2])
    assert error_payload["error"]["code"] == "stream_failed"
    assert error_payload["error"]["message"] == "the response stream failed"
    # Must not leak the internal exception string or partial placeholder
    assert "connection reset by peer" not in resp1.text
    assert "[[PER" not in resp1.text

    # 2. Second request on the SAME session succeeds and restores Turn 1's placeholder
    req2 = {
        "model": "test-model",
        "stream": True,
        "messages": [{"role": "user", "content": "Are you still there?"}],
    }
    resp2 = client.post(path, json=req2)
    assert resp2.status_code == 200

    resp2_lines = [line for line in resp2.text.splitlines() if line.startswith("data: {")]
    content2 = "".join(
        json.loads(line[6:])["choices"][0]["delta"].get("content") or "" for line in resp2_lines
    )
    assert content2 == "Hello Teszt Elek, your session is healthy!"


# --- Scenario 3: Multi-Turn Responses API (/v1/responses) Parallel Function Calls ------------


def test_e2e_responses_api_multi_turn_parallel_functions(e2e_harness: E2EHarness) -> None:
    """End-to-End: multi-turn /v1/responses with parallel function calls and outputs.

    Verifies:
    1. Turn 1: Upstream returns multiple function_call items in output.
               Gateway restores function arguments.
    2. Turn 2: Client provides function_call_output items.
               Gateway masks outputs and forwards request without leaking PII.
               Upstream replies with final text, restored to client.
    """
    recorded: list[httpx.Request] = []
    ph_map: dict[str, str] = {}

    def upstream_handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        body = json.loads(request.content)
        turn = len(recorded)

        if turn == 1:
            ph_map.update(_extract_placeholders(body.get("input", [])))
            person_ph = ph_map["PERSON"]
            bank_ph = ph_map["BANK_ACCOUNT"]

            response_body = {
                "id": "resp_001",
                "model": "muse-spark-1.3",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "fn_verify",
                        "name": "verify_identity",
                        "arguments": json.dumps({"name": person_ph}),
                    },
                    {
                        "type": "function_call",
                        "call_id": "fn_pay",
                        "name": "execute_transfer",
                        "arguments": json.dumps({"account": bank_ph, "holder": person_ph}),
                    },
                ],
            }
            return httpx.Response(200, json=response_body)

        if turn == 2:
            person_ph = ph_map["PERSON"]
            bank_ph = ph_map["BANK_ACCOUNT"]
            response_body = {
                "id": "resp_002",
                "model": "muse-spark-1.3",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": f"Identity {person_ph} verified. Wired to {bank_ph}.",
                            }
                        ],
                    }
                ],
            }
            return httpx.Response(200, json=response_body)

        return httpx.Response(400, json={"error": "unexpected"})

    e2e_harness.use_upstream(upstream_handler)
    client = e2e_harness.client
    path = f"/s/{SESSION_RESP}/v1/responses"

    # --- Turn 1 ---
    turn1_body = {
        "model": "muse-spark-1.3",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": f"Please verify Teszt Elek and transfer funds to {IBAN}.",
            }
        ],
        "tools": [
            {"type": "function", "name": "verify_identity", "parameters": {}},
            {"type": "function", "name": "execute_transfer", "parameters": {}},
        ],
    }

    r1 = client.post(path, json=turn1_body)
    assert r1.status_code == 200
    data1 = r1.json()

    # Upstream saw masked values
    assert len(recorded) == 1
    assert leaked_values(recorded[0].content) == []

    # Client receives restored function arguments
    calls = [item for item in data1["output"] if item.get("type") == "function_call"]
    assert len(calls) == 2
    args_0 = json.loads(calls[0]["arguments"])
    args_1 = json.loads(calls[1]["arguments"])
    assert args_0 == {"name": "Teszt Elek"}
    assert args_1 == {"account": IBAN, "holder": "Teszt Elek"}
    assert "[[" not in calls[0]["arguments"]
    assert "[[" not in calls[1]["arguments"]

    # --- Turn 2 ---
    turn2_body = {
        "model": "muse-spark-1.3",
        "input": [
            *turn1_body["input"],
            *data1["output"],
            {
                "type": "function_call_output",
                "call_id": "fn_verify",
                "output": json.dumps({"verified": True, "name": "Teszt Elek"}),
            },
            {
                "type": "function_call_output",
                "call_id": "fn_pay",
                "output": json.dumps({"status": "sent", "account": IBAN}),
            },
            {"type": "message", "role": "user", "content": "Please give me confirmation."},
        ],
    }

    r2 = client.post(path, json=turn2_body)
    assert r2.status_code == 200
    data2 = r2.json()

    # Upstream saw 0 raw leaks
    assert len(recorded) == 2
    assert leaked_values(recorded[1].content) == []

    # Client receives restored final confirmation
    msg = data2["output"][0]
    text_out = msg["content"][0]["text"]
    assert text_out == f"Identity Teszt Elek verified. Wired to {IBAN}."
    assert "[[" not in text_out


# --- Scenario 4: Custom Tool Input (Shell Command Freeform) Multi-Turn E2E -------------------


def test_e2e_custom_tool_input_shell_multi_turn(e2e_harness: E2EHarness) -> None:
    """End-to-End: custom tool input with shell commands and freeform PII restoration.

    Turn 1: Model issues a custom tool call (e.g. bash shell) containing masked values.
            Gateway restores custom tool input as freeform text (not JSON escaped).
    Turn 2: Client returns execution output of the shell command with PII.
            Gateway masks output, forwards to upstream, and restores the final assistant reply.
    """
    recorded: list[httpx.Request] = []
    ph_map: dict[str, str] = {}

    def upstream_handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        body = json.loads(request.content)
        turn = len(recorded)

        if turn == 1:
            ph_map.update(_extract_placeholders(body["messages"][-1]["content"]))
            email_ph = ph_map["EMAIL"]
            call = {
                "id": "custom_call_001",
                "type": "custom",
                "custom": {
                    "name": "bash",
                    "input": f"grep -rn '{email_ph}' /workspace/config",
                },
            }
            resp_body = {
                "id": "chatcmpl-custom",
                "object": "chat.completion",
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [call],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }
            return httpx.Response(200, json=resp_body)

        if turn == 2:
            email_ph = ph_map["EMAIL"]
            resp_body = {
                "id": "chatcmpl-custom-2",
                "object": "chat.completion",
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"Found matching configuration for {email_ph}.",
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
            return httpx.Response(200, json=resp_body)

        return httpx.Response(400, json={"error": "unexpected"})

    e2e_harness.use_upstream(upstream_handler)
    client = e2e_harness.client
    path = f"/s/{SESSION_CUSTOM}/v1/chat/completions"

    # --- Turn 1 ---
    turn1_body = {
        "model": "test-model",
        "messages": [
            {
                "role": "user",
                "content": "Please grep for teszt.elek@example.com in the workspace.",
            }
        ],
        "tools": [{"type": "custom", "custom": {"name": "bash"}}],
    }

    r1 = client.post(path, json=turn1_body)
    assert r1.status_code == 200
    data1 = r1.json()

    # Upstream saw 0 leaked values
    assert len(recorded) == 1
    assert leaked_values(recorded[0].content) == []

    # Custom tool input restored as freeform text
    tc = data1["choices"][0]["message"]["tool_calls"][0]
    assert tc["custom"]["name"] == "bash"
    assert tc["custom"]["input"] == "grep -rn 'teszt.elek@example.com' /workspace/config"
    assert "[[" not in tc["custom"]["input"]

    # --- Turn 2 ---
    turn2_messages = [
        turn1_body["messages"][0],
        data1["choices"][0]["message"],
        {
            "role": "tool",
            "tool_call_id": "custom_call_001",
            "content": "/workspace/config/env.sh: ADMIN_EMAIL=teszt.elek@example.com",
        },
        {"role": "user", "content": "What did you find?"},
    ]

    r2 = client.post(path, json={"model": "test-model", "messages": turn2_messages})
    assert r2.status_code == 200
    data2 = r2.json()

    # Upstream received masked content in tool result
    assert len(recorded) == 2
    assert leaked_values(recorded[1].content) == []

    # Final assistant response is restored cleanly
    final_content = data2["choices"][0]["message"]["content"]
    assert final_content == "Found matching configuration for teszt.elek@example.com."
    assert "[[" not in final_content


# --- Scenario 5: Streamed /v1/responses Multi-Turn Interleaved Function & Custom Tools -------


def _responses_sse(events: list[dict[str, Any]]) -> bytes:
    for seq, ev in enumerate(events):
        ev["sequence_number"] = seq
    raw = "".join(
        f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n" for ev in events
    )
    return (raw + "data: [DONE]\n\n").encode()


def test_e2e_responses_api_streaming_interleaved_tools_multi_turn(
    e2e_harness: E2EHarness,
) -> None:
    """End-to-End: streamed /v1/responses with interleaved function_call & custom_tool_call deltas.

    Verifies:
    1. Turn 1 streams interleaved ``response.function_call_arguments.delta`` (output_index 0) and
       ``response.custom_tool_call_input.delta`` (output_index 1) split across 4-char pieces.
    2. Held-back placeholders flush before ``.done``, keeping ``sequence_number`` strictly
       monotonic and ``delta`` concatenation equal to ``.done`` and ``response.completed``.
    3. Turn 2 sends ``function_call_output`` and ``custom_tool_call_output``; gateway masks them
       with zero leaks and streams the restored final answer.
    """
    recorded: list[httpx.Request] = []
    ph_map: dict[str, str] = {}

    def upstream_handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        body = json.loads(request.content)
        turn = len(recorded)

        if turn == 1:
            ph_map.update(_extract_placeholders(body["input"]))
            person_ph = ph_map["PERSON"]
            email_ph = ph_map["EMAIL"]
            bank_ph = ph_map["BANK_ACCOUNT"]

            fn_args = json.dumps({"recipient": person_ph, "iban": bank_ph})
            custom_in = f"grep -F '{email_ph}' /var/log/audit.log"
            fn_pieces = _split_text(fn_args, 4)
            custom_pieces = _split_text(custom_in, 4)

            whole_output = [
                {
                    "type": "function_call",
                    "id": "fc_01",
                    "call_id": "call_fn_01",
                    "name": "prepare_transfer",
                    "arguments": fn_args,
                    "status": "completed",
                },
                {
                    "type": "custom_tool_call",
                    "id": "ct_02",
                    "call_id": "call_sh_02",
                    "name": "bash",
                    "input": custom_in,
                    "status": "completed",
                },
            ]
            events: list[dict[str, Any]] = [
                {
                    "type": "response.created",
                    "response": {"id": "resp_s1", "status": "in_progress", "output": []},
                },
            ]
            for i in range(max(len(fn_pieces), len(custom_pieces))):
                if i < len(fn_pieces):
                    events.append(
                        {
                            "type": "response.function_call_arguments.delta",
                            "item_id": "fc_01",
                            "output_index": 0,
                            "delta": fn_pieces[i],
                        }
                    )
                if i < len(custom_pieces):
                    events.append(
                        {
                            "type": "response.custom_tool_call_input.delta",
                            "item_id": "ct_02",
                            "output_index": 1,
                            "delta": custom_pieces[i],
                        }
                    )
            events += [
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": "fc_01",
                    "output_index": 0,
                    "arguments": fn_args,
                },
                {
                    "type": "response.custom_tool_call_input.done",
                    "item_id": "ct_02",
                    "output_index": 1,
                    "input": custom_in,
                },
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_s1",
                        "status": "completed",
                        "output": whole_output,
                        "usage": {"input_tokens": 20, "output_tokens": 12, "total_tokens": 32},
                    },
                },
            ]
            return httpx.Response(
                200,
                content=_responses_sse(events),
                headers={"content-type": "text/event-stream"},
            )

        if turn == 2:
            ph_map.update(_extract_placeholders(body["input"]))
            person_ph = ph_map["PERSON"]
            email_ph = ph_map["EMAIL"]
            bank_ph = ph_map["BANK_ACCOUNT"]
            final_text = f"Verified {email_ph} and queued transfer to {bank_ph} for {person_ph}."
            events = [
                {
                    "type": "response.created",
                    "response": {"id": "resp_s2", "status": "in_progress", "output": []},
                },
                *[
                    {
                        "type": "response.output_text.delta",
                        "item_id": "msg_s2",
                        "output_index": 0,
                        "content_index": 0,
                        "delta": piece,
                    }
                    for piece in _split_text(final_text, 5)
                ],
                {
                    "type": "response.output_text.done",
                    "item_id": "msg_s2",
                    "output_index": 0,
                    "content_index": 0,
                    "text": final_text,
                },
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_s2",
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "id": "msg_s2",
                                "role": "assistant",
                                "status": "completed",
                                "content": [{"type": "output_text", "text": final_text}],
                            }
                        ],
                    },
                },
            ]
            return httpx.Response(
                200,
                content=_responses_sse(events),
                headers={"content-type": "text/event-stream"},
            )

        return httpx.Response(400, json={"error": "unexpected turn"})

    e2e_harness.use_upstream(upstream_handler)
    client = e2e_harness.client
    path = f"/s/{SESSION_RESP_STREAM}/v1/responses"

    # --- Turn 1 ---
    turn1_body: dict[str, Any] = {
        "model": "muse-spark-1.3",
        "stream": True,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": (
                    f"Audit teszt.elek@example.com and prepare transfer for Teszt Elek to {IBAN}."
                ),
            }
        ],
        "tools": [
            {"type": "function", "name": "prepare_transfer", "parameters": {}},
            {"type": "custom", "name": "bash"},
        ],
    }

    r1 = client.post(path, json=turn1_body)
    assert r1.status_code == 200
    assert leaked_values(recorded[0].content) == []
    assert not PLACEHOLDER_RE.search(r1.text)

    events1 = _parse_named_sse(r1.text)
    assert events1[-1] == (None, "[DONE]")
    named1 = [(n, d) for n, d in events1 if d != "[DONE]"]
    seq_numbers = [d["sequence_number"] for _, d in named1]
    assert seq_numbers == list(range(len(seq_numbers)))

    streamed_fn_args = "".join(
        d["delta"] for n, d in named1 if n == "response.function_call_arguments.delta"
    )
    done_fn_args = next(
        d["arguments"] for n, d in named1 if n == "response.function_call_arguments.done"
    )
    assert streamed_fn_args == done_fn_args
    assert json.loads(done_fn_args) == {"recipient": "Teszt Elek", "iban": IBAN}

    streamed_custom_in = "".join(
        d["delta"] for n, d in named1 if n == "response.custom_tool_call_input.delta"
    )
    done_custom_in = next(
        d["input"] for n, d in named1 if n == "response.custom_tool_call_input.done"
    )
    assert streamed_custom_in == done_custom_in
    assert done_custom_in == "grep -F 'teszt.elek@example.com' /var/log/audit.log"

    completed1 = next(d["response"] for n, d in named1 if n == "response.completed")

    # --- Turn 2 ---
    turn2_body = {
        "model": "muse-spark-1.3",
        "stream": True,
        "input": [
            *turn1_body["input"],
            *completed1["output"],
            {
                "type": "function_call_output",
                "call_id": "call_fn_01",
                "output": json.dumps({"queued": True, "iban": IBAN, "recipient": "Teszt Elek"}),
            },
            {
                "type": "custom_tool_call_output",
                "call_id": "call_sh_02",
                "output": "audit.log:12: user=teszt.elek@example.com status=ok",
            },
            {"type": "message", "role": "user", "content": "Summarize the result."},
        ],
    }

    r2 = client.post(path, json=turn2_body)
    assert r2.status_code == 200
    assert len(recorded) == 2
    assert leaked_values(recorded[1].content) == []
    assert not PLACEHOLDER_RE.search(r2.text)

    events2 = [(n, d) for n, d in _parse_named_sse(r2.text) if d != "[DONE]"]
    streamed_text = "".join(d["delta"] for n, d in events2 if n == "response.output_text.delta")
    done_text = next(d["text"] for n, d in events2 if n == "response.output_text.done")
    assert streamed_text == done_text
    assert (
        done_text
        == f"Verified teszt.elek@example.com and queued transfer to {IBAN} for Teszt Elek."
    )


# --- Scenario 6: Anthropic /v1/messages Streaming Parallel Tool Use & Cache Hit -------------


def test_e2e_messages_api_streaming_parallel_tool_use_and_cache_hit(
    e2e_harness: E2EHarness,
) -> None:
    """End-to-End: Anthropic /v1/messages multi-turn streaming with thinking, text & parallel tools.

    Verifies:
    1. Turn 1 streams ``thinking_delta`` + ``signature_delta`` (opaque, untouched),
       ``text_delta``, and two parallel ``tool_use`` blocks (``input_json_delta``) with
       placeholders split across chunks.
    2. All blocks flush before their ``content_block_stop`` events and restore cleanly.
    3. Turn 2 sends the restored assistant turn + ``tool_result`` blocks; ``DetectionCache``
       avoids re-running the LLM detector on Turn 1's user prompt and assistant text block.
    """
    recorded: list[httpx.Request] = []
    ph_map: dict[str, str] = {}
    signature = "EqQBCkYIBxgCKkB-opaque-signature-e2e"

    def upstream_handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        body = json.loads(request.content)
        turn = len(recorded)

        if turn == 1:
            ph_map.update(_extract_placeholders(body["messages"]))
            person_ph = ph_map["PERSON"]
            email_ph = ph_map["EMAIL"]
            bank_ph = ph_map["BANK_ACCOUNT"]

            thinking_text = f"Checking {person_ph} and account {bank_ph}."
            reply_text = f"I will look up {person_ph} and wire to {bank_ph}."
            tool0_json = json.dumps({"email": email_ph, "name": person_ph})
            tool1_json = json.dumps({"command": f"echo 'wiring to {bank_ph} for {person_ph}'"})

            events: list[dict[str, Any]] = [
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_e2e_1",
                        "type": "message",
                        "role": "assistant",
                        "model": body["model"],
                        "content": [],
                        "stop_reason": None,
                        "usage": {"input_tokens": 25, "output_tokens": 1},
                    },
                },
                # Block 0: thinking + opaque signature
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "thinking", "thinking": ""},
                },
                *[
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "thinking_delta", "thinking": piece},
                    }
                    for piece in _split_text(thinking_text, 4)
                ],
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "signature_delta", "signature": signature},
                },
                {"type": "content_block_stop", "index": 0},
                # Block 1: assistant text
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {"type": "text", "text": ""},
                },
                *[
                    {
                        "type": "content_block_delta",
                        "index": 1,
                        "delta": {"type": "text_delta", "text": piece},
                    }
                    for piece in _split_text(reply_text, 4)
                ],
                {"type": "content_block_stop", "index": 1},
                # Block 2 & Block 3: parallel tool_use blocks
                {
                    "type": "content_block_start",
                    "index": 2,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_lookup",
                        "name": "lookup_contact",
                        "input": {},
                    },
                },
                {
                    "type": "content_block_start",
                    "index": 3,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_bash",
                        "name": "Bash",
                        "input": {},
                    },
                },
            ]
            pieces_0 = _split_text(tool0_json, 4)
            pieces_1 = _split_text(tool1_json, 4)
            for i in range(max(len(pieces_0), len(pieces_1))):
                if i < len(pieces_0):
                    events.append(
                        {
                            "type": "content_block_delta",
                            "index": 2,
                            "delta": {"type": "input_json_delta", "partial_json": pieces_0[i]},
                        }
                    )
                if i < len(pieces_1):
                    events.append(
                        {
                            "type": "content_block_delta",
                            "index": 3,
                            "delta": {"type": "input_json_delta", "partial_json": pieces_1[i]},
                        }
                    )
            events += [
                {"type": "content_block_stop", "index": 2},
                {"type": "content_block_stop", "index": 3},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                    "usage": {"output_tokens": 40},
                },
                {"type": "message_stop"},
            ]
            raw = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
            return httpx.Response(
                200, content=raw.encode(), headers={"content-type": "text/event-stream"}
            )

        if turn == 2:
            person_ph = ph_map["PERSON"]
            bank_ph = ph_map["BANK_ACCOUNT"]
            final_text = f"Completed transfer to {bank_ph} for {person_ph}."
            events = [
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_e2e_2",
                        "type": "message",
                        "role": "assistant",
                        "model": body["model"],
                        "content": [],
                        "stop_reason": None,
                        "usage": {"input_tokens": 50, "output_tokens": 1},
                    },
                },
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
                *[
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": piece},
                    }
                    for piece in _split_text(final_text, 5)
                ],
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 15},
                },
                {"type": "message_stop"},
            ]
            raw = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
            return httpx.Response(
                200, content=raw.encode(), headers={"content-type": "text/event-stream"}
            )

        return httpx.Response(400, json={"type": "error"})

    e2e_harness.use_upstream(upstream_handler)
    client = e2e_harness.client
    path = f"/s/{SESSION_MESSAGES_STREAM}/v1/messages"

    # --- Turn 1 ---
    turn1_user_msg = {
        "role": "user",
        "content": (
            f"Please contact Teszt Elek (teszt.elek@example.com) and wire funds to {IBAN}."
        ),
    }
    turn1_body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 1024,
        "stream": True,
        "messages": [turn1_user_msg],
        "tools": [
            {"name": "lookup_contact", "input_schema": {"type": "object"}},
            {"name": "Bash", "input_schema": {"type": "object"}},
        ],
    }

    r1 = client.post(path, json=turn1_body)
    assert r1.status_code == 200
    assert leaked_values(recorded[0].content) == []
    assert not PLACEHOLDER_RE.search(r1.text)
    assert e2e_harness.llm.calls == 4  # 1 user message + model + 2 tool names

    evs1 = [d for _, d in _parse_named_sse(r1.text)]
    thinking_out = "".join(
        e["delta"]["thinking"]
        for e in evs1
        if e["type"] == "content_block_delta"
        and e["index"] == 0
        and e["delta"]["type"] == "thinking_delta"
    )
    sig_out = "".join(
        e["delta"]["signature"]
        for e in evs1
        if e["type"] == "content_block_delta"
        and e["index"] == 0
        and e["delta"]["type"] == "signature_delta"
    )
    text_out = "".join(
        e["delta"]["text"]
        for e in evs1
        if e["type"] == "content_block_delta"
        and e["index"] == 1
        and e["delta"]["type"] == "text_delta"
    )
    tool0_out = "".join(
        e["delta"]["partial_json"]
        for e in evs1
        if e["type"] == "content_block_delta"
        and e["index"] == 2
        and e["delta"]["type"] == "input_json_delta"
    )
    tool1_out = "".join(
        e["delta"]["partial_json"]
        for e in evs1
        if e["type"] == "content_block_delta"
        and e["index"] == 3
        and e["delta"]["type"] == "input_json_delta"
    )

    assert thinking_out == f"Checking Teszt Elek and account {IBAN}."
    assert sig_out == signature
    assert text_out == f"I will look up Teszt Elek and wire to {IBAN}."
    assert json.loads(tool0_out) == {"email": "teszt.elek@example.com", "name": "Teszt Elek"}
    assert json.loads(tool1_out) == {"command": f"echo 'wiring to {IBAN} for Teszt Elek'"}

    # --- Turn 2 ---
    e2e_harness.llm.calls = 0
    turn2_body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 1024,
        "stream": True,
        "messages": [
            turn1_user_msg,
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": text_out},
                    {
                        "type": "tool_use",
                        "id": "toolu_lookup",
                        "name": "lookup_contact",
                        "input": json.loads(tool0_out),
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_bash",
                        "name": "Bash",
                        "input": json.loads(tool1_out),
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_lookup",
                        "content": "Contact verified: Teszt Elek",
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_bash",
                        "content": f"wired to {IBAN}",
                    },
                ],
            },
        ],
    }

    r2 = client.post(path, json=turn2_body)
    assert r2.status_code == 200
    assert len(recorded) == 2
    assert leaked_values(recorded[1].content) == []
    assert not PLACEHOLDER_RE.search(r2.text)

    # Turn 1 user message, model id, and restored assistant text block all hit DetectionCache;
    # only the 6 tool_use input keys/values + 2 tool_use names + 2 tool_result strings run FakeLlm.
    assert e2e_harness.llm.calls == 10
    evs2 = [d for _, d in _parse_named_sse(r2.text)]
    final_reply = "".join(
        e["delta"]["text"]
        for e in evs2
        if e["type"] == "content_block_delta" and e["delta"]["type"] == "text_delta"
    )
    assert final_reply == f"Completed transfer to {IBAN} for Teszt Elek."


# --- Scenario 7: Cross-Endpoint Session Continuity ------------------------------------------


def test_e2e_cross_endpoint_session_continuity(e2e_harness: E2EHarness) -> None:
    """End-to-End: a single session shares placeholders & cache across all gateway endpoints.

    Exercises ``/v1/messages/count_tokens`` -> ``/v1/messages`` -> ``/v1/responses`` ->
    ``/v1/chat/completions`` -> ``/v1/unmask`` under one session ID.
    """
    seen_placeholders: list[dict[str, str]] = []

    def upstream_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert leaked_values(request.content) == []
        phs = _extract_placeholders(body)
        seen_placeholders.append(phs)
        person_ph = phs["PERSON"]
        bank_ph = phs["BANK_ACCOUNT"]

        if request.url.path.endswith("/messages/count_tokens"):
            return httpx.Response(200, json={"input_tokens": 42})
        if request.url.path.endswith("/messages"):
            return httpx.Response(
                200,
                json={
                    "id": "msg_cross",
                    "type": "message",
                    "role": "assistant",
                    "model": body["model"],
                    "content": [{"type": "text", "text": f"Anthropic: {person_ph} / {bank_ph}"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            )
        if request.url.path.endswith("/responses"):
            return httpx.Response(
                200,
                json={
                    "id": "resp_cross",
                    "model": body["model"],
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": f"Responses: {person_ph} / {bank_ph}",
                                }
                            ],
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-cross",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"Chat: {person_ph} / {bank_ph}",
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    e2e_harness.use_upstream(upstream_handler)
    client = e2e_harness.client
    prompt = f"Account holder Teszt Elek with IBAN {IBAN}."
    base = f"/s/{SESSION_CROSS_ENDPOINT}"

    # 1. /v1/messages/count_tokens seeds the session vault and detection cache (prompt + model id)
    r_count = client.post(
        f"{base}/v1/messages/count_tokens",
        json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": prompt}]},
    )
    assert r_count.status_code == 200
    assert r_count.json() == {"input_tokens": 42}
    assert e2e_harness.llm.calls == 2

    # 2. /v1/messages with the exact same prompt hits DetectionCache (0 new LLM calls!)
    e2e_harness.llm.calls = 0
    r_msg = client.post(
        f"{base}/v1/messages",
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 256,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    assert r_msg.status_code == 200
    assert e2e_harness.llm.calls == 0
    assert r_msg.json()["content"][0]["text"] == f"Anthropic: Teszt Elek / {IBAN}"

    # 3. /v1/responses on the same session reuses identical placeholders
    r_resp = client.post(
        f"{base}/v1/responses",
        json={
            "model": "muse-spark-1.3",
            "input": [{"type": "message", "role": "user", "content": prompt}],
        },
    )
    assert r_resp.status_code == 200
    assert r_resp.json()["output"][0]["content"][0]["text"] == f"Responses: Teszt Elek / {IBAN}"

    # 4. /v1/chat/completions on the same session reuses identical placeholders
    r_chat = client.post(
        f"{base}/v1/chat/completions",
        json={"model": "test-model", "messages": [{"role": "user", "content": prompt}]},
    )
    assert r_chat.status_code == 200
    assert r_chat.json()["choices"][0]["message"]["content"] == f"Chat: Teszt Elek / {IBAN}"

    # All 4 upstream calls received the exact same PERSON and BANK_ACCOUNT placeholders
    assert len(seen_placeholders) == 4
    first_phs = seen_placeholders[0]
    assert all(phs == first_phs for phs in seen_placeholders)

    # 5. /v1/unmask restores the session's placeholders and reports unknown ones
    person_ph = first_phs["PERSON"]
    bank_ph = first_phs["BANK_ACCOUNT"]
    r_unmask = client.post(
        "/v1/unmask",
        json={
            "session_id": SESSION_CROSS_ENDPOINT,
            "text": f"Holder {person_ph}, account {bank_ph}, unknown [[PERSON_deadbeef]].",
        },
    )
    assert r_unmask.status_code == 200
    assert r_unmask.json() == {
        "text": f"Holder Teszt Elek, account {IBAN}, unknown [[PERSON_deadbeef]].",
        "unresolved": ["[[PERSON_deadbeef]]"],
    }


# --- Scenario 8: Mid-Stream Fault Recovery on /v1/responses and /v1/messages ----------------


@pytest.mark.parametrize("protocol", ["responses", "messages"])
def test_e2e_responses_and_messages_mid_stream_fault_recovery(
    e2e_harness: E2EHarness, protocol: str
) -> None:
    """End-to-End: mid-stream httpx.ReadError on /v1/responses and /v1/messages.

    Verifies protocol-native sanitized error event emission, stream closure, zero leakage of
    partial placeholders or exception messages, and Turn 2 session recovery.
    """
    turn = 0
    ph_map: dict[str, str] = {}
    broken_streams: list[BrokenSseStream] = []

    def upstream_handler(request: httpx.Request) -> httpx.Response:
        nonlocal turn
        turn += 1
        body = json.loads(request.content)
        ph_map.update(_extract_placeholders(body))
        person_ph = ph_map["PERSON"]

        if turn == 1:
            partial_ev: dict[str, Any]
            if protocol == "responses":
                partial_ev = {
                    "type": "response.output_text.delta",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "Hello [[PER",
                    "sequence_number": 0,
                }
            else:
                partial_ev = {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hello [[PER"},
                }
            raw = f"event: {partial_ev['type']}\ndata: {json.dumps(partial_ev)}\n\n".encode()
            stream = BrokenSseStream(raw)
            broken_streams.append(stream)
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

        # Turn 2: healthy response referencing Turn 1's placeholder
        reply = f"Recovered session for {person_ph}."
        if protocol == "responses":
            events = [
                {
                    "type": "response.output_text.delta",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": reply,
                },
                {
                    "type": "response.output_text.done",
                    "output_index": 0,
                    "content_index": 0,
                    "text": reply,
                },
            ]
            return httpx.Response(
                200,
                content=_responses_sse(events),
                headers={"content-type": "text/event-stream"},
            )

        msg_events: list[dict[str, Any]] = [
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": reply},
            },
            {"type": "content_block_stop", "index": 0},
            {"type": "message_stop"},
        ]
        raw_msg = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in msg_events)
        return httpx.Response(
            200, content=raw_msg.encode(), headers={"content-type": "text/event-stream"}
        )

    e2e_harness.use_upstream(upstream_handler)
    client = e2e_harness.client
    session_id = f"{SESSION_PROTOCOL_FAULT}_{protocol}"

    if protocol == "responses":
        path = f"/s/{session_id}/v1/responses"
        req1 = {
            "model": "muse-spark-1.3",
            "stream": True,
            "input": [{"type": "message", "role": "user", "content": "Hi from Teszt Elek"}],
        }
        req2 = {
            "model": "muse-spark-1.3",
            "stream": True,
            "input": [{"type": "message", "role": "user", "content": "Retry please"}],
        }
    else:
        path = f"/s/{session_id}/v1/messages"
        req1 = {
            "model": "claude-sonnet-4-6",
            "max_tokens": 256,
            "stream": True,
            "messages": [{"role": "user", "content": "Hi from Teszt Elek"}],
        }
        req2 = {
            "model": "claude-sonnet-4-6",
            "max_tokens": 256,
            "stream": True,
            "messages": [{"role": "user", "content": "Retry please"}],
        }

    # Turn 1: fails mid-stream
    r1 = client.post(path, json=req1)
    assert r1.status_code == 200
    assert broken_streams[0].closed is True
    assert "connection reset by peer" not in r1.text
    assert "[[PER" not in r1.text

    parsed1 = _parse_named_sse(r1.text)
    err_name, err_data = parsed1[-1]
    assert err_name == "error"
    if protocol == "responses":
        assert err_data["code"] == "stream_failed"
        assert err_data["message"] == "the response stream failed"
    else:
        assert err_data == {
            "type": "error",
            "error": {"type": "api_error", "message": "the response stream failed"},
        }

    # Turn 2: recovers cleanly and restores Turn 1's PERSON placeholder
    r2 = client.post(path, json=req2)
    assert r2.status_code == 200
    assert "Recovered session for Teszt Elek." in r2.text
    assert not PLACEHOLDER_RE.search(r2.text)
