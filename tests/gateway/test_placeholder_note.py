"""The placeholder note the gateway adds to requests that carry placeholders (LAB-1471)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import (
    NOTE_MESSAGE,
    MockUpstream,
    completion,
    conversation_turn_one,
    leaked_values,
    make_app,
)

from pii_guard.gateway import GatewayConfig, Mode
from pii_guard.gateway.placeholder_note import (
    NOTE_HEADER,
    PLACEHOLDER_NOTE,
    add_chat_note,
    add_responses_note,
)
from pii_guard.vault import PLACEHOLDER_RE, Vault
from pii_guard.vault.placeholders import is_placeholder_prefix

RESPONSE = {
    "id": "resp_1",
    "object": "response",
    "status": "completed",
    "model": "m",
    "output": [
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "Kész.", "annotations": []}],
        }
    ],
    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
}


def _chat(upstream: MockUpstream, messages: list[dict[str, Any]], **kw: Any) -> httpx.Response:
    with TestClient(make_app(upstream, **kw)) as http:
        return http.post("/v1/chat/completions", json={"model": "m", "messages": messages})


def _responses(body: dict[str, Any], **kw: Any) -> tuple[httpx.Response, list[dict[str, Any]]]:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=RESPONSE)

    app = make_app(MockUpstream(), **kw)
    app.state.gateway_transport = httpx.MockTransport(handler)
    with TestClient(app) as http:
        return http.post("/v1/responses", json={"model": "m", **body}), seen


# --- The note itself ------------------------------------------------------------------------


def test_note_holds_no_placeholder_and_restores_to_itself() -> None:
    """A model quoting the note back produces nothing the restorer would touch or hold back."""
    assert PLACEHOLDER_RE.search(PLACEHOLDER_NOTE) is None
    assert "[[" in PLACEHOLDER_NOTE  # it does show the shape
    session = Vault(b"k" * 32).session()
    session.mask("Teszt Elek, teszt.elek@example.com", [])
    assert session.unmask_with_report(PLACEHOLDER_NOTE).text == PLACEHOLDER_NOTE
    start = PLACEHOLDER_NOTE.index("[[")
    # "[[TYPE_id]]" can't grow into a placeholder: lower-case "id" stops the prefix.
    assert not is_placeholder_prefix(PLACEHOLDER_NOTE[start : start + len("[[TYPE_id")])


def test_add_chat_note_prepends_one_system_message() -> None:
    body: dict[str, Any] = {"messages": [{"role": "user", "content": "x"}]}
    add_chat_note(body)
    assert body["messages"] == [NOTE_MESSAGE, {"role": "user", "content": "x"}]


@pytest.mark.parametrize(
    ("instructions", "expected"),
    [
        (None, PLACEHOLDER_NOTE),
        ("", PLACEHOLDER_NOTE),
        ("Be brief.", f"{PLACEHOLDER_NOTE}\n\nBe brief."),
    ],
)
def test_add_responses_note_leads_the_instructions(instructions: str | None, expected: str) -> None:
    body: dict[str, Any] = {"input": "x"}
    if instructions is not None:
        body["instructions"] = instructions
    add_responses_note(body)
    assert body == {"input": "x", "instructions": expected}


# --- Chat Completions -----------------------------------------------------------------------


def test_chat_request_with_placeholders_gets_the_note_first() -> None:
    upstream = MockUpstream()
    response = _chat(upstream, conversation_turn_one())
    assert response.status_code == 200
    assert response.headers[NOTE_HEADER] == "added"
    raw = upstream.raw_bodies[0]
    assert raw["messages"][0] == NOTE_MESSAGE
    # Everything after it is what the client sent, masked, in its order and roles.
    assert [m["role"] for m in raw["messages"][1:]] == ["system", "user"]
    assert raw["messages"][1:] == upstream.bodies[0]["messages"]
    assert leaked_values(upstream.requests[0].content) == []
    # The restored answer is unaffected.
    assert "Teszt Elek" in response.json()["choices"][0]["message"]["content"]


def test_chat_request_without_personal_data_is_forwarded_as_sent() -> None:
    upstream = MockUpstream()
    messages = [{"role": "user", "content": "Mennyi kettő meg kettő?"}]
    response = _chat(upstream, messages)
    assert NOTE_HEADER not in response.headers
    assert upstream.raw_bodies[0]["messages"] == messages


def test_placeholder_shaped_text_the_session_did_not_issue_gets_no_note() -> None:
    """A client's own ``[[EMAIL_abcd]]`` isn't a placeholder this gateway can restore."""
    upstream = MockUpstream()
    messages = [{"role": "user", "content": "Mit jelent az, hogy [[EMAIL_abcd]]?"}]
    response = _chat(upstream, messages)
    assert response.status_code == 200
    assert NOTE_HEADER not in response.headers
    assert upstream.raw_bodies[0]["messages"] == messages


def test_note_can_be_turned_off() -> None:
    upstream = MockUpstream()
    config = GatewayConfig(mode=Mode.AUDIT, placeholder_note=False)
    response = _chat(upstream, conversation_turn_one(), config=config)
    assert NOTE_HEADER not in response.headers
    assert upstream.raw_bodies[0]["messages"][0]["role"] == "system"
    assert upstream.raw_bodies[0]["messages"][0] != NOTE_MESSAGE
    assert len(upstream.raw_bodies[0]["messages"]) == 2


def test_note_is_off_by_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_GATEWAY_PLACEHOLDER_NOTE", "false")
    assert GatewayConfig().placeholder_note is False
    monkeypatch.delenv("PII_GUARD_GATEWAY_PLACEHOLDER_NOTE")
    assert GatewayConfig().placeholder_note is True


def test_streamed_chat_request_gets_the_note_too() -> None:
    upstream = MockUpstream(stream_chunks=lambda t: [t[i : i + 3] for i in range(0, len(t), 3)])
    with TestClient(make_app(upstream)) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one(), "stream": True},
        )
    assert response.headers[NOTE_HEADER] == "added"
    assert upstream.raw_bodies[0]["messages"][0] == NOTE_MESSAGE
    assert "Teszt Elek" in response.text


def test_echo_reports_the_note_as_a_flag_not_a_message() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one()},
            headers={"X-PII-Guard-Echo": "masked"},
        )
    echo = response.json()["pii_guard"]
    assert echo["placeholder_note"] is True
    assert [m["role"] for m in echo["masked_messages"]] == ["system", "user"]
    assert echo["masked_messages"][0]["content"] != PLACEHOLDER_NOTE


def test_chat_tool_call_arguments_still_restore_with_the_note() -> None:
    upstream = MockUpstream()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        upstream.requests.append(request)
        body = json.loads(request.content)
        assert body["messages"][0] == NOTE_MESSAGE
        token = PLACEHOLDER_RE.search(body["messages"][2]["content"]).group(0)
        seen.append(token)
        args = json.dumps({"path": "contacts.json", "content": token})
        calls = [{"id": "c1", "type": "function", "function": {"name": "write", "arguments": args}}]
        return httpx.Response(200, json=completion("", tool_calls=calls))

    app = make_app(upstream)
    app.state.gateway_transport = httpx.MockTransport(handler)
    with TestClient(app) as http:
        result = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": conversation_turn_one()}
        ).json()
    args = json.loads(result["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
    assert PLACEHOLDER_RE.search(args["content"]) is None
    assert args["content"] in json.dumps(conversation_turn_one(), ensure_ascii=False)


# --- Responses ------------------------------------------------------------------------------


def test_responses_request_gets_the_note_ahead_of_its_instructions() -> None:
    response, seen = _responses(
        {"instructions": "Be brief.", "input": "Írj Teszt Eleknek: teszt.elek@example.com"}
    )
    assert response.status_code == 200
    assert response.headers[NOTE_HEADER] == "added"
    assert seen[0]["instructions"] == f"{PLACEHOLDER_NOTE}\n\nBe brief."
    assert PLACEHOLDER_RE.search(seen[0]["input"])
    assert "teszt.elek@example.com" not in json.dumps(seen[0])


def test_responses_request_without_instructions_gets_the_note_as_instructions() -> None:
    _, seen = _responses({"input": "Írj Teszt Eleknek: teszt.elek@example.com"})
    assert seen[0]["instructions"] == PLACEHOLDER_NOTE


def test_responses_request_without_personal_data_is_forwarded_as_sent() -> None:
    response, seen = _responses({"instructions": "Be brief.", "input": "Mennyi 2+2?"})
    assert NOTE_HEADER not in response.headers
    assert seen[0]["instructions"] == "Be brief."


def test_responses_note_can_be_turned_off() -> None:
    config = GatewayConfig(mode=Mode.AUDIT, placeholder_note=False)
    _, seen = _responses({"input": "Írj: teszt.elek@example.com"}, config=config)
    assert "instructions" not in seen[0]
