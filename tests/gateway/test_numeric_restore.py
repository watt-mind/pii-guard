"""A masked JSON number comes back as a JSON number in tool-call arguments (LAB-1361).

LAB-1348 masks ``{"tax_id": 8123456786}`` to the placeholder **string**. When the upstream's
tool call echoes that placeholder as a whole string value, restore writes the original number
literal (``8123456786``, ``8123456786.0`` for a float) instead of ``"8123456786"``, so a tool
whose schema wants an integer accepts it. A placeholder inside a longer string, an object key,
or one that also replaced a whole string stays a string (fail closed). Chat Completions and
Responses, whole and streamed. All values are fictional (ADR 0005).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import TEST_TENANT_KEY, MockUpstream, chunk, completion, make_app
from test_responses import ResponsesUpstream, events_for, response_object, sse

from pii_guard.gateway.restore import RestoreReport, restore_arguments, restore_completion
from pii_guard.gateway.stream import DONE, SseRestorer
from pii_guard.types import EntityType, Span
from pii_guard.vault import (
    PLACEHOLDER_RE,
    SessionNotFoundError,
    UnmaskOutputTooLargeError,
    Vault,
    VaultSession,
)

TAX_ID = 8123456786  # fictional, checksum-valid


def _placeholders(text: str) -> list[str]:
    return [f"[[{t}_{i}]]" for t, i in dict.fromkeys(PLACEHOLDER_RE.findall(text))]


def _echo_arguments(body: dict[str, Any]) -> str:
    """The upstream's tool call: the placeholder as a whole value, a key, and inside text."""
    (ph,) = _placeholders(json.dumps(body))
    return json.dumps({"tax_id": ph, "float_id": ph, "note": f"id {ph}", "by_id": {ph: 1}})


class ChatToolUpstream(MockUpstream):
    """Answers every chat request with one tool call echoing the forwarded placeholder."""

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        arguments = _echo_arguments(body)
        call = {"id": "c2", "type": "function", "function": {"name": "f", "arguments": arguments}}
        if not body.get("stream"):
            return httpx.Response(200, json=completion("", tool_calls=[call]))
        start = {**call, "index": 0, "function": {"name": "f", "arguments": ""}}
        events = [chunk({"role": "assistant", "tool_calls": [start]})]
        events += [
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": arguments[i : i + 5]}}]})
            for i in range(0, len(arguments), 5)
        ]
        events.append(chunk({}, finish="tool_calls"))
        out = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, content=out, headers={"content-type": "text/event-stream"})


