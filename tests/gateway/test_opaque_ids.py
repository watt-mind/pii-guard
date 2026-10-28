"""Opaque ids in identifier fields are forwarded as sent, not refused (LAB-1469).

Live with pi 1.3.0 and Muse Code 1.4.14 against the Meta Model API: the upstream mints call ids
such as ``call_01a1849936ef77df938b17792f84e7f8``, the NER encoder read that one as a PHONE
(about one random call id in eight), and the next turn, which sends the id back in
``tool_calls[].id`` / ``tool_call_id`` (Chat Completions) or ``call_id`` (Responses), was
refused as "personal data detected in an identifier". The fake detector here flags the id the
way the NER did. An id the upstream did not issue in this session is still checked (fail
closed). Codex 0.163.0 mints its own message ids (``msg_<uuid>``), refused on the first request:
those are hex tokens, where NER hits are dropped. All values are fictional (ADR 0005).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient
from gateway_helpers import NAMES, FakeLlm, MockUpstream, chunk, completion, make_app
from test_responses import ResponsesUpstream, events_for, muse_body, sse

from pii_guard.config import Settings
from pii_guard.detect.stack import build_detectors
from pii_guard.gateway import GatewayConfig, Mode, build_mode_detectors
from pii_guard.gateway.opaque_ids import IssuedIds, is_opaque_token, upstream_ids

#: A real upstream call id the NER encoder read as a PHONE (an opaque token, not personal data).
CALL_ID = "call_01a1849936ef77df938b17792f84e7f8"
PERSON = NAMES[0]  # Teszt Elek
SESSION = "X-PII-Guard-Session"
#: A session that never saw the upstream's answer (a base-URL session, LAB-1286).
OTHER = "/s/c_5f0c3a9e1b7d4f2a8c6e0b9d3a1f7e2c"


def llm() -> FakeLlm:
    return FakeLlm((PERSON, CALL_ID))


def tool_call(arguments: str = '{"path": "contacts.json"}') -> dict[str, Any]:
    return {
        "id": CALL_ID,
        "type": "function",
        "function": {"name": "read", "arguments": arguments},
    }


class ToolCallUpstream(MockUpstream):
    """Answers the first request with a tool call (streamed or not), later ones with text."""

    def handler(self, request: Any) -> Any:  # type: ignore[override]
        import httpx

        self.requests.append(request)
        body = json.loads(request.content)
        if len(self.requests) > 1:
            return httpx.Response(200, json=completion("Done.", model=body["model"]))
        if not body.get("stream"):
            return httpx.Response(200, json=completion("", tool_calls=[tool_call()]))
        call = {**tool_call(), "index": 0}
        call["function"] = {"name": "read", "arguments": ""}
        events = [
            chunk({"role": "assistant", "content": None, "tool_calls": [call]}),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"path": "a"}'}}]}),
            chunk({}, finish="tool_calls"),
        ]
        raw = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, content=raw, headers={"content-type": "text/event-stream"})


def chat_messages(with_call: bool) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a coding agent."},
        {"role": "user", "content": f"Read contacts.json for {PERSON}."},
    ]
    if with_call:
        messages += [
            {"role": "assistant", "content": None, "tool_calls": [tool_call()]},
            {"role": "tool", "tool_call_id": CALL_ID, "content": f"{PERSON}: ok"},
        ]
    return messages


def run_chat(stream: bool) -> tuple[ToolCallUpstream, Any, Any]:
    upstream = ToolCallUpstream()
    with TestClient(make_app(upstream, llm=llm())) as client:
        first = client.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": chat_messages(False), "stream": stream},
        )
        assert first.status_code == 200, first.text
        session = first.headers[SESSION]
        second = client.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": chat_messages(True)},
            headers={SESSION: session},
        )
        # Another session never saw the id: it is checked, and refused, as before.
        other = client.post(
            OTHER + "/v1/chat/completions", json={"model": "m", "messages": chat_messages(True)}
        )
    return upstream, second, other


def test_chat_streamed_tool_call_id_comes_back_unchanged() -> None:
    upstream, second, other = run_chat(stream=True)
    assert second.status_code == 200, second.text
    sent = upstream.bodies[1]["messages"]
    assert sent[2]["tool_calls"][0]["id"] == CALL_ID
    assert sent[3]["tool_call_id"] == CALL_ID
    assert PERSON not in json.dumps(sent, ensure_ascii=False)  # the rest is still masked
    assert other.status_code == 400
    assert other.json()["error"]["code"] == "unsupported_content"
    assert len(upstream.requests) == 2  # the refused request never reached the upstream


def test_chat_non_streamed_tool_call_id_comes_back_unchanged() -> None:
    upstream, second, other = run_chat(stream=False)
    assert second.status_code == 200, second.text
    assert upstream.bodies[1]["messages"][3]["tool_call_id"] == CALL_ID
    assert other.status_code == 400


def responses_events(body: dict[str, Any]) -> bytes:
    events = events_for("Reading it.", json.dumps({"path": "reply.md"}))
    for event in events:
        for holder in (event.get("item"), *((event.get("response") or {}).get("output") or [])):
            if isinstance(holder, dict) and holder.get("type") == "function_call":
                holder["call_id"] = CALL_ID
    return sse(events)


def responses_history() -> dict[str, Any]:
    body = muse_body(stream=True)
    for item in body["input"]:
        if item.get("call_id") == "call_1":
            item["call_id"] = CALL_ID
    return body


def test_responses_streamed_call_id_comes_back_unchanged() -> None:
    upstream = ResponsesUpstream(responses_events)
    with TestClient(make_app(upstream, llm=llm())) as client:
        first = client.post(
            "/v1/responses", json=muse_body(stream=True, input=muse_body()["input"][:2])
        )
        assert first.status_code == 200, first.text
        assert CALL_ID in first.text
        session = first.headers[SESSION]
        second = client.post("/v1/responses", json=responses_history(), headers={SESSION: session})
        other = client.post(OTHER + "/v1/responses", json=responses_history())
    assert second.status_code == 200, second.text
    calls = [i for i in upstream.bodies[1]["input"] if "call_id" in i]
    assert {i["call_id"] for i in calls} == {CALL_ID}
    assert other.status_code == 400
    assert "call_id" in other.json()["error"]["message"]


def test_upstream_ids_skips_text_and_placeholders() -> None:
    payload = {
        "id": "resp_1",
        "output": [
            {"id": "fc_2", "call_id": CALL_ID, "arguments": '{"id": "not-walked"}'},
            {"id": "has space"},
            {"id": "[[PERSON_1a2b3c]]"},
            {"id": "x" * 300},
        ],
    }
    assert sorted(upstream_ids(payload)) == sorted(["resp_1", "fc_2", CALL_ID])


def test_issued_ids_are_bounded_per_session_and_by_sessions() -> None:
    store = IssuedIds(max_sessions=2, max_ids=2)
    store.add("s1", ["a", "b", "c"])
    assert store.of("s1") == {"b", "c"}
    store.add("s2", ["x"])
    store.add("s3", ["y"])
    assert store.of("s1") == frozenset()  # least recently used session evicted
    assert store.of("s3") == {"y"}


#: A Codex 0.163.0 client message id the NER encoder read as a PHONE.
MESSAGE_ID = "msg_01a184b6-8156-7cc2-b584-a0fb83dedf84"


class FakeNer(FakeLlm):
    """Stands in for the NER encoder (``ner``): flags the person, the id and a word id."""

    name = "ner"
    model = "fake-ner"


def fast_app(upstream: MockUpstream, flagged: tuple[str, ...]) -> Any:
    app = make_app(upstream, config=GatewayConfig(mode=Mode.FAST))
    settings: Settings = app.state.settings
    base = [*build_detectors(["rules"], settings), FakeNer(flagged)]
    app.state.gateway_detectors = build_mode_detectors(
        settings, GatewayConfig(mode=Mode.FAST), base=base, llm_detector=FakeLlm()
    )
    return app


def codex_body(message_id: str) -> dict[str, Any]:
    body = muse_body(stream=True)
    body["input"] = [
        {"type": "message", "id": message_id, "role": "user", "content": f"Hi, I am {PERSON}."}
    ]
    return body


def test_codex_message_id_is_not_read_as_a_phone() -> None:
    upstream = ResponsesUpstream()
    with TestClient(fast_app(upstream, (PERSON, MESSAGE_ID, "Elek-Teszt"))) as client:
        ok = client.post("/v1/responses", json=codex_body(MESSAGE_ID))
        # A word id is no hex token: the NER hit still refuses it (fail closed).
        refused = client.post("/v1/responses", json=codex_body("Elek-Teszt"))
    assert ok.status_code == 200, ok.text
    sent = upstream.bodies[0]["input"][0]
    assert sent["id"] == MESSAGE_ID
    assert PERSON not in json.dumps(sent, ensure_ascii=False)
    assert refused.status_code == 400
    assert len(upstream.requests) == 1


def test_opaque_tokens() -> None:
    tokens = (MESSAGE_ID, CALL_ID, "fc_68a1b2c3d4e5f60718293a4b", "0123456789abcdef")
    for token in (*tokens, "-9007199254740991", "1.5e10"):
        assert is_opaque_token(token), token
    for text in ("call_1", "msg_Jane", "Teszt Elek", "+36 30 123 4567", "x_0123456789abcde"):
        assert not is_opaque_token(text), text


#: OpenCode 1.18.26's ``read`` tool: zod writes Number.MAX_SAFE_INTEGER as the bounds.
OPENCODE_READ_TOOL = {
    "type": "function",
    "function": {
        "name": "read",
        "description": "Read a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "filePath": {"type": "string"},
                "offset": {"type": "number", "minimum": 0, "maximum": 9007199254740991},
                "limit": {"type": "number", "minimum": -9007199254740991, "exclusiveMinimum": 0},
            },
            "required": ["filePath"],
        },
    },
}


def test_schema_bounds_are_not_read_as_bank_accounts() -> None:
    upstream = MockUpstream()
    flagged = ("9007199254740991", "-9007199254740991", PERSON)
    body = {
        "model": "m",
        "messages": [{"role": "user", "content": f"Read the letter from {PERSON}."}],
        "tools": [OPENCODE_READ_TOOL],
    }
    with TestClient(fast_app(upstream, flagged)) as client:
        response = client.post("/v1/chat/completions", json=body)
    assert response.status_code == 200, response.text
    sent = upstream.bodies[0]
    assert sent["tools"] == [OPENCODE_READ_TOOL]
    assert PERSON not in json.dumps(sent["messages"], ensure_ascii=False)
