"""End-to-end gateway tests through the official ``openai`` client and a mock upstream.

All values are fictional (ADR 0005). The upstream is an ``httpx.MockTransport``; nothing
leaves the process.
"""

from __future__ import annotations

import itertools
import json
import re
import time

import httpx
import openai
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway_helpers import (
    EMAILS,
    IBAN,
    NAMES,
    TEST_TENANT_KEY,
    UPSTREAM_KEY,
    UPSTREAM_URL,
    FakeLlm,
    MockUpstream,
    completion,
    conversation_turn_one,
    full_conversation,
    leaked_values,
    make_app,
    without_note,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.detect.rules import RuleDetector
from pii_guard.gateway import GatewayConfig, Mode, build_mode_detectors
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def openai_client(http: TestClient, **headers: str) -> openai.OpenAI:
    return openai.OpenAI(
        base_url="http://127.0.0.1:8787/v1",
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
    # No session header: the client's default session (LAB-1286), a derived id.
    assert raw.headers["x-pii-guard-session"].startswith("d_")
    assert raw.headers["x-pii-guard-session-source"] == "default"
    assert raw.headers["x-pii-guard-mode"] == "audit"
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


@pytest.mark.parametrize("mode", ["audit", "fast"])
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
    if mode == "audit":
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
        body = without_note(json.loads(request.content))
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


def test_without_session_header_requests_share_the_default_session() -> None:
    # LAB-1286: a client that can't send the header still keeps its placeholders.
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        client = openai_client(http)
        a = client.chat.completions.with_raw_response.create(
            model="m", messages=conversation_turn_one()
        )
        b = client.chat.completions.with_raw_response.create(
            model="m", messages=conversation_turn_one()
        )
    assert a.headers["x-pii-guard-session"] == b.headers["x-pii-guard-session"]
    assert b.headers["x-pii-guard-session-source"] == "default"
    assert b.headers["x-pii-guard-cache-misses"] == "0"
    assert upstream.bodies[0]["messages"] == upstream.bodies[1]["messages"]


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


def test_audit_mode_calls_the_llm_detector() -> None:
    llm = FakeLlm()
    with TestClient(make_app(MockUpstream(), llm=llm)) as http:
        openai_client(http, **{"X-PII-Guard-Mode": "audit"}).chat.completions.create(
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
def test_audit_detector_timeout_blocks_the_request(stream: bool) -> None:
    upstream = MockUpstream()
    app = make_app(
        upstream,
        llm=FakeLlm(delay=1.0),
        config=GatewayConfig(mode=Mode.AUDIT, detection_timeout=0.1),
    )
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
    assert response.headers["x-pii-guard-session"].startswith("d_")


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


# --- LAB-1279: fast mode detects a request's uncached texts in one batched job --------------


class BatchingNames:
    """A batching detector (like NER) that finds the fictional names; counts its calls."""

    name = "ner"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.batches: list[list[str]] = []
        self.detect_calls = 0

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        self.detect_calls += 1
        return self._find(text)

    def detect_batch(self, texts: list[str], language: str = "hu") -> list[list[Span]]:
        self.batches.append(list(texts))
        if self.fail:
            raise RuntimeError("Teszt Elek")
        return [self._find(t) for t in texts]

    def _find(self, text: str) -> list[Span]:
        return [
            Span(m.start(), m.end(), EntityType.PERSON, m.group(), 0.9, self.name)
            for name in NAMES
            for m in re.finditer(re.escape(name), text)
        ]


def batching_app(upstream: MockUpstream, ner: BatchingNames, **config: object) -> FastAPI:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL, upstream_api_key=UPSTREAM_KEY
    )
    gateway_config = GatewayConfig(mode=Mode.FAST, **config)
    app = create_app(settings)
    app.state.gateway_config = gateway_config
    app.state.gateway_transport = upstream.transport()
    app.state.gateway_detectors = build_mode_detectors(
        settings, gateway_config, base=[RuleDetector(), ner], llm_detector=FakeLlm()
    )
    return app


def test_fast_mode_detects_uncached_texts_in_one_batch() -> None:
    ner = BatchingNames()
    upstream = MockUpstream()
    messages = full_conversation()
    with TestClient(batching_app(upstream, ner)) as http:
        client = openai_client(http)
        first = client.chat.completions.with_raw_response.create(model="m", messages=messages)
        first.parse()
        misses = int(first.headers["x-pii-guard-cache-misses"])
        assert misses > 3
        # One worker job and one detector call for every uncached text of the request.
        assert len(ner.batches) == 1 and len(ner.batches[0]) == misses
        assert ner.detect_calls == 0
        assert len(set(ner.batches[0])) == misses  # a repeated text is detected once
        session = first.headers["x-pii-guard-session"]

        # Cache hits are unchanged: the same request again detects nothing.
        again = client.chat.completions.with_raw_response.create(
            model="m", messages=messages, extra_headers={"X-PII-Guard-Session": session}
        )
        again.parse()
        assert again.headers["x-pii-guard-cache-misses"] == "0"
        assert len(ner.batches) == 1

        # A new message: one batch with just that text.
        extra = [*messages, {"role": "user", "content": "Teszt Elek kérdezi: kész?"}]
        third = client.chat.completions.with_raw_response.create(
            model="m", messages=extra, extra_headers={"X-PII-Guard-Session": session}
        )
        third.parse()
        assert third.headers["x-pii-guard-cache-misses"] == "1"
        assert ner.batches[-1] == ["Teszt Elek kérdezi: kész?"]
    assert leaked_values(upstream.requests[0].content) == []
    assert all(leaked_values(r.content) == [] for r in upstream.requests)


def test_fast_mode_batch_error_blocks_the_whole_request() -> None:
    upstream = MockUpstream()
    app = batching_app(upstream, BatchingNames(fail=True))
    with TestClient(app) as http:
        response = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": full_conversation()}
        )
        assert len(app.state.gateway.vault) == 0
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "detection_failed"
    assert upstream.requests == []
    assert "Teszt" not in response.text


def test_fast_mode_batch_keeps_the_detection_timeout() -> None:
    class Slow(BatchingNames):
        def detect_batch(self, texts: list[str], language: str = "hu") -> list[list[Span]]:
            time.sleep(1.0)
            return super().detect_batch(texts, language)

    upstream = MockUpstream()
    with TestClient(batching_app(upstream, Slow(), detection_timeout=0.1)) as http:
        response = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": conversation_turn_one()}
        )
    assert response.status_code == 503
    assert "timed out" in response.json()["error"]["message"]
    assert upstream.requests == []


