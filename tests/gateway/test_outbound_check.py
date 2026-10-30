"""The outbound re-check: a value the session knows that survives masking blocks the request.

LAB-1500. Each payload kind is tested twice: as the gateway masks it (passed, the header says
so) and with a masking fault that writes one text back unmasked (blocked: 422
``outbound_check_failed``, nothing reaches the upstream, types and counts only). The fault
stands in for any bug between detection and the bytes sent; the re-check must catch it
wherever the text is. All values are fictional (ADR 0005).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import (
    NAMES,
    TEST_TENANT_KEY,
    UPSTREAM_KEY,
    UPSTREAM_URL,
    FakeLlm,
    MockUpstream,
    make_app,
)
from test_image_parts import FakeOcr as TajOcr
from test_image_parts import Sam, data_url, png
from test_responses import ResponsesUpstream, muse_body

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway import Gateway, GatewayConfig, Mode, build_mode_detectors
from pii_guard.gateway.outbound import (
    MIN_DIGITS,
    MIN_MODEL_CHARS,
    OUTBOUND_CHECK_HEADER,
    blocks,
    check_slots,
)
from pii_guard.gateway.request import ImageSlot, TextSlot
from pii_guard.observability import ObservabilitySettings
from pii_guard.types import EntityType, Span
from pii_guard.vault import Unmasked, Vault
from pii_guard.vault.known import KnownValue
from pii_guard.visual import SamClient

PERSON = NAMES[0]  # Teszt Elek
HEADER = OUTBOUND_CHECK_HEADER.lower()


@pytest.fixture
def leak(monkeypatch: pytest.MonkeyPatch) -> Callable[[Callable[[str], bool]], None]:
    """Install a masking fault: texts matching ``hit`` are written back as the client sent them."""

    def install(hit: Callable[[str], bool]) -> None:
        original = Gateway._write

        def faulty(slots: list[TextSlot], masked: list[str], *args: Any, **kwargs: Any) -> None:
            original(slots, masked, *args, **kwargs)
            for slot in slots:
                if slot.kind != "identifier" and hit(slot.text):
                    slot.write(slot.text)

        monkeypatch.setattr(Gateway, "_write", staticmethod(faulty))

    return install


def assert_blocked(response: httpx.Response, upstream: MockUpstream, **types: int) -> None:
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "outbound_check_failed"
    assert response.headers[HEADER] == "blocked"
    assert upstream.requests == []
    assert PERSON not in response.text
    message = response.json()["error"]["message"]
    for entity_type, count in types.items():
        assert f"{entity_type} ({count})" in message


def assert_passed(response: httpx.Response, upstream: MockUpstream) -> None:
    assert response.status_code == 200, response.text
    assert response.headers[HEADER] == "passed"
    assert len(upstream.requests) == 1
    assert PERSON not in upstream.requests[0].content.decode()


def chat(client: TestClient, messages: list[dict[str, Any]], **extra: Any) -> httpx.Response:
    return client.post(
        "/v1/chat/completions", json={"model": "test-model", "messages": messages, **extra}
    )


# --- Chat Completions: every payload kind ---------------------------------------------------

USER = [{"role": "user", "content": f"Szia, {PERSON} vagyok. Mit tudsz rólam?"}]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": f"Send an e-mail. Escalations go to {PERSON}.",
            "parameters": {"type": "object", "properties": {"to": {"type": "string"}}},
        },
    }
]

TOOL_CALL = [
    {"role": "user", "content": f"Írj {PERSON} nevében."},
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "send_email",
                    "arguments": json.dumps({"signed": PERSON}, ensure_ascii=False),
                },
            }
        ],
    },
    {"role": "tool", "tool_call_id": "call_1", "content": f"Delivered, signed by {PERSON}."},
]

CASES: dict[str, tuple[list[dict[str, Any]], dict[str, Any], Callable[[str], bool]]] = {
    "message": (USER, {}, lambda t: t.startswith("Szia")),
    "tool definition": (USER, {"tools": TOOLS}, lambda t: t.startswith("Send an e-mail")),
    "tool-call arguments": (TOOL_CALL, {}, lambda t: t == PERSON),
    "tool result": (TOOL_CALL, {}, lambda t: t.startswith("Delivered")),
}


@pytest.mark.parametrize("kind", list(CASES))
def test_chat_payload_passes_when_masked(kind: str) -> None:
    messages, extra, _ = CASES[kind]
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as client:
        assert_passed(chat(client, messages, **extra), upstream)


@pytest.mark.parametrize("kind", list(CASES))
def test_chat_payload_is_blocked_when_a_value_survives(
    kind: str, leak: Callable[[Callable[[str], bool]], None]
) -> None:
    messages, extra, hit = CASES[kind]
    leak(hit)
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as client:
        assert_blocked(chat(client, messages, **extra), upstream, PERSON=1)


@pytest.mark.parametrize("stream", [False, True])
def test_streamed_chat_passes_and_blocks_before_anything_is_sent(
    stream: bool, leak: Callable[[Callable[[str], bool]], None]
) -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as client:
        passed = chat(client, USER, stream=stream)
        assert_passed(passed, upstream)
        assert passed.headers["content-type"].startswith(
            "text/event-stream" if stream else "application/json"
        )
    leak(lambda t: t.startswith("Szia"))
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as client:
        blocked = chat(client, USER, stream=stream)
    # A refusal before the upstream call is a plain JSON error, never a half-open stream.
    assert blocked.headers["content-type"].startswith("application/json")
    assert_blocked(blocked, upstream, PERSON=1)


def test_a_value_from_an_earlier_turn_blocks_too(
    leak: Callable[[Callable[[str], bool]], None],
) -> None:
    """The session's values from earlier requests count, not only this request's detections."""
    upstream = MockUpstream()
    url = "/s/s-outbound-1/v1/chat/completions"
    llm = FakeLlm()
    with TestClient(make_app(upstream, llm=llm)) as client:
        first = client.post(url, json={"model": "m", "messages": USER})
        assert first.status_code == 200
        # The next turn's detector misses the name; the sweep masks it from the session...
        later = [{"role": "user", "content": f"Még egyszer: {PERSON}."}]
        llm.names = ()
        ok = client.post(url, json={"model": "m", "messages": later})
        assert ok.headers[HEADER] == "passed"
        # ...and with the sweep broken, the session's value is caught on the way out.
        leak(lambda t: t.startswith("Még"))
        upstream.requests.clear()
        blocked = client.post(url, json={"model": "m", "messages": later})
    assert_blocked(blocked, upstream, PERSON=1)


# --- Responses API --------------------------------------------------------------------------

RESPONSES_CASES: dict[str, Callable[[str], bool]] = {
    "instructions": lambda t: t.startswith("You are a coding agent"),
    "function_call arguments": lambda t: t == "for Minta Mária",
    "function_call_output": lambda t: t.startswith("Read text file"),
    "tool definition": lambda t: t.startswith("Write a file"),
}


@pytest.mark.parametrize("stream", [False, True])
def test_responses_passes_when_masked(stream: bool) -> None:
    upstream = ResponsesUpstream()
    with TestClient(make_app(upstream)) as client:
        response = client.post("/v1/responses", json=muse_body(stream=stream))
    assert response.status_code == 200, response.text
    assert response.headers[HEADER] == "passed"
    assert len(upstream.requests) == 1


@pytest.mark.parametrize("kind", list(RESPONSES_CASES))
@pytest.mark.parametrize("stream", [False, True])
def test_responses_is_blocked_when_a_value_survives(
    kind: str, stream: bool, leak: Callable[[Callable[[str], bool]], None]
) -> None:
    leak(RESPONSES_CASES[kind])
    upstream = ResponsesUpstream()
    with TestClient(make_app(upstream)) as client:
        response = client.post("/v1/responses", json=muse_body(stream=stream))
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "outbound_check_failed"
    assert response.headers[HEADER] == "blocked"
    assert upstream.requests == []


# --- image transcripts and summaries --------------------------------------------------------


def image_app(upstream: MockUpstream) -> Any:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
        image_render="labels",  # the transcript and summary go upstream as a text part
    )
    config = GatewayConfig(mode=Mode.AUDIT)
    app = create_app(settings)
    app.state.gateway = Gateway(
        settings=settings,
        vault=Vault.from_settings(settings),
        config=config,
        detectors=build_mode_detectors(settings, config, llm_detector=FakeLlm()),
        transport=upstream.transport(),
        sam=SamClient(api_key="test-key", transport=httpx.MockTransport(Sam()), max_retries=0),
        ocr=TajOcr(),  # type: ignore[arg-type]
    )
    return app


IMAGE_MESSAGES = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": f"{PERSON} kártyája:"},
            {"type": "image_url", "image_url": {"url": data_url(png())}},
        ],
    }
]


def test_image_transcript_passes_when_masked() -> None:
    upstream = MockUpstream()
    with TestClient(image_app(upstream)) as client:
        response = chat(client, IMAGE_MESSAGES)
    assert_passed(response, upstream)
    forwarded = json.loads(upstream.requests[0].content)["messages"][-1]["content"]
    assert any("Masked transcript" in part.get("text", "") for part in forwarded)


def test_image_transcript_is_blocked_when_a_value_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # LAB-1689 sweeps the generated annotation before attaching it. Inject a fault
    # after that sweep so this still exercises a value surviving all masking.
    real = ImageSlot.annotate
    monkeypatch.setattr(
        ImageSlot,
        "annotate",
        lambda slot, text: real(slot, text + f"\nOwner: {PERSON}"),
    )
    upstream = MockUpstream()
    with TestClient(image_app(upstream)) as client:
        assert_blocked(chat(client, IMAGE_MESSAGES), upstream, PERSON=1)


# --- exemptions: what masking keeps on purpose never blocks ---------------------------------


def test_a_tool_name_the_session_holds_as_a_value_passes() -> None:
    """LAB-1324: an identifier that is a declared tool name goes as written; not a hit."""
    upstream = MockUpstream()
    tools = [{"type": "function", "function": {"name": "muse", "parameters": {}}}]
    messages = [{"role": "user", "content": "Kérdezd meg Muse-t, Teszt Elek kéri."}]
    with TestClient(make_app(upstream, llm=FakeLlm((*NAMES, "Muse")))) as client:
        response = chat(client, messages, tools=tools, tool_choice="auto")
    assert_passed(response, upstream)
    assert json.loads(upstream.requests[0].content)["tools"][0]["function"]["name"] == "muse"


# --- the short-value policy -----------------------------------------------------------------


def occurrence(
    chars: int, *, digits: bool = False, model: bool = False, known: bool = False
) -> Unmasked:
    return Unmasked(0, 0, chars, EntityType.PERSON, chars, digits, model_only=model, known=known)


def test_short_value_policy() -> None:
    # A value only the NER found needs MIN_MODEL_CHARS letters and digits.
    assert not blocks(occurrence(MIN_MODEL_CHARS - 1, model=True))  # "len", "pi", "89"
    assert blocks(occurrence(MIN_MODEL_CHARS, model=True))
    # Rules and the LLM: from 3, a known value's own minimum ("Ann").
    assert not blocks(occurrence(2))
    assert blocks(occurrence(3))
    # A number needs MIN_DIGITS digits, whoever found it.
    assert not blocks(occurrence(MIN_DIGITS - 1, digits=True))
    assert blocks(occurrence(MIN_DIGITS, digits=True))
    # The operator's known values always block.
    assert blocks(occurrence(3, known=True))
    assert blocks(occurrence(3, digits=True, known=True))


def test_short_occurrences_are_counted_not_blocked() -> None:
    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session()
    text = "Bo és 12345 és Anna"
    session.mask(
        text,
        [
            Span(0, 2, EntityType.PERSON, "Bo", 0.9, "ner"),
            Span(6, 11, EntityType.BANK_ACCOUNT, "12345", 1.0, "rules"),
            Span(15, 19, EntityType.PERSON, "Anna", 0.9, "ner"),
        ],
    )
    check = check_slots([TextSlot("Bo és 12345", lambda _: None)], session, "hu")
    assert check.result == "passed" and check.short == 2 and not check.hits
    check = check_slots([TextSlot("Anna írt", lambda _: None)], session, "hu")
    assert check.result == "blocked" and check.hits == {"PERSON": 1}


def test_a_short_known_value_blocks() -> None:
    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session()
    session.known_values.add([KnownValue("Ann", EntityType.PERSON)])
    check = check_slots([TextSlot("Ann írt", lambda _: None)], session, "hu")
    assert check.hits == {"PERSON": 1}
    # In an identifier too, tool name or not: a known value fails closed (LAB-1324).
    check = check_slots(
        [TextSlot("Ann", lambda _: None, "identifier")],
        session,
        "hu",
        tool_names=frozenset({"ann"}),
    )
    assert check.hits == {"PERSON": 1}


# --- headers, traffic event and log ---------------------------------------------------------


def traffic_app(upstream: MockUpstream) -> Any:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL, upstream_api_key=UPSTREAM_KEY
    )
    app = create_app(settings, ObservabilitySettings(traffic_log="masked"))
    config = GatewayConfig(mode=Mode.AUDIT)
    app.state.gateway_config = config
    app.state.gateway_transport = upstream.transport()
    app.state.gateway_detectors = build_mode_detectors(settings, config, llm_detector=FakeLlm())
    return app


@pytest.fixture
def records(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    with caplog.at_level(logging.DEBUG):
        yield caplog


def test_traffic_event_and_log_carry_the_result(
    leak: Callable[[Callable[[str], bool]], None], records: pytest.LogCaptureFixture
) -> None:
    upstream = MockUpstream()
    with TestClient(traffic_app(upstream)) as client:
        assert chat(client, USER).status_code == 200
        leak(lambda t: t.startswith("Szia"))
        assert chat(client, USER).status_code == 422
        passed, blocked = client.get("/v1/traffic").json()["events"][-2:]
    assert passed["outcome"] == "ok"
    check = passed["outbound_check"]
    assert check["result"] == "passed" and check["hits"] == {} and check["short"] == 0
    assert check["texts"] == 2 and check["ms"] >= 0  # the message and ``model`` (LAB-1563)
    assert blocked["outcome"] == "blocked"
    error = dict(blocked["error"])
    assert error.pop("message")  # the API error message, types and counts only (LAB-1314)
    assert error == {
        "code": "outbound_check_failed",
        "status": 422,
        "entity_types": {"PERSON": 1},
    }
    assert blocked["outbound_check"]["result"] == "blocked"
    assert blocked["outbound_check"]["hits"] == {"PERSON": 1}
    assert blocked["request"] == {"masked": None}  # nothing went out, nothing to show
    assert PERSON not in json.dumps([passed, blocked], ensure_ascii=False)
    lines = [r.getMessage() for r in records.records]
    assert any("outbound=blocked outbound_hits=PERSON:1" in line for line in lines)
    assert any("outbound=passed" in line for line in lines)
    assert not any(PERSON in line for line in lines)


def test_a_session_created_by_a_blocked_request_is_dropped(
    leak: Callable[[Callable[[str], bool]], None],
) -> None:
    """Fail closed: the values of a request nobody forwarded are not kept (LAB-1316)."""
    leak(lambda t: t.startswith("Szia"))
    upstream = MockUpstream()
    app = make_app(upstream)
    with TestClient(app) as client:
        response = client.post(
            "/s/s-outbound-dropped/v1/chat/completions", json={"model": "m", "messages": USER}
        )
        assert_blocked(response, upstream)
        assert len(client.app.state.gateway.vault) == 0


# --- beyond the walker's slots: the serialized-body scan (LAB-1563) --------------------------


def _blind_spot_body() -> dict[str, Any]:
    """A session value in a provider-signed blob: forwarded opaque, never a walker slot."""
    return {
        "model": "m",
        "messages": [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": "x",
                "reasoning_details": [{"type": "reasoning.encrypted", "signature": PERSON}],
            },
        ],
    }


def test_serialized_scan_sees_what_the_walker_does_not() -> None:
    from pii_guard.gateway.outbound import check_outbound
    from pii_guard.gateway.request import collect_texts

    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session()
    text = f"Szia, {PERSON} vagyok."
    session.mask(text, [Span(6, 16, EntityType.PERSON, PERSON, 0.9, "llm")])
    body = _blind_spot_body()
    slots = collect_texts(json.loads(json.dumps(body))).slots
    assert check_slots(slots, session, "hu").result == "passed"  # the walker is blind here
    check = check_outbound(body, collect_texts, session, "hu")
    assert check.result == "blocked" and check.hits == {"PERSON": 1}


def test_a_value_in_an_opaque_blob_blocks_the_request_end_to_end() -> None:
    upstream = MockUpstream()
    body = _blind_spot_body()
    body["messages"][0]["content"] = f"Szia, {PERSON} vagyok."  # the session learns it here
    with TestClient(make_app(upstream)) as client:
        response = client.post("/v1/chat/completions", json=body)
    assert_blocked(response, upstream, PERSON=1)


def test_serialized_scan_exempts_an_issued_id_enclosing_a_value() -> None:
    from pii_guard.gateway.outbound import check_outbound
    from pii_guard.gateway.request import collect_texts

    digits = "123456788"
    issued = frozenset({f"call-{digits}"})
    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session()
    session.mask(digits, [Span(0, 9, EntityType.BANK_ACCOUNT, digits, 1.0, "rules")])
    body = {
        "model": "m",
        "messages": [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call-{digits}",
                        "type": "function",
                        "function": {"name": "send", "arguments": "{}"},
                    }
                ],
            },
        ],
    }
    assert check_outbound(body, collect_texts, session, "hu", issued=issued).result == "passed"
    assert check_outbound(body, collect_texts, session, "hu").result == "blocked"


def test_enclosing_json_string_handles_trailing_escaped_backslash() -> None:
    from pii_guard.gateway.outbound import _enclosing_json_string

    serialized = json.dumps({"path": "C:\\", "id": "call-123456788"})
    start = serialized.index("123456788")
    assert _enclosing_json_string(serialized, start, start + 9) == "call-123456788"
