"""The gateway's request allow-list fails closed across the whole body (LAB-1157).

Every case puts fictional personal data (ADR 0005) in a field that used to be forwarded
verbatim. Each one must either be masked upstream or rejected with a 400 before anything is
forwarded, and the traffic log's ``masked`` event must not contain the values either.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway_helpers import (
    TEST_TENANT_KEY,
    UPSTREAM_KEY,
    UPSTREAM_URL,
    FakeLlm,
    MockUpstream,
)

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway import GatewayConfig, build_mode_detectors
from pii_guard.gateway.request import (
    InvalidChatRequestError,
    UnsupportedContentError,
    collect_texts,
)
from pii_guard.observability import ObservabilitySettings

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

EMAIL = "teszt.elek@example.com"
NAME = "Teszt Elek"
GOLD = (EMAIL, NAME)
HELLO = [{"role": "user", "content": "hello"}]


def _call(function: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": function}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
    ]


#: name -> (extra body fields, expected outcome: "masked" or the 400 error code).
CASES: dict[str, tuple[dict[str, Any], str]] = {
    # 1. tool-call arguments as a JSON object (LiteLLM/Ollama style)
    "tool_args_object": (
        {"messages": _call({"name": "send", "arguments": {"to": EMAIL, "name": NAME}})},
        "masked",
    ),
    "tool_args_list": ({"messages": _call({"name": "send", "arguments": [EMAIL]})}, "masked"),
    "tool_args_number": (
        {"messages": _call({"name": "send", "arguments": 42})},
        "invalid_request",
    ),
    # 2. message-level fields and extra keys on content parts
    "msg_reasoning_details": (
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": "x",
                    "reasoning_details": [
                        {"type": "reasoning.text", "text": f"user is {NAME} {EMAIL}"}
                    ],
                },
                {"role": "user", "content": "hi"},
            ]
        },
        "masked",
    ),
    "msg_audio_transcript": (
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": None,
                    "audio": {"id": "a1", "transcript": f"{NAME} {EMAIL}"},
                },
                {"role": "user", "content": "hi"},
            ]
        },
        "masked",
    ),
    "msg_unknown_field": (
        {"messages": [{"role": "user", "content": "hi", "x_note": f"{NAME} {EMAIL}"}]},
        "unsupported_content",
    ),
    "msg_unknown_field_named_by_value": (
        {"messages": [{"role": "user", "content": "hi", EMAIL: 1}]},
        "unsupported_content",
    ),
    "msg_reasoning_object": (
        {"messages": [{"role": "assistant", "content": "x", "reasoning": {"text": EMAIL}}, *HELLO]},
        "masked",
    ),
    "content_part_extra_key": (
        {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "hi", "annotation": f"{NAME} {EMAIL}"}],
                }
            ]
        },
        "unsupported_content",
    ),
    "image_url_extra_key": (
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "data:,", "alt": EMAIL}}
                    ],
                }
            ]
        },
        "unsupported_content",
    ),
    "tool_call_extra_key": (
        {
            "messages": [
                {"role": "user", "content": "hi"},
                {
                    "role": "assistant",
                    "tool_calls": [{"id": "c1", "type": "function", "note": EMAIL}],
                },
            ]
        },
        "unsupported_content",
    ),
    "unknown_role": (
        {"messages": [{"role": EMAIL, "content": "hi"}]},
        "invalid_request",
    ),
    # 3. standard top-level fields
    "stop_list": ({"stop": [f"Write to {EMAIL}"]}, "masked"),
    "stop_str": ({"stop": f"mail {EMAIL} or {NAME}"}, "masked"),
    "prediction": (
        {"prediction": {"type": "content", "content": f"Dear {NAME}, {EMAIL}"}},
        "masked",
    ),
    "prediction_parts": (
        {
            "prediction": {
                "type": "content",
                "content": [{"type": "text", "text": f"{NAME} {EMAIL}"}],
            }
        },
        "masked",
    ),
    "web_search_options": (
        {
            "web_search_options": {
                "user_location": {
                    "type": "approximate",
                    "approximate": {"city": f"{NAME} street", "region": EMAIL},
                }
            }
        },
        "masked",
    ),
    "safety_identifier": ({"safety_identifier": EMAIL}, "masked"),
    "prompt_cache_key": ({"prompt_cache_key": EMAIL}, "masked"),
    "user": ({"user": EMAIL}, "masked"),
    "metadata": ({"metadata": {"note": EMAIL}}, "masked"),
    "metadata_not_object": ({"metadata": EMAIL}, "invalid_request"),
    "unknown_top_level": ({"x_provider_note": f"{NAME} {EMAIL}"}, "unsupported_content"),
    "unknown_top_level_named_by_value": ({EMAIL: True}, "unsupported_content"),
    "logit_bias_key": ({"logit_bias": {EMAIL: 1}}, "invalid_request"),
    "scalar_field_string": ({"temperature": EMAIL}, "invalid_request"),
    "reasoning_effort_value": ({"reasoning_effort": EMAIL}, "unsupported_content"),
    "tool_choice_string": ({"tool_choice": EMAIL}, "unsupported_content"),
    "stream_options_value": ({"stream_options": {"include_usage": EMAIL}}, "unsupported_content"),
    "response_format_extra_key": (
        {"response_format": {"type": "text", "note": EMAIL}},
        "unsupported_content",
    ),
    # 4. tool strings and identifiers
    "tool_toplevel_string": (
        {
            "tools": [
                {
                    "type": "mcp",
                    "server_label": "x",
                    "server_description": f"for {NAME} {EMAIL}",
                    "function": {"name": "f", "description": "d"},
                }
            ]
        },
        "masked",
    ),
    "tool_not_object": ({"tools": [f"{NAME} {EMAIL}"]}, "invalid_request"),
    "tool_call_name": (
        {"messages": _call({"name": EMAIL, "arguments": "{}"})},
        "unsupported_content",
    ),
    "tool_call_id": (
        {
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "tool", "tool_call_id": EMAIL, "content": "ok"},
            ]
        },
        "unsupported_content",
    ),
    "function_message_name": (
        {"messages": [{"role": "function", "name": EMAIL, "content": "ok"}, *HELLO]},
        "unsupported_content",
    ),
}


def _app(upstream: MockUpstream) -> FastAPI:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL, upstream_api_key=UPSTREAM_KEY
    )
    app = create_app(settings, ObservabilitySettings(traffic_log="masked"))
    config = GatewayConfig()
    app.state.gateway_config = config
    app.state.gateway_transport = upstream.transport()
    app.state.gateway_detectors = build_mode_detectors(settings, config, llm_detector=FakeLlm())
    return app


@pytest.mark.parametrize("case", sorted(CASES))
def test_no_field_reaches_the_upstream_raw(case: str) -> None:
    extra, expected = CASES[case]
    upstream = MockUpstream()
    client = TestClient(_app(upstream))
    body = {"model": "m", "messages": HELLO, **extra}
    r = client.post("/v1/chat/completions", json=body, headers={"X-PII-Guard-Mode": "strict"})

    forwarded = b"".join(req.content for req in upstream.requests).decode()
    assert not [v for v in GOLD if v in forwarded], "personal data reached the upstream"
    if expected == "masked":
        assert r.status_code == 200, r.text
        assert len(upstream.requests) == 1
    else:
        assert r.status_code == 400
        assert r.json()["error"]["code"] == expected
        assert upstream.requests == []
        # The error names the location, never the value.
        assert not [v for v in GOLD if v in r.text]

    log = client.get("/v1/traffic")
    assert log.status_code == 200
    events = log.json()["events"]
    assert len(events) == 1 and events[0]["level"] == "masked"
    if expected == "masked":
        assert "masked" in events[0]["request"]  # the masked request body was logged
    dump = json.dumps(events, ensure_ascii=False)
    assert not [v for v in GOLD if v in dump], "the traffic log leaks personal data"


def test_object_arguments_stay_objects_and_are_masked_in_place() -> None:
    body = {"model": "m", "messages": _call({"name": "send", "arguments": {"to": EMAIL, "n": 1}})}
    collected = collect_texts(body)
    for slot in collected.slots:
        slot.write(slot.text.replace(EMAIL, "[[EMAIL_aaaa]]"))
    collected.finalize()
    args = body["messages"][1]["tool_calls"][0]["function"]["arguments"]
    assert args == {"to": "[[EMAIL_aaaa]]", "n": 1}


def test_structural_fields_pass_through_untouched() -> None:
    body: dict[str, Any] = {
        "model": "m",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}],
            },
            {
                "role": "assistant",
                "content": "x",
                "reasoning_details": [
                    {"type": "reasoning.encrypted", "data": "b64+/=", "id": "r1"}
                ],
            },
        ],
        "temperature": 0.2,
        "top_p": 1,
        "n": 2,
        "seed": 7,
        "stream": True,
        "stream_options": {"include_usage": True},
        "reasoning_effort": "low",
        "logit_bias": {"50256": -100},
        "tool_choice": "auto",
        "response_format": {"type": "json_object"},
        "top_k": 40,
    }
    snapshot = json.loads(json.dumps(body))
    collected = collect_texts(body)
    for slot in collected.slots:
        slot.write(slot.text)
    collected.finalize()
    assert body == snapshot
    # Opaque provider blobs are never sent to the detectors.
    assert "b64+/=" not in {slot.text for slot in collected.slots}


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"stop": [1]}, InvalidChatRequestError),
        (
            {"prediction": {"type": "content", "content": [{"type": "image_url"}]}},
            UnsupportedContentError,
        ),
        ({"web_search_options": {"filters": {}}}, UnsupportedContentError),
        ({"functions": "f"}, InvalidChatRequestError),
    ],
)
def test_malformed_fields_are_rejected(body: dict[str, Any], error: type[Exception]) -> None:
    with pytest.raises(error):
        collect_texts({"model": "m", "messages": HELLO, **body})
