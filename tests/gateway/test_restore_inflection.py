"""Non-streaming restore matches streaming and ``/v1/unmask`` on inflected forms (LAB-1194).

A Hungarian suffix the model writes after a placeholder can change the restored stem
(``[[PERSON_x]]nak`` -> ``Minta Máriának``). Every restore path has to go through the vault
with the suffix, so they all agree. All values are fictional (ADR 0005).
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import FakeLlm, MockUpstream, completion, make_app

from pii_guard.gateway.restore import JsonEscapingSession, restore_completion, restore_text
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, StreamUnmasker, Vault, VaultSession

TEST_KEY = bytes.fromhex("0f" * 32)

# (value, entity type, suffix the model writes, expected restored form)
CASES = [
    ("Minta Mária", "PERSON", "nak", "Minta Máriának"),  # long-vowel stem: Mária -> Máriá-
    ("Minta Mária", "PERSON", "val", "Minta Máriával"),
    ("Kiss Tóth", "PERSON", "val", "Kiss Tóthtal"),  # old orthography th
    ("Gipsz Kovácz", "PERSON", "val", "Gipsz Kováczcal"),  # old orthography cz
    ("Placeholder Kft.", "ORGANIZATION", "-vel", "Placeholder Kft.-vel"),
    ("Teszt Elek", "PERSON", "kel", "Teszt Elekkel"),
]
IDS = [expected for *_, expected in CASES]


def _session(value: str, entity_type: str, *, case_sensitive: bool) -> tuple[VaultSession, str]:
    vault = Vault(TEST_KEY, case_sensitive_placeholders=case_sensitive)
    session = vault.session()
    text = f"Szia, {value} itt van."
    start = text.index(value)
    span = Span(start, start + len(value), EntityType(entity_type), value, 1.0, "test")
    masked = session.mask(text, [span])
    token = PLACEHOLDER_RE.search(masked)
    assert token is not None
    return session, token.group(0)


def _stream(session: VaultSession | JsonEscapingSession, text: str) -> str:
    """One character per chunk: the hardest split for the streaming unmasker."""
    unmasker = StreamUnmasker(session)  # type: ignore[arg-type]
    out = [unmasker.feed(char) for char in text]
    out.append(unmasker.flush())
    return "".join(out)


@pytest.mark.parametrize("case_sensitive", [False, True], ids=["default", "case-sensitive"])
@pytest.mark.parametrize(("value", "entity_type", "suffix", "expected"), CASES, ids=IDS)
def test_text_restore_matches_streaming_and_unmask(
    value: str, entity_type: str, suffix: str, expected: str, case_sensitive: bool
) -> None:
    session, token = _session(value, entity_type, case_sensitive=case_sensitive)
    answer = f"Írtam {token}{suffix}, és {token} is tudja."
    want = f"Írtam {expected}, és {value} is tudja."

    restored, spans, unresolved = restore_text(session, answer)

    assert restored == want
    assert restored == session.unmask(answer) == _stream(session, answer)
    assert unresolved == ()
    # Spans cover the restored value (the inflected stem), not the suffix after it.
    stem = expected.removesuffix(suffix)
    assert [(restored[s.start : s.end], s.entity_type.value) for s in spans] == [
        (stem, entity_type),
        (value, entity_type),
    ]
    assert all(s.text == restored[s.start : s.end] for s in spans)


@pytest.mark.parametrize("case_sensitive", [False, True], ids=["default", "case-sensitive"])
@pytest.mark.parametrize(("value", "entity_type", "suffix", "expected"), CASES, ids=IDS)
def test_tool_arguments_restore_matches_streaming(
    value: str, entity_type: str, suffix: str, expected: str, case_sensitive: bool
) -> None:
    session, token = _session(value, entity_type, case_sensitive=case_sensitive)
    arguments = json.dumps({"to": token, "note": f"Írj {token}{suffix}!"}, ensure_ascii=False)
    call = {"id": "c1", "type": "function", "function": {"name": "f", "arguments": arguments}}
    body = {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": f"{token}{suffix}",
                    "tool_calls": [call],
                },
            }
        ]
    }

    report = restore_completion(session, body)

    message = body["choices"][0]["message"]
    assert message["content"] == expected
    restored_args = message["tool_calls"][0]["function"]["arguments"]
    assert json.loads(restored_args) == {"to": value, "note": f"Írj {expected}!"}
    assert restored_args == _stream(JsonEscapingSession(session), arguments)
    assert report.unresolved == {}
    assert report.restored_spans[0][0] == expected


def test_unknown_placeholder_and_its_suffix_stay_as_is() -> None:
    session, _ = _session("Minta Mária", "PERSON", case_sensitive=False)
    answer = "Írj [[PERSON_ffff]]nak!"
    restored, spans, unresolved = restore_text(session, answer)
    assert restored == answer == session.unmask(answer)
    assert spans == [] and unresolved == ("[[PERSON_ffff]]",)


# --- End to end: the gateway, non-streaming and streaming, on a model-added suffix ---------


def _suffixing_upstream(upstream: MockUpstream, *, stream: bool) -> httpx.MockTransport:
    """Answers ``Írtam <placeholder>nak.``: a suffix the input never had after the name."""

    def handler(request: httpx.Request) -> httpx.Response:
        upstream.requests.append(request)
        body = json.loads(request.content)
        token = PLACEHOLDER_RE.search(body["messages"][-1]["content"])
        assert token is not None
        content = f"Írtam {token.group(0)}nak."
        if not stream:
            return httpx.Response(200, json=completion(content))
        events = [
            {"id": "x", "object": "chat.completion.chunk", "model": "m",
             "choices": [{"index": 0, "delta": {"content": char}, "finish_reason": None}]}
            for char in content
        ]  # fmt: skip
        lines = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
        return httpx.Response(
            200,
            content=(lines + "data: [DONE]\n\n").encode(),
            headers={"content-type": "text/event-stream"},
        )

    return httpx.MockTransport(handler)


def _gateway_answer(*, stream: bool) -> str:
    upstream = MockUpstream()
    app = make_app(upstream, llm=FakeLlm(["Minta Mária"]))
    app.state.gateway_transport = _suffixing_upstream(upstream, stream=stream)
    payload = {
        "model": "m",
        "messages": [{"role": "user", "content": "Minta Mária holnap jön."}],
        "stream": stream,
    }
    with TestClient(app) as http:
        response = http.post("/v1/chat/completions", json=payload)
        assert response.status_code == 200
        if not stream:
            return response.json()["choices"][0]["message"]["content"]
        parts = []
        for line in response.text.splitlines():
            if line.startswith("data: ") and line != "data: [DONE]":
                for choice in json.loads(line[6:]).get("choices", []):
                    parts.append(choice.get("delta", {}).get("content") or "")
        return "".join(parts)


def test_gateway_non_streaming_restore_matches_streaming() -> None:
    assert _gateway_answer(stream=False) == "Írtam Minta Máriának."
    assert _gateway_answer(stream=True) == "Írtam Minta Máriának."
