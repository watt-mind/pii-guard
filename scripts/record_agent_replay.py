"""Record the landing's agent-turn replay (LAB-1499).

The landing (``ui/src/hosted/AgentReplay.tsx``) replays one agent turn through the gateway:
the agent reads a fictional CRM record with a tool, the model sees it with placeholders, the
model streams a ``send_email`` tool call whose arguments carry placeholders, PII Guard restores
them before the agent runs the tool, and the model's closing text is restored as it streams,
with a placeholder held back while it is split across chunks.

This script makes that recording with the real gateway in fast mode (rules + the published
NER, as in production) and a scripted stand-in upstream, so no model provider is called. The
stand-in answers from the placeholders it received, and splits its stream so that placeholders
cross chunk boundaries.

The written JSON is value-free: the masked tool result the upstream saw, the chunks the
upstream streamed and the chunks the agent received, with every restored value written back as
its placeholder (the browser puts the fictional values back from ``RECORD`` in
``AgentReplay.tsx``, which must stay in step with ``RECORD`` below). The script fails if any
fictional value reaches the upstream or would be written. Needs the ``ner`` extra::

    uv run --no-sync python scripts/record_agent_replay.py            # writes the recording
    uv run --no-sync python scripts/record_agent_replay.py --check    # checks, writes nothing
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import secrets
import sys
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway import GatewayConfig, Mode, build_mode_detectors
from pii_guard.vault import PLACEHOLDER_RE

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ui" / "src" / "content" / "agentReplayRecording.json"
UPSTREAM = "https://upstream.invalid/v1"

#: The task. No personal data in it: the agent has to read the record.
TASK = "Refund ticket 4471 is approved. Look up the customer in crm.json and email them."
#: The fictional CRM record the agent's read_file tool returns. Keep in step with RECORD in
#: ui/src/hosted/AgentReplay.tsx.
RECORD = (
    '{"customer": "Robin Example", "email": "robin.example@example.com", '
    '"iban": "DE89 3704 0044 0532 0130 00"}'
)
VALUES = ("Robin Example", "robin.example@example.com", "DE89 3704 0044 0532 0130 00")
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
            person = PLACEHOLDER_RE.search(args["body"]).group(0)
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


def record() -> dict[str, Any]:
    standin = StandIn()
    settings = Settings(
        tenant_key=secrets.token_hex(32),
        upstream_base_url=UPSTREAM,
        upstream_api_key="sk-stand-in-0000",
        ner_fallback="cached",
    )
    config = GatewayConfig(mode=Mode.FAST)
    app = create_app(settings)
    app.state.gateway_config = config
    app.state.gateway_transport = httpx.MockTransport(standin.handler)
    app.state.gateway_detectors = build_mode_detectors(settings, config)
    headers = {"Authorization": f"Bearer {settings.tenant_key}"}
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a support agent with file and e-mail tools."},
        {"role": "user", "content": TASK},
    ]
    received: list[list[dict[str, Any]]] = []
    session = None
    with TestClient(app, base_url="http://127.0.0.1") as http:
        for step in range(3):
            h = {**headers, **({"X-PII-Guard-Session": session} if session else {})}
            r = http.post(
                "/v1/chat/completions",
                json={"model": "stand-in", "stream": True, "messages": messages, "tools": TOOLS},
                headers=h,
            )
            r.raise_for_status()
            session = r.headers["x-pii-guard-session"]
            events = parse_sse(r.text)
            received.append(events)
            if step == 0:
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_read",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": "".join(deltas(events, "arguments")),
                                },
                            }
                        ],
                    }
                )
                messages.append({"role": "tool", "tool_call_id": "call_read", "content": RECORD})
            elif step == 1:
                args = "".join(deltas(events, "arguments"))
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_send",
                                "type": "function",
                                "function": {"name": "send_email", "arguments": args},
                            }
                        ],
                    }
                )
                messages.append(
                    {"role": "tool", "tool_call_id": "call_send", "content": '{"status": "sent"}'}
                )

    for raw in standin.raw:
        text = raw.decode()
        for value in VALUES:
            if value in text or value in json.dumps(json.loads(raw), ensure_ascii=False):
                sys.exit(f"leak: a fictional value reached the upstream: {value!r}")

    masked_record = next(
        m["content"] for m in standin.bodies[1]["messages"] if m.get("role") == "tool"
    )
    mapping = {f"[[{t}_{i}]]": None for t, i in PLACEHOLDER_RE.findall(masked_record)}
    # Which value each placeholder stands for, from what the agent received back.
    restored_args = json.loads("".join(deltas(received[1], "arguments")))
    sent_args = json.loads("".join(deltas(standin.streams[1], "arguments")))
    for key in ("to", "body"):
        for ph in PLACEHOLDER_RE.finditer(sent_args[key]):
            mapping[ph.group(0)] = None
    values = {}
    for ph in mapping:
        kind = PLACEHOLDER_RE.match(ph).group(1)
        values[ph] = {"PERSON": VALUES[0], "EMAIL": VALUES[1], "BANK_ACCOUNT": VALUES[2]}[kind]
    for key in ("to", "body"):
        expected = sent_args[key]
        for ph, value in values.items():
            expected = expected.replace(ph, value)
        if restored_args[key] != expected:
            sys.exit(f"restore check failed for {key!r}")

    def value_free(pieces: list[str]) -> list[str]:
        out = []
        for piece in pieces:
            for ph, value in values.items():
                piece = piece.replace(value, ph)
            out.append(piece)
        return out

    recording = {
        "recorded": dt.date.today().isoformat(),
        "how": (
            "scripts/record_agent_replay.py: the gateway in fast mode (rules + published NER), "
            "a scripted stand-in upstream, fictional data"
        ),
        "task": TASK,
        "upstream_requests": len(standin.raw),
        "values_reaching_upstream": 0,
        "read_call": {"name": "read_file", "arguments": "".join(deltas(received[0], "arguments"))},
        "masked_record": masked_record,
        "send_call": {
            "name": "send_email",
            "upstream": deltas(standin.streams[1], "arguments"),
            "agent": value_free(deltas(received[1], "arguments")),
        },
        "answer": {
            "upstream": deltas(standin.streams[2], "content"),
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
    args = parser.parse_args()
    recording = record()
    if args.check:
        print(json.dumps(recording, indent=1, ensure_ascii=False))
        return
    OUT.write_text(json.dumps(recording, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
