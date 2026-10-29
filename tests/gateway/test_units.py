"""Unit tests of the gateway building blocks. All values are fictional (ADR 0005)."""

from __future__ import annotations

import asyncio
import itertools
import json

import pytest
from gateway_helpers import TEST_TENANT_KEY, chunk
from hypothesis import given, settings
from hypothesis import strategies as st

from pii_guard.gateway import DetectionCache, GatewayConfig, Mode, SseRestorer, collect_texts
from pii_guard.gateway.request import InvalidChatRequestError, UnsupportedContentError
from pii_guard.gateway.restore import JsonEscapingSession, restore_completion, restore_text
from pii_guard.gateway.stream import iter_sse_data
from pii_guard.types import EntityType, Span
from pii_guard.vault import Vault, VaultSession


def make_session() -> tuple[VaultSession, dict[str, str]]:
    session = Vault(bytes.fromhex(TEST_TENANT_KEY)).session()
    values = {
        "PERSON": "Teszt Elek",
        "EMAIL": "teszt.elek@example.com",
        "ADDRESS": 'Fő utca 1. "B" lépcsőház',
    }
    text = " | ".join(values.values())
    spans, cursor = [], 0
    for kind, value in values.items():
        start = text.index(value, cursor)
        spans.append(Span(start, start + len(value), EntityType(kind), value, 1.0, "rules"))
        cursor = start + len(value)
    masked = session.mask(text, spans)
    placeholders = dict(zip(values, masked.split(" | "), strict=True))
    return session, placeholders


def split(text: str, cuts: list[int]) -> list[str]:
    points = sorted({c % (len(text) + 1) for c in cuts} | {0, len(text)})
    return [text[a:b] for a, b in itertools.pairwise(points)]


# --- SSE restoration: any chunking --------------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(
    cuts=st.lists(st.integers(min_value=0, max_value=500), max_size=60),
    filler=st.text(alphabet="ab [_]Z1", max_size=12),
    finish=st.booleans(),
)
def test_sse_restorer_any_chunking(cuts: list[int], filler: str, finish: bool) -> None:
    session, ph = make_session()
    masked = f"Kedves {ph['PERSON']}!{filler}[[{ph['EMAIL'][2:]} {ph['ADDRESS']}[[PERSON_ffff]]"
    expected = session.unmask(masked)
    restorer = SseRestorer(session)
    out = []
    for piece in split(masked, cuts):
        for payload in restorer.process(json.dumps(chunk({"content": piece}))):
            out.append(json.loads(payload)["choices"][0]["delta"].get("content", ""))
    tail = [json.dumps(chunk({}, finish="stop"))] if finish else []
    payloads = [p for t in tail for p in restorer.process(t)] + restorer.process("[DONE]")
    for payload in payloads:
        if payload != "[DONE]":
            out.append(json.loads(payload)["choices"][0]["delta"].get("content", ""))
    assert payloads[-1] == "[DONE]"
    assert "".join(out) == expected
    assert restorer.unresolved == ("[[PERSON_ffff]]",)
    assert restorer.masked_content() == {0: masked}


@settings(max_examples=200, deadline=None)
@given(cuts=st.lists(st.integers(min_value=0, max_value=300), max_size=40))
def test_sse_restorer_tool_call_arguments_json_safe(cuts: list[int]) -> None:
    session, ph = make_session()
    arguments = json.dumps({"to": ph["EMAIL"], "address": ph["ADDRESS"], "who": ph["PERSON"]})
    restorer = SseRestorer(session)
    out = []
    pieces = split(arguments, cuts)
    for i, piece in enumerate(pieces):
        delta = {"tool_calls": [{"index": 0, "function": {"arguments": piece}}]}
        finish = "tool_calls" if i == len(pieces) - 1 else None
        for payload in restorer.process(json.dumps(chunk(delta, finish=finish))):
            calls = json.loads(payload)["choices"][0]["delta"].get("tool_calls") or []
            out.extend(c["function"]["arguments"] for c in calls)
    assert json.loads("".join(out)) == {
        "to": "teszt.elek@example.com",
        "address": 'Fő utca 1. "B" lépcsőház',
        "who": "Teszt Elek",
    }


def test_sse_restorer_flushes_without_finish_and_passes_other_payloads() -> None:
    session, ph = make_session()
    restorer = SseRestorer(session)
    first = restorer.process(json.dumps(chunk({"content": "Hi " + ph["PERSON"][:5]})))
    assert json.loads(first[0])["choices"][0]["delta"]["content"] == "Hi "
    assert restorer.process("not json") == ["not json"]
    assert restorer.process("[1]") == ["[1]"]
    usage = json.dumps({"choices": [], "usage": {"total_tokens": 3}})
    assert json.loads(restorer.process(usage)[0])["usage"] == {"total_tokens": 3}
    middle = restorer.process(json.dumps(chunk({"content": ph["PERSON"][5:] + " [["})))
    assert json.loads(middle[0])["choices"][0]["delta"]["content"] == "Teszt Elek "
    rest = restorer.finish()
    assert restorer.finish() == []
    assert json.loads(rest[0])["choices"][0]["delta"]["content"] == "[["
    assert json.loads(rest[0])["id"] == "chatcmpl-test"


