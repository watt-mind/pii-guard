"""End-to-end gateway tests through the official ``openai`` client and a mock upstream.

All values are fictional (ADR 0005). The upstream is an ``httpx.MockTransport``; nothing
leaves the process.
"""

from __future__ import annotations

import itertools
import json
import re

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import (
    EMAILS,
    IBAN,
    NAMES,
    UPSTREAM_KEY,
    FakeLlm,
    MockUpstream,
    completion,
    conversation_turn_one,
    full_conversation,
    leaked_values,
    make_app,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pii_guard.config import Settings
from pii_guard.gateway import GatewayConfig
from pii_guard.vault import PLACEHOLDER_RE

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def openai_client(http: TestClient, **headers: str) -> openai.OpenAI:
    return openai.OpenAI(
        base_url="http://testserver/v1",
        api_key="client-key-not-forwarded",
        http_client=http,
        default_headers=headers or None,
        max_retries=0,
    )


# --- AC1: the official client, non-streaming and streaming ------------------------------


def test_openai_client_non_streaming_round_trip() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        raw = openai_client(http).chat.completions.with_raw_response.create(
            model="test-model", messages=conversation_turn_one()
        )
        answer = raw.parse()
    content = answer.choices[0].message.content
    assert "Teszt Elek" in content
    assert "teszt.elek@example.com" in content
    assert "+36 30 123 4567" in content
    assert PLACEHOLDER_RE.search(content) is None
    assert raw.headers["x-pii-guard-session"].startswith("s_")
    assert raw.headers["x-pii-guard-mode"] == "strict"
    assert raw.headers["x-pii-guard-unresolved"] == "0"
    assert int(raw.headers["x-pii-guard-masked"]) >= 4
    # Forwarded with the configured key and the client's model, never the client's key.
    forwarded = upstream.requests[0]
    assert forwarded.url == httpx.URL("https://upstream.test/v1/chat/completions")
    assert forwarded.headers["authorization"] == f"Bearer {UPSTREAM_KEY}"
    assert upstream.bodies[0]["model"] == "test-model"
    assert leaked_values(forwarded.content) == []


def test_openai_client_streaming_round_trip() -> None:
    upstream = MockUpstream(
        stream_chunks=lambda text: [text[i : i + 3] for i in range(0, len(text), 3)]
    )
    with TestClient(make_app(upstream)) as http:
        stream = openai_client(http).chat.completions.create(
            model="test-model", messages=conversation_turn_one(), stream=True
        )
        pieces = [c.choices[0].delta.content or "" for c in stream if c.choices]
    content = "".join(pieces)
    assert "Teszt Elek" in content and "teszt.elek@example.com" in content
    assert PLACEHOLDER_RE.search(content) is None
    assert upstream.bodies[0]["stream"] is True
    assert leaked_values(upstream.requests[0].content) == []


def test_params_pass_through() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        openai_client(http).chat.completions.create(
            model="muse-spark-1.3",
            messages=[{"role": "user", "content": "Hello"}],
            temperature=0.2,
            max_tokens=50,
            extra_body={"reasoning_effort": "minimal"},
        )
    body = upstream.bodies[0]
    assert body["model"] == "muse-spark-1.3"
    assert body["temperature"] == 0.2
    assert body["max_tokens"] == 50
    assert body["reasoning_effort"] == "minimal"


# --- AC2: no labelled value reaches the upstream ------------------------------------------


@pytest.mark.parametrize("mode", ["strict", "fast"])
@pytest.mark.parametrize("stream", [False, True])
def test_upstream_receives_no_labelled_value(mode: str, stream: bool) -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        client = openai_client(http, **{"X-PII-Guard-Mode": mode})
        result = client.chat.completions.create(
            model="test-model", messages=full_conversation(), stream=stream
        )
        if stream:
            list(result)
    leaks = leaked_values(upstream.requests[0].content)
    if mode == "strict":
        assert leaks == []
    else:
        # fast = rules only: every structured value is masked; names need the LLM pass.
        assert {leak.removesuffix(" (compact)") for leak in leaks} <= set(NAMES)
    body = upstream.bodies[0]
    arguments = json.loads(body["messages"][2]["tool_calls"][0]["function"]["arguments"])
    assert PLACEHOLDER_RE.fullmatch(arguments["to"])
    assert PLACEHOLDER_RE.fullmatch(arguments["cc"][0])
    assert PLACEHOLDER_RE.search(body["messages"][3]["content"])


def test_same_value_gets_same_placeholder_everywhere() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        openai_client(http).chat.completions.create(model="m", messages=full_conversation())
    raw = upstream.requests[0].content.decode()
    placeholders = set(PLACEHOLDER_RE.findall(raw))
    # 3 people + 3 emails + 2 phones + 1 IBAN, one placeholder each: the inflected
    # "Minta Máriának" shares "Minta Mária"'s placeholder, with the suffix kept outside.
    assert len(placeholders) == 9
    assert re.search(r"\[\[PERSON_[0-9a-f]+\]\]nak", raw)


def test_name_field_with_personal_data_is_dropped() -> None:
    upstream = MockUpstream()
    messages = [
        {"role": "user", "name": "Teszt Elek", "content": "Hi"},
        {"role": "user", "name": "agent_1", "content": "Hello"},
    ]
    with TestClient(make_app(upstream)) as http:
        openai_client(http).chat.completions.create(model="m", messages=messages)
    forwarded = upstream.bodies[0]["messages"]
    assert "name" not in forwarded[0]
    assert forwarded[1]["name"] == "agent_1"


def test_user_field_is_masked() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        openai_client(http).chat.completions.create(
            model="m", messages=[{"role": "user", "content": "Hi"}], user=EMAILS[0]
        )
    assert PLACEHOLDER_RE.fullmatch(upstream.bodies[0]["user"])


# --- Tool-call arguments are restored JSON-safely -----------------------------------------


def test_tool_call_arguments_restored_as_valid_json() -> None:
    def answer_with_tool(body: dict) -> str:
        return ""

    upstream = MockUpstream(answer=answer_with_tool)
    quoted = 'Teszt "Tesztike" Elek'

    def handler(request: httpx.Request) -> httpx.Response:
        upstream.requests.append(request)
        body = json.loads(request.content)
        placeholder = PLACEHOLDER_RE.search(body["messages"][0]["content"]).group(0)
        args = json.dumps({"name": placeholder, "note": f"to {placeholder}"})
        calls = [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": args}}]
        return httpx.Response(200, json=completion("", tool_calls=calls))

    app = make_app(upstream, llm=FakeLlm([quoted]))
    app.state.gateway_transport = httpx.MockTransport(handler)
    with TestClient(app) as http:
        result = openai_client(http).chat.completions.create(
            model="m", messages=[{"role": "user", "content": f"Ő {quoted}."}]
        )
    args = json.loads(result.choices[0].message.tool_calls[0].function.arguments)
    assert args == {"name": quoted, "note": f"to {quoted}"}
    assert quoted not in upstream.requests[0].content.decode()


# --- AC3: split placeholders across arbitrary chunk boundaries (end to end) ---------------


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(cuts=st.lists(st.integers(min_value=1, max_value=400), max_size=40))
def test_streamed_placeholders_restored_across_any_chunking(cuts: list[int]) -> None:
    def chunker(text: str) -> list[str]:
        points = sorted({c % (len(text) + 1) for c in cuts} | {0, len(text)})
        return [text[a:b] for a, b in itertools.pairwise(points)]

    upstream = MockUpstream(stream_chunks=chunker)
    with TestClient(make_app(upstream)) as http:
        stream = openai_client(http).chat.completions.create(
            model="m", messages=conversation_turn_one(), stream=True
        )
        content = "".join(c.choices[0].delta.content or "" for c in stream if c.choices)
    # "Minta Máriának" is masked as Minta Mária's placeholder + "nak"; the mock upstream echoes
    # only the placeholder, so the base form comes back.
    expected = "Rendben: Teszt Elek, teszt.elek@example.com, +36 30 123 4567, Minta Mária."
    assert content == expected


# --- AC4: the second turn re-detects only the new message ---------------------------------


@pytest.mark.parametrize("stream", [False, True])
def test_second_turn_detects_only_the_new_message(stream: bool) -> None:
    llm = FakeLlm()
    upstream = MockUpstream()
    with TestClient(make_app(upstream, llm=llm)) as http:
        client = openai_client(http)
        turn_one = conversation_turn_one()
        raw = client.chat.completions.with_raw_response.create(
            model="m", messages=turn_one, stream=stream
        )
        session = raw.headers["x-pii-guard-session"]
        assert raw.headers["x-pii-guard-cache-hits"] == "0"
        assert raw.headers["x-pii-guard-cache-misses"] == "2"
        parsed = raw.parse()
        if stream:
            answer = "".join(c.choices[0].delta.content or "" for c in parsed if c.choices)
        else:
            answer = parsed.choices[0].message.content
        assert llm.calls == 2

        turn_two = [
            *turn_one,
            {"role": "assistant", "content": answer},
            {"role": "user", "content": "Köszönöm, Teszt Elek. Küldd el Jane Placeholdernek is."},
        ]
        raw2 = client.chat.completions.with_raw_response.create(
            model="m", messages=turn_two, extra_headers={"X-PII-Guard-Session": session}
        )
        raw2.parse()
    assert raw2.headers["x-pii-guard-session"] == session
    assert raw2.headers["x-pii-guard-cache-hits"] == "3"  # system, user 1, the answer
    assert raw2.headers["x-pii-guard-cache-misses"] == "1"  # only the new message
    assert llm.calls == 3
    first, second = upstream.bodies[0], upstream.bodies[1]
    # Re-sent history masks identically (deterministic per session).
    assert second["messages"][:2] == first["messages"][:2]
    assert leaked_values(upstream.requests[1].content) == []


def test_without_session_header_each_request_is_a_new_session() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        client = openai_client(http)
        a = client.chat.completions.with_raw_response.create(
            model="m", messages=conversation_turn_one()
        )
        b = client.chat.completions.with_raw_response.create(
            model="m", messages=conversation_turn_one()
        )
    assert a.headers["x-pii-guard-session"] != b.headers["x-pii-guard-session"]
    assert b.headers["x-pii-guard-cache-hits"] == "0"


# --- AC5: modes, timeouts, fail closed -----------------------------------------------------


def test_fast_mode_never_calls_the_llm_detector() -> None:
    llm = FakeLlm()
    upstream = MockUpstream()
    with TestClient(make_app(upstream, llm=llm)) as http:
        raw = openai_client(
            http, **{"X-PII-Guard-Mode": "fast"}
        ).chat.completions.with_raw_response.create(model="m", messages=full_conversation())
    assert raw.headers["x-pii-guard-mode"] == "fast"
    assert llm.calls == 0
    assert len(upstream.requests) == 1


def test_strict_mode_calls_the_llm_detector() -> None:
    llm = FakeLlm()
    with TestClient(make_app(MockUpstream(), llm=llm)) as http:
        openai_client(http, **{"X-PII-Guard-Mode": "strict"}).chat.completions.create(
            model="m", messages=conversation_turn_one()
        )
    assert llm.calls == 2


def test_default_mode_comes_from_the_config() -> None:
    llm = FakeLlm()
    config = GatewayConfig(mode="fast")
    with TestClient(make_app(MockUpstream(), llm=llm, config=config)) as http:
        raw = openai_client(http).chat.completions.with_raw_response.create(
            model="m", messages=conversation_turn_one()
        )
    assert raw.headers["x-pii-guard-mode"] == "fast"
    assert llm.calls == 0


@pytest.mark.parametrize("stream", [False, True])
def test_strict_detector_timeout_blocks_the_request(stream: bool) -> None:
    upstream = MockUpstream()
    app = make_app(upstream, llm=FakeLlm(delay=1.0), config=GatewayConfig(detection_timeout=0.1))
    with TestClient(app) as http, pytest.raises(openai.APIStatusError) as caught:
        openai_client(http).chat.completions.create(
            model="m", messages=conversation_turn_one(), stream=stream
        )
    assert caught.value.status_code == 503
    assert caught.value.body["code"] == "detection_failed"
    assert "timed out" in caught.value.body["message"]
    assert upstream.requests == []


def test_detector_error_blocks_the_request() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream, llm=FakeLlm(fail=True))) as http:
        response = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": conversation_turn_one()}
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "detection_failed"
    assert upstream.requests == []
    assert "Teszt" not in response.text


