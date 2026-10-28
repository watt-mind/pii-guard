"""Numbers in JSON are detected and masked like strings (LAB-1348).

The JSON walker used to make slots for strings only, so ``{"tax_id": 8123456786}`` in tool-call
arguments went upstream unchanged while the same value as a string was masked. A masked number
becomes the placeholder string; every other number keeps its type and value. All values are
fictional (ADR 0005).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from gateway_helpers import MockUpstream, make_app
from test_responses import ResponsesUpstream

from pii_guard.gateway.request import UnsupportedContentError, collect_texts
from pii_guard.vault import PLACEHOLDER_RE

TAX_ID = 8123456786  # fictional, checksum-valid
TAJ = 123456788  # fictional, checksum-valid
PLAIN = {"count": 3, "ratio": 0.25, "flag": True, "big": 1_800_000_000, "none": None}


def arguments() -> dict[str, Any]:
    return {"tax_id": TAX_ID, "ids": [TAJ, 42], "float_id": float(TAX_ID), **PLAIN}


def chat(args: Any) -> dict[str, Any]:
    call = {"id": "c1", "type": "function", "function": {"name": "lookup", "arguments": args}}
    return {
        "model": "m",
        "messages": [
            {"role": "user", "content": "Ellenőrizd az adószámot."},
            {"role": "assistant", "content": None, "tool_calls": [call]},
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        ],
    }


def assert_masked(forwarded: dict[str, Any], raw: bytes) -> None:
    assert str(TAX_ID) not in raw.decode()
    assert str(TAJ) not in raw.decode()
    for key in ("tax_id", "float_id"):
        assert isinstance(forwarded[key], str) and PLACEHOLDER_RE.fullmatch(forwarded[key])
    assert PLACEHOLDER_RE.fullmatch(forwarded["ids"][0])
    assert forwarded["ids"][1] == 42
    for key, value in PLAIN.items():
        assert forwarded[key] == value and type(forwarded[key]) is type(value)


@pytest.mark.parametrize("as_string", [True, False])
def test_numbers_in_chat_tool_call_arguments_are_masked(as_string: bool) -> None:
    upstream = MockUpstream()
    args = json.dumps(arguments()) if as_string else arguments()
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/chat/completions", json=chat(args))
    assert response.status_code == 200, response.text
    sent = upstream.bodies[0]["messages"][1]["tool_calls"][0]["function"]["arguments"]
    assert_masked(json.loads(sent) if as_string else sent, upstream.requests[0].content)


def test_numbers_in_responses_function_call_arguments_are_masked() -> None:
    upstream = ResponsesUpstream()
    body = {
        "model": "m",
        "input": [
            {"role": "user", "content": "Ellenőrizd az adószámot."},
            {
                "type": "function_call",
                "call_id": "c1",
                "name": "lookup",
                "arguments": json.dumps(arguments()),
            },
            {"type": "function_call_output", "call_id": "c1", "output": "ok"},
        ],
    }
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json=body)
    assert response.status_code == 200, response.text
    sent = json.loads(upstream.requests[0].content)["input"][1]["arguments"]
    assert_masked(json.loads(sent), upstream.requests[0].content)


def test_a_number_and_the_same_value_as_text_share_one_placeholder() -> None:
    upstream = MockUpstream()
    body = chat(json.dumps({"tax_id": TAX_ID}))
    body["messages"][0]["content"] = f"Az adóazonosítóm {TAX_ID}."
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/chat/completions", json=body)
    assert response.status_code == 200, response.text
    sent = upstream.bodies[0]["messages"]
    placeholder = json.loads(sent[1]["tool_calls"][0]["function"]["arguments"])["tax_id"]
    assert placeholder in sent[0]["content"]


def test_numbers_in_metadata_and_schema_data_are_masked() -> None:
    body = chat("{}")
    body["metadata"] = {"ref": TAX_ID}
    schema = {"type": "object", "properties": {"id": {"type": "integer", "enum": [TAX_ID, 7]}}}
    body["tools"] = [{"type": "function", "function": {"name": "lookup", "parameters": schema}}]
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/chat/completions", json=body)
    assert response.status_code == 200, response.text
    sent = upstream.bodies[0]
    assert PLACEHOLDER_RE.fullmatch(sent["metadata"]["ref"])
    enum = sent["tools"][0]["function"]["parameters"]["properties"]["id"]["enum"]
    assert PLACEHOLDER_RE.fullmatch(enum[0]) and enum[1] == 7
    assert str(TAX_ID) not in upstream.requests[0].content.decode()


def test_a_schema_keyword_number_with_personal_data_fails_closed() -> None:
    """``maximum`` is structure: it can't carry a placeholder, so it is checked, not masked."""
    body = chat("{}")
    schema = {"type": "object", "properties": {"id": {"type": "integer", "maximum": TAX_ID}}}
    body["tools"] = [{"type": "function", "function": {"name": "lookup", "parameters": schema}}]
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/chat/completions", json=body)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "unsupported_content"
    assert str(TAX_ID) not in response.text
    assert upstream.requests == []


def test_short_numbers_and_booleans_are_not_slots() -> None:
    collected = collect_texts(chat({"a": 12345, "b": True, "c": 1.5, "d": 123456}))
    numbers = [s.text for s in collected.slots if s.text.lstrip("-").replace(".", "").isdigit()]
    assert numbers == ["123456"]


def test_an_unmasked_number_is_written_back_as_the_same_number() -> None:
    body = chat({"big": 1_800_000_000, "f": 1234567.5})
    collected = collect_texts(body)
    for slot in collected.slots:
        slot.write(slot.text)
    collected.finalize()
    args = body["messages"][1]["tool_calls"][0]["function"]["arguments"]
    assert args == {"big": 1_800_000_000, "f": 1234567.5}


def test_a_checked_number_with_personal_data_raises() -> None:
    body = chat("{}")
    body["tool_choice"] = {"type": "function", "function": {"name": "lookup", "n": TAX_ID}}
    collected = collect_texts(body)
    slot = next(s for s in collected.slots if s.text == str(TAX_ID))
    with pytest.raises(UnsupportedContentError):
        slot.write("[[NATIONAL_ID_HU_TAX_abcd]]")
