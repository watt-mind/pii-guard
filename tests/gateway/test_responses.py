"""``POST /v1/responses``: mask a Responses API request, forward it natively, restore the
answer and the ``response.*`` event stream. Fictional values only (ADR 0005).

The request bodies have the shape Muse Code 1.4.13 and 1.4.14 send (docs/integrations/muse-code.md):
developer and user messages, a ``namespace`` tool, earlier reasoning items with
``encrypted_content``, function calls and their outputs, ``include``, ``store: false``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import (
    EMAILS,
    IBAN,
    NAMES,
    PHONES,
    UPSTREAM_KEY,
    FakeLlm,
    MockUpstream,
    leaked_values,
    make_app,
)

from pii_guard.gateway.responses import responses_url
from pii_guard.gateway.responses_restore import ResponsesSseRestorer
from pii_guard.gateway.tool_names import tool_names, without_tool_names
from pii_guard.vault import PLACEHOLDER_RE

BLOB = "gAAAAB-opaque-provider-blob-0000"


def muse_body(**extra: Any) -> dict[str, Any]:
    return {
        "model": "muse-spark-1.3",
        "instructions": "You are a coding agent. The owner is Teszt Elek (teszt.elek@example.com).",
        "input": [
            {
                "type": "message",
                "role": "developer",
                "content": "Workspace root: /work. Support line +36 30 123 4567.",
            },
            {
                "type": "message",
                "role": "user",
                "content": "Read client-letter.md and reply to Jane Placeholder.",
            },
            {
                "type": "reasoning",
                "id": "rs_1",
                "summary": [{"type": "summary_text", "text": "Mail Minta Mária first."}],
            },
            {
                "type": "message",
                "role": "assistant",
                "content": "Reading the letter from Jane Placeholder now.",
                "id": "msg_1",
                "phase": "commentary",
            },
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "muse.read_file",
                "arguments": json.dumps({"path": "client-letter.md", "note": "for Minta Mária"}),
            },
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": (
                    "Read text file `client-letter.md`.\n1|Dear team, I am Jane Placeholder "
                    f"(jane.placeholder@example.net, +44 20 7946 0958). Refund to {IBAN}."
                ),
            },
        ],
        "tools": [
            {
                "type": "namespace",
                "name": "muse",
                "description": "Muse tools",
                "tools": [
                    {
                        "type": "function",
                        "name": "write_file",
                        "description": "Write a file. Escalations go to minta.maria@example.org.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["path", "content"],
                        },
                        "strict": False,
                    }
                ],
            }
        ],
        "reasoning": {"effort": "low", "summary": "auto"},
        "include": ["reasoning.encrypted_content"],
        "prompt_cache_key": "tbh:main:0001",
        "max_output_tokens": 1000,
        "store": False,
        **extra,
    }


def placeholders_of(body: dict[str, Any]) -> list[str]:
    text = json.dumps(body, ensure_ascii=False)
    return list(dict.fromkeys(m.group(0) for m in PLACEHOLDER_RE.finditer(text)))


def response_object(text: str, arguments: str) -> dict[str, Any]:
    return {
        "id": "resp_1",
        "object": "response",
        "status": "completed",
        "model": "muse-spark-1.3",
        "output": [
            {"type": "reasoning", "id": "rs_2", "summary": [], "encrypted_content": BLOB},
            {
                "type": "message",
                "id": "msg_2",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            },
            {
                "type": "function_call",
                "id": "fc_2",
                "call_id": "call_2",
                "name": "muse.write_file",
                "arguments": arguments,
                "status": "completed",
            },
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }


def answer_for(body: dict[str, Any]) -> tuple[str, str]:
    """Echo every placeholder the upstream saw: in the text and in write_file arguments."""
    seen = placeholders_of(body)
    text = "Reply sent to " + ", ".join(seen) + "."
    arguments = json.dumps({"path": "reply.md", "content": "\n".join(seen)})
    return text, arguments


def events_for(text: str, arguments: str, size: int = 5) -> list[dict[str, Any]]:
    """A ``response.*`` stream: text and arguments in ``size``-character deltas."""
    whole = response_object(text, arguments)
    pieces = [text[i : i + size] for i in range(0, len(text), size)]
    arg_pieces = [arguments[i : i + size] for i in range(0, len(arguments), size)]
    created = {**whole, "status": "in_progress", "output": []}
    events: list[dict[str, Any]] = [{"type": "response.created", "response": created}]
    events.append({"type": "response.output_item.added", "output_index": 1, "item": {}})
    for piece in pieces:
        events.append(
            {
                "type": "response.output_text.delta",
                "item_id": "msg_2",
                "output_index": 1,
                "content_index": 0,
                "delta": piece,
                "logprobs": [],
            }
        )
    events.append(
        {
            "type": "response.output_text.done",
            "item_id": "msg_2",
            "output_index": 1,
            "content_index": 0,
            "text": text,
        }
    )
    for piece in arg_pieces:
        events.append(
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_2",
                "output_index": 2,
                "delta": piece,
            }
        )
    events.append(
        {
            "type": "response.function_call_arguments.done",
            "item_id": "fc_2",
            "output_index": 2,
            "name": "muse.write_file",
            "arguments": arguments,
        }
    )
    events.append(
        {"type": "response.output_item.done", "output_index": 2, "item": whole["output"][2]}
    )
    events.append({"type": "response.completed", "response": whole})
    for number, event in enumerate(events):
        event["sequence_number"] = number
    return events


def sse(events: list[dict[str, Any]], *, done: bool = True) -> bytes:
    out = "".join(
        f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events
    )
    return (out + ("data: [DONE]\n\n" if done else "")).encode()


class ResponsesUpstream(MockUpstream):
    """Records requests; answers like the Meta Model API's ``/v1/responses``."""

    def __init__(self, events: Callable[[dict[str, Any]], bytes] | None = None) -> None:
        super().__init__()
        self.events = events

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status >= 400:
            return httpx.Response(self.status, json=self.error_body or {"error": {}})
        body = json.loads(request.content)
        if request.url.path.endswith("/muse-code/models"):
            return httpx.Response(404)
        text, arguments = answer_for(body)
        if body.get("stream"):
            content = self.events(body) if self.events else sse(events_for(text, arguments))
            return httpx.Response(
                200, content=content, headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(200, json=response_object(text, arguments))


def parse_sse(raw: str) -> list[tuple[str | None, Any]]:
    out: list[tuple[str | None, Any]] = []
    for block in raw.strip().split("\n\n"):
        name = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        assert data is not None
        out.append((name, data if data == "[DONE]" else json.loads(data)))
    return out


SECRETS = ("Teszt Elek", "Jane Placeholder", "Minta Mária", *EMAILS, *PHONES, IBAN)


def test_non_streamed_request_is_masked_everywhere_and_answer_restored() -> None:
    upstream = ResponsesUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json=muse_body())
    assert response.status_code == 200, response.text
    assert len(upstream.requests) == 1
    request = upstream.requests[0]
    assert request.url == httpx.URL("https://upstream.test/v1/responses")
    assert request.headers["authorization"] == f"Bearer {UPSTREAM_KEY}"
    assert leaked_values(request.content) == []
    forwarded = json.loads(request.content)
    # Every free-text field carries placeholders now.
    assert PLACEHOLDER_RE.search(forwarded["instructions"])
    assert PLACEHOLDER_RE.search(forwarded["input"][0]["content"])
    assert PLACEHOLDER_RE.search(forwarded["input"][2]["summary"][0]["text"])
    assert PLACEHOLDER_RE.search(forwarded["input"][5]["output"])
    assert PLACEHOLDER_RE.search(forwarded["tools"][0]["tools"][0]["description"])
    arguments = json.loads(forwarded["input"][4]["arguments"])
    assert PLACEHOLDER_RE.search(arguments["note"])
    # IDs, names and settings are untouched; imported encrypted history is omitted.
    assert "encrypted_content" not in forwarded["input"][2]
    assert forwarded["input"][4]["name"] == "muse.read_file"
    assert forwarded["input"][3]["phase"] == "commentary"
    assert forwarded["include"] == ["reasoning.encrypted_content"]
    assert forwarded["store"] is False

    answer = response.json()
    text = answer["output"][1]["content"][0]["text"]
    written = json.loads(answer["output"][2]["arguments"])["content"]
    assert answer["output"][0]["encrypted_content"] == BLOB
    assert not PLACEHOLDER_RE.search(text)
    assert not PLACEHOLDER_RE.search(written)
    for value in ("jane.placeholder@example.net", "+44 20 7946 0958", IBAN, "Jane Placeholder"):
        assert value in text
        assert value in written
    assert response.headers["x-pii-guard-unresolved"] == "0"
    assert int(response.headers["x-pii-guard-masked"]) > 0


