"""A reasoning upstream that spends its whole budget thinking answers ``content: null`` (LAB-1334).

``muse-spark-1.3`` with a small ``max_tokens`` returns reasoning and no answer. The gateway must
pass that through as is: no crash, ``content`` stays ``null`` (never a placeholder or masked
text to forward), the reasoning is restored, ``finish_reason`` reaches the client (the
Playground turns ``length`` + an empty answer into a "raise max tokens" hint, LAB-1335), and
the echo and traffic log record an empty answer. All values are fictional (ADR 0005).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway_helpers import (
    EMAILS,
    TEST_TENANT_KEY,
    UPSTREAM_KEY,
    UPSTREAM_URL,
    FakeLlm,
    chunk,
    completion,
    conversation_turn_one,
)

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway import GatewayConfig, Mode, build_mode_detectors
from pii_guard.observability import ObservabilitySettings
from pii_guard.vault import PLACEHOLDER_RE

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

ECHO = {"X-PII-Guard-Echo": "masked"}


def _email_placeholder(request: httpx.Request) -> str:
    """The placeholder the gateway forwarded for the user's e-mail address."""
    body = json.loads(request.content)
    text = json.dumps(body["messages"], ensure_ascii=False)
    kind, ident = next((k, i) for k, i in PLACEHOLDER_RE.findall(text) if k == "EMAIL")
    return f"[[{kind}_{ident}]]"


def _reasoning_only(request: httpx.Request) -> httpx.Response:
    """Answers like a reasoning model out of budget: reasoning, ``content: null``."""
    placeholder = _email_placeholder(request)
    reasoning = f"The user wrote from {placeholder}; I should draft a short letter"
    if json.loads(request.content).get("stream"):
        events = [
            chunk({"role": "assistant", "content": None}),
            chunk({"reasoning_content": reasoning[:20]}),
            chunk({"reasoning_content": reasoning[20:]}),
            chunk({"content": None}, finish="length"),
        ]
        sse = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
        return httpx.Response(
            200,
            content=(sse + "data: [DONE]\n\n").encode(),
            headers={"content-type": "text/event-stream"},
        )
    body: dict[str, Any] = completion("")
    choice = body["choices"][0]
    choice["message"] = {"role": "assistant", "content": None, "reasoning_content": reasoning}
    choice["finish_reason"] = "length"
    body["usage"] = {"prompt_tokens": 40, "completion_tokens": 120, "total_tokens": 160}
    return httpx.Response(200, json=body)


def _app(traffic: str = "masked") -> FastAPI:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL, upstream_api_key=UPSTREAM_KEY
    )
    app = create_app(settings, ObservabilitySettings(traffic_log=traffic))
    config = GatewayConfig(mode=Mode.AUDIT)
    app.state.gateway_config = config
    app.state.gateway_transport = httpx.MockTransport(_reasoning_only)
    app.state.gateway_detectors = build_mode_detectors(settings, config, llm_detector=FakeLlm())
    return app


def _chat(client: TestClient, **extra: Any) -> httpx.Response:
    body = {"model": "muse-spark-1.3", "max_tokens": 120, "messages": conversation_turn_one()}
    return client.post("/v1/chat/completions", json={**body, **extra}, headers=ECHO)


def _events(raw: str) -> list[str]:
    return [line[6:] for line in raw.splitlines() if line.startswith("data: ")]


def test_non_streaming_null_content_passes_through_with_finish_reason() -> None:
    with TestClient(_app()) as client:
        response = _chat(client)
        (event,) = client.get("/v1/traffic").json()["events"]
    assert response.status_code == 200
    body = response.json()
    (choice,) = body["choices"]
    # Null stays null: not "", not a placeholder, nothing masked handed to the client.
    assert choice["message"]["content"] is None
    assert choice["finish_reason"] == "length"
    # The reasoning is restored like any other text field.
    assert EMAILS[0] in choice["message"]["reasoning_content"]
    assert not PLACEHOLDER_RE.search(choice["message"]["reasoning_content"])
    # Echo: an empty masked answer, not a crash or a "None" string.
    assert body["pii_guard"]["masked_answer"] == [{"index": 0, "content": ""}]
    # Traffic log: an ordinary ok event; the masked side never holds the real value.
    assert event["outcome"] == "ok"
    assert event["usage"]["completion_tokens"] == 120
    assert EMAILS[0] not in json.dumps(event, ensure_ascii=False)


def test_streaming_null_content_passes_through_with_finish_reason() -> None:
    with TestClient(_app(traffic="full")) as client:
        response = _chat(client, stream=True)
        (event,) = client.get("/v1/traffic").json()["events"]
    assert response.status_code == 200
    events = _events(response.text)
    assert events[-1] == "[DONE]"
    assert json.loads(events[0])["object"] == "pii_guard.masked_request"
    echo = json.loads(events[-2])
    assert echo["object"] == "pii_guard.masked_answer"
    assert echo["choices"] == []  # no answer text at all
    chunks = [json.loads(e) for e in events[1:-2]]
    deltas = [c["choices"][0]["delta"] for c in chunks]
    # No answer text was made up, and content never became masked text.
    assert all(d.get("content") is None for d in deltas)
    reasoning = "".join(d.get("reasoning_content") or "" for d in deltas)
    assert EMAILS[0] in reasoning and not PLACEHOLDER_RE.search(reasoning)
    assert chunks[-1]["choices"][0]["finish_reason"] == "length"
    assert event["outcome"] == "ok" and event["stream"]
    assert event["response"]["masked"]["content"] == {}
