"""Scripted demo traffic through the gateway, and the checks the smoke test makes on it.

Every value is fictional (ADR 0005): the names are the project's placeholder identities, the
e-mail domains are ``example.*`` and the identifiers are well-known test numbers. Each scenario
lists its **gold** values: the ones the rules detector (the offline default) must mask, so
none of them may ever reach the upstream.

With the mock upstream (:mod:`pii_guard.bench.mock_upstream`) the answers are predictable:
the client must get back ``Echo: <its own last message>`` -- exactly, after unmasking -- or a
tool call whose arguments carry that text. :func:`run` sends the scenarios and returns one
:class:`Outcome` each; :func:`check` turns outcomes plus what the upstream received into a
list of failures (empty = pass).
"""

from __future__ import annotations

import base64
import io
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

__all__ = ["SCENARIOS", "Outcome", "Scenario", "check", "gold_values", "leaks", "run"]

TEXT_HU = (
    "Szia! Teszt Elek vagyok, e-mail: teszt.elek@example.com, telefon: +36 30 123 4567. "
    "Kérlek, utald a díjat a HU42 1177 3016 1111 1018 0000 0000 számlára, TAJ számom "
    "123 456 788."
)
TEXT_HU_ADDRESS = "Az új lakcímem 1051 Budapest, Minta utca 12., kérlek frissítsd a szerződésen."
TEXT_EN = (
    "Hi, this is Jane Placeholder (jane.placeholder@example.net, +44 20 7946 0958). Please "
    "refund the deposit to GB82 WEST 1234 5698 7654 32 and void card 4111 1111 1111 1111."
)
TEXT_DE = (
    "Hallo, hier ist Erika Mustermann, E-Mail erika.mustermann@example.de, Telefon "
    "+49 30 901820. Bitte überweisen Sie auf DE89 3704 0044 0532 0130 00."
)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an e-mail on the user's behalf.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    }
]


@dataclass(frozen=True)
class Scenario:
    """One scripted request. ``expect``: ``echo``, ``tool`` or ``refused_or_echo`` (images)."""

    name: str
    language: str
    text: str
    gold: tuple[str, ...]
    stream: bool = False
    tools: bool = False
    expect: str = "echo"
    system: str | None = None
    known_values: tuple[tuple[str, str], ...] = ()  # (value, entity type)
    image: bool = False
    follow_up: str | None = None  # a second turn in the same session
    mode: str = "fast"


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "hu-chat",
        "hu",
        TEXT_HU,
        (
            "teszt.elek@example.com",
            "+36 30 123 4567",
            "HU42 1177 3016 1111 1018 0000 0000",
            "123 456 788",
        ),
        system="Ügyfélszolgálati asszisztens vagy. Válaszolj röviden.",
        follow_up="Köszönöm! Kérlek, erősítsd meg az e-mail címemet: teszt.elek@example.com.",
    ),
    Scenario(
        "hu-stream",
        "hu",
        TEXT_HU_ADDRESS,
        ("1051 Budapest, Minta utca 12",),
        stream=True,
    ),
    Scenario(
        "en-stream",
        "en",
        TEXT_EN,
        (
            "jane.placeholder@example.net",
            "+44 20 7946 0958",
            "GB82 WEST 1234 5698 7654 32",
            "4111 1111 1111 1111",
        ),
        stream=True,
    ),
    Scenario(
        "de-tools",
        "de",
        TEXT_DE,
        ("erika.mustermann@example.de", "+49 30 901820", "DE89 3704 0044 0532 0130 00"),
        tools=True,
        expect="tool",
    ),
    Scenario(
        "de-tools-stream",
        "de",
        TEXT_DE,
        ("erika.mustermann@example.de", "+49 30 901820", "DE89 3704 0044 0532 0130 00"),
        tools=True,
        stream=True,
        expect="tool",
    ),
    Scenario(
        "en-known-values",
        "en",
        "Please draft a short note to Minta Mária about the Placeholder Kft. contract.",
        ("Minta Mária", "Placeholder Kft."),
        known_values=(("Minta Mária", "PERSON"), ("Placeholder Kft.", "ORGANIZATION")),
    ),
    Scenario(
        "hu-image",
        "hu",
        "Mi látható ezen a képen? Teszt Elek személyi igazolványa.",
        (),
        image=True,
        expect="refused_or_echo",
    ),
)


@dataclass
class Outcome:
    scenario: Scenario
    status: int
    content: str | None = None
    tool_arguments: str | None = None
    expected: str = ""
    session: str | None = None
    request_id: str | None = None
    elapsed_ms: float = 0.0
    turn: int = 1
    error: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


def gold_values(scenarios: Sequence[Scenario] = SCENARIOS) -> list[str]:
    return sorted({g for s in scenarios for g in s.gold})