def test_failed_new_session_is_dropped() -> None:
    upstream = MockUpstream()
    app = make_app(upstream, llm=FakeLlm(fail=True))
    with TestClient(app) as http:
        http.post("/v1/chat/completions", json={"model": "m", "messages": conversation_turn_one()})
        assert len(app.state.gateway.vault) == 0


@pytest.mark.parametrize(
    "part",
    [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        {"type": "input_audio", "input_audio": {"data": "AAAA", "format": "wav"}},
        {"type": "file", "file": {"file_id": "f1"}},
    ],
)
def test_unsupported_content_parts_are_rejected(part: dict) -> None:
    upstream = MockUpstream()
    messages = [{"role": "user", "content": [{"type": "text", "text": "Nézd:"}, part]}]
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/chat/completions", json={"model": "m", "messages": messages})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_content"
    assert upstream.requests == []


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"model": "m"}, 400, "invalid_request"),
        ({"model": "m", "messages": []}, 400, "invalid_request"),
        ({"messages": [{"role": "user", "content": "x"}]}, 400, "invalid_request"),
        ({"model": "m", "messages": ["x"]}, 400, "invalid_request"),
        ({"model": "m", "messages": [{"role": "user", "content": 5}]}, 400, "invalid_request"),
        ([1, 2], 400, "invalid_request"),
    ],
)
def test_malformed_bodies_are_rejected(body: object, status: int, code: str) -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/chat/completions", json=body)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert upstream.requests == []


