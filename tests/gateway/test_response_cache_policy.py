"""Model output is not a certified detection result (LAB-1756)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import TEST_TENANT_KEY, UPSTREAM_KEY, UPSTREAM_URL, chunk, completion, make_app

from pii_guard.config import Settings

EMAIL = "synthetic.cache@example.org"
ANSWER = f"Contact {EMAIL} for help."


def _request(protocol: str, role: str, text: str, *, stream: bool = False) -> dict[str, Any]:
    key = "input" if protocol == "responses" else "messages"
    body: dict[str, Any] = {
        "model": "test-model",
        key: [{"role": role, "content": text}],
        "stream": stream,
    }
    if protocol == "messages":
        body["max_tokens"] = 64
    return body


def _response(protocol: str) -> dict[str, Any]:
    if protocol == "chat":
        return completion(ANSWER)
    if protocol == "responses":
        return {
            "id": "resp_fixture",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "msg_fixture",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": ANSWER}],
                }
            ],
        }
    return {
        "id": "msg_fixture",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": ANSWER}],
        "stop_reason": "end_turn",
    }


def _events(protocol: str) -> list[dict[str, Any]]:
    if protocol == "chat":
        return [chunk({"content": ANSWER}), chunk({}, finish="stop")]
    if protocol == "responses":
        return [
            {
                "type": "response.output_text.delta",
                "item_id": "msg_fixture",
                "output_index": 0,
                "content_index": 0,
                "delta": ANSWER,
            },
            {"type": "response.completed", "response": _response(protocol)},
        ]
    return [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": ANSWER},
        },
        {"type": "content_block_stop", "index": 0},
        {"type": "message_stop"},
    ]


@pytest.mark.parametrize("protocol", ["chat", "responses", "messages"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("role", ["user", "assistant"])
@pytest.mark.parametrize("action", ["block", "mask"])
def test_reused_model_output_gets_full_detection(
    protocol: str, stream: bool, role: str, action: str
) -> None:
    sent: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if json.loads(request.content).get("stream"):
            data = "".join(f"data: {json.dumps(event)}\n\n" for event in _events(protocol))
            if protocol == "chat":
                data += "data: [DONE]\n\n"
            return httpx.Response(200, content=data, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=_response(protocol))

    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
        policy_overrides=f"EMAIL={action}",
    )
    path = "chat/completions" if protocol == "chat" else protocol
    with TestClient(make_app(settings=settings, transport=httpx.MockTransport(upstream))) as client:
        first = client.post(
            f"/s/cache-policy/v1/{path}", json=_request(protocol, "user", "Hello", stream=stream)
        )
        assert first.status_code == 200, first.text
        assert EMAIL in first.text
        second = client.post(f"/s/cache-policy/v1/{path}", json=_request(protocol, role, ANSWER))
    if action == "block":
        assert second.status_code == 422, second.text
        assert second.json()["error"]["code"] == "blocked_entity"
        assert len(sent) == 1
    else:
        assert second.status_code == 200, second.text
        assert len(sent) == 2
        assert EMAIL not in sent[1].content.decode()
        assert "[[EMAIL_" in sent[1].content.decode()
