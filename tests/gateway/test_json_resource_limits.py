"""Bound JSON work before walking it, and preserve nested masking order (LAB-1759)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import TEST_TENANT_KEY, UPSTREAM_KEY, UPSTREAM_URL, MockUpstream, make_app

from pii_guard.config import Settings
from pii_guard.gateway import GatewayConfig, Mode
from pii_guard.gateway import request as walker
from pii_guard.gateway.messages_request import collect_message_texts
from pii_guard.gateway.responses_request import collect_response_texts
from pii_guard.projects.middleware import ProjectAccessError, _read_endpoint_json_body


def _body(protocol: str, value: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"model": "test-model"}
    if protocol == "responses":
        body.update(input="hello", metadata={"items": value})
    else:
        body["messages"] = [{"role": "user", "content": "hello"}]
        if protocol == "messages":
            body["max_tokens"] = 64
            body["messages"].append(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_fixture",
                            "name": "fixture",
                            "input": value,
                        }
                    ],
                }
            )
        else:
            body["metadata"] = {"items": value}
    return body


COLLECTORS = {
    "chat": walker.collect_texts,
    "responses": collect_response_texts,
    "messages": collect_message_texts,
}


@pytest.mark.parametrize("protocol", COLLECTORS)
@pytest.mark.parametrize("shape", ["wide", "deep"])
def test_structure_is_rejected_before_any_text_slots_are_allocated(
    protocol: str, shape: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(walker, "MAX_JSON_NODES", 20_000)
    value: Any = [{} for _ in range(40_000)] if shape == "wide" else "fixture"
    if shape == "deep":
        for _ in range(walker.MAX_JSON_DEPTH + 1):
            value = [value]

    def unexpected_slot(*args: Any, **kwargs: Any) -> None:
        pytest.fail("collection started before the structural limit was enforced")

    monkeypatch.setattr(walker, "TextSlot", unexpected_slot)
    with pytest.raises(walker.InvalidChatRequestError, match="JSON exceeds structural limits"):
        COLLECTORS[protocol](_body(protocol, value))


def test_each_decoded_tool_tree_spends_the_same_request_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(walker, "MAX_JSON_NODES", 40)
    out = walker.CollectedTexts([], [])
    out.check_structure({"input": "fixture"})
    # Each tree fits alone, but repeated decoded tool strings cannot reset the budget.
    for _ in range(3):
        holder = [[{} for _ in range(10)]]
        walker._collect_json(holder, 0, out)
    with pytest.raises(walker.InvalidChatRequestError, match="structural limits"):
        walker._collect_json([[{} for _ in range(10)]], 0, out)


def test_aliases_and_cycles_do_not_bypass_the_structural_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(walker, "MAX_JSON_NODES", 20)
    shared = {"fixture": "value"}
    with pytest.raises(walker.InvalidChatRequestError, match="structural limits"):
        walker.CollectedTexts([], []).check_structure([shared] * 20)
    cycle: list[Any] = []
    cycle.append(cycle)
    with pytest.raises(walker.InvalidChatRequestError, match="structural limits"):
        walker.CollectedTexts([], []).check_structure(cycle)


def test_child_json_serialization_finishes_before_parent_rebuild() -> None:
    original = {"outer": {"encoded": '{"fixture":"before"}'}}
    holder = [original]
    out = walker.CollectedTexts([], [])

    def string_leaf(container: Any, key: Any, collected: Any, kind: str) -> None:
        text = container[key]
        if text.startswith("{"):
            decoded = [json.loads(text)]
            collected.check_structure(decoded[0])
            walker._collect_json(decoded, 0, collected, kind)
            collected.finalizers.append(lambda: container.__setitem__(key, json.dumps(decoded[0])))
        else:
            collected.slots.append(walker.TextSlot(text, walker._setter(container, key), kind))

    walker._collect_json(holder, 0, out, string_collector=string_leaf)
    for slot in out.slots:
        slot.write("after" if slot.text == "before" else slot.text)
    out.finalize()
    assert json.loads(original["outer"]["encoded"]) == {"fixture": "after"}


@pytest.mark.parametrize(
    "path", ["chat/completions", "responses", "messages", "messages/count_tokens"]
)
def test_raw_json_beyond_decoder_recursion_limit_fails_closed(path: str) -> None:
    upstream = MockUpstream()
    raw = b'{"fixture":' + b"[" * 2_000 + b"0" + b"]" * 2_000 + b"}"
    with TestClient(make_app(upstream)) as client:
        response = client.post(
            f"/v1/{path}", content=raw, headers={"content-type": "application/json"}
        )
    assert response.status_code == 400
    # Some test runners raise Python's recursion limit. Either the decoder refuses the
    # wire body or the iterative structural guard refuses the resulting tree safely.
    assert response.json()["error"]["message"] in {
        "request body is not valid JSON",
        "request JSON exceeds structural limits",
    }
    assert not upstream.requests


def test_endpoint_body_decoder_recursion_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"[" * 2_000 + b"0" + b"]" * 2_000

    def recursion_failure(value: Any) -> None:
        raise RecursionError("synthetic caller detail must stay private")

    monkeypatch.setattr(json, "loads", recursion_failure)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": raw, "more_body": False}

    with pytest.raises(ProjectAccessError, match=r"^Invalid endpoint JSON request$"):
        asyncio.run(_read_endpoint_json_body(receive, SimpleNamespace(), len(raw) + 1))


def _agent_session(rounds: int, tools: int) -> dict[str, Any]:
    """A Claude Code-shaped Messages body: many tool definitions and tool rounds."""
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "A file path"},
            "limit": {"type": "integer", "description": "How many lines"},
        },
        "required": ["path"],
    }
    messages: list[dict[str, Any]] = [{"role": "user", "content": "Fix the failing test."}]
    for i in range(rounds):
        call = f"toolu_{i:05d}"
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Reading the file."},
                    {
                        "type": "tool_use",
                        "id": call,
                        "name": "read",
                        "input": {"path": f"src/module_{i}.py", "limit": 40},
                    },
                ],
            }
        )
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": call,
                        "content": [{"type": "text", "text": f"1|def fixture_{i}():\n2|    pass"}],
                    }
                ],
            }
        )
    return {
        "model": "test-model",
        "max_tokens": 64,
        "system": [{"type": "text", "text": "You are a coding agent."}],
        "tools": [
            {"name": f"tool_{t}", "description": "A tool", "input_schema": schema}
            for t in range(tools)
        ],
        "messages": messages,
    }


def test_long_agent_sessions_fit_the_request_budget() -> None:
    body = _agent_session(rounds=500, tools=25)
    budget = walker._JsonBudget()
    budget.check(body)
    assert budget.nodes > 20_000  # the old budget refused this ordinary session
    forwarded: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        forwarded.append(request.content)
        return httpx.Response(200, json={"type": "message", "role": "assistant", "content": []})

    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
        detection_profile="local-only",
        detectors=("rules",),
    )
    app = make_app(
        transport=httpx.MockTransport(handler),
        settings=settings,
        config=GatewayConfig(mode=Mode.FAST),
    )
    with TestClient(app) as client:
        response = client.post("/v1/messages", json=body)
    assert response.status_code == 200, response.text
    assert len(forwarded) == 1


def test_over_budget_tool_json_does_not_spend_the_request_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(walker, "MAX_TOOL_JSON_NODES", 10)
    out = walker.CollectedTexts([], [])
    holder = [json.dumps([{} for _ in range(20)])]
    walker._collect_tool_output(holder, 0, out)
    assert [slot.kind for slot in out.slots] == ["tool"]
    assert out._json_budget.nodes == 0
