"""Record the landing's agent-turn replay (LAB-1499).

The landing (``ui/src/hosted/AgentReplay.tsx``) replays one agent turn through the gateway:
the agent reads a fictional CRM record with a tool, the model sees it with placeholders, the
model streams a ``send_email`` tool call whose arguments carry placeholders, PII Guard restores
them before the agent runs the tool, and the model's closing text is restored as it streams,
with a placeholder held back while it is split across chunks.

This script makes that recording with the real gateway in fast mode (rules + the published
NER, as in production) and Muse Spark (``muse-spark-1.3`` on the Meta Model API, the hosted
preview's included model) as the upstream (LAB-1524). The model's own streamed chunks are kept
as it sent them: a placeholder spans several of its tokens, so the hold-back shows on the
recorded chunking, not on forced splits (Muse Spark streams a tool call's arguments a JSON
field at a time, so the hold-back shows in its closing text). ``--stand-in`` swaps in the
scripted upstream of LAB-1499 (no provider called, placeholders cut on purpose) to try the
script offline.

The written JSON is value-free: the masked tool result the upstream saw, the chunks the
upstream streamed and the chunks the agent received, with every restored value written back as
its placeholder (the browser puts the fictional values back from ``RECORD`` in
``AgentReplay.tsx``, which must stay in step with ``RECORD`` below). The script fails if any
fictional value reaches the upstream or would be written, or if the model's turn doesn't
have the shape the replay shows (read_file, then send_email to placeholders, then a closing
text with a placeholder split across chunks); it tries up to three times. Needs the ``ner``
extra and ``META_API_KEY``::

    uv run --no-sync python scripts/record_agent_replay.py              # writes the recording
    uv run --no-sync python scripts/record_agent_replay.py --check      # checks, writes nothing
    uv run --no-sync python scripts/record_agent_replay.py --stand-in --check   # offline
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway import GatewayConfig, Mode, build_mode_detectors
from pii_guard.upstreams import PRESETS
from pii_guard.vault import PLACEHOLDER_RE

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ui" / "src" / "content" / "agentReplayRecording.json"
STAND_IN_UPSTREAM = "https://upstream.invalid/v1"
MUSE = PRESETS["meta"]
#: Muse Spark always reasons; a low effort keeps the turn short and cheap.
REASONING_EFFORT = "low"
ATTEMPTS = 3

#: The task. No personal data in it: the agent has to read the record.
TASK = "Refund ticket 4471 is approved. Look up the customer in crm.json and email them."
#: The fictional CRM record the agent's read_file tool returns. Keep in step with RECORD in
#: ui/src/hosted/AgentReplay.tsx.
RECORD = (
    '{"customer": "Robin Example", "email": "robin.example@example.com", '
    '"iban": "DE89 3704 0044 0532 0130 00"}'
)
VALUES = ("Robin Example", "robin.example@example.com", "DE89 3704 0044 0532 0130 00")
SYSTEM = (
    "You are a support agent with file and e-mail tools. Use the tools; don't ask questions. "
    "Keep emails to two short sentences. When the email is sent, reply with one short sentence "
    "saying whom you emailed."
)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props},
        },
    }
    for name, desc, props in (
        ("read_file", "Read a file in the workspace.", {"path": {"type": "string"}}),
        (
            "send_email",
            "Send an e-mail.",
            {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
        ),
    )
]


def chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    return {
        "id": "chatcmpl-replay",
        "object": "chat.completion.chunk",
        "created": 1_800_000_000,
        "model": "stand-in",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def sse(events: list[dict[str, Any]]) -> bytes:
    return (
        "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
        + "data: [DONE]\n\n"
    ).encode()


def split_inside(text: str, sizes: list[int]) -> list[str]:
    """``text`` cut at the given sizes; the rest is the last piece."""
    out, at = [], 0
    for size in sizes:
        out.append(text[at : at + size])
        at += size
    out.append(text[at:])
    return [piece for piece in out if piece]


def cut_through_placeholders(text: str) -> list[str]:
    """Pieces of ``text`` of a few words each, every placeholder cut in two."""
    cuts = sorted(
        {m.start() + 6 for m in PLACEHOLDER_RE.finditer(text)} | set(range(9, len(text), 9))
    )
    pieces, at = [], 0
    for cut in cuts:
        if cut > at:
            pieces.append(text[at:cut])
            at = cut
    pieces.append(text[at:])
    return [p for p in pieces if p]


class Retry(Exception):
    """The model's turn didn't have the replay's shape; try again."""


