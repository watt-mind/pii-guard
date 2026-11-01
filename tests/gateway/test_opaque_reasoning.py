"""Opaque provider blobs require session provenance, else they are stripped; synthetic
values only (LAB-1753)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import TEST_TENANT_KEY, chunk, completion, make_app

from pii_guard.gateway import opaque_reasoning as opaque
from pii_guard.gateway.request import CollectedTexts, OpaqueBlob
from pii_guard.vault import Vault

BLOB = "provider-signed-synthetic-blob"
CASES = [
    ("chat", "data"),
    ("chat", "signature"),
    ("chat", "encrypted_content"),
    ("responses", "encrypted_content"),
    ("messages", "signature"),
    ("messages", "data"),
]


def body(protocol: str, key: str, value: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"model": "test-model"}
    if protocol == "responses":
        result["input"] = [{"role": "user", "content": "Hello"}]
        if value is not None:
            result["input"].insert(0, {"type": "reasoning", key: value})
    else:
        result["messages"] = [{"role": "user", "content": "Hello"}]
        if protocol == "messages":
            result["max_tokens"] = 64
        if value is not None:
            message: dict[str, Any] = {"role": "assistant", "content": "Hello"}
            if protocol == "chat":
                message["reasoning_details"] = [{"type": "reasoning.encrypted", key: value}]
            else:
                block = {"type": "thinking", "thinking": "Hello", key: value}
                if key == "data":
                    block = {"type": "redacted_thinking", key: value}
                message["content"] = [block]
            result["messages"].insert(0, message)
    return result


def endpoint(protocol: str) -> str:
    return "chat/completions" if protocol == "chat" else protocol


def answer(protocol: str, key: str) -> dict[str, Any]:
    if protocol == "chat":
        result = completion("Hello")
        result["choices"][0]["message"]["reasoning_details"] = [
            {"type": "reasoning.encrypted", key: BLOB}
        ]
        return result
    if protocol == "responses":
        return {
            "id": "resp_test",
            "object": "response",
            "status": "completed",
            "output": [{"type": "reasoning", key: BLOB}],
        }
    block = {"type": "thinking", "thinking": "Hello", key: BLOB}
    if key == "data":
        block = {"type": "redacted_thinking", key: BLOB}
    return {"id": "msg_test", "type": "message", "role": "assistant", "content": [block]}


def events(protocol: str, key: str) -> list[dict[str, Any]]:
    if protocol == "chat":
        return [
            chunk({"reasoning_details": [{"index": 0, "type": "reasoning.encrypted", key: part}]})
            for part in [BLOB[:10], BLOB[10:]]
        ] + [chunk({}, finish="stop")]
    if protocol == "responses":
        return [
            {"type": "response.output_item.done", "item": answer(protocol, key)["output"][0]},
            {"type": "response.completed", "response": answer(protocol, key)},
        ]
    if key == "data":
        return [
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "redacted_thinking", "data": BLOB},
            },
            {"type": "content_block_stop", "index": 0},
            {"type": "message_stop"},
        ]
    return [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": "", "signature": ""},
        },
        *[
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": part},
            }
            for part in [BLOB[:10], BLOB[10:]]
        ],
        {"type": "content_block_stop", "index": 0},
        {"type": "message_stop"},
    ]


def forwarded_reasoning(protocol: str, sent: dict[str, Any]) -> list[Any]:
    """Every reasoning item/block of the forwarded body (none: all stripped)."""
    if protocol == "responses":
        return [item for item in sent["input"] if item.get("type") == "reasoning"]
    found: list[Any] = []
    for message in sent["messages"]:
        if protocol == "chat":
            found += message.get("reasoning_details", [])
        elif isinstance(message["content"], list):
            found += [b for b in message["content"] if "thinking" in b["type"]]
    return found


def known(session: Any, protocol: str, key: str, value: str) -> bool:
    return opaque.verified(session, protocol, key, value)


@pytest.mark.parametrize(("protocol", "key"), CASES)
def test_fresh_plaintext_in_opaque_fields_is_stripped_never_forwarded(
    protocol: str, key: str
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=answer(protocol, key))

    with TestClient(make_app(transport=httpx.MockTransport(handler))) as client:
        response = client.post(
            f"/v1/{endpoint(protocol)}", json=body(protocol, key, "synthetic.person@example.org")
        )
    assert response.status_code == 200, response.text
    assert response.headers[opaque.OPAQUE_STRIPPED_HEADER] == "1"
    assert len(requests) == 1
    sent = json.loads(requests[0].content)
    assert "synthetic.person" not in requests[0].content.decode()
    assert forwarded_reasoning(protocol, sent) == []
    # Only the reasoning was removed: the conversation itself is forwarded.
    conversation = sent["input"] if protocol == "responses" else sent["messages"]
    assert any(m.get("content") == "Hello" for m in conversation)


def test_only_unverified_blobs_are_stripped_and_thinking_text_goes_with_its_block() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=answer("messages", "signature"))

    request_body = body("messages", "signature")
    with TestClient(make_app(transport=httpx.MockTransport(handler))) as client:
        assert client.post("/s/mixed/v1/messages", json=request_body).status_code == 200
        request_body["messages"].insert(
            0,
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Readable fixture text", "signature": BLOB},
                    {"type": "thinking", "thinking": "Imported fixture", "signature": "forged"},
                    {"type": "redacted_thinking", "data": "forged-data"},
                    {"type": "text", "text": "Hello"},
                ],
            },
        )
        response = client.post("/s/mixed/v1/messages", json=request_body)
    assert response.status_code == 200, response.text
    assert response.headers[opaque.OPAQUE_STRIPPED_HEADER] == "2"
    sent = requests[-1].content.decode()
    assert BLOB in sent and "Readable fixture text" in sent
    assert "forged" not in sent and "Imported fixture" not in sent
    assert '"text": "Hello"' in sent or '"text":"Hello"' in sent


@pytest.mark.parametrize(("protocol", "key"), CASES)
@pytest.mark.parametrize("stream", [False, True])
def test_provider_blob_roundtrip_is_unchanged_and_session_scoped(
    protocol: str, key: str, stream: bool
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if json.loads(request.content).get("stream"):
            data = "".join(f"data: {json.dumps(e)}\n\n" for e in events(protocol, key))
            return httpx.Response(200, content=data, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=answer(protocol, key))

    with TestClient(make_app(transport=httpx.MockTransport(handler))) as client:
        first = client.post(
            f"/s/source-session/v1/{endpoint(protocol)}",
            json={**body(protocol, key), "stream": stream},
        )
        assert first.status_code == 200, first.text
        second = client.post(
            f"/s/source-session/v1/{endpoint(protocol)}", json=body(protocol, key, BLOB)
        )
        assert second.status_code == 200, second.text
        assert BLOB in requests[-1].content.decode()
        stripped = client.post(
            f"/s/other-session/v1/{endpoint(protocol)}", json=body(protocol, key, BLOB)
        )
        assert stripped.status_code == 200, stripped.text
        assert stripped.headers[opaque.OPAQUE_STRIPPED_HEADER] == "1"
        assert BLOB not in requests[-1].content.decode()
        assert len(requests) == 3


def test_expired_or_recreated_session_cannot_reuse_blobs() -> None:
    now = [0.0]
    vault = Vault(bytes.fromhex(TEST_TENANT_KEY), ttl_seconds=1, clock=lambda: now[0])
    session, _ = vault.session_or_create("same-session")
    opaque.remember(session, "chat", "data", BLOB)
    assert known(session, "chat", "data", BLOB)
    blob = OpaqueBlob("data", BLOB)
    assert BLOB not in repr(CollectedTexts([], [], opaque=[blob]))
    now[0] = 2
    fresh, _ = vault.session_or_create("same-session")
    assert not known(fresh, "chat", "data", BLOB)


def test_storage_is_bounded_and_never_retains_raw_blobs(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session_or_create("test-session")[0]
    monkeypatch.setattr(opaque, "MAX_BLOBS", 2)
    for text in ["first", "second", "third"]:
        opaque.remember(session, "chat", "data", text)
    assert len(session.opaque_reasoning) == 2
    assert all(isinstance(key, bytes) and len(key) == 32 for key in session.opaque_reasoning)
    assert not known(session, "chat", "data", "first")
    assert known(session, "chat", "data", "third")


def test_incomplete_or_overflowed_signature_stream_does_not_authorize_fragments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session_or_create("test-session")[0]
    stream = opaque.OpaqueStream(session, "messages")
    delta = {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "signature_delta", "signature": BLOB},
    }
    stream.observe(delta)
    assert not known(session, "messages", "signature", BLOB)
    monkeypatch.setattr(opaque, "MAX_STREAM_CHARS", 1)
    stream.observe(delta)
    stream.observe({"type": "content_block_stop", "index": 0})
    stream.finish()
    assert not known(session, "messages", "signature", BLOB)


def test_provenance_is_bound_to_protocol_and_field() -> None:
    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session_or_create("test-session")[0]
    opaque.remember(session, "chat", "data", BLOB)
    for protocol, key in [("messages", "data"), ("chat", "signature")]:
        assert not known(session, protocol, key, BLOB)


def test_chat_finishing_another_choice_does_not_authorize_incomplete_blob() -> None:
    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session_or_create("test-session")[0]
    stream = opaque.OpaqueStream(session, "chat")
    stream.observe(chunk({"reasoning_details": [{"index": 0, "data": BLOB}]}, index=1))
    stream.observe(chunk({}, finish="stop", index=0))
    assert not known(session, "chat", "data", BLOB)
    stream.observe(chunk({}, finish="stop", index=1))
    assert known(session, "chat", "data", BLOB)


def test_empty_fragments_and_oversized_blobs_are_not_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session_or_create("test-session")[0]
    stream = opaque.OpaqueStream(session, "messages")
    for _ in range(10):
        stream.observe(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": ""},
            }
        )
    assert not stream.parts
    monkeypatch.setattr(opaque, "MAX_BLOB_CHARS", 1)
    opaque.remember(session, "chat", "data", BLOB)
    assert not session.opaque_reasoning


def test_malformed_upstream_shapes_do_not_authorize_or_raise() -> None:
    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session_or_create("test-session")[0]
    for protocol, malformed in [
        ("chat", {"choices": 1}),
        ("chat", {"choices": [{"delta": {"reasoning_details": 1}}]}),
        ("chat", {"choices": [{"delta": {"reasoning_details": [{"index": [], "data": BLOB}]}}]}),
        ("responses", {"output": 1}),
        ("messages", {"content": 1}),
        (
            "messages",
            {
                "type": "content_block_delta",
                "index": [],
                "delta": {"type": "signature_delta", "signature": BLOB},
            },
        ),
    ]:
        opaque.OpaqueStream(session, protocol).observe(malformed)
    assert not session.opaque_reasoning


def test_stream_ending_without_finish_reason_still_records_complete_blobs() -> None:
    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session_or_create("test-session")[0]
    stream = opaque.OpaqueStream(session, "chat")
    for part in (BLOB[:10], BLOB[10:]):
        stream.observe(chunk({"reasoning_details": [{"index": 0, "data": part}]}))
    assert not known(session, "chat", "data", BLOB)
    stream.finish()  # the restorer's end of stream, with no finish_reason seen
    assert known(session, "chat", "data", BLOB)


@pytest.mark.parametrize("protocol", ["chat", "messages", "responses"])
def test_restorer_end_of_stream_records_blobs(protocol: str) -> None:
    requests: list[httpx.Request] = []
    key = {"chat": "data", "messages": "signature", "responses": "encrypted_content"}[protocol]
    stream_events = events(protocol, key)
    if protocol == "chat":
        stream_events = stream_events[:-1]  # no finish_reason chunk
    elif protocol == "messages":
        stream_events = stream_events[:-2]  # no content_block_stop or message_stop

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if json.loads(request.content).get("stream"):
            data = "".join(f"data: {json.dumps(e)}\n\n" for e in stream_events)
            return httpx.Response(200, content=data, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=answer(protocol, key))

    with TestClient(make_app(transport=httpx.MockTransport(handler))) as client:
        first = client.post(
            f"/s/eos/v1/{endpoint(protocol)}", json={**body(protocol, key), "stream": True}
        )
        assert first.status_code == 200, first.text
        second = client.post(f"/s/eos/v1/{endpoint(protocol)}", json=body(protocol, key, BLOB))
    assert second.status_code == 200, second.text
    assert opaque.OPAQUE_STRIPPED_HEADER not in second.headers
    assert BLOB in requests[-1].content.decode()


def test_unindexed_openrouter_reasoning_details_are_keyed_by_id_or_type() -> None:
    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session_or_create("test-session")[0]
    stream = opaque.OpaqueStream(session, "chat")
    # OpenRouter-shaped chunks: complete details, no ``index``; one encrypted blob split
    # over two chunks under one id, and a text detail whose signature arrives whole.
    detail = {"type": "reasoning.encrypted", "id": "rd_fixture", "format": "fixture-v1"}
    for chunk_body in (
        {"type": "reasoning.text", "text": "Thinking.", "signature": "sig-fixture"},
        {**detail, "data": "enc-part-one-"},
        {**detail, "data": "enc-part-two"},
        {"type": "reasoning.summary", "summary": "Summary."},
    ):
        stream.observe(chunk({"reasoning_details": [chunk_body]}))
    stream.observe(chunk({}, finish="stop"))
    assert known(session, "chat", "signature", "sig-fixture")
    assert known(session, "chat", "data", "enc-part-one-enc-part-two")
    assert known(session, "chat", "data", "enc-part-one-")
    # Fragments of different details never form one digest.
    assert not known(session, "chat", "signature", "sig-fixtureenc-part-one-")