def test_streamed_events_are_restored_across_split_placeholders() -> None:
    upstream = ResponsesUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json=muse_body(stream=True))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    forwarded = json.loads(upstream.requests[0].content)
    assert forwarded["stream"] is True
    assert upstream.requests[0].headers["accept"] == "text/event-stream"
    events = parse_sse(response.text)
    assert events[-1] == (None, "[DONE]")
    named = [(n, d) for n, d in events if d != "[DONE]"]
    assert all(name == data["type"] for name, data in named)  # event: lines kept
    sequence = [d["sequence_number"] for _, d in named]
    assert sequence == list(range(len(sequence)))  # still strictly increasing
    text = "".join(d["delta"] for n, d in named if n == "response.output_text.delta")
    arguments = "".join(
        d["delta"] for n, d in named if n == "response.function_call_arguments.delta"
    )
    done_text = next(d["text"] for n, d in named if n == "response.output_text.done")
    done_arguments = next(
        d["arguments"] for n, d in named if n == "response.function_call_arguments.done"
    )
    assert text == done_text
    assert arguments == done_arguments
    assert json.loads(arguments)["content"]  # valid JSON, values escaped
    completed = next(d for n, d in named if n == "response.completed")["response"]
    assert completed["output"][1]["content"][0]["text"] == done_text
    assert completed["output"][2]["arguments"] == done_arguments
    for value in ("jane.placeholder@example.net", "+44 20 7946 0958", IBAN):
        assert value in text
        assert value in json.loads(arguments)["content"]
    assert not PLACEHOLDER_RE.search(response.text)


