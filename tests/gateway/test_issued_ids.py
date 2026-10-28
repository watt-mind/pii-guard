"""Upstream-issued ids are forwarded as sent when the client sends them back (LAB-1469).

Live with pi 1.3.0 and Muse Code 1.4.14 against the Meta Model API: the upstream mints call ids
such as ``call_01a1849936ef77df938b17792f84e7f8``, the NER encoder read that one as a PHONE
(about one random call id in eight), and the next turn, which sends the id back in
``tool_calls[].id`` / ``tool_call_id`` (Chat Completions) or ``call_id`` (Responses), was
refused as "personal data detected in an identifier". The fake detector here flags the id the
way the NER did. An id the upstream did not issue in this session is still checked (fail
closed). All values are fictional (ADR 0005).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient
from gateway_helpers import NAMES, FakeLlm, MockUpstream, chunk, completion, make_app
from test_responses import ResponsesUpstream, events_for, muse_body, sse

from pii_guard.gateway.issued_ids import IssuedIds, upstream_ids

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