class ResponsesToolUpstream(ResponsesUpstream):
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        if request.url.path.endswith("/muse-code/models"):
            return httpx.Response(404)
        arguments = _echo_arguments(body)
        if body.get("stream"):
            content = sse(events_for("ok", arguments))
            return httpx.Response(
                200, content=content, headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(200, json=response_object("ok", arguments))


def _chat_body(args: dict[str, Any], stream: bool) -> dict[str, Any]:
    call = {"id": "c1", "type": "function", "function": {"name": "f", "arguments": args}}
    return {
        "model": "m",
        "stream": stream,
        "messages": [
            {"role": "user", "content": "Ellenőrizd."},
            {"role": "assistant", "content": None, "tool_calls": [call]},
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        ],
    }


def _responses_body(args: dict[str, Any], stream: bool) -> dict[str, Any]:
    return {
        "model": "m",
        "stream": stream,
        "input": [
            {"role": "user", "content": "Ellenőrizd."},
            {
                "type": "function_call",
                "call_id": "c1",
                "name": "f",
                "arguments": json.dumps(args),
            },
            {"type": "function_call_output", "call_id": "c1", "output": "ok"},
        ],
    }


def _chat_arguments(response: httpx.Response, stream: bool) -> str:
    if not stream:
        return response.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    parts = []
    for line in response.text.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            for choice in json.loads(line[6:])["choices"]:
                for call in choice["delta"].get("tool_calls", []):
                    parts.append(call.get("function", {}).get("arguments", ""))
    return "".join(parts)


def _responses_arguments(response: httpx.Response, stream: bool) -> str:
    if not stream:
        return response.json()["output"][2]["arguments"]
    deltas, done = [], None
    for line in response.text.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        event = json.loads(line[6:])
        if event["type"] == "response.function_call_arguments.delta":
            deltas.append(event["delta"])
        elif event["type"] == "response.function_call_arguments.done":
            done = event["arguments"]
    assert "".join(deltas) == done
    return "".join(deltas)


def _call(api: str, args: dict[str, Any], stream: bool) -> dict[str, Any]:
    if api == "chat":
        upstream: MockUpstream = ChatToolUpstream()
        path, body, read = "/v1/chat/completions", _chat_body(args, stream), _chat_arguments
    else:
        upstream = ResponsesToolUpstream()
        path, body, read = "/v1/responses", _responses_body(args, stream), _responses_arguments
    with TestClient(make_app(upstream)) as http:
        response = http.post(path, json=body)
    assert response.status_code == 200, response.text
    assert str(TAX_ID) not in upstream.requests[-1].content.decode()
    restored: dict[str, Any] = json.loads(read(response, stream))
    return restored


@pytest.mark.parametrize("stream", [False, True], ids=["whole", "streamed"])
@pytest.mark.parametrize("api", ["chat", "responses"])
def test_a_whole_value_placeholder_of_a_masked_number_restores_as_that_number(
    api: str, stream: bool
) -> None:
    restored = _call(api, {"tax_id": TAX_ID}, stream)
    for key in ("tax_id", "float_id"):
        assert restored[key] == TAX_ID and type(restored[key]) is int
    assert restored["note"] == f"id {TAX_ID}"  # inside a longer string: stays a string
    assert restored["by_id"] == {str(TAX_ID): 1}  # an object key can't be a number


@pytest.mark.parametrize("stream", [False, True], ids=["whole", "streamed"])
@pytest.mark.parametrize("api", ["chat", "responses"])
def test_a_float_number_restores_as_the_float_literal(api: str, stream: bool) -> None:
    args = {"float_id": float(TAX_ID)}
    restored = _call(api, args, stream)
    assert restored["tax_id"] == float(TAX_ID) and type(restored["tax_id"]) is float


@pytest.mark.parametrize("stream", [False, True], ids=["whole", "streamed"])
@pytest.mark.parametrize("api", ["chat", "responses"])
@pytest.mark.parametrize("other", [str(TAX_ID), float(TAX_ID)], ids=["string", "float"])
def test_a_value_also_sent_in_another_type_restores_as_a_string(
    api: str, stream: bool, other: Any
) -> None:
    restored = _call(api, {"tax_id": TAX_ID, "copy": other}, stream)
    assert restored["tax_id"] == str(TAX_ID)


# --- units ------------------------------------------------------------------------------


def _session(**extra: Any) -> VaultSession:
    return Vault(bytes.fromhex(TEST_TENANT_KEY), **extra).session()


def _masked_number(session: VaultSession, literal: str = str(TAX_ID)) -> str:
    text = str(TAX_ID)
    placeholder = session.mask(
        text, [Span(0, len(text), EntityType.NATIONAL_ID_HU_TAX, text, 1.0, "test")]
    )
    session.note_json_leaf(placeholder, (text, literal))
    return placeholder


def test_the_vault_ignores_a_placeholder_it_did_not_issue() -> None:
    session = _session()
    session.note_json_leaf("[[NATIONAL_ID_HU_TAX_abcdef]]", (str(TAX_ID), str(TAX_ID)))
    assert session.json_number("[[NATIONAL_ID_HU_TAX_abcdef]]") is None


def test_a_string_note_makes_the_placeholder_a_string_for_good() -> None:
    session = _session()
    ph = _masked_number(session)
    assert session.json_number(ph) == (str(TAX_ID), str(TAX_ID))
    session.note_json_leaf(ph, None)
    session.note_json_leaf(ph, (str(TAX_ID), str(TAX_ID)))
    assert session.json_number(ph) is None


def test_a_closed_session_answers_no_lookup() -> None:
    session = _session()
    ph = _masked_number(session)
    session.close()
    with pytest.raises(SessionNotFoundError):
        session.json_number(ph)


@pytest.mark.parametrize(
    "template",
    [
        '{"a": "PH"}',
        '{"a": ["PH", "PH"]}',
        '["PH"]',
        '{"a": "PH" , "b": 1}',
    ],
)
def test_whole_value_placeholders_become_numbers(template: str) -> None:
    session = _session()
    ph = _masked_number(session)
    out = restore_arguments(session, template.replace("PH", ph), RestoreReport())
    assert out == template.replace('"PH"', str(TAX_ID))


@pytest.mark.parametrize(
    "template",
    [
        '{"a": "x PH"}',
        '{"a": "PHs"}',
        '{"PH": 1}',
        '{"a": "\\"PH\\""}',  # inside a string, between escaped quotes
        "not json PH",
    ],
)
def test_other_placeholders_stay_strings(template: str) -> None:
    session = _session()
    ph = _masked_number(session)
    out = restore_arguments(session, template.replace("PH", ph), RestoreReport())
    assert out == template.replace("PH", str(TAX_ID))


def test_a_restored_number_is_charged_to_the_budget() -> None:
    session = _session(max_restored_chars=5)
    ph = _masked_number(session)
    with pytest.raises(UnmaskOutputTooLargeError):
        restore_arguments(session, json.dumps({"a": ph}), RestoreReport())


def _streamed(session: VaultSession, pieces: list[str]) -> str:
    start = {"index": 0, "id": "c", "type": "function", "function": {"name": "f", "arguments": ""}}
    payloads = [chunk({"tool_calls": [start]})]
    payloads += [
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": p}}]}) for p in pieces
    ]
    payloads.append(chunk({}, finish="tool_calls"))
    restorer = SseRestorer(session)
    out: list[str] = []
    for payload in payloads:
        out += restorer.process(json.dumps(payload))
    out += restorer.process(DONE)
    return "".join(
        call.get("function", {}).get("arguments", "")
        for item in out
        if item != DONE
        for choice in json.loads(item).get("choices", [])
        for call in choice["delta"].get("tool_calls", [])
    )


def test_a_streamed_whole_value_placeholder_split_anywhere_matches_the_whole_restore() -> None:
    session = _session()
    ph = _masked_number(session)
    arguments = json.dumps({"a": ph, "b": f'"{ph}"', "c": [ph]})
    whole = completion(
        "", tool_calls=[{"type": "function", "function": {"name": "f", "arguments": arguments}}]
    )
    restore_completion(session, whole)
    expected = whole["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(expected) == {"a": TAX_ID, "b": f'"{TAX_ID}"', "c": [TAX_ID]}
    for cut in range(len(arguments) + 1):
        assert _streamed(session, [arguments[:cut], arguments[cut:]]) == expected, cut
    assert _streamed(session, list(arguments)) == expected