def test_stream_without_done_events_flushes_what_is_held_back() -> None:
    def cut(body: dict[str, Any]) -> bytes:
        token = placeholders_of(body)[0]
        events = [
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "content_index": 0,
                "delta": piece,
                "sequence_number": i,
            }
            for i, piece in enumerate(("Hi ", token[:6]))
        ]
        events.append(
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "content_index": 0,
                "delta": token[6:],
                "sequence_number": 2,
            }
        )
        return sse(events, done=False)

    upstream = ResponsesUpstream(events=cut)
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json=muse_body(stream=True))
    deltas = [d["delta"] for _, d in parse_sse(response.text)]
    assert not PLACEHOLDER_RE.search("".join(deltas))
    assert "".join(deltas).startswith("Hi ")
    assert len("".join(deltas)) > len("Hi ")


def test_upstream_error_events_are_replaced() -> None:
    def failing(body: dict[str, Any]) -> bytes:
        quoted = "bad request: " + json.dumps(body["input"][0])
        events = [
            {"type": "error", "code": "bad", "message": quoted, "sequence_number": 0},
            {
                "type": "response.failed",
                "response": {"id": "r", "status": "failed", "error": {"message": quoted}},
                "sequence_number": 1,
            },
        ]
        return sse(events)

    upstream = ResponsesUpstream(events=failing)
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json=muse_body(stream=True))
    assert "bad request" not in response.text
    events = parse_sse(response.text)
    assert events[0][1]["code"] == "upstream_error"
    assert events[1][1]["response"]["error"] == {
        "code": "upstream_error",
        "message": "upstream failed",
    }


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"previous_response_id": "resp_0"}, "server-side conversation state"),
        ({"conversation": "conv_0"}, "server-side conversation state"),
        ({"surprise": 1}, "unsupported request field"),
        ({"tools": [{"type": "web_search"}]}, "hosted tools"),
        (
            {
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_image", "image_url": "https://x.test/a.png"}],
                    }
                ]
            },
            "remote image URLs are not fetched",
        ),
        ({"input": [{"type": "item_reference", "id": "msg_0"}]}, "unsupported input item type"),
        (
            {"input": [{"type": "message", "role": "user", "content": "x", "extra": 1}]},
            "input.0.#3",
        ),
        ({"input": [{"type": "reasoning", "summary": [{"type": "x", "text": "y"}]}]}, "summary"),
    ],
)
def test_unsupported_fields_fail_closed(change: dict[str, Any], fragment: str) -> None:
    upstream = ResponsesUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json={**muse_body(), **change})
    assert response.status_code == 400, response.text
    assert fragment in response.json()["error"]["message"]
    assert upstream.requests == []