def test_invalid_json_is_rejected_without_echo() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post(
            "/v1/chat/completions",
            content=b'{"model": "m", "messages": "Teszt Elek',
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 400
    assert "Teszt" not in response.text


def test_invalid_mode_header_is_rejected() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one()},
            headers={"X-PII-Guard-Mode": "yolo"},
        )
    assert response.status_code == 400
    assert upstream.requests == []


@pytest.mark.parametrize("header", ["s_doesnotexist", "bad id!"])
def test_unknown_or_malformed_session_is_rejected(header: str) -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one()},
            headers={"X-PII-Guard-Session": header},
        )
    assert response.status_code in (400, 404)
    assert upstream.requests == []


def test_invalid_language_header_is_rejected() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one()},
            headers={"X-PII-Guard-Language": "not a language"},
        )
    assert response.status_code == 400


def test_language_header_is_accepted() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one()},
            headers={"X-PII-Guard-Language": "en"},
        )
    assert response.status_code == 200


def test_upstream_not_configured_fails_closed() -> None:
    upstream = MockUpstream()
    app = make_app(upstream, settings=Settings(tenant_key="00" * 32))
    with TestClient(app) as http:
        response = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": conversation_turn_one()}
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_not_configured"
    assert upstream.requests == []


def test_no_tenant_key_fails_closed() -> None:
    upstream = MockUpstream()
    app = make_app(upstream, settings=Settings(upstream_base_url="https://upstream.test/v1"))
    with TestClient(app, raise_server_exceptions=False) as http:
        response = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": conversation_turn_one()}
        )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "vault_not_configured"
    assert upstream.requests == []