def test_sse_restorer_flushes_tool_calls_on_finish_into_a_new_entry() -> None:
    session, ph = make_session()
    restorer = SseRestorer(session)
    pieces = ['{"a": "' + ph["PERSON"][:6], ph["PERSON"][6:] + '", "b": "[[']
    out = []
    for piece in pieces:
        delta = {"tool_calls": [{"index": 2, "function": {"arguments": piece}}]}
        for payload in restorer.process(json.dumps(chunk(delta))):
            out.append(json.loads(payload)["choices"][0]["delta"]["tool_calls"][0])
    final = restorer.process(json.dumps({"choices": [{"index": 0, "finish_reason": "stop"}]}))
    calls = json.loads(final[0])["choices"][0]["delta"]["tool_calls"]
    assert calls == [{"index": 2, "function": {"arguments": "[["}}]
    joined = "".join(c["function"]["arguments"] for c in out) + "[["
    assert joined == '{"a": "Teszt Elek", "b": "[['


def test_iter_sse_data() -> None:
    async def lines():
        for line in ["data: a", "data:b", "", ": comment", "event: x", "", "data: c"]:
            yield line

    async def collect():
        return [d async for d in iter_sse_data(lines())]

    assert asyncio.run(collect()) == ["a\nb", "c"]


# --- Restore -------------------------------------------------------------------------------


def test_restore_text_reports_value_spans() -> None:
    session, ph = make_session()
    text, spans, unresolved = restore_text(session, f"A {ph['PERSON']}, {ph['EMAIL']} [[X_abcd]]")
    assert text == "A Teszt Elek, teszt.elek@example.com [[X_abcd]]"
    assert [(text[s.start : s.end], s.entity_type) for s in spans] == [
        ("Teszt Elek", EntityType.PERSON),
        ("teszt.elek@example.com", EntityType.EMAIL),
    ]
    assert unresolved == ("[[X_abcd]]",)
    assert text == session.unmask(f"A {ph['PERSON']}, {ph['EMAIL']} [[X_abcd]]")


def test_json_escaping_session() -> None:
    session, ph = make_session()
    result = JsonEscapingSession(session).unmask_with_report(f'{{"a": "{ph["ADDRESS"]}"}}')
    assert json.loads(result.text) == {"a": 'Fő utca 1. "B" lépcsőház'}


def test_restore_completion_all_fields() -> None:
    session, ph = make_session()
    body = {
        "choices": [
            {
                "index": 0,
                "message": {
                    "content": [{"type": "text", "text": ph["PERSON"]}],
                    "refusal": ph["EMAIL"],
                    "function_call": {"arguments": json.dumps({"x": ph["ADDRESS"]})},
                    "tool_calls": [{"function": {"arguments": "[[PERSON_ffff]]"}}],
                },
            },
            "junk",
            {"index": 2},
        ]
    }
    report = restore_completion(session, body)
    message = body["choices"][0]["message"]
    assert message["content"][0]["text"] == "Teszt Elek"
    assert message["refusal"] == "teszt.elek@example.com"
    assert json.loads(message["function_call"]["arguments"]) == {"x": 'Fő utca 1. "B" lépcsőház'}
    assert list(report.unresolved) == ["[[PERSON_ffff]]"]
    assert "Teszt" not in repr(report)
    assert restore_completion(session, {"choices": None}).unresolved == {}


# --- Request collection --------------------------------------------------------------------