def test_personal_data_in_an_identifier_is_refused() -> None:
    body = muse_body()
    body["input"][4]["call_id"] = "teszt.elek@example.com"
    upstream = ResponsesUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json=body)
    assert response.status_code == 400
    assert "identifier" in response.json()["error"]["message"]
    assert "teszt.elek" not in response.text
    assert upstream.requests == []


def test_a_tool_name_read_as_a_name_does_not_refuse_the_request() -> None:
    """Muse 1.4.14 says "Muse" alone in its prompts and the NER can read it as a PERSON. The
    vault then masked the ``muse`` namespace as another occurrence of that value, and the
    request was refused as personal data in an identifier (LAB-1299). The tool vocabulary is
    left as written in identifiers; since LAB-1563 the prose occurrence itself is masked,
    and real names around it are still masked too."""
    body = muse_body()
    body["input"][0]["content"] = "You are Muse, a coding agent. Support line +36 30 123 4567."
    upstream = ResponsesUpstream()
    detector = FakeLlm((*NAMES, "Muse", "Write_File"))
    with TestClient(make_app(upstream, llm=detector)) as http:
        response = http.post("/s/c_tool_names_0001/v1/responses", json=body)
    assert response.status_code == 200, response.text
    forwarded = json.loads(upstream.requests[0].content)
    assert forwarded["tools"][0]["name"] == "muse"
    assert forwarded["tools"][0]["tools"][0]["name"] == "write_file"
    assert forwarded["input"][4]["name"] == "muse.read_file"
    assert forwarded["input"][0]["content"].startswith("You are [[PERSON_")
    assert leaked_values(upstream.requests[0].content) == []


def test_tool_names_and_the_spans_they_drop() -> None:
    from pii_guard.types import EntityType, Span

    names = tool_names(muse_body())
    assert names == frozenset({"muse", "write_file"})
    assert tool_names({"tools": "not a list"}) == frozenset()
    text = "Muse wrote to Jane Placeholder via MUSE"
    found = [
        Span(0, 4, EntityType.PERSON, "Muse", 0.9, "ner"),
        Span(14, 30, EntityType.PERSON, "Jane Placeholder", 0.9, "ner"),
        Span(35, 39, EntityType.PERSON, "MUSE", 1.0, "known"),  # pre-loaded: kept
    ]
    # In an identifier slot the tool word is dropped; the pre-loaded one is kept. In prose
    # (any other kind, or none) nothing is dropped since LAB-1563.
    kept = without_tool_names([text], [found], names, ["identifier"])[0]
    assert [s.text for s in kept] == ["Jane Placeholder", "MUSE"]
    assert without_tool_names([text], [found], names, ["content"]) == [found]
    assert without_tool_names([text], [found], names) == [found]
    assert without_tool_names([text], [found], frozenset()) == [found]


def test_string_input_and_easy_messages() -> None:
    upstream = ResponsesUpstream()
    with TestClient(make_app(upstream)) as http:
        one = http.post(
            "/v1/responses", json={"model": "m", "input": "Mail teszt.elek@example.com"}
        )
        two = http.post(
            "/v1/responses",
            json={
                "model": "m",
                "input": [
                    {"role": "user", "content": [{"type": "input_text", "text": IBAN}]},
                ],
                "text": {"format": {"type": "text"}, "verbosity": "low"},
            },
        )
    assert one.status_code == 200 and two.status_code == 200
    assert all(leaked_values(r.content) == [] for r in upstream.requests)
    assert "teszt.elek@example.com" in one.json()["output"][1]["content"][0]["text"]


def test_upstream_without_responses_api_gets_501() -> None:
    upstream = ResponsesUpstream()
    upstream.status = 404
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json=muse_body())
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "responses_unsupported"


def test_upstream_error_status_keeps_no_message() -> None:
    upstream = ResponsesUpstream()
    upstream.status = 429
    upstream.error_body = {"error": {"type": "rate_limit", "message": "quota for Teszt Elek"}}
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json=muse_body())
    assert response.status_code == 429
    assert "Teszt" not in response.text
    assert response.json()["error"]["upstream_type"] == "rate_limit"