def test_client_key_is_passed_through_when_no_upstream_key_is_set() -> None:
    upstream = MockUpstream()
    settings_ = Settings(tenant_key="00" * 32, upstream_base_url="https://upstream.test/v1/")
    with TestClient(make_app(upstream, settings=settings_)) as http:
        openai_client(http).chat.completions.create(
            model="m", messages=[{"role": "user", "content": "Hi"}]
        )
    assert upstream.requests[0].headers["authorization"] == "Bearer client-key-not-forwarded"


# --- Upstream errors ------------------------------------------------------------------------


@pytest.mark.parametrize("stream", [False, True])
def test_upstream_error_passes_status_without_content(stream: bool) -> None:
    upstream = MockUpstream(
        status=400,
        error_body={
            "error": {
                "message": "bad request: [[PERSON_abcdef]] Teszt Elek",
                "type": "invalid_request_error",
                "code": "bad param!",
            }
        },
    )
    with TestClient(make_app(upstream)) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one(), "stream": stream},
        )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "upstream_error"
    assert error["upstream_type"] == "invalid_request_error"
    assert "upstream_code" not in error  # not a safe token
    assert "PERSON" not in response.text and "Teszt" not in response.text
    assert response.headers["x-pii-guard-session"].startswith("s_")


def test_upstream_unreachable_is_502() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    upstream = MockUpstream()
    app = make_app(upstream)
    app.state.gateway_transport = httpx.MockTransport(boom)
    with TestClient(app) as http:
        response = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": conversation_turn_one()}
        )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_unavailable"


