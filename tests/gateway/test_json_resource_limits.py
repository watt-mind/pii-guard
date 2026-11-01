"""Bound JSON work before walking it, and preserve nested masking order (LAB-1759)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from gateway_helpers import MockUpstream, make_app

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