def test_audit_mode_still_detects_texts_as_parallel_jobs() -> None:
    # The LLM detector is remote and per text: audit mode keeps one job per text.
    llm = FakeLlm()
    with TestClient(make_app(MockUpstream(), llm=llm)) as http:
        raw = openai_client(http).chat.completions.with_raw_response.create(
            model="m", messages=full_conversation()
        )
    assert llm.calls == int(raw.headers["x-pii-guard-cache-misses"])


# --- LAB-1278: the second pass scans only entries newer than each text ---------------------


class ScriptedNer:
    """Reports, in a text holding a marker, the values listed for it: a detector that misses
    a value in one message and finds it in a later one (late confirmation)."""

    name = "llm"
    model = "scripted-ner"

    def __init__(self, found: dict[str, list[tuple[str, EntityType]]]) -> None:
        self.found = found

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        spans: list[Span] = []
        for marker, values in self.found.items():
            if marker not in text:
                continue
            for value, entity_type in values:
                for m in re.finditer(rf"(?<!\w){re.escape(value)}(?!\w)", text):
                    if any(s.start < m.end() and m.start() < s.end for s in spans):
                        continue
                    spans.append(Span(m.start(), m.end(), entity_type, value, 0.9, "llm"))
        return spans


P, E, PH = EntityType.PERSON, EntityType.EMAIL, EntityType.PHONE
#: Each turn's new user message. Values first written undetected (or inflected) are confirmed
#: in a later message, so the second pass has work in earlier texts; LAB-1284's widening
#: cases (a CSV row with only the surname detected, a name known from an earlier turn) too.
LATE_TURNS = [
    "Szia! Holnap Próba Zsuzsannával és Kovács Bélával találkozom, a címük "
    "zsuzsa.proba@example.com.",
    "Marker2: Próba Zsuzsanna telefonszáma +36 30 555 0101, Kovács Béla is jön. "
    "Próba Zsuzsannának küldd el.",
    "id,name,email\n1,Jane Placeholder,jane.placeholder@example.net\n2,John Sample,x@example.org",
    "Dear Jane Placeholder, Kovács Bélának is szólj (+36 30 555 0101).",
    "Client: John Sample. Attendees:\n- John Sample\n- someone else",
    "Köszönöm, ennyi volt.",
    "Még egyszer: Próba Zsuzsannát és Jane Placeholdert hívd fel.",
]
LATE_FOUND = {
    "Marker2": [("Próba Zsuzsanna", P), ("Kovács Béla", P), ("Próba Zsuzsannának", P)],
    "id,name": [("Placeholder", P), ("Sample", P)],
    "Dear": [("Jane Placeholder", P), ("Kovács Bélának", P)],
    "Client:": [("John Sample", P)],
    "- John": [("John", P)],
    "Még egyszer": [("Próba Zsuzsannát", P), ("Jane Placeholdert", P)],
}


def _echo_all(body: dict) -> str:
    """Echo every placeholder of the request, so the restored history carries them all."""
    text = json.dumps(body["messages"], ensure_ascii=False)
    tokens = dict.fromkeys(f"[[{t}_{i}]]" for t, i in PLACEHOLDER_RE.findall(text))
    return "Rendben: " + ", ".join(tokens) + "."


