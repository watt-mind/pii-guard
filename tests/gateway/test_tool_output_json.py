"""Structured tool-result text is decoded and masked before forwarding (LAB-1755)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import TEST_TENANT_KEY, UPSTREAM_KEY, UPSTREAM_URL, make_app

from pii_guard.config import Settings
from pii_guard.gateway import GatewayConfig, Mode
from pii_guard.gateway import request as walker
from pii_guard.vault import PLACEHOLDER_RE

NAME = "Gyakorló Tihamér"  # Fictional.
NUMBER = 123456789
CASES = (
    "chat-string",
    "chat-function",
    "chat-part",
    "responses-string",
    "responses-custom",
    "responses-part",
    "messages-string",
    "messages-part",
    "messages-count",
)


def payload(case: str, text: str) -> tuple[str, dict[str, Any]]:
    result: dict[str, Any] = {"model": "test-model"}
    if case.startswith("chat"):
        content: Any = [{"type": "text", "text": text}] if case.endswith("part") else text
        message = {"role": "tool", "tool_call_id": "call_test", "content": content}
        if case == "chat-function":
            message = {"role": "function", "name": "lookup", "content": content}
        result["messages"] = [message]
        return "/v1/chat/completions", result
    if case.startswith("responses"):
        output: Any = [{"type": "input_text", "text": text}] if case.endswith("part") else text
        kind = "custom_tool_call_output" if case.endswith("custom") else "function_call_output"
        result["input"] = [{"type": kind, "call_id": "call_test", "output": output}]
        return "/v1/responses", result
    content = [{"type": "text", "text": text}] if case.endswith("part") else text
    result.update(
        max_tokens=64,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "call_test", "content": content}
                ],
            }
        ],
    )
    path = "/v1/messages/count_tokens" if case.endswith("count") else "/v1/messages"
    return path, result


def output_of(case: str, body: dict[str, Any]) -> str:
    if case.startswith("chat"):
        value = body["messages"][-1]["content"]
    elif case.startswith("responses"):
        value = body["input"][0]["output"]
    else:
        value = body["messages"][-1]["content"][0]["content"]
    return value[0]["text"] if isinstance(value, list) else value


def client_for(policy: str = "mask") -> tuple[TestClient, list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 1})
        if request.url.path.endswith("responses"):
            return httpx.Response(200, json={"object": "response", "output": []})
        if request.url.path.endswith("messages"):
            return httpx.Response(200, json={"type": "message", "content": []})
        return httpx.Response(
            200, json={"choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}}]}
        )

    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
        detection_profile="local-only",
        detectors=("rules",),
        policy_overrides=f"PERSON={policy}",
    )
    app = make_app(
        transport=httpx.MockTransport(handler),
        settings=settings,
        config=GatewayConfig(mode=Mode.FAST),
    )
    return TestClient(app), requests


def known_session(client: TestClient) -> dict[str, str]:
    created = client.post(
        "/v1/sessions",
        json={
            "known_values": [
                {"value": NAME, "entity_type": "PERSON"},
                {"value": str(NUMBER), "entity_type": "ID_DOCUMENT"},
            ]
        },
    )
    assert created.status_code == 201, created.text
    return {"X-PII-Guard-Session": created.json()["session_id"]}


@pytest.mark.parametrize("case", CASES)
def test_json_unicode_escapes_cannot_bypass_known_block_policy(case: str) -> None:
    client, forwarded = client_for("block")
    with client:
        headers = known_session(client)
        for text in (NAME, json.dumps({"name": NAME})):
            path, body = payload(case, text)
            response = client.post(path, json=body, headers=headers)
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "blocked_entity"
            assert NAME not in response.text
    assert not forwarded


@pytest.mark.parametrize("case", CASES)
def test_json_keys_values_numbers_and_structure_are_preserved_safely(case: str) -> None:
    client, forwarded = client_for()
    original = {
        "record": {NAME: {"name": NAME, "numbers": [NUMBER, 7], "flag": True}},
        "items": [None, "safe"],
    }
    with client:
        path, body = payload(case, json.dumps(original))
        response = client.post(path, json=body, headers=known_session(client))
        assert response.status_code == 200, response.text
        assert response.headers["X-PII-Guard-Outbound-Check"] == "passed"
    masked = json.loads(output_of(case, forwarded[0]))
    key = next(iter(masked["record"]))
    assert PLACEHOLDER_RE.fullmatch(key)
    record = masked["record"][key]
    assert PLACEHOLDER_RE.fullmatch(record["name"])
    assert PLACEHOLDER_RE.fullmatch(record["numbers"][0])
    assert record["numbers"][1] == 7
    assert record["flag"] is True
    assert masked["items"] == [None, "safe"]
    assert NAME not in json.dumps(masked, ensure_ascii=False)


@pytest.mark.parametrize("case", CASES)
def test_plain_text_and_line_number_gutters_keep_their_shape(case: str) -> None:
    client, forwarded = client_for()
    with client:
        text = "12|first safe line\n13|second safe line"
        path, body = payload(case, text)
        response = client.post(path, json=body)
        assert response.status_code == 200, response.text
    assert output_of(case, forwarded[0]) == text


@pytest.mark.parametrize("case", ["chat-string", "responses-part", "messages-part"])
def test_nested_json_string_layers_are_masked_before_reserialization(case: str) -> None:
    client, forwarded = client_for()
    text = json.dumps({"embedded": json.dumps({"name": NAME, "number": NUMBER})})
    with client:
        path, body = payload(case, text)
        response = client.post(path, json=body, headers=known_session(client))
        assert response.status_code == 200, response.text
    decoded = json.loads(json.loads(output_of(case, forwarded[0]))["embedded"])
    assert PLACEHOLDER_RE.fullmatch(decoded["name"])
    assert PLACEHOLDER_RE.fullmatch(decoded["number"])


@pytest.mark.parametrize("case", ["chat-string", "responses-string", "messages-string"])
def test_tool_json_layer_limit_fails_closed(case: str) -> None:
    text = json.dumps({"name": NAME})
    for _ in range(walker.MAX_TOOL_JSON_LAYERS):
        text = json.dumps(text)
    client, forwarded = client_for()
    with client:
        path, body = payload(case, text)
        response = client.post(path, json=body)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_request"
    assert not forwarded


@pytest.mark.parametrize("case", ["chat-string", "responses-string", "messages-string"])
@pytest.mark.parametrize("limit", ["size", "depth", "nodes"])
def test_over_budget_tool_json_is_masked_as_plain_text(
    case: str, limit: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Over its own budget, a tool JSON text is detected as one text slot (LAB-1759): never
    # a 400 that breaks the agent session, and never forwarded unmasked.
    if limit == "size":
        monkeypatch.setattr(walker, "MAX_TOOL_JSON_CHARS", 16)
        text = json.dumps({"value": "x" * 32, "name": NAME}, ensure_ascii=False)
    elif limit == "depth":
        text = "[" * 80 + json.dumps(NAME, ensure_ascii=False) + "]" * 80
    else:
        monkeypatch.setattr(walker, "MAX_TOOL_JSON_NODES", 40)
        text = json.dumps([{"id": i, "name": NAME} for i in range(20)], ensure_ascii=False)
    client, forwarded = client_for()
    with client:
        path, body = payload(case, text)
        response = client.post(path, json=body, headers=known_session(client))
        assert response.status_code == 200, response.text
        assert response.headers["X-PII-Guard-Outbound-Check"] == "passed"
    sent = output_of(case, forwarded[0])
    assert NAME not in sent
    assert PLACEHOLDER_RE.search(sent)
    assert sent.count("[") >= text.count("[")  # shape kept: one masked text, not re-encoded


@pytest.mark.parametrize("case", ["chat-string", "responses-string", "messages-string"])
@pytest.mark.parametrize("shape", ["string", "array"])
def test_json_root_strings_and_arrays_remain_valid_json(case: str, shape: str) -> None:
    client, forwarded = client_for()
    original: Any = NAME if shape == "string" else [NAME, {"number": NUMBER}, 7]
    with client:
        path, body = payload(case, json.dumps(original))
        response = client.post(path, json=body, headers=known_session(client))
        assert response.status_code == 200, response.text
    masked = json.loads(output_of(case, forwarded[0]))
    if shape == "string":
        assert PLACEHOLDER_RE.fullmatch(masked)
    else:
        assert PLACEHOLDER_RE.fullmatch(masked[0])
        assert PLACEHOLDER_RE.fullmatch(masked[1]["number"])
        assert masked[2] == 7


def _echo_answer(path: str, text: str) -> dict[str, Any]:
    if path.endswith("responses"):
        return {
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
        }
    if path.endswith("messages"):
        return {"type": "message", "role": "assistant", "content": [{"type": "text", "text": text}]}
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": text}}]}


def _answer_text(case: str, body: dict[str, Any]) -> str:
    if case.startswith("responses"):
        return body["output"][0]["content"][0]["text"]
    if case.startswith("messages"):
        return body["content"][0]["text"]
    return body["choices"][0]["message"]["content"]


@pytest.mark.parametrize("case", ["chat-string", "responses-string", "messages-string"])
@pytest.mark.parametrize("surrogate", ["\ud83d", "\udc00"])
def test_lone_surrogates_in_tool_json_are_masked_and_restored(case: str, surrogate: str) -> None:
    forwarded: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        forwarded.append(body)
        tokens = PLACEHOLDER_RE.findall(json.dumps(body))
        echo = " ".join(f"[[{kind}_{tag}]]" for kind, tag in tokens)
        return httpx.Response(200, json=_echo_answer(request.url.path, f"Saw {echo}."))

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
    email = "fixture.user@example.com"
    # A tool output truncated mid-emoji: valid JSON, but its decoded string is not UTF-8.
    text = json.dumps({"note": surrogate + " truncated", "mail": email})
    path, body = payload(case, text)
    with TestClient(app) as client:
        response = client.post(
            path, content=json.dumps(body).encode(), headers={"content-type": "application/json"}
        )
    assert response.status_code == 200, response.text
    sent = json.loads(output_of(case, forwarded[0]))
    assert sent["note"] == surrogate + " truncated"
    assert PLACEHOLDER_RE.fullmatch(sent["mail"])
    assert email not in json.dumps(forwarded[0])
    assert _answer_text(case, response.json()) == f"Saw {email}."