def test_upstream_non_json_is_502() -> None:
    app = make_app(MockUpstream())
    app.state.gateway_transport = httpx.MockTransport(
        lambda r: httpx.Response(200, content=b"<html>")
    )
    with TestClient(app) as http:
        response = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": conversation_turn_one()}
        )
    assert response.status_code == 502


def test_upstream_stream_error_event_is_sanitized() -> None:
    body = (
        b'data: {"choices":[{"index":0,"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
        b'data: {"error":{"message":"oops [[PERSON_abcdef]]"}}\n\n'
    )
    app = make_app(MockUpstream())
    app.state.gateway_transport = httpx.MockTransport(
        lambda r: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
    )
    with TestClient(app) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one(), "stream": True},
        )
    assert "PERSON" not in response.text
    assert "upstream_error" in response.text


def test_unresolved_placeholders_are_left_and_counted() -> None:
    upstream = MockUpstream(answer=lambda body: "Hello [[PERSON_ffffff]] and [[PERSON_ffffff]]")
    with TestClient(make_app(upstream)) as http:
        raw = openai_client(http).chat.completions.with_raw_response.create(
            model="m", messages=conversation_turn_one()
        )
    assert raw.parse().choices[0].message.content == "Hello [[PERSON_ffffff]] and [[PERSON_ffffff]]"
    assert raw.headers["x-pii-guard-unresolved"] == "1"


def test_logs_carry_no_values(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        client = openai_client(http)
        a = client.chat.completions.with_raw_response.create(
            model="m", messages=full_conversation()
        )
        b = client.chat.completions.with_raw_response.create(
            model="m", messages=full_conversation(), stream=True
        )
        list(b.parse())
    sessions = [a.headers["x-pii-guard-session"], b.headers["x-pii-guard-session"]]
    # The openai client's own debug log quotes the request; only check pii-guard's loggers.
    text = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("pii_guard"))
    assert "chat.completions ok" in text
    for value in (*NAMES, *EMAILS, IBAN, UPSTREAM_KEY, *sessions):
        assert value not in text
