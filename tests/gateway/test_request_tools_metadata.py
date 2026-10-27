"""Tool definitions, ``response_format`` schemas and ``metadata`` are masked (LAB-1113).

Free-text strings in a JSON Schema are masked; structural strings and identifiers are kept,
and personal data in an identifier rejects the request. All values are fictional (ADR 0005).
"""

from __future__ import annotations

import copy
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import (
    EMAILS,
    NAMES,
    UPSTREAM_KEY,
    MockUpstream,
    chunk,
    completion,
    make_app,
)

from pii_guard.gateway.request import collect_texts
from pii_guard.vault import PLACEHOLDER_RE

PERSON, OTHER, THIRD = NAMES[0], NAMES[1], NAMES[3]  # Teszt Elek, Minta Mária, Jane Placeholder
EMAIL = EMAILS[0]
VALUES = (PERSON, OTHER, THIRD, EMAIL)
MESSAGES = [{"role": "user", "content": "Küldd el a levelet."}]


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": f"Levél, ügyintéző: {OTHER}.",
        "properties": {
            "recipient": {
                "type": "string",
                "description": f"Címzett, például {THIRD}.",
                "enum": [PERSON, "other"],
                "default": PERSON,
            },
            "address": {"$ref": "#/$defs/address"},
            "count": {"type": "integer", "default": 3, "examples": [1, 2]},
        },
        "required": ["recipient"],
        "additionalProperties": False,
        "$defs": {"address": {"type": "string", "format": "email", "title": "E-mail cím"}},
    }


def tool(name: str = "send_letter", parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Levelet küld {PERSON} nevében.",
            "parameters": parameters if parameters is not None else schema(),
        },
    }


def post(upstream: MockUpstream, app: Any = None, **fields: Any) -> httpx.Response:
    with TestClient(app or make_app(upstream)) as http:
        return http.post(
            "/v1/chat/completions", json={"model": "m", "messages": MESSAGES, **fields}
        )


def assert_masked_schema(forwarded: dict[str, Any]) -> None:
    """Same keys and structure as :func:`schema`, with every free-text value masked."""
    original = schema()
    assert forwarded["type"] == "object"
    assert list(forwarded) == list(original)
    assert list(forwarded["properties"]) == list(original["properties"])
    assert forwarded["required"] == ["recipient"]
    assert forwarded["additionalProperties"] is False
    assert forwarded["$defs"] == original["$defs"]
    recipient = forwarded["properties"]["recipient"]
    assert recipient["type"] == "string"
    assert PLACEHOLDER_RE.fullmatch(recipient["enum"][0])
    assert recipient["enum"][1] == "other"
    assert recipient["default"] == recipient["enum"][0]
    assert PLACEHOLDER_RE.search(recipient["description"])
    assert PLACEHOLDER_RE.search(forwarded["description"])
    assert forwarded["properties"]["address"] == {"$ref": "#/$defs/address"}
    assert forwarded["properties"]["count"] == original["properties"]["count"]


def assert_no_values(raw: bytes) -> None:
    text = raw.decode("utf-8")
    decoded = json.dumps(json.loads(raw), ensure_ascii=False)
    for value in VALUES:
        assert value not in text
        assert value not in decoded


# --- free text is masked, structure kept --------------------------------------------------


def test_tools_and_metadata_are_masked() -> None:
    upstream = MockUpstream()
    response = post(upstream, tools=[tool()], metadata={"case_owner": EMAIL, "ref": "A-17"})
    assert response.status_code == 200
    assert_no_values(upstream.requests[0].content)
    forwarded = upstream.bodies[0]
    function = forwarded["tools"][0]["function"]
    assert forwarded["tools"][0]["type"] == "function"
    assert function["name"] == "send_letter"
    assert PLACEHOLDER_RE.search(function["description"])
    assert_masked_schema(function["parameters"])
    assert PLACEHOLDER_RE.fullmatch(forwarded["metadata"]["case_owner"])
    assert forwarded["metadata"]["ref"] == "A-17"
    # The same person gets the same placeholder in the description and in the enum.
    enum_value = function["parameters"]["properties"]["recipient"]["enum"][0]
    assert enum_value in function["description"]


def test_legacy_functions_are_masked() -> None:
    upstream = MockUpstream()
    response = post(upstream, functions=[tool()["function"]], function_call={"name": "send_letter"})
    assert response.status_code == 200
    assert_no_values(upstream.requests[0].content)
    forwarded = upstream.bodies[0]
    assert forwarded["functions"][0]["name"] == "send_letter"
    assert forwarded["function_call"] == {"name": "send_letter"}
    assert_masked_schema(forwarded["functions"][0]["parameters"])


def test_response_format_json_schema_is_masked() -> None:
    upstream = MockUpstream()
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "letter",
            "description": f"{PERSON} levele",
            "schema": schema(),
            "strict": True,
        },
    }
    response = post(upstream, response_format=response_format)
    assert response.status_code == 200
    assert_no_values(upstream.requests[0].content)
    forwarded = upstream.bodies[0]["response_format"]
    assert forwarded["type"] == "json_schema"
    assert forwarded["json_schema"]["name"] == "letter"
    assert forwarded["json_schema"]["strict"] is True
    assert PLACEHOLDER_RE.search(forwarded["json_schema"]["description"])
    assert_masked_schema(forwarded["json_schema"]["schema"])


