"""Restore of the legacy ``function_call`` and of custom tool input (LAB-1354).

Chat completions: ``delta.function_call.arguments`` (streamed; the whole message was already
restored) and ``tool_calls[].custom.input`` (whole and streamed). Responses API:
``custom_tool_call.input`` (whole and streamed), as regression guards. Arguments are JSON and
get JSON-escaped values; custom input is freeform text and is restored as is. Every path draws
on the response's one restore budget (LAB-1350).

Every value is fictional (ADR 0005).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import (
    TEST_TENANT_KEY,
    UPSTREAM_KEY,
    UPSTREAM_URL,
    MockUpstream,
    chunk,
    completion,
    make_app,
)

from pii_guard.config import Settings
from pii_guard.gateway.responses_restore import ResponsesSseRestorer, restore_response
from pii_guard.gateway.restore import restore_completion
from pii_guard.gateway.stream import DONE, SseRestorer
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, UnmaskOutputTooLargeError, Vault, VaultSession

NAME = "Teszt Elek"
QUOTED = 'Fő utca 1. "B" lépcsőház'


def _session(**extra: Any) -> VaultSession:
    return Vault(bytes.fromhex(TEST_TENANT_KEY), **extra).session()


def _placeholder(session: VaultSession, value: str, entity: EntityType) -> str:
    text = f"v {value}"
    return session.mask(text, [Span(2, len(text), entity, value, 1.0, "test")])[2:]


def _split(text: str, placeholder: str) -> tuple[str, str]:
    """``text`` cut in the middle of ``placeholder`` (``[[PERS`` + ``ON_x]]...``)."""
    cut = text.index(placeholder) + 6
    return text[:cut], text[cut:]


def _run(restorer: SseRestorer, payloads: list[dict[str, Any]], *, done: bool = True) -> list:
    out: list[str] = []
    for payload in payloads:
        out += restorer.process(json.dumps(payload))
    out += restorer.process(DONE) if done else restorer.finish()
    return [json.loads(item) for item in out if item != DONE]


def _deltas(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [choice["delta"] for event in events for choice in event.get("choices", [])]


# --- chat completions: legacy function_call, streamed -------------------------------------


@pytest.mark.parametrize("finish", [True, False], ids=["finish_reason", "stream_end"])
def test_streamed_function_call_arguments_are_restored_across_a_split(finish: bool) -> None:
    session = _session()
    ph = _placeholder(session, QUOTED, EntityType.ADDRESS)
    args = json.dumps({"address": ph, "note": "x"})
    first, second = _split(args, ph)
    payloads = [
        chunk({"role": "assistant", "function_call": {"name": "ship", "arguments": first}}),
        chunk({"function_call": {"arguments": second}}),
    ]
    if finish:
        payloads.append(chunk({}, finish="function_call"))
    events = _run(SseRestorer(session), payloads, done=finish)
    deltas = _deltas(events)
    restored = "".join(d.get("function_call", {}).get("arguments", "") for d in deltas)
    assert json.loads(restored) == {"address": QUOTED, "note": "x"}
    assert "[[" not in json.dumps(events)
    assert deltas[0]["function_call"]["name"] == "ship"


def test_held_back_function_call_tail_is_flushed_at_finish() -> None:
    session = _session()
    ph = _placeholder(session, NAME, EntityType.PERSON)
    payloads = [
        chunk({"function_call": {"name": "greet", "arguments": '{"to": "'}}),
        chunk({"function_call": {"arguments": ph}}),  # complete, but held: a suffix may follow
        chunk({}, finish="function_call"),
    ]
    events = _run(SseRestorer(session), payloads)
    assert events[-1]["choices"][0]["finish_reason"] == "function_call"
    # The opening quote is held with it: it may open a masked number (LAB-1361).
    assert events[-1]["choices"][0]["delta"]["function_call"]["arguments"] == '"' + NAME


# --- chat completions: custom tool input -------------------------------------------------


def test_custom_tool_input_is_restored_in_a_whole_completion() -> None:
    session = _session()
    ph = _placeholder(session, QUOTED, EntityType.ADDRESS)
    body = completion(
        "",
        tool_calls=[
            {"id": "call_1", "type": "custom", "custom": {"name": "shell", "input": f"go {ph}"}}
        ],
    )
    report = restore_completion(session, body)
    call = body["choices"][0]["message"]["tool_calls"][0]
    assert call["custom"]["input"] == f"go {QUOTED}"  # freeform: no JSON escaping
    assert call["custom"]["name"] == "shell"
    assert report.unresolved == {}


def test_unknown_placeholder_in_custom_input_is_counted() -> None:
    session = _session()
    body = completion(
        "", tool_calls=[{"type": "custom", "custom": {"name": "t", "input": "[[PERSON_000000]]"}}]
    )
    report = restore_completion(session, body)
    assert list(report.unresolved) == ["[[PERSON_000000]]"]


@pytest.mark.parametrize("finish", [True, False], ids=["finish_reason", "stream_end"])
def test_streamed_custom_tool_input_is_restored_across_a_split(finish: bool) -> None:
    session = _session()
    ph = _placeholder(session, QUOTED, EntityType.ADDRESS)
    text = f"deliver to {ph} today"
    first, second = _split(text, ph)
    payloads = [
        chunk(
            {
                "tool_calls": [
                    {"index": 0, "id": "c1", "type": "custom", "custom": {"name": "t", "input": ""}}
                ]
            }
        ),
        chunk({"tool_calls": [{"index": 0, "custom": {"input": first}}]}),
        chunk({"tool_calls": [{"index": 0, "custom": {"input": second}}]}),
    ]
    if finish:
        payloads.append(chunk({}, finish="tool_calls"))
    events = _run(SseRestorer(session), payloads, done=finish)
    restored = "".join(
        call.get("custom", {}).get("input", "")
        for delta in _deltas(events)
        for call in delta.get("tool_calls", [])
    )
    assert restored == f"deliver to {QUOTED} today"


def test_custom_and_function_tool_calls_stream_side_by_side() -> None:
    session = _session()
    ph = _placeholder(session, NAME, EntityType.PERSON)
    payloads = [
        chunk(
            {
                "tool_calls": [
                    {"index": 0, "type": "function", "function": {"name": "f", "arguments": ""}},
                    {"index": 1, "type": "custom", "custom": {"name": "c", "input": ""}},
                ]
            }
        ),
        chunk(
            {
                "tool_calls": [
                    {"index": 0, "function": {"arguments": f'{{"n": "{ph}'}},
                    {"index": 1, "custom": {"input": f"hi {ph}"}},
                ]
            }
        ),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"}'}}]}),
        chunk({}, finish="tool_calls"),
    ]
    events = _run(SseRestorer(session), payloads)
    by_index: dict[int, dict[str, str]] = {0: {}, 1: {}}
    for delta in _deltas(events):
        for call in delta.get("tool_calls", []):
            for field, inner in (("function", "arguments"), ("custom", "input")):
                if field in call:
                    got = by_index[call["index"]]
                    got[field] = got.get(field, "") + call[field].get(inner, "")
    assert json.loads(by_index[0]["function"]) == {"n": NAME}
    assert by_index[1]["custom"] == f"hi {NAME}"


# --- the restore budget (LAB-1350) covers the new paths ----------------------------------


def _long_secret(session: VaultSession) -> tuple[str, str]:
    value = "gh" + "p_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    return value, _placeholder(session, value, EntityType.SECRET)


@pytest.mark.parametrize("fmt", ["function_call", "custom"])
def test_streamed_new_paths_share_the_response_budget(fmt: str) -> None:
    session = _session(max_restored_chars=200)
    _, ph = _long_secret(session)

    def payload() -> dict[str, Any]:
        if fmt == "function_call":
            return chunk({"function_call": {"arguments": ph + " "}})
        return chunk({"tool_calls": [{"index": 0, "custom": {"input": ph + " "}}]})

    restorer = SseRestorer(session)
    with pytest.raises(UnmaskOutputTooLargeError):
        for _ in range(10):
            restorer.process(json.dumps(payload()))


def test_streamed_new_paths_and_content_draw_on_one_budget() -> None:
    session = _session(max_restored_chars=200)
    value, ph = _long_secret(session)
    assert 3 * len(value) < 200 < 6 * len(value)
    restorer = SseRestorer(session)
    for delta in (
        {"content": f"{ph} {ph} "},
        {"function_call": {"arguments": f"{ph} {ph} "}},
    ):
        restorer.process(json.dumps(chunk(delta)))
    with pytest.raises(UnmaskOutputTooLargeError):
        restorer.process(
            json.dumps(
                chunk({"tool_calls": [{"index": 0, "custom": {"input": ph + " " + ph + " "}}]})
            )
        )


def test_whole_completion_custom_input_is_charged_to_the_budget() -> None:
    session = _session(max_restored_chars=200)
    _, ph = _long_secret(session)
    body = completion(
        "", tool_calls=[{"type": "custom", "custom": {"name": "t", "input": " ".join([ph] * 10)}}]
    )
    with pytest.raises(UnmaskOutputTooLargeError):
        restore_completion(session, body)


# --- Responses API: custom_tool_call input (regression guards) ---------------------------


def test_responses_custom_tool_call_input_is_restored_whole() -> None:
    session = _session()
    ph = _placeholder(session, QUOTED, EntityType.ADDRESS)
    body = {
        "object": "response",
        "output": [{"type": "custom_tool_call", "call_id": "c1", "name": "t", "input": f"go {ph}"}],
    }
    restore_response(session, body)
    assert body["output"][0]["input"] == f"go {QUOTED}"


def test_responses_streamed_custom_tool_call_input_is_restored_across_a_split() -> None:
    session = _session()
    ph = _placeholder(session, QUOTED, EntityType.ADDRESS)
    text = f"go {ph}"
    first, second = _split(text, ph)
    restorer = ResponsesSseRestorer(session)
    out: list[tuple[str | None, str]] = []
    for part in (first, second):
        event = {"type": "response.custom_tool_call_input.delta", "output_index": 0, "delta": part}
        out += restorer.process(event["type"], json.dumps(event))
    done = {"type": "response.custom_tool_call_input.done", "output_index": 0, "input": text}
    out += restorer.process(done["type"], json.dumps(done))
    events = [json.loads(data) for _, data in out]
    deltas = "".join(e["delta"] for e in events if e["type"].endswith(".delta"))
    assert deltas == f"go {QUOTED}"
    assert events[-1]["input"] == f"go {QUOTED}"


# --- end to end through the gateway ------------------------------------------------------


@pytest.mark.parametrize("transport", ["whole", "completed", "item_added", "item_done"])
def test_responses_tool_escaping_is_limited_to_structural_fields(transport: str) -> None:
    session = _session()
    value = 'Teszt "Minta" \\ út'
    ph = _placeholder(session, value, EntityType.PERSON)
    plain = f'echo "{ph}"'
    metadata = {
        "arguments": plain,
        "input": plain,
        "nested": [
            {"type": "function_call", "arguments": plain},
            {"type": "custom_tool_call", "input": plain},
        ],
    }
    expected_metadata = {
        "arguments": f'echo "{value}"',
        "input": f'echo "{value}"',
        "nested": [
            {"type": "function_call", "arguments": f'echo "{value}"'},
            {"type": "custom_tool_call", "input": f'echo "{value}"'},
        ],
    }
    items = [
        {
            "type": "function_call",
            "arguments": json.dumps({"value": ph}),
            "input": plain,
            "metadata": metadata,
        },
        {
            "type": "custom_tool_call",
            "input": f'echo "{ph}"',
            "arguments": plain,
            "metadata": metadata,
        },
        {"type": "message", "arguments": plain, "input": plain, "metadata": metadata},
    ]
    if transport in ("whole", "completed"):
        body = {
            "output": items,
            "input": items,
            "metadata": metadata,
            "tools": [{"type": "function_call", "arguments": plain, "input": plain}],
        }
        if transport == "whole":
            restore_response(session, body)
        else:
            payload = {"type": "response.completed", "response": body}
            out = ResponsesSseRestorer(session).process(payload["type"], json.dumps(payload))
            body = json.loads(out[-1][1])["response"]
        assert body["metadata"] == expected_metadata
        assert body["tools"][0]["arguments"] == f'echo "{value}"'
        assert body["tools"][0]["input"] == f'echo "{value}"'
        assert body["input"] == body["output"]
        restored_items = body["output"]
    else:
        restored_items = []
        for item in items:
            event_type = "response.output_item." + transport.removeprefix("item_")
            payload = {"type": event_type, "item": item, "metadata": metadata}
            out = ResponsesSseRestorer(session).process(event_type, json.dumps(payload))
            restored = json.loads(out[-1][1])
            assert restored["metadata"] == expected_metadata
            restored_items.append(restored["item"])
    assert json.loads(restored_items[0]["arguments"]) == {"value": value}
    assert restored_items[0]["input"] == f'echo "{value}"'
    assert restored_items[1]["input"] == 'echo "Teszt \\"Minta\\" \\\\ út"'
    assert restored_items[1]["arguments"] == f'echo "{value}"'
    assert restored_items[2]["arguments"] == f'echo "{value}"'
    assert restored_items[2]["input"] == f'echo "{value}"'
    assert all(item["metadata"] == expected_metadata for item in restored_items)


@pytest.mark.parametrize("tool", ["function_call_arguments", "custom_tool_call_input"])
@pytest.mark.parametrize("header_only", [False, True])
def test_responses_tool_delta_done_and_completed_use_the_same_adapter(
    tool: str, header_only: bool
) -> None:
    session = _session()
    value = 'Teszt "Minta" \\ út'
    ph = _placeholder(session, value, EntityType.PERSON)
    is_json = tool == "function_call_arguments"
    field = "arguments" if is_json else "input"
    text = json.dumps({"value": ph}) if is_json else f'echo "{ph}"'
    restorer = ResponsesSseRestorer(session)
    out = []
    for part in _split(text, ph):
        event_type = f"response.{tool}.delta"
        payload = {"output_index": 0, "delta": part}
        if not header_only:
            payload["type"] = event_type
        out += restorer.process(event_type, json.dumps(payload))
    event_type = f"response.{tool}.done"
    payload = {
        "output_index": 0,
        field: text,
        "metadata": {"arguments": ph, "input": f'echo "{ph}"'},
    }
    if not header_only:
        payload["type"] = event_type
    out += restorer.process(event_type, json.dumps(payload))
    events = [json.loads(data) for _, data in out]
    joined = "".join(e["delta"] for e in events if "delta" in e)
    assert events[-1][field] == joined
    assert events[-1]["metadata"] == {"arguments": value, "input": f'echo "{value}"'}
    item = {"type": "function_call" if is_json else "custom_tool_call", field: text}
    payload = {"type": "response.completed", "response": {"output": [item]}}
    completed = restorer.process(payload["type"], json.dumps(payload))
    assert json.loads(completed[-1][1])["response"]["output"][0][field] == joined
    if is_json:
        assert json.loads(joined) == {"value": value}
    else:
        assert joined == 'echo "Teszt \\"Minta\\" \\\\ út"'


class _ToolUpstream(MockUpstream):
    """Answers with the placeholder it received, inside a tool call of the given format."""

    def __init__(self, fmt: str) -> None:
        super().__init__()
        self.fmt = fmt

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        ph = PLACEHOLDER_RE.search(body["messages"][-1]["content"]).group(0)  # type: ignore[union-attr]
        if not body.get("stream"):
            message: dict[str, Any] = {"role": "assistant", "content": None}
            if self.fmt == "function_call":
                message["function_call"] = {"name": "f", "arguments": json.dumps({"to": ph})}
            else:
                message["tool_calls"] = [
                    {"id": "c", "type": "custom", "custom": {"name": "t", "input": f"to {ph}"}}
                ]
            answer = completion("", model=body["model"])
            answer["choices"][0]["message"] = message
            return httpx.Response(200, json=answer)
        whole = json.dumps({"to": ph}) if self.fmt == "function_call" else f"to {ph}"
        first, second = _split(whole, ph)
        if self.fmt == "function_call":
            deltas = [{"function_call": {"name": "f", "arguments": p}} for p in (first, second)]
        else:
            deltas = [
                {"tool_calls": [{"index": 0, "type": "custom", "custom": {"input": p}}]}
                for p in (first, second)
            ]
        events = [chunk(d) for d in deltas] + [chunk({}, finish="tool_calls")]
        sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(
            200, content=sse.encode(), headers={"content-type": "text/event-stream"}
        )


def _collect(text: str, fmt: str) -> str:
    out = []
    for line in text.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        for choice in json.loads(line[6:]).get("choices", []):
            delta = choice["delta"]
            if fmt == "function_call":
                out.append(delta.get("function_call", {}).get("arguments", ""))
            else:
                out += [c.get("custom", {}).get("input", "") for c in delta.get("tool_calls", [])]
    return "".join(out)


@pytest.mark.parametrize("stream", [False, True], ids=["whole", "stream"])
@pytest.mark.parametrize("fmt", ["function_call", "custom"])
def test_gateway_restores_tool_formats(fmt: str, stream: bool) -> None:
    upstream = _ToolUpstream(fmt)
    settings = Settings(
        tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL, upstream_api_key=UPSTREAM_KEY
    )
    messages = [{"role": "user", "content": f"Írj {NAME} részére."}]
    with TestClient(make_app(upstream, settings=settings), raise_server_exceptions=False) as c:
        response = c.post(
            "/v1/chat/completions", json={"model": "m", "messages": messages, "stream": stream}
        )
    assert response.status_code == 200, response.text
    assert NAME not in upstream.requests[0].content.decode()
    if stream:
        restored = _collect(response.text, fmt)
    else:
        message = response.json()["choices"][0]["message"]
        restored = (
            message["function_call"]["arguments"]
            if fmt == "function_call"
            else message["tool_calls"][0]["custom"]["input"]
        )
    if fmt == "function_call":
        assert json.loads(restored) == {"to": NAME}
    else:
        assert restored == f"to {NAME}"
    assert "[[" not in response.text
