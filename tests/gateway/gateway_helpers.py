"""Gateway test helpers: a fake LLM detector, a mock upstream and a fictional conversation.

Every value here is fictional (ADR 0005). The tenant key is a fixed test key.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import FastAPI

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway import GatewayConfig, Mode, build_mode_detectors
from pii_guard.gateway.placeholder_note import PLACEHOLDER_NOTE
from pii_guard.types import DetectionError, EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE

TEST_TENANT_KEY = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"
UPSTREAM_URL = "https://upstream.test/v1"
UPSTREAM_KEY = "sk-test-upstream-key-0000"

# Fictional values. Names are found by the fake LLM detector, the rest by the real rules.
# "Minta Máriának" is a stem-changing inflection (Mária -> Máriá-nak): labelled as a whole word,
# as an LLM detector reports it (docs/contracts.md, evaluation fixtures).
NAMES = ("Teszt Elek", "Minta Mária", "Minta Máriának", "Jane Placeholder")
EMAILS = ("teszt.elek@example.com", "minta.maria@example.org", "jane.placeholder@example.net")
PHONES = ("+36 30 123 4567", "+44 20 7946 0958")
IBAN = "HU42 1177 3016 1111 1018 0000 0000"
LABELLED_VALUES = (*NAMES, *EMAILS, *PHONES, IBAN)


class FakeLlm:
    """Stands in for the LLM detector: finds the fictional names. Counts its calls."""

    name = "llm"
    model = "fake-llm"

    def __init__(
        self, names: Sequence[str] = NAMES, *, delay: float = 0.0, fail: bool = False
    ) -> None:
        self.names = tuple(names)
        self.delay = delay
        self.fail = fail
        self.calls = 0
        self._lock = threading.Lock()

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        with self._lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise DetectionError("fake llm failed")
        spans = []
        for name in self.names:
            for match in re.finditer(re.escape(name), text):
                spans.append(
                    Span(match.start(), match.end(), EntityType.PERSON, name, 0.9, self.name)
                )
        return spans


Handler = Callable[[httpx.Request], httpx.Response]


def without_note(body: dict[str, Any]) -> dict[str, Any]:
    """``body`` without the gateway's placeholder note (LAB-1471)."""
    messages = body.get("messages")
    if isinstance(messages, list) and messages and messages[0] == NOTE_MESSAGE:
        body = {**body, "messages": messages[1:]}
    return body


NOTE_MESSAGE = {"role": "system", "content": PLACEHOLDER_NOTE}


@dataclass
class MockUpstream:
    """Records every forwarded request; answers by echoing the placeholders it received."""

    stream_chunks: Callable[[str], list[str]] | None = None
    status: int = 200
    error_body: dict[str, Any] | None = None
    answer: Callable[[dict[str, Any]], str] | None = None
    requests: list[httpx.Request] = field(default_factory=list)

    @property
    def bodies(self) -> list[dict[str, Any]]:
        """The forwarded bodies without the placeholder note, so message indexes match the
        client's (``raw_bodies`` keeps it; the note itself: ``test_placeholder_note.py``)."""
        return [without_note(body) for body in self.raw_bodies]

    @property
    def raw_bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]

    def default_answer(self, body: dict[str, Any]) -> str:
        last = body["messages"][-1]["content"]
        text = last if isinstance(last, str) else json.dumps(last)
        placeholders = list(dict.fromkeys(PLACEHOLDER_RE.findall(text)))
        tokens = [f"[[{t}_{i}]]" for t, i in placeholders]
        return "Rendben: " + ", ".join(tokens) + "."

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status >= 400:
            return httpx.Response(self.status, json=self.error_body or {"error": {}})
        body = json.loads(request.content)
        answer = (self.answer or self.default_answer)(body)
        if body.get("stream"):
            chunks = self.stream_chunks(answer) if self.stream_chunks else [answer]
            return httpx.Response(
                200,
                content=sse_body(chunks),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json=completion(answer, model=body["model"]))

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def completion(content: str, *, model: str = "test-model", tool_calls: Any = None) -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1_800_000_000,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def chunk(delta: dict[str, Any], finish: str | None = None, index: int = 0) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 1_800_000_000,
        "model": "test-model",
        "choices": [{"index": index, "delta": delta, "finish_reason": finish}],
    }


def sse_body(pieces: Sequence[str], *, done: bool = True) -> bytes:
    events = [chunk({"role": "assistant", "content": ""})]
    events += [chunk({"content": piece}) for piece in pieces]
    events.append(chunk({}, finish="stop"))
    out = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
    if done:
        out += "data: [DONE]\n\n"
    return out.encode()


def make_app(
    upstream: MockUpstream | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    llm: FakeLlm | None = None,
    config: GatewayConfig | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    settings = settings or Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
    )
    # Audit mode by default here: the fake LLM detector is what finds names in these tests.
    config = config or GatewayConfig(mode=Mode.AUDIT)
    app = create_app(settings)
    app.state.gateway_config = config
    app.state.gateway_transport = transport or (upstream or MockUpstream()).transport()
    app.state.gateway_detectors = build_mode_detectors(
        settings, config, llm_detector=llm or FakeLlm()
    )
    return app


def conversation_turn_one() -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "Jogi asszisztens vagy. Az ügyfél neve Teszt Elek."},
        {
            "role": "user",
            "content": (
                "Szia! Teszt Elek vagyok, e-mail: teszt.elek@example.com, telefon: "
                "+36 30 123 4567. Írj egy levelet Minta Máriának!"
            ),
        },
    ]


def full_conversation() -> list[dict[str, Any]]:
    """A hu + en multi-turn conversation with tool calls and tool results."""
    return [
        *conversation_turn_one(),
        {
            "role": "assistant",
            "content": "Elküldöm a levelet Minta Máriának.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "send_email",
                        "arguments": json.dumps(
                            {
                                "to": "minta.maria@example.org",
                                "recipient_name": "Minta Mária",
                                "body": f"Tisztelt Minta Mária! Üdv: Teszt Elek ({IBAN})",
                                "cc": ["jane.placeholder@example.net"],
                            }
                        ),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "Delivered to minta.maria@example.org (Minta Mária). Reply from Jane "
            "Placeholder, +44 20 7946 0958.",
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Please also brief Jane Placeholder (jane.placeholder@example.net, "
                    "+44 20 7946 0958) and pay to IBAN " + IBAN + ".",
                }
            ],
        },
    ]


def leaked_values(raw: bytes) -> list[str]:
    """Labelled values present in a forwarded body, raw or JSON-decoded (incl. escapes)."""
    text = raw.decode("utf-8")
    decoded = json.dumps(json.loads(raw), ensure_ascii=False)
    found = []
    for value in LABELLED_VALUES:
        escaped = json.dumps(value)[1:-1]
        if value in text or value in decoded or escaped in text:
            found.append(value)
        # A value split by whitespace changes (e.g. the IBAN without spaces).
        compact = value.replace(" ", "")
        if len(compact) > 8 and compact in text.replace(" ", ""):
            found.append(value + " (compact)")
    return found
