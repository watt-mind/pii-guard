"""End-to-End (E2E) in-process gateway scenarios filling test coverage gaps.

Tests multi-turn parallel tool calls across chunk boundaries, upstream mid-stream
disconnect/error fault injection with session recovery, multi-turn Responses API
function calls, and custom tool input unmasking/re-masking. All tests are strictly
hermetic, offline, and in-process (ADR 0005).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi.testclient import TestClient
from gateway_helpers import (
    IBAN,
    NAMES,
    TEST_TENANT_KEY,
    UPSTREAM_KEY,
    UPSTREAM_URL,
    FakeLlm,
    MockUpstream,
    chunk,
    leaked_values,
    make_app,
)

from pii_guard.config import Settings
from pii_guard.gateway import GatewayConfig, Mode
from pii_guard.vault import PLACEHOLDER_RE

SESSION_TOOLS = "e2e_parallel_tools_001"
SESSION_FAULT = "e2e_fault_recovery_002"
SESSION_RESP = "e2e_responses_parallel_003"
SESSION_CUSTOM = "e2e_custom_tools_004"


# --- Helpers for splitting chunks -----------------------------------------------------------


def _split_text(text: str, piece_size: int = 4) -> list[str]:
    """Split text into small pieces to test placeholder reconstruction across chunk boundaries."""
    return [text[i : i + piece_size] for i in range(0, len(text), piece_size)]


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


def test_e2e_multi_turn_parallel_tool_calls_streaming() -> None:
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
            # Extract generated placeholders from forwarded request
            content = body["messages"][-1]["content"]
            matches = PLACEHOLDER_RE.findall(content)
            for entity_type, token_id in matches:
                placeholders_map[entity_type] = f"[[{entity_type}_{token_id}]]"

            person_ph = placeholders_map.get("PERSON", "[[PERSON_000000]]")
            email_ph = placeholders_map.get("EMAIL", "[[EMAIL_000000]]")
            bank_ph = placeholders_map.get("BANK_ACCOUNT", "[[BANK_ACCOUNT_000000]]")

            args_0 = json.dumps({"name": person_ph, "email": email_ph})
            args_1 = json.dumps({"recipient": person_ph, "iban": bank_ph, "amount": 500})

            sse_bytes = _build_interleaved_tool_chunks(args_0, args_1, piece_size=4)
            return httpx.Response(
                200, content=sse_bytes, headers={"content-type": "text/event-stream"}
            )

        if turn == 2:
            # Turn 2: upstream returns final confirmation text
            person_ph = placeholders_map.get("PERSON", "[[PERSON_000000]]")
            bank_ph = placeholders_map.get("BANK_ACCOUNT", "[[BANK_ACCOUNT_000000]]")
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

    mock_transport = httpx.MockTransport(upstream_handler)
    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
    )
    config = GatewayConfig(mode=Mode.AUDIT)
    app = make_app(upstream=MockUpstream(), llm=FakeLlm(NAMES), config=config, settings=settings)
    app.state.gateway_transport = mock_transport

    path = f"/s/{SESSION_TOOLS}/v1/chat/completions"

    with TestClient(app) as client:
        # --- Turn 1 ---
        turn1_body = {
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


def test_e2e_upstream_200_stream_read_error_recovery() -> None:
    """End-to-End: upstream 200 stream fails mid-stream with httpx.ReadError.

    Verifies that:
    1. Gateway terminates SSE stream with a sanitized error event and [DONE].
    2. No exception details or raw placeholders are leaked to client.
    3. The session vault is not corrupted; subsequent requests on the same session succeed.
    """

    class BrokenSseStream(httpx.AsyncByteStream):
        """Simulates an upstream that sends partial data and then encounters network failure."""

        def __init__(self, partial_chunk: bytes) -> None:
            self.partial_chunk = partial_chunk
            self.closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield self.partial_chunk
            raise httpx.ReadError("connection reset by peer mid-stream")

        async def aclose(self) -> None:
            self.closed = True

    requests_count = 0

    def upstream_handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests_count
        requests_count += 1

        if requests_count == 1:
            # First request: send a partial chunk and then crash
            first_event = chunk({"role": "assistant", "content": "Starting response for [[PER"})
            raw = f"data: {json.dumps(first_event)}\n\n".encode()
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=BrokenSseStream(raw)
            )

        # Second request: clean response
        text = "Hello, your session is healthy!"
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

    mock_transport = httpx.MockTransport(upstream_handler)
    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
    )
    config = GatewayConfig(mode=Mode.AUDIT)
    app = make_app(upstream=MockUpstream(), llm=FakeLlm(NAMES), config=config, settings=settings)
    app.state.gateway_transport = mock_transport

    path = f"/s/{SESSION_FAULT}/v1/chat/completions"

    with TestClient(app) as client:
        # 1. First request fails mid-stream
        req1 = {
            "model": "test-model",
            "stream": True,
            "messages": [{"role": "user", "content": "Hello from Teszt Elek!"}],
        }
        resp1 = client.post(path, json=req1)
        assert resp1.status_code == 200

        # Gateway terminates with error event and [DONE]
        lines = resp1.text.splitlines()
        data_lines = [line[6:] for line in lines if line.startswith("data: ")]
        assert len(data_lines) >= 2
        assert data_lines[-1] == "[DONE]"

        # The last data payload before [DONE] must be the stream_failed error
        error_payload = json.loads(data_lines[-2])
        assert error_payload["error"]["code"] == "stream_failed"
        assert error_payload["error"]["message"] == "the response stream failed"
        # Must not leak the internal exception string
        assert "connection reset by peer" not in resp1.text

        # 2. Second request on the SAME session succeeds completely
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
        assert content2 == "Hello, your session is healthy!"


# --- Scenario 3: Multi-Turn Responses API (/v1/responses) Parallel Function Calls ------------


def test_e2e_responses_api_multi_turn_parallel_functions() -> None:
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
            # Extract generated placeholders
            content = json.dumps(body.get("input", []))
            for entity_type, token_id in PLACEHOLDER_RE.findall(content):
                ph_map[entity_type] = f"[[{entity_type}_{token_id}]]"

            person_ph = ph_map.get("PERSON", "[[PERSON_000000]]")
            bank_ph = ph_map.get("BANK_ACCOUNT", "[[BANK_ACCOUNT_000000]]")

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
            person_ph = ph_map.get("PERSON", "[[PERSON_000000]]")
            bank_ph = ph_map.get("BANK_ACCOUNT", "[[BANK_ACCOUNT_000000]]")
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

    mock_transport = httpx.MockTransport(upstream_handler)
    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
    )
    config = GatewayConfig(mode=Mode.AUDIT)
    app = make_app(upstream=MockUpstream(), llm=FakeLlm(NAMES), config=config, settings=settings)
    app.state.gateway_transport = mock_transport

    path = f"/s/{SESSION_RESP}/v1/responses"

    with TestClient(app) as client:
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


def test_e2e_custom_tool_input_shell_multi_turn() -> None:
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
            content = body["messages"][-1]["content"]
            for entity_type, token_id in PLACEHOLDER_RE.findall(content):
                ph_map[entity_type] = f"[[{entity_type}_{token_id}]]"

            email_ph = ph_map.get("EMAIL", "[[EMAIL_000000]]")
            # Custom tool call with shell grep command
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
            email_ph = ph_map.get("EMAIL", "[[EMAIL_000000]]")
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

    mock_transport = httpx.MockTransport(upstream_handler)
    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
    )
    config = GatewayConfig(mode=Mode.AUDIT)
    app = make_app(upstream=MockUpstream(), llm=FakeLlm(NAMES), config=config, settings=settings)
    app.state.gateway_transport = mock_transport

    path = f"/s/{SESSION_CUSTOM}/v1/chat/completions"

    with TestClient(app) as client:
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