def test_tools_without_personal_data_are_forwarded_unchanged() -> None:
    clean = {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Returns the weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "enum": ["Budapest", "Szeged"]},
                    "unit": {"type": ["string", "null"], "default": "celsius"},
                },
                "required": ["city"],
            },
            "strict": True,
        },
    }
    upstream = MockUpstream()
    fields = {
        "tools": [clean],
        "tool_choice": {"type": "function", "function": {"name": "get_weather"}},
        "metadata": {"ref": "A-17"},
        "response_format": {"type": "json_object"},
    }
    response = post(upstream, **copy.deepcopy(fields))
    assert response.status_code == 200
    forwarded = upstream.bodies[0]
    for key, value in fields.items():
        assert forwarded[key] == value
    assert json.dumps(forwarded["tools"]) == json.dumps(fields["tools"])  # key order too


def test_structural_strings_are_never_slots() -> None:
    body = {"model": "m", "messages": MESSAGES, "tools": [tool()]}
    texts = {slot.text for slot in collect_texts(body).slots}
    for structural in ("string", "object", "integer", "email", "#/$defs/address", "function"):
        assert structural not in texts


# --- identifiers are checked, not masked --------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "where"),
    [
        ({"tools": [tool(name=PERSON)]}, "tools.0.function.name"),
        (
            {"tools": [tool(parameters={"type": "object", "properties": {THIRD: {}}})]},
            "tools.0.function.parameters.properties.0",
        ),
        (
            {"tools": [tool()], "tool_choice": {"type": "function", "function": {"name": OTHER}}},
            "tool_choice.function.name",
        ),
        ({"functions": [tool(name=PERSON)["function"]]}, "functions.0.name"),
        ({"metadata": {"ref": "A-17", EMAIL: "owner"}}, "metadata.1"),
    ],
)
def test_personal_data_in_an_identifier_is_rejected(fields: dict[str, Any], where: str) -> None:
    upstream = MockUpstream()
    app = make_app(upstream)
    response = post(upstream, app, **fields)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_content"
    assert where in response.json()["error"]["message"]
    for value in VALUES:
        assert value not in response.text
        assert all(value not in v for v in response.headers.values())
    assert upstream.requests == []
    assert len(app.state.gateway.vault) == 0  # the new session is dropped


# --- placeholders echoed back in tool calls are restored ----------------------------------


def _enum_placeholder(request: httpx.Request) -> str:
    body = json.loads(request.content)
    return body["tools"][0]["function"]["parameters"]["properties"]["recipient"]["enum"][0]


def test_tool_call_echoing_an_enum_placeholder_is_restored() -> None:
    upstream = MockUpstream()

    def handler(request: httpx.Request) -> httpx.Response:
        upstream.requests.append(request)
        args = json.dumps({"recipient": _enum_placeholder(request)})
        calls = [
            {"id": "c1", "type": "function", "function": {"name": "send_letter", "arguments": args}}
        ]
        return httpx.Response(200, json=completion("", tool_calls=calls))

    app = make_app(upstream)
    app.state.gateway_transport = httpx.MockTransport(handler)
    response = post(upstream, app, tools=[tool()])
    assert response.status_code == 200
    call = response.json()["choices"][0]["message"]["tool_calls"][0]
    assert json.loads(call["function"]["arguments"]) == {"recipient": PERSON}
    assert_no_values(upstream.requests[0].content)


def test_streamed_tool_call_echoing_an_enum_placeholder_is_restored() -> None:
    upstream = MockUpstream()

    def handler(request: httpx.Request) -> httpx.Response:
        upstream.requests.append(request)
        args = json.dumps({"recipient": _enum_placeholder(request)})
        head = {"index": 0, "id": "c1", "type": "function", "function": {"name": "send_letter"}}
        events = [chunk({"role": "assistant", "tool_calls": [head]})]
        events += [
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": args[i : i + 7]}}]})
            for i in range(0, len(args), 7)
        ]
        events.append(chunk({}, finish="tool_calls"))
        sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(
            200, content=sse.encode(), headers={"content-type": "text/event-stream"}
        )

    app = make_app(upstream)
    app.state.gateway_transport = httpx.MockTransport(handler)
    response = post(upstream, app, tools=[tool()], stream=True)
    assert response.status_code == 200
    arguments = ""
    for line in response.text.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        for choice in json.loads(line[6:])["choices"]:
            for call in choice["delta"].get("tool_calls") or []:
                arguments += (call.get("function") or {}).get("arguments") or ""
    assert json.loads(arguments) == {"recipient": PERSON}


# --- no raw values in logs or headers ------------------------------------------------------


def test_logs_and_headers_carry_no_values(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    upstream = MockUpstream()
    ok = post(upstream, tools=[tool()], metadata={"case_owner": EMAIL})
    rejected = post(upstream, tools=[tool(name=PERSON)])
    assert ok.status_code == 200
    assert rejected.status_code == 400
    text = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("pii_guard"))
    headers = json.dumps([dict(r.headers) for r in (ok, rejected)])
    forwarded_headers = json.dumps([dict(r.headers) for r in upstream.requests])
    for value in (*VALUES, UPSTREAM_KEY):
        assert value not in text
        assert value not in headers
    for value in VALUES:
        assert value not in forwarded_headers


def test_flat_tool_definition_is_masked() -> None:
    upstream = MockUpstream()
    flat = {"type": "function", **tool()["function"]}
    response = post(upstream, tools=[flat])
    assert response.status_code == 200
    assert_no_values(upstream.requests[0].content)
    forwarded = upstream.bodies[0]["tools"][0]
    assert forwarded["type"] == "function"
    assert forwarded["name"] == "send_letter"
    assert_masked_schema(forwarded["parameters"])