class Recorder(httpx.AsyncBaseTransport):
    """The real upstream (Muse Spark), with each request and streamed response kept."""

    def __init__(self) -> None:
        self.inner = httpx.AsyncHTTPTransport()
        self.bodies: list[dict[str, Any]] = []
        self.raw: list[bytes] = []
        self.streams: list[list[dict[str, Any]]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        content = await request.aread()
        self.raw.append(content)
        self.bodies.append(json.loads(content))
        raw = await self.inner.handle_async_request(request)
        response = httpx.Response(
            raw.status_code, headers=raw.headers, stream=raw.stream, request=request
        )
        body = await response.aread()  # decoded, as the gateway's client would read it
        if response.status_code != 200:
            raise SystemExit(f"upstream answered {response.status_code}")
        self.streams.append(parse_sse(body.decode()))
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


class StandIn:
    """The scripted upstream: one tool call per step, answered from the placeholders it got."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.raw: list[bytes] = []
        self.streams: list[list[dict[str, Any]]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.raw.append(request.content)
        body = json.loads(request.content)
        self.bodies.append(body)
        tools_done = sum(1 for m in body["messages"] if m.get("role") == "tool")
        if tools_done == 0:
            events = [
                chunk(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_read",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": ""},
                            }
                        ],
                    }
                ),
                chunk(
                    {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": '{"path": "crm.json"}'}}
                        ]
                    }
                ),
                chunk({}, finish="tool_calls"),
            ]
        elif tools_done == 1:
            seen = next(m["content"] for m in body["messages"] if m.get("role") == "tool")
            found = {t: f"[[{t}_{i}]]" for t, i in PLACEHOLDER_RE.findall(seen)}
            person, email, iban = found["PERSON"], found["EMAIL"], found["BANK_ACCOUNT"]
            args = json.dumps(
                {
                    "to": email,
                    "subject": "Your refund",
                    "body": f"Dear {person}, your refund for ticket 4471 is on its way to {iban}.",
                }
            )
            events = [
                chunk(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_send",
                                "type": "function",
                                "function": {"name": "send_email", "arguments": ""},
                            }
                        ],
                    }
                )
            ]
            events += [
                chunk({"tool_calls": [{"index": 0, "function": {"arguments": piece}}]})
                for piece in cut_through_placeholders(args)
            ]
            events.append(chunk({}, finish="tool_calls"))
        else:
            sent = next(
                m
                for m in body["messages"]
                if m.get("role") == "assistant"
                and m.get("tool_calls")
                and m["tool_calls"][0]["function"]["name"] == "send_email"
            )
            args = json.loads(sent["tool_calls"][0]["function"]["arguments"])
            match = PLACEHOLDER_RE.search(args["body"])
            if match is None:
                raise SystemExit("the stand-in's email has no placeholder")
            person = match.group(0)
            text = f"Done. I emailed {person} at {args['to']} that the refund is on its way."
            events = [chunk({"role": "assistant", "content": ""})]
            events += [chunk({"content": piece}) for piece in cut_through_placeholders(text)]
            events.append(chunk({}, finish="stop"))
        self.streams.append(events)
        return httpx.Response(
            200, content=sse(events), headers={"content-type": "text/event-stream"}
        )


def deltas(events: list[dict[str, Any]], kind: str) -> list[str]:
    """The text pieces of a stream: content, or the first tool call's argument fragments."""
    out = []
    for event in events:
        for choice in event.get("choices", []):
            delta = choice.get("delta") or {}
            if kind == "content" and delta.get("content"):
                out.append(delta["content"])
            if kind == "arguments":
                for call in delta.get("tool_calls") or []:
                    piece = (call.get("function") or {}).get("arguments")
                    if piece:
                        out.append(piece)
    return out


def parse_sse(raw: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[6:])
        for line in raw.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


def split_placeholder(pieces: list[str]) -> bool:
    """Whether some placeholder in the joined stream starts in one chunk and ends in another."""
    ends, at = set(), 0
    for piece in pieces:
        at += len(piece)
        ends.add(at)
    return any(
        any(m.start() < end < m.end() for end in ends)
        for m in PLACEHOLDER_RE.finditer("".join(pieces))
    )


def tool_call(events: list[dict[str, Any]]) -> tuple[str, str]:
    """The first tool call's id and name in a stream ("" when there is none)."""
    for event in events:
        for choice in event.get("choices", []):
            for call in (choice.get("delta") or {}).get("tool_calls") or []:
                if call.get("id"):
                    return call["id"], (call.get("function") or {}).get("name") or ""
    return "", ""


def record(stand_in: bool = False) -> dict[str, Any]:
    """One agent turn through the gateway; raise :class:`Retry` if the model went off-script."""
    upstream: StandIn | Recorder = StandIn() if stand_in else Recorder()
    if stand_in:
        base, key, model = STAND_IN_UPSTREAM, "sk-stand-in-0000", "stand-in"
    else:
        key = os.environ.get(MUSE.key_env, "")
        if not key:
            sys.exit(f"set {MUSE.key_env} (or pass --stand-in)")
        base, model = MUSE.base_url, MUSE.default_model or "muse-spark-1.3"
    tenant = secrets.token_hex(32)
    settings = Settings(
        tenant_key=SecretStr(tenant),
        upstream_base_url=base,
        upstream_api_key=SecretStr(key),
        ner_fallback="cached",
    )
    config = GatewayConfig(mode=Mode.FAST)
    app = create_app(settings)
    app.state.gateway_config = config
    app.state.gateway_transport = (
        httpx.MockTransport(upstream.handler) if isinstance(upstream, StandIn) else upstream
    )
    app.state.gateway_detectors = build_mode_detectors(settings, config)
    headers = {"Authorization": f"Bearer {tenant}"}
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": TASK},
    ]
    extra = {} if stand_in else {"reasoning_effort": REASONING_EFFORT}
    received: list[list[dict[str, Any]]] = []
    session = None
    with TestClient(app, base_url="http://127.0.0.1") as http:
        for step, (want, result) in enumerate(
            (("read_file", RECORD), ("send_email", '{"status": "sent"}'), ("", ""))
        ):
            h = {**headers, **({"X-PII-Guard-Session": session} if session else {})}
            body = {"model": model, "stream": True, "messages": messages, "tools": TOOLS, **extra}
            r = http.post("/v1/chat/completions", json=body, headers=h)
            r.raise_for_status()
            session = r.headers["x-pii-guard-session"]
            events = parse_sse(r.text)
            received.append(events)
            call_id, name = tool_call(events)
            if name != want:
                raise Retry(f"step {step}: the model called {name or 'no tool'!r}, not {want!r}")
            if not want:
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": "".join(deltas(events, "arguments")),
                            },
                        }
                    ],
                }
            )
            messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
    for raw in upstream.raw:
        text = raw.decode()
        for value in VALUES:
            if value in text or value in json.dumps(json.loads(raw), ensure_ascii=False):
                sys.exit(f"leak: a fictional value reached the upstream: {value!r}")

    masked_record = next(
        m["content"] for m in upstream.bodies[1]["messages"] if m.get("role") == "tool"
    )
    by_kind = {"PERSON": VALUES[0], "EMAIL": VALUES[1], "BANK_ACCOUNT": VALUES[2]}
    values: dict[str, str] = {}
    for kind, ident in PLACEHOLDER_RE.findall(masked_record):
        if kind not in by_kind:
            sys.exit(f"the record was masked as an unexpected type: {kind}")
        values[f"[[{kind}_{ident}]]"] = by_kind[kind]
    if sorted(values.values()) != sorted(VALUES):
        sys.exit("the record was not masked as one name, one email and one IBAN")

    sent_pieces = deltas(upstream.streams[1], "arguments")
    answer_pieces = deltas(upstream.streams[2], "content")
    try:
        sent_args = json.loads("".join(sent_pieces))
        restored_args = json.loads("".join(deltas(received[1], "arguments")))
    except json.JSONDecodeError as exc:
        raise Retry("send_email arguments are not JSON") from exc
    if not isinstance(sent_args, dict) or not PLACEHOLDER_RE.fullmatch(
        str(sent_args.get("to", "")).strip()
    ):
        raise Retry("send_email is not addressed to a placeholder")
    # Every placeholder the model wrote is one it was given, and comes back as its value.
    for pieces in (sent_pieces, answer_pieces):
        for found in PLACEHOLDER_RE.finditer("".join(pieces)):
            if found.group(0) not in values:
                raise Retry(f"the model wrote a placeholder it wasn't given: {found.group(0)}")
    for key, sent in sent_args.items():
        expected = sent
        if isinstance(sent, str):
            for ph, value in values.items():
                expected = expected.replace(ph, value)
        if restored_args.get(key) != expected:
            sys.exit(f"restore check failed for {key!r}")
    # Muse Spark streams a tool call's arguments a JSON field at a time, so a placeholder there
    # arrives whole; its text streams in tokens, so the closing text shows the hold-back.
    pieces_to_split = [("answer", answer_pieces)]
    if stand_in:
        pieces_to_split.append(("send_email", sent_pieces))
    for label, pieces in pieces_to_split:
        if not split_placeholder(pieces):
            raise Retry(f"no placeholder is split across the {label} stream's chunks")

    def value_free(pieces: list[str]) -> list[str]:
        out = []
        for piece in pieces:
            for ph, value in values.items():
                piece = piece.replace(value, ph)
            out.append(piece)
        return out

    upstream_name = (
        "a scripted stand-in upstream"
        if stand_in
        else f"{model} (Muse Spark, Meta Model API) as the upstream, its own stream chunks"
    )
    recording = {
        "recorded": dt.date.today().isoformat(),
        "how": (
            "scripts/record_agent_replay.py: the gateway in fast mode (rules + published NER), "
            f"{upstream_name}, fictional data"
        ),
        "model": model,
        "task": TASK,
        "upstream_requests": len(upstream.raw),
        "values_reaching_upstream": 0,
        "read_call": {"name": "read_file", "arguments": "".join(deltas(received[0], "arguments"))},
        "masked_record": masked_record,
        "send_call": {
            "name": "send_email",
            "upstream": sent_pieces,
            "agent": value_free(deltas(received[1], "arguments")),
        },
        "answer": {
            "upstream": answer_pieces,
            "agent": value_free(deltas(received[2], "content")),
        },
    }
    text = json.dumps(recording, ensure_ascii=False)
    for value in VALUES:
        if value in text:
            sys.exit(f"the recording would contain a fictional value: {value!r}")
    return recording


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="record and check, write nothing")
    parser.add_argument(
        "--stand-in", action="store_true", help="the scripted upstream, no provider called"
    )
    args = parser.parse_args()
    for attempt in range(1, ATTEMPTS + 1):
        try:
            recording = record(stand_in=args.stand_in)
            break
        except Retry as exc:
            print(f"attempt {attempt}: {exc}", file=sys.stderr)
    else:
        sys.exit(f"no usable turn in {ATTEMPTS} attempts; nothing written")
    if args.check:
        print(json.dumps(recording, indent=1, ensure_ascii=False))
        return
    OUT.write_text(json.dumps(recording, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