def test_echo_shows_the_masked_boundary_and_refuses_streams() -> None:
    upstream = ResponsesUpstream()
    headers = {"X-PII-Guard-Echo": "masked"}
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json=muse_body(), headers=headers)
        streamed = http.post("/v1/responses", json=muse_body(stream=True), headers=headers)
    echo = response.json()["pii_guard"]
    seen = json.dumps(echo, ensure_ascii=False)
    assert PLACEHOLDER_RE.search(seen)
    assert all(value not in seen for value in SECRETS)
    assert echo["masked_input"][1]["role"] == "user"
    assert streamed.status_code == 400


def test_responses_url() -> None:
    assert responses_url("https://api.meta.ai/v1") == "https://api.meta.ai/v1/responses"
    assert responses_url("https://x.test/v1/chat/completions/") == "https://x.test/v1/responses"
    assert responses_url("https://x.test/v1/responses") == "https://x.test/v1/responses"


def test_sse_restorer_passes_unknown_events_and_restores_whole_ones() -> None:
    class Session:
        def restore_budget(self) -> Any:
            from pii_guard.vault import RestoreBudget

            return RestoreBudget(1000)

        def unmask_with_report(self, text: str, *, budget: Any = None) -> Any:
            from pii_guard.vault import UnmaskResult

            return UnmaskResult(text.replace("[[EMAIL_abcd12]]", "a@example.com"), ())

    restorer = ResponsesSseRestorer(Session())  # type: ignore[arg-type]
    out = restorer.process("ping", "not json")
    assert out == [("ping", "not json")]
    item = {"type": "response.output_item.done", "item": {"text": "to [[EMAIL_abcd12]]"}}
    [(name, data)] = restorer.process(None, json.dumps(item))
    assert name == "response.output_item.done"
    assert json.loads(data)["item"]["text"] == "to a@example.com"


def test_line_number_gutters_are_hidden_from_detection_and_kept_upstream() -> None:
    """Muse's read_file prints ``12|text``: detectors see spaces there, the model the gutter."""
    from pii_guard.gateway.responses_request import collect_response_texts

    output = "Read text file `letter.md`.\n1|Dear team,\n2|Jane Placeholder\n 3|x"
    body = {
        "model": "m",
        "input": [
            {"type": "function_call_output", "call_id": "c", "output": output},
            {
                "role": "user",
                "content": "<conversation>\n7|Hi\n8|Jane Placeholder\n</conversation>",
            },
        ],
    }
    slots = [s for s in collect_response_texts(body).slots if s.kind in ("tool", "content")]
    assert [s.text for s in slots] == [
        "Read text file `letter.md`.\n  Dear team,\n  Jane Placeholder\n   x",
        "<conversation>\n  Hi\n  Jane Placeholder\n</conversation>",
    ]
    for slot in slots:
        slot.write(slot.text.replace("Jane Placeholder", "[[PERSON_abcd12]]"))
    assert body["input"][0]["output"] == (
        "Read text file `letter.md`.\n1|Dear team,\n2|[[PERSON_abcd12]]\n 3|x"
    )
    assert (
        body["input"][1]["content"] == "<conversation>\n7|Hi\n8|[[PERSON_abcd12]]\n</conversation>"
    )
    # A masked value that swallowed a line break: the gutters go, nothing unmasked comes back.
    output_slot = slots[0]
    output_slot.write("[[ADDRESS_abcd12]]\n   x")
    assert body["input"][0]["output"] == "[[ADDRESS_abcd12]]\n   x"


def test_gutters_through_the_gateway() -> None:
    upstream = ResponsesUpstream()
    body = muse_body()
    body["input"][5]["output"] = "Read text file `a.md`.\n1|Hi,\n2|teszt.elek@example.com"
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json=body)
    assert response.status_code == 200
    forwarded = json.loads(upstream.requests[0].content)["input"][5]["output"]
    assert forwarded.startswith("Read text file `a.md`.\n1|Hi,\n2|[[EMAIL_")