def test_collect_texts_masks_json_keys_and_nested_values() -> None:
    args = {"Teszt Elek": {"emails": ["teszt.elek@example.com"]}, "n": 1}
    body = {
        "model": "m",
        "messages": [
            {"role": "assistant", "tool_calls": [{"function": {"arguments": json.dumps(args)}}]},
            {"role": "assistant", "function_call": {"arguments": "not json Teszt Elek"}},
            {"role": "function", "name": "lookup", "content": None},
            {"role": "assistant", "reasoning_content": "thinking", "tool_calls": [None]},
        ],
    }
    collected = collect_texts(body)
    texts = sorted(s.text for s in collected.slots)
    assert "Teszt Elek" in texts and "teszt.elek@example.com" in texts
    assert "not json Teszt Elek" in texts and "thinking" in texts
    # A function result's name is only checked as an identifier, never masked.
    assert {s.kind for s in collected.slots if s.text == "lookup"} == {"identifier"}
    for slot in collected.slots:
        slot.write(slot.text.replace("Teszt Elek", "[[PERSON_aaaa]]"))
    collected.finalize()
    rewritten = json.loads(body["messages"][0]["tool_calls"][0]["function"]["arguments"])
    assert rewritten == {"[[PERSON_aaaa]]": {"emails": ["teszt.elek@example.com"]}, "n": 1}
    assert "Teszt" not in repr(collected.slots[0])


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (
            {"model": "m", "messages": [{"role": "user", "content": [{"type": "image_url"}]}]},
            UnsupportedContentError,
        ),
        (
            {"model": "m", "messages": [{"role": "user", "content": [{"type": "x" * 40}]}]},
            UnsupportedContentError,
        ),
        (
            {"model": "m", "messages": [{"role": "user", "content": ["text"]}]},
            InvalidChatRequestError,
        ),
        (
            {"model": "m", "messages": [{"role": "user", "content": [{"type": "text"}]}]},
            InvalidChatRequestError,
        ),
        (
            {"model": "m", "messages": [{"role": "assistant", "tool_calls": {}}]},
            InvalidChatRequestError,
        ),
        (
            {"model": "m", "messages": [{"role": "assistant", "tool_calls": ["x"]}]},
            InvalidChatRequestError,
        ),
    ],
)
def test_collect_texts_rejects(body: dict, error: type[Exception]) -> None:
    with pytest.raises(error):
        collect_texts(body)


# --- Cache and config -----------------------------------------------------------------------


def test_cache_stores_offsets_only_and_expires() -> None:
    now = [0.0]
    cache = DetectionCache(2, ttl_seconds=10, clock=lambda: now[0])
    text = "Teszt Elek írt"
    span = Span(0, 10, EntityType.PERSON, "Teszt Elek", 0.9, "llm")
    key = cache.key("s1", "hu", "audit", text)
    cache.put(key, [span])
    assert "Teszt" not in repr(cache._data) and b"Teszt" not in key[1]
    assert cache.get(key, text) == [span]
    assert cache.get(cache.key("s2", "hu", "audit", text), text) is None
    assert cache.get(cache.key("s1", "en", "audit", text), text) is None
    assert cache.get(key, "short") is None  # offsets don't fit: a miss, never a bad span
    now[0] = 11
    assert cache.get(key, text) is None
    for i in range(3):
        cache.put(cache.key("s1", "hu", "c", str(i)), [])
    assert len(cache) == 2
    cache.drop_session("s1")
    assert len(cache) == 0
    disabled = DetectionCache(0)
    disabled.put(key, [span])
    assert len(disabled) == 0
    assert "entries" in repr(cache)


def test_gateway_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_GATEWAY_MODE", "fast")
    monkeypatch.setenv("PII_GUARD_GATEWAY_DETECTION_TIMEOUT", "5")
    monkeypatch.setenv("PII_GUARD_GATEWAY_KEEP_TYPES", "organization, ")
    monkeypatch.setenv("PII_GUARD_LLM_DETECTOR_REASONING_EFFORT", "minimal")
    config = GatewayConfig()
    assert config.mode is Mode.FAST
    assert config.detection_timeout == 5
    assert config.keep_types == frozenset({EntityType.ORGANIZATION})
    assert config.llm_reasoning_effort == "minimal"
    assert GatewayConfig(keep_types="").keep_types == frozenset()


@pytest.mark.parametrize("nested", [False, True], ids=["top-level", "nested"])
@pytest.mark.parametrize("serialized", [False, True], ids=["object", "json-string"])
def test_json_key_collision_does_not_replace_object(nested: bool, serialized: bool) -> None:
    original = {"Teszt Elek": 1, "TESZT ELEK": 2}
    args = {"outer": [{"inner": original}]} if nested else original
    function = {"arguments": json.dumps(args) if serialized else args}
    body = {"model": "m", "messages": [{"role": "assistant", "function_call": function}]}
    collected = collect_texts(body)
    for slot in collected.slots:
        slot.write("[[PERSON_aaaa]]" if slot.text.casefold() == "teszt elek" else slot.text)
    with pytest.raises(
        InvalidChatRequestError, match="masking JSON object keys produced a collision"
    ) as exc:
        collected.finalize()
    assert "Teszt" not in str(exc.value)
    assert "TESZT" not in str(exc.value)
    # Reject before clearing the colliding object or serializing a lossy replacement.
    assert original == {"Teszt Elek": 1, "TESZT ELEK": 2}
    assert function["arguments"] == (json.dumps(args) if serialized else args)
