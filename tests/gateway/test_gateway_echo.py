"""``X-PII-Guard-Echo: masked``: the gateway echoes what the upstream saw and said.

All values are fictional (ADR 0005). The upstream is an ``httpx.MockTransport``.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from gateway_helpers import FakeLlm, MockUpstream, conversation_turn_one, leaked_values, make_app

import pii_guard.gateway.stream as stream_module
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE

ECHO = {"X-PII-Guard-Echo": "masked"}


def _events(raw: str) -> list[str]:
    return [line[6:] for line in raw.splitlines() if line.startswith("data: ")]


def test_non_streaming_echo_carries_masked_request_and_answer() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one()},
            headers=ECHO,
        )
    assert response.status_code == 200
    body = response.json()
    echo = body["pii_guard"]
    sent = upstream.bodies[0]["messages"]
    assert echo["masked_messages"] == [{"role": m["role"], "content": m["content"]} for m in sent]
    assert leaked_values(json.dumps(echo, ensure_ascii=False).encode()) == []
    masked = echo["masked_answer"][0]["content"]
    assert PLACEHOLDER_RE.search(masked)
    # The restored answer is still the real one.
    assert "Teszt Elek" in body["choices"][0]["message"]["content"]


def test_streaming_echo_frames_the_upstream_stream() -> None:
    upstream = MockUpstream(stream_chunks=lambda t: [t[i : i + 4] for i in range(0, len(t), 4)])
    with TestClient(make_app(upstream)) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one(), "stream": True},
            headers=ECHO,
        )
    events = _events(response.text)
    first = json.loads(events[0])
    assert first["object"] == "pii_guard.masked_request"
    assert first["messages"][1]["content"] == upstream.bodies[0]["messages"][1]["content"]
    assert events[-1] == "[DONE]"
    last = json.loads(events[-2])
    assert last["object"] == "pii_guard.masked_answer"
    assert PLACEHOLDER_RE.search(last["choices"][0]["content"])
    echoed = (events[0] + events[-2]).encode()
    assert leaked_values(json.dumps(json.loads(events[0])).encode()) == []
    assert "Teszt Elek" not in echoed.decode()
    restored = "".join(
        c["choices"][0]["delta"].get("content") or ""
        for c in map(json.loads, events[1:-2])
        if c.get("choices")
    )
    assert "Teszt Elek" in restored


def test_streaming_echo_marks_an_over_cap_choice_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    # LAB-1581: a choice past the retention cap is marked, not silently left out.
    monkeypatch.setattr(stream_module, "MAX_MASKED_CONTENT_CHARS", 8)
    upstream = MockUpstream(stream_chunks=lambda t: [t[i : i + 4] for i in range(0, len(t), 4)])
    with TestClient(make_app(upstream)) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one(), "stream": True},
            headers=ECHO,
        )
    events = _events(response.text)
    last = json.loads(events[-2])
    assert last["object"] == "pii_guard.masked_answer"
    assert last["choices"] == [{"index": 0, "content": None, "truncated": True}]
    restored = "".join(
        c["choices"][0]["delta"].get("content") or ""
        for c in map(json.loads, events[1:-2])
        if c.get("choices")
    )
    assert "Teszt Elek" in restored  # the client's answer is whole; only the echo copy is cut


def test_streaming_echo_of_a_short_answer_is_not_marked_truncated() -> None:
    upstream = MockUpstream(stream_chunks=lambda t: [t])
    with TestClient(make_app(upstream)) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one(), "stream": True},
            headers=ECHO,
        )
    last = json.loads(_events(response.text)[-2])
    assert [sorted(c) for c in last["choices"]] == [["content", "index"]]


def test_without_the_header_nothing_is_echoed() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        body = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": conversation_turn_one()}
        ).json()
        stream = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one(), "stream": True},
        ).text
    assert "pii_guard" not in body
    assert "pii_guard." not in stream


def test_invalid_echo_header_is_rejected() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one()},
            headers={"X-PII-Guard-Echo": "values"},
        )
    assert response.status_code == 400
    assert upstream.requests == []


class _OrgLlm(FakeLlm):
    """Also finds the fictional organization, which the default policy keeps."""

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        spans = super().detect(text, language)
        start = text.find(ORG)
        if start >= 0:
            spans.append(Span(start, start + len(ORG), EntityType.ORGANIZATION, ORG, 0.9, "llm"))
        return spans


ORG = "Minta Kft"
# An astral character first: offsets are code points, not UTF-16 units.
KEPT_MESSAGE = f"\U0001f600 Teszt Elek a {ORG} nevében ír."


def _kept_request(stream: bool) -> dict[str, object]:
    return {
        "model": "m",
        "messages": [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": KEPT_MESSAGE},
        ],
        "stream": stream,
    }


@pytest.mark.parametrize("stream", [False, True])
def test_echo_reports_kept_spans_as_type_and_offsets(stream: bool) -> None:
    # LAB-1180: a value kept by policy is reported per message, without the value.
    upstream = MockUpstream()
    with TestClient(make_app(upstream, llm=_OrgLlm())) as http:
        response = http.post("/v1/chat/completions", json=_kept_request(stream), headers=ECHO)
        again = http.post("/v1/chat/completions", json=_kept_request(stream), headers=ECHO)
    start = KEPT_MESSAGE.index(ORG)
    expected = [[], [{"type": "ORGANIZATION", "start": start, "end": start + len(ORG)}]]
    for answer in (response, again):  # the second request hits the detection cache
        if stream:
            echo = json.loads(_events(answer.text)[0])
            assert echo["object"] == "pii_guard.masked_request"
        else:
            echo = answer.json()["pii_guard"]
        assert echo["kept_spans"] == expected
        assert ORG not in json.dumps(echo["kept_spans"], ensure_ascii=False)
    # The kept value is still forwarded as is.
    assert ORG in upstream.bodies[0]["messages"][1]["content"]


def test_echo_kept_spans_align_with_masked_messages() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        echo = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one()},
            headers=ECHO,
        ).json()["pii_guard"]
    assert len(echo["kept_spans"]) == len(echo["masked_messages"])
    assert all(spans == [] for spans in echo["kept_spans"])