@pytest.mark.parametrize("stream", [False, True])
def test_through_the_bench_mock_upstream(stream: bool) -> None:
    """The gateway in front of ``pii-guard bench mock-upstream``'s ``/v1/responses`` echo."""
    from pii_guard.bench.mock_upstream import create_mock_upstream

    mock_app = create_mock_upstream(chunk_chars=4)
    app = make_app(MockUpstream())
    app.state.gateway_transport = httpx.ASGITransport(app=mock_app)
    sent = "Mail jane.placeholder@example.net or call +44 20 7946 0958."
    with TestClient(app) as http:
        plain = http.post("/v1/responses", json={"model": "m", "input": sent, "stream": stream})
        tools = muse_body(stream=stream)
        called = http.post("/v1/responses", json={**tools, "input": [tools["input"][1]]})
    received = list(mock_app.state.mock.received)
    assert all("jane.placeholder@example.net" not in r for r in received)
    if stream:
        deltas = [d for n, d in parse_sse(plain.text) if n == "response.output_text.delta"]
        assert "".join(d["delta"] for d in deltas) == f"Echo: {sent}"
        args = [d for n, d in parse_sse(called.text) if n and n.endswith("arguments.delta")]
        assert "Jane Placeholder" in json.loads("".join(d["delta"] for d in args))["text"]
    else:
        assert plain.json()["output"][0]["content"][0]["text"] == f"Echo: {sent}"
        call = called.json()["output"][0]
        assert call["name"] == "muse.write_file"
        assert "Jane Placeholder" in json.loads(call["arguments"])["text"]


def test_codex_client_metadata_is_masked_like_metadata() -> None:
    """Codex sends per-turn ids in ``client_metadata`` (LAB-1331): walked, not refused."""
    from pii_guard.gateway.request import InvalidChatRequestError
    from pii_guard.gateway.responses_request import collect_response_texts

    body = {
        "model": "m",
        "input": "hi",
        "client_metadata": {"session_id": "01a1", "x-codex-turn-metadata": '{"turn_id":"t1"}'},
    }
    slots = collect_response_texts(body).slots
    assert {"01a1", '{"turn_id":"t1"}'} <= {s.text for s in slots}
    with pytest.raises(InvalidChatRequestError, match="client_metadata must be an object"):
        collect_response_texts({"model": "m", "input": "hi", "client_metadata": "x"})


# --- custom-tool grammar definitions and ``model`` (LAB-1563) --------------------------------


def test_custom_tool_grammar_definition_is_masked() -> None:
    """``format.grammar.definition`` was skipped as schema-structural, so personal data in a
    custom tool's grammar went upstream verbatim. It is free text: masked."""
    email = "teszt.elek@example.com"
    body: dict[str, Any] = {
        "model": "m",
        "input": "hello",
        "tools": [
            {
                "type": "custom",
                "name": "grep",
                "description": "Search text.",
                "format": {
                    "type": "grammar",
                    "grammar": {"syntax": "lark", "definition": f'start: "mail {email}"'},
                },
            }
        ],
    }
    upstream = ResponsesUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json=body)
    assert response.status_code == 200, response.text
    forwarded = json.loads(upstream.requests[0].content)
    definition = forwarded["tools"][0]["format"]["grammar"]["definition"]
    assert "[[EMAIL_" in definition
    assert email not in upstream.requests[0].content.decode()


def test_a_pii_shaped_model_is_refused_on_responses() -> None:
    email = "teszt.elek@example.com"
    upstream = ResponsesUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json={"model": email, "input": "hello"})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "unsupported_content"
    assert email not in response.text
    assert upstream.requests == []


def test_unknown_delta_types_hold_back_a_split_placeholder() -> None:
    """An unmodelled ``*.delta`` event type with a string ``delta`` streams through the same
    holdback as a known one, so a split placeholder is never emitted in fragments, and its
    ``.done`` flushes it before the whole text (LAB-1564)."""

    class Session:
        def restore_budget(self) -> Any:
            from pii_guard.vault import RestoreBudget

            return RestoreBudget(1000)

        def unmask_with_report(self, text: str, *, budget: Any = None) -> Any:
            from pii_guard.vault import UnmaskResult

            return UnmaskResult(text.replace("[[EMAIL_abcd12]]", "a@example.com"), ())

    restorer = ResponsesSseRestorer(Session())  # type: ignore[arg-type]
    kind = "response.future_text"
    out: list[tuple[str | None, str]] = []
    for piece in ("to [[EM", "AIL_abcd12]] !"):
        event = {"type": f"{kind}.delta", "output_index": 1, "delta": piece}
        out += restorer.process(event["type"], json.dumps(event))
        assert "[[EM" not in out[-1][1]
    done = {"type": f"{kind}.done", "output_index": 1, "text": "to [[EMAIL_abcd12]] !"}
    out += restorer.process(done["type"], json.dumps(done))
    events = [json.loads(data) for _, data in out]
    deltas = "".join(e["delta"] for e in events if e["type"].endswith(".delta"))
    assert deltas == events[-1]["text"] == "to a@example.com !"