def _png() -> str:
    """A small fictional test image (a grey card), as a data URL."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (96, 64), (220, 220, 220))
    ImageDraw.Draw(img).rectangle((8, 8, 40, 56), fill=(150, 150, 150))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _messages(scenario: Scenario, history: Sequence[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if scenario.system and not history:
        messages.append({"role": "system", "content": scenario.system})
    messages.extend(history)
    if scenario.image:
        content: Any = [
            {"type": "text", "text": scenario.text},
            {"type": "image_url", "image_url": {"url": _png()}},
        ]
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": scenario.text})
    return messages


def _read_stream(response: httpx.Response) -> tuple[str, str]:
    content: list[str] = []
    arguments: list[str] = []
    for line in response.iter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        if "error" in chunk:
            raise RuntimeError(f"stream error: {chunk['error'].get('code')}")
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if isinstance(delta.get("content"), str):
                content.append(delta["content"])
            for call in delta.get("tool_calls") or []:
                piece = (call.get("function") or {}).get("arguments")
                if isinstance(piece, str):
                    arguments.append(piece)
    return "".join(content), "".join(arguments)


def _send(
    client: httpx.Client,
    scenario: Scenario,
    messages: list[dict[str, Any]],
    *,
    model: str,
    session: str | None,
    turn: int,
) -> Outcome:
    body: dict[str, Any] = {"model": model, "messages": messages}
    if scenario.stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    if scenario.tools:
        body["tools"] = TOOLS
    headers = {"X-PII-Guard-Mode": scenario.mode, "X-PII-Guard-Language": scenario.language}
    if session:
        headers["X-PII-Guard-Session"] = session
    expected = f"Echo: {scenario.text if turn == 1 else scenario.follow_up}"
    started = time.perf_counter()
    outcome = Outcome(scenario, 0, expected=expected, turn=turn)
    try:
        if scenario.stream:
            with client.stream("POST", "/v1/chat/completions", json=body, headers=headers) as r:
                outcome.status = r.status_code
                outcome.headers = dict(r.headers)
                if r.status_code < 400:
                    outcome.content, outcome.tool_arguments = _read_stream(r)
                else:
                    r.read()
                    outcome.error = _error_code(r)
        else:
            r = client.post("/v1/chat/completions", json=body, headers=headers)
            outcome.status = r.status_code
            outcome.headers = dict(r.headers)
            if r.status_code < 400:
                message = r.json()["choices"][0]["message"]
                outcome.content = message.get("content")
                calls = message.get("tool_calls") or []
                if calls:
                    outcome.tool_arguments = calls[0]["function"]["arguments"]
            else:
                outcome.error = _error_code(r)
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
        outcome.error = f"{type(exc).__name__}: {exc}"
    outcome.elapsed_ms = (time.perf_counter() - started) * 1000
    outcome.session = outcome.headers.get("x-pii-guard-session", session)
    outcome.request_id = outcome.headers.get("x-pii-guard-request-id")
    return outcome


def _error_code(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return f"HTTP {response.status_code}"


def run(
    base_url: str,
    *,
    scenarios: Sequence[Scenario] = SCENARIOS,
    model: str = "pii-guard-mock",
    timeout: float = 120.0,
    on_outcome: Callable[[Outcome], None] | None = None,
    client: httpx.Client | None = None,
) -> list[Outcome]:
    """Send every scenario (and its follow-up turn) through the gateway at ``base_url``.

    ``client`` (tests: a ``TestClient``) replaces the HTTP client built from ``base_url``.
    """
    outcomes: list[Outcome] = []
    owned = client is None
    if client is None:
        client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
    try:
        for scenario in scenarios:
            session = None
            if scenario.known_values:
                r = client.post(
                    "/v1/sessions",
                    json={
                        "known_values": [
                            {"value": v, "entity_type": t} for v, t in scenario.known_values
                        ]
                    },
                )
                r.raise_for_status()
                session = r.json()["session_id"]
            messages = _messages(scenario)
            first = _send(client, scenario, messages, model=model, session=session, turn=1)
            outcomes.append(first)
            if on_outcome:
                on_outcome(first)
            if scenario.follow_up and first.status < 400 and first.content is not None:
                history = [
                    *messages,
                    {"role": "assistant", "content": first.content},
                ]
                follow = Scenario(
                    scenario.name,
                    scenario.language,
                    scenario.follow_up,
                    scenario.gold,
                    stream=scenario.stream,
                    mode=scenario.mode,
                )
                second = _send(
                    client,
                    scenario,
                    _messages(follow, history),
                    model=model,
                    session=first.session,
                    turn=2,
                )
                outcomes.append(second)
                if on_outcome:
                    on_outcome(second)
    finally:
        if owned:
            client.close()
    return outcomes


def leaks(received: Sequence[str], gold: Sequence[str]) -> list[str]:
    """Gold values present in what the upstream received: raw, JSON-escaped or without spaces."""
    found = []
    for raw in received:
        try:
            decoded = json.dumps(json.loads(raw), ensure_ascii=False)
        except ValueError:
            decoded = raw
        compact = raw.replace(" ", "")
        for value in gold:
            escaped = json.dumps(value)[1:-1]
            squeezed = value.replace(" ", "")
            if value in raw or value in decoded or escaped in raw:
                found.append(value)
            elif len(squeezed) > 8 and squeezed in compact:
                found.append(value + " (without spaces)")
    return sorted(set(found))


def check(outcomes: Sequence[Outcome], received: Sequence[str]) -> list[str]:
    """Failures: a wrong (not exactly restored) answer, an unexpected error, or a leak."""
    failures = []
    for o in outcomes:
        label = f"{o.scenario.name} (turn {o.turn})"
        expect = o.scenario.expect
        if expect == "refused_or_echo" and o.status >= 400:
            continue  # fail closed: the image could not be masked, nothing was forwarded
        if o.status >= 400 or o.error:
            failures.append(f"{label}: HTTP {o.status} {o.error or ''}".strip())
            continue
        if expect == "tool":
            try:
                args = json.loads(o.tool_arguments or "")
            except ValueError:
                failures.append(f"{label}: tool arguments are not JSON")
                continue
            if args != {"text": o.scenario.text}:
                failures.append(f"{label}: tool arguments were not restored exactly")
        elif o.content != o.expected:
            failures.append(f"{label}: answer was not restored exactly")
    gold = gold_values([o.scenario for o in outcomes])
    for value in leaks(received, gold):
        failures.append(f"gold value reached the upstream: {value}")
    return failures