def _run_late_session(
    stream: bool,
) -> tuple[list[bytes], list[str], list[int], int, list[tuple[str, object, int]]]:
    """The LATE_TURNS session; returns forwarded bodies, answers, entries scanned per request,
    the number of entries at the end and the session's ``entities()`` (masked counts)."""
    upstream = MockUpstream(answer=_echo_all)
    app = make_app(upstream, llm=ScriptedNer(LATE_FOUND))
    history: list[dict] = [{"role": "system", "content": "Asszisztens vagy."}]
    answers, scanned = [], []
    with TestClient(app) as http:
        client = openai_client(http)
        session_id = None
        for turn in LATE_TURNS:
            history.append({"role": "user", "content": turn})
            extra = {"X-PII-Guard-Session": session_id} if session_id else {}
            raw = client.chat.completions.with_raw_response.create(
                model="m", messages=history, stream=stream, extra_headers=extra
            )
            session_id = raw.headers["x-pii-guard-session"]
            parsed = raw.parse()
            if stream:
                answer = "".join(c.choices[0].delta.content or "" for c in parsed if c.choices)
            else:
                answer = parsed.choices[0].message.content
            session = app.state.gateway.vault.session(session_id)
            scanned.append(session.entries_scanned - sum(scanned))
            answers.append(answer)
            history.append({"role": "assistant", "content": answer})
        entries = len(session._by_key)
        entities = session.entities()
    return [r.content for r in upstream.requests], answers, scanned, entries, entities


def _canonical(raw: bytes) -> str:
    """Placeholders renumbered in order of first appearance."""
    names: dict[str, str] = {}
    return PLACEHOLDER_RE.sub(
        lambda m: names.setdefault(m.group(0), f"[[{m.group(1)}_{len(names)}]]"),
        raw.decode("utf-8"),
    )


@pytest.mark.parametrize("stream", [False, True])
def test_remask_since_changes_no_masked_body(monkeypatch: pytest.MonkeyPatch, stream: bool) -> None:
    from pii_guard.vault import vault as vault_module

    fast = _run_late_session(stream)
    monkeypatch.setattr(vault_module, "_REMASK_SINCE", False)
    full = _run_late_session(stream)
    fast_bodies, fast_answers, fast_scanned, entries, _ = fast
    full_bodies, full_answers, full_scanned, _, _ = full
    assert [_canonical(b) for b in fast_bodies] == [_canonical(b) for b in full_bodies]
    assert fast_bodies == full_bodies  # same tenant key and session ids: same placeholders
    assert fast_answers == full_answers  # and the same restored answers
    # The late values reached the upstream as placeholders, in the earlier turns too.
    last = full_bodies[-1].decode("utf-8")
    for value in ("Próba Zsuzsann", "Kovács Bél", "Jane", "Placeholder", "Sample", "555 0101"):
        assert value not in json.dumps(json.loads(last), ensure_ascii=False)
    # The shortcut scans less, never more.
    assert all(a <= b for a, b in zip(fast_scanned, full_scanned, strict=True))
    assert sum(fast_scanned) < sum(full_scanned)
    assert entries > 5


@pytest.mark.parametrize("stream", [False, True])
def test_mask_memo_changes_no_masked_body(monkeypatch: pytest.MonkeyPatch, stream: bool) -> None:
    from pii_guard.vault import vault as vault_module

    memo = _run_late_session(stream)
    monkeypatch.setattr(vault_module, "_MASK_MEMO", False)
    scratch = _run_late_session(stream)
    assert memo[0] == scratch[0]  # forwarded bodies, byte for byte
    assert memo[1] == scratch[1]  # restored answers
    assert memo[4] == scratch[4]  # entities() with their counts: the same masked counts
    # Pass 1 re-scans only what changed since the previous request (LAB-1315).
    assert all(a <= b for a, b in zip(memo[2], scratch[2], strict=True))
    assert sum(memo[2]) * 2 < sum(scratch[2])


def test_request_with_no_new_value_runs_no_remask_pass() -> None:
    upstream = MockUpstream()
    app = make_app(upstream)
    messages = conversation_turn_one()
    with TestClient(app) as http:
        client = openai_client(http)
        first = client.chat.completions.with_raw_response.create(model="m", messages=messages)
        session = app.state.gateway.vault.session(first.headers["x-pii-guard-session"])
        entries, before = len(session._by_key), session.entries_scanned
        generation = session.generation
        # The same texts again: every value is known, nothing new is confirmed.
        headers = {"X-PII-Guard-Session": session.session_id}
        client.chat.completions.with_raw_response.create(
            model="m", messages=messages, extra_headers=headers
        )
        second = session.entries_scanned
        client.chat.completions.with_raw_response.create(
            model="m", messages=messages, extra_headers=headers
        )
    assert session.generation == generation
    # Pass 1 only, and of it only the entries created after each text was first masked (it
    # was texts x entries before LAB-1315, and 2 x texts x entries before LAB-1278).
    assert 0 < second - before < len(messages) * entries
    # Then every text was masked at the current generation: nothing is scanned at all.
    assert session.entries_scanned == second
    assert upstream.bodies[0]["messages"] == upstream.bodies[1]["messages"]
    assert upstream.bodies[1]["messages"] == upstream.bodies[2]["messages"]