def test_unknown_delta_without_a_string_delta_is_restored_whole() -> None:
    """Other unmodelled events keep the existing whole-event restore (LAB-1564)."""

    class Session:
        def restore_budget(self) -> Any:
            from pii_guard.vault import RestoreBudget

            return RestoreBudget(1000)

        def unmask_with_report(self, text: str, *, budget: Any = None) -> Any:
            from pii_guard.vault import UnmaskResult

            return UnmaskResult(text.replace("[[EMAIL_abcd12]]", "a@example.com"), ())

    restorer = ResponsesSseRestorer(Session())  # type: ignore[arg-type]
    event = {"type": "response.future.delta", "delta": {"text": "to [[EMAIL_abcd12]]"}}
    [(name, data)] = restorer.process(event["type"], json.dumps(event))
    assert name == "response.future.delta"
    assert json.loads(data)["delta"] == {"text": "to a@example.com"}


def test_stream_request_refuses_non_sse_upstream_response() -> None:
    """When ``stream=True`` is requested, a non-SSE upstream response fails closed with 502."""

    class NonStreamingResponsesUpstream(ResponsesUpstream):
        def handler(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(200, json=response_object("hello", "{}"))

    upstream = NonStreamingResponsesUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json=muse_body(stream=True))
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_did_not_stream"


def test_refused_identifier_does_not_pollute_existing_session() -> None:
    """Refusing an identifier with PII must not store the refused value in an existing session."""
    upstream = ResponsesUpstream()
    app = make_app(upstream)
    with TestClient(app) as http:
        first = http.post(
            "/v1/responses", json={"model": "m", "input": "Mail teszt.elek@example.com"}
        )
        session_id = first.headers["X-PII-Guard-Session"]
        bad = {
            "model": "m",
            "input": [
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "minta.maria@example.org",
                    "name": "muse.read_file",
                    "arguments": "{}",
                }
            ],
        }
        refused = http.post(
            "/v1/responses",
            json=bad,
            headers={"X-PII-Guard-Session": session_id},
        )
        assert refused.status_code == 400
        session = app.state.gateway.vault.session(session_id)
        assert len(session._by_placeholder) == 1


def test_sse_restorer_flushes_open_unmaskers_before_terminal_and_ignores_after_finish() -> None:
    """Held-back partial placeholders flush before ``response.completed`` and post-finish stops."""

    class Session:
        def restore_budget(self) -> Any:
            from pii_guard.vault import RestoreBudget

            return RestoreBudget(1000)

        def unmask_with_report(self, text: str, *, budget: Any = None) -> Any:
            from pii_guard.vault import UnmaskResult

            return UnmaskResult(text.replace("[[EMAIL_abcd12]]", "a@example.com"), ())

    restorer = ResponsesSseRestorer(Session())  # type: ignore[arg-type]
    delta = {
        "type": "response.output_text.delta",
        "output_index": 0,
        "content_index": 0,
        "delta": "Hi [[EM",
    }
    out = restorer.process(delta["type"], json.dumps(delta))
    completed = {
        "type": "response.completed",
        "response": {
            "id": "r1",
            "status": "completed",
            "error": {"message": "secret [[EMAIL_abcd12]]"},
        },
    }
    out += restorer.process(completed["type"], json.dumps(completed))
    events = [json.loads(data) for _, data in out]
    assert [e["type"] for e in events] == [
        "response.output_text.delta",
        "response.output_text.delta",
        "response.completed",
    ]
    assert events[1]["delta"] == "[[EM"
    assert events[2]["response"]["error"] == {
        "code": "upstream_error",
        "message": "upstream failed",
    }
    assert restorer.finish() == []
    assert restorer.process(delta["type"], json.dumps(delta)) == []
