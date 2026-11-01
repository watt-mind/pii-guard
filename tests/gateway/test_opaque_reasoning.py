"""Opaque provider blobs require session provenance; synthetic values only (LAB-1753)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import TEST_TENANT_KEY, chunk, completion, make_app

from pii_guard.gateway import opaque_reasoning as opaque
from pii_guard.gateway.request import CollectedTexts, UnsupportedContentError
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


@pytest.mark.parametrize(("protocol", "key"), CASES)
def test_fresh_plaintext_in_opaque_fields_is_never_forwarded(protocol: str, key: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=answer(protocol, key))

    with TestClient(make_app(transport=httpx.MockTransport(handler))) as client:
        response = client.post(
            f"/v1/{endpoint(protocol)}", json=body(protocol, key, "synthetic.person@example.org")
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_content"
    assert "synthetic.person" not in response.text
    assert not requests


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
        refused = client.post(
            f"/s/other-session/v1/{endpoint(protocol)}", json=body(protocol, key, BLOB)
        )
        assert refused.status_code == 400
        assert len(requests) == 2


def test_expired_or_recreated_session_cannot_reuse_blobs() -> None:
    now = [0.0]
    vault = Vault(bytes.fromhex(TEST_TENANT_KEY), ttl_seconds=1, clock=lambda: now[0])
    session, _ = vault.session_or_create("same-session")
    opaque.remember(session, "chat", "data", BLOB)
    collected = CollectedTexts([], [], opaque=[("data", BLOB)])
    opaque.validate(session, "chat", collected)
    assert BLOB not in repr(collected)
    now[0] = 2
    fresh, _ = vault.session_or_create("same-session")
    with pytest.raises(UnsupportedContentError):
        opaque.validate(fresh, "chat", collected)


def test_storage_is_bounded_and_never_retains_raw_blobs(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session_or_create("test-session")[0]
    monkeypatch.setattr(opaque, "MAX_BLOBS", 2)
    for text in ["first", "second", "third"]:
        opaque.remember(session, "chat", "data", text)
    assert len(session.opaque_reasoning) == 2
    assert all(isinstance(key, bytes) and len(key) == 32 for key in session.opaque_reasoning)
    with pytest.raises(UnsupportedContentError):
        opaque.validate(session, "chat", CollectedTexts([], [], opaque=[("data", "first")]))


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
    with pytest.raises(UnsupportedContentError):
        opaque.validate(session, "messages", CollectedTexts([], [], opaque=[("signature", BLOB)]))
    monkeypatch.setattr(opaque, "MAX_STREAM_CHARS", 1)
    stream.observe(delta)
    stream.observe({"type": "content_block_stop", "index": 0})
    with pytest.raises(UnsupportedContentError):
        opaque.validate(session, "messages", CollectedTexts([], [], opaque=[("signature", BLOB)]))


def test_provenance_is_bound_to_protocol_and_field() -> None:
    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session_or_create("test-session")[0]
    opaque.remember(session, "chat", "data", BLOB)
    for protocol, key in [("messages", "data"), ("chat", "signature")]:
        with pytest.raises(UnsupportedContentError):
            opaque.validate(session, protocol, CollectedTexts([], [], opaque=[(key, BLOB)]))


def test_chat_finishing_another_choice_does_not_authorize_incomplete_blob() -> None:
    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session_or_create("test-session")[0]
    stream = opaque.OpaqueStream(session, "chat")
    stream.observe(chunk({"reasoning_details": [{"index": 0, "data": BLOB}]}, index=1))
    stream.observe(chunk({}, finish="stop", index=0))
    with pytest.raises(UnsupportedContentError):
        opaque.validate(session, "chat", CollectedTexts([], [], opaque=[("data", BLOB)]))
    stream.observe(chunk({}, finish="stop", index=1))
    opaque.validate(session, "chat", CollectedTexts([], [], opaque=[("data", BLOB)]))


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
