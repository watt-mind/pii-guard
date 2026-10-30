"""A regex-escaped placeholder in a tool-call argument is restored, escaped the same way (LAB-1481).

The model writes ``\\[\\[EMAIL_x\\]\\]`` in a ``sed``/``perl``/``python`` pattern (LAB-1475,
Codex turn 2). The gateway restores it to the value as a regex literal, so the command still
matches the file on disk. Only tool-call fields are covered (``function.arguments``, the legacy
``function_call.arguments``, custom tool ``input``; Chat Completions and Responses, whole and
streamed); message text is unchanged. In JSON arguments the escape is JSON-encoded too
(``\\\\[\\\\[``). Other escape depths, and unknown or other sessions' placeholders, stay as is.

Every value is fictional (ADR 0005).
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from gateway_helpers import TEST_TENANT_KEY, chunk, completion

from pii_guard.gateway.responses_restore import ResponsesSseRestorer, restore_response
from pii_guard.gateway.restore import (
    JsonEscapingSession,
    ToolInputSession,
    regex_literal,
    restore_completion,
)
from pii_guard.gateway.stream import DONE, SseRestorer
from pii_guard.types import EntityType, Span
from pii_guard.vault import UnmaskOutputTooLargeError, Vault, VaultSession
from pii_guard.vault.placeholders import MAX_PLACEHOLDER_LENGTH

EMAIL = "teszt.elek+munka@example.com"
PHONE = "+36 (1) 555-0100"
CONTACTS = '{\n  "email": "teszt.elek+munka@example.com",\n  "phone": "+36 (1) 555-0100"\n}\n'


def _session(**extra: Any) -> VaultSession:
    return Vault(bytes.fromhex(TEST_TENANT_KEY), **extra).session()


def _placeholder(session: VaultSession, value: str, entity: EntityType) -> str:
    text = f"v {value}"
    return session.mask(text, [Span(2, len(text), entity, value, 1.0, "test")])[2:]


def _escaped(placeholder: str) -> str:
    """``[[EMAIL_x]]`` -> ``\\[\\[EMAIL_x\\]\\]``, as a model writes it in a regex."""
    return placeholder.replace("[", "\\[").replace("]", "\\]")


def _sed_command(session: VaultSession) -> tuple[str, str]:
    """The LAB-1475 command (escaped in the pattern, plain in the replacement) and its email."""
    ph = _placeholder(session, EMAIL, EntityType.EMAIL)
    return f'sed -i \'s/"email": "{_escaped(ph)}",/"email": "{ph}", "ok": 1,/\' c.json', ph


def _pattern(command: str) -> str:
    return command.split("s/", 1)[1].split("/", 1)[0]


# --- the escape itself --------------------------------------------------------------------


@pytest.mark.parametrize("value", [EMAIL, PHONE, "a.b*c[d]^e$f/g\\h?i{2}j|k"])
def test_regex_literal_matches_only_the_value(value: str) -> None:
    literal = regex_literal(value)
    assert re.fullmatch(literal, value)
    assert re.search(literal, f"x{value}y").group(0) == value  # type: ignore[union-attr]
    # "+ ( ) ? { } |" are bracketed, not backslashed: "\+" and "\(" are operators in GNU sed BRE.
    assert "\\+" not in literal and "\\(" not in literal
    assert "@" not in literal.replace("[@]", "")  # Perl would interpolate "@example"


def test_regex_literal_of_an_email_does_not_match_a_lookalike() -> None:
    assert re.search(regex_literal(EMAIL), "teszt-elek+munka@example.com") is None
    assert re.search(regex_literal(EMAIL), "teszt.elekkmunka@example.com") is None


# --- chat completions, whole ---------------------------------------------------------------


def test_escaped_placeholder_in_function_arguments_is_restored_as_a_regex_literal() -> None:
    session = _session()
    command, _ = _sed_command(session)
    body = completion(
        "",
        tool_calls=[
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "shell", "arguments": json.dumps({"cmd": command})},
            }
        ],
    )
    report = restore_completion(session, body)
    restored = json.loads(body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
    cmd = restored["cmd"]
    assert "[[" not in cmd and "\\[\\[" not in cmd
    pattern = _pattern(cmd)
    assert pattern == f'"email": "{regex_literal(EMAIL)}",'
    assert re.search(pattern, CONTACTS)  # the edit now matches the file on disk
    assert f'"email": "{EMAIL}", "ok": 1,' in cmd  # the plain one, as before
    assert report.unresolved == {}


def test_escaped_placeholder_in_custom_tool_input_is_restored() -> None:
    session = _session()
    command, _ = _sed_command(session)
    body = completion(
        "", tool_calls=[{"id": "c", "type": "custom", "custom": {"name": "sh", "input": command}}]
    )
    restore_completion(session, body)
    cmd = body["choices"][0]["message"]["tool_calls"][0]["custom"]["input"]
    assert _pattern(cmd) == f'"email": "{regex_literal(EMAIL)}",'
    assert re.search(_pattern(cmd), CONTACTS)


def test_escaped_placeholder_in_legacy_function_call_is_restored() -> None:
    session = _session()
    ph = _placeholder(session, PHONE, EntityType.PHONE)
    body = completion("")
    body["choices"][0]["message"]["function_call"] = {
        "name": "grep",
        "arguments": json.dumps({"pattern": _escaped(ph)}),
    }
    restore_completion(session, body)
    args = json.loads(body["choices"][0]["message"]["function_call"]["arguments"])
    assert args == {"pattern": regex_literal(PHONE)}
    assert re.search(args["pattern"], CONTACTS)


def test_open_only_escape_is_restored() -> None:
    """``\\[\\[EMAIL_x]]`` is a valid regex too: an unescaped ``]`` is a literal."""
    session = _session()
    ph = _placeholder(session, EMAIL, EntityType.EMAIL)
    written = ph.replace("[", "\\[")
    body = completion(
        "", tool_calls=[{"type": "custom", "custom": {"name": "t", "input": written}}]
    )
    restore_completion(session, body)
    assert body["choices"][0]["message"]["tool_calls"][0]["custom"]["input"] == regex_literal(EMAIL)


# --- not over-matching ---------------------------------------------------------------------


def test_message_text_is_unchanged() -> None:
    """Prose is not a tool argument: an escaped placeholder in content stays as written."""
    session = _session()
    ph = _placeholder(session, EMAIL, EntityType.EMAIL)
    body = completion(f"run sed 's/{_escaped(ph)}/x/'")
    restore_completion(session, body)
    assert body["choices"][0]["message"]["content"] == f"run sed 's/{_escaped(ph)}/x/'"


@pytest.mark.parametrize(
    "template",
    [
        "\\\\[\\\\[{body}\\\\]\\\\]",  # a double escape (a shell-quoted backslash): not ours
        "\\\\\\[\\[{body}\\]\\]",  # preceded by an escaped backslash
        "\\[{body}\\]",  # a single bracket
        "\\[\\[{body} \\]\\]",  # broken
    ],
)
def test_other_escape_shapes_in_custom_input_stay_as_is(template: str) -> None:
    session = _session()
    ph = _placeholder(session, EMAIL, EntityType.EMAIL)
    written = template.format(body=ph[2:-2])
    body = completion(
        "", tool_calls=[{"type": "custom", "custom": {"name": "t", "input": written}}]
    )
    restore_completion(session, body)
    assert body["choices"][0]["message"]["tool_calls"][0]["custom"]["input"] == written


def test_single_backslash_escape_in_json_arguments_is_not_read_as_json() -> None:
    """In JSON, ``\\[`` is no escape at all: only the JSON-encoded ``\\\\[`` form is restored."""
    session = _session()
    ph = _placeholder(session, EMAIL, EntityType.EMAIL)
    arguments = '{"p": "' + _escaped(ph) + '"}'
    body = completion(
        "", tool_calls=[{"type": "function", "function": {"name": "f", "arguments": arguments}}]
    )
    restore_completion(session, body)
    assert body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == arguments


def test_escaped_backslash_before_u005b_is_not_corrupted_in_json_arguments() -> None:
    """``\\\\u005b[EMAIL_x]]`` has a literal backslash before ``u005b`` and must stay valid JSON."""
    session = _session()
    ph = _placeholder(session, EMAIL, EntityType.EMAIL)
    arguments = '{"p": "\\\\u005b' + ph[1:] + '"}'
    body = completion(
        "", tool_calls=[{"type": "function", "function": {"name": "f", "arguments": arguments}}]
    )
    restore_completion(session, body)
    restored = body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert restored == arguments
    assert json.loads(restored) == {"p": "\\u005b" + ph[1:]}


def test_unknown_escaped_placeholder_is_left_and_counted() -> None:
    session = _session()
    written = "\\[\\[EMAIL_000000\\]\\]"
    body = completion(
        "", tool_calls=[{"type": "custom", "custom": {"name": "t", "input": written}}]
    )
    report = restore_completion(session, body)
    assert body["choices"][0]["message"]["tool_calls"][0]["custom"]["input"] == written
    assert list(report.unresolved) == ["[[EMAIL_000000]]"]


def test_another_sessions_escaped_placeholder_is_not_restored() -> None:
    vault = Vault(bytes.fromhex(TEST_TENANT_KEY))
    mine, other = vault.session(), vault.session()
    ph = _placeholder(other, EMAIL, EntityType.EMAIL)
    arguments = json.dumps({"p": _escaped(ph)})
    body = completion(
        "", tool_calls=[{"type": "function", "function": {"name": "f", "arguments": arguments}}]
    )
    report = restore_completion(mine, body)
    assert body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == arguments
    assert list(report.unresolved) == [ph]


def test_escaped_restore_is_charged_to_the_budget() -> None:
    session = _session(max_restored_chars=len(EMAIL) - 1)
    ph = _placeholder(session, EMAIL, EntityType.EMAIL)
    body = completion(
        "", tool_calls=[{"type": "custom", "custom": {"name": "t", "input": _escaped(ph)}}]
    )
    with pytest.raises(UnmaskOutputTooLargeError):
        restore_completion(session, body)


# --- chat completions, streamed ------------------------------------------------------------


def _run(restorer: SseRestorer, payloads: list[dict[str, Any]], *, done: bool = True) -> list:
    out: list[str] = []
    for payload in payloads:
        out += restorer.process(json.dumps(payload))
    out += restorer.process(DONE) if done else restorer.finish()
    return [json.loads(item) for item in out if item != DONE]


def _cuts(text: str, needle: str) -> list[int]:
    """Every cut position inside ``needle`` (and one on each side)."""
    start = text.index(needle)
    return list(range(start, start + len(needle) + 1))


def _streamed_arguments(session: VaultSession, pieces: list[str], finish: bool) -> str:
    payloads = [
        chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "c",
                        "type": "function",
                        "function": {"name": "sh", "arguments": ""},
                    }
                ]
            }
        )
    ]
    payloads += [
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": p}}]}) for p in pieces
    ]
    if finish:
        payloads.append(chunk({}, finish="tool_calls"))
    events = _run(SseRestorer(session), payloads, done=finish)
    return "".join(
        call.get("function", {}).get("arguments", "")
        for event in events
        for choice in event.get("choices", [])
        for call in choice["delta"].get("tool_calls", [])
    )


@pytest.mark.parametrize("finish", [True, False], ids=["finish_reason", "stream_end"])
def test_streamed_arguments_restore_an_escaped_placeholder_split_anywhere(finish: bool) -> None:
    session = _session()
    command, ph = _sed_command(session)
    arguments = json.dumps({"cmd": command})
    encoded = json.dumps(_escaped(ph))[1:-1]  # "\\[\\[EMAIL_x\\]\\]" as the JSON text has it
    whole = completion(
        "", tool_calls=[{"type": "function", "function": {"name": "sh", "arguments": arguments}}]
    )
    restore_completion(session, whole)
    expected = whole["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    for cut in _cuts(arguments, encoded):
        streamed = _streamed_arguments(session, [arguments[:cut], arguments[cut:]], finish)
        assert streamed == expected, cut
    assert re.search(_pattern(json.loads(expected)["cmd"]), CONTACTS)


def test_streamed_arguments_restore_one_character_at_a_time() -> None:
    session = _session()
    command, _ = _sed_command(session)
    arguments = json.dumps({"cmd": command})
    streamed = _streamed_arguments(session, list(arguments), True)
    cmd = json.loads(streamed)["cmd"]
    assert _pattern(cmd) == f'"email": "{regex_literal(EMAIL)}",'


def test_streamed_custom_input_restores_an_escaped_placeholder_split_anywhere() -> None:
    session = _session()
    command, ph = _sed_command(session)
    for cut in _cuts(command, _escaped(ph)):
        payloads = [
            chunk(
                {
                    "tool_calls": [
                        {"index": 0, "type": "custom", "custom": {"name": "t", "input": p}}
                    ]
                }
            )
            for p in (command[:cut], command[cut:])
        ]
        payloads.append(chunk({}, finish="tool_calls"))
        events = _run(SseRestorer(session), payloads)
        restored = "".join(
            call.get("custom", {}).get("input", "")
            for event in events
            for choice in event.get("choices", [])
            for call in choice["delta"].get("tool_calls", [])
        )
        assert _pattern(restored) == f'"email": "{regex_literal(EMAIL)}",', cut


def test_streamed_double_escape_split_at_the_backslashes_stays_as_is() -> None:
    """A cut between the backslashes of ``\\\\[`` must not make the second one look single."""
    session = _session()
    ph = _placeholder(session, EMAIL, EntityType.EMAIL)
    written = "x\\\\" + _escaped(ph)[1:]  # "x\\[\\[EMAIL_x\\]\\]": the "\[" after "\\" is no escape
    for cut in range(len(written) + 1):
        payloads = [
            chunk(
                {
                    "tool_calls": [
                        {"index": 0, "type": "custom", "custom": {"name": "t", "input": p}}
                    ]
                }
            )
            for p in (written[:cut], written[cut:])
        ]
        events = _run(SseRestorer(session), payloads)
        restored = "".join(
            call.get("custom", {}).get("input", "")
            for event in events
            for choice in event.get("choices", [])
            for call in choice["delta"].get("tool_calls", [])
        )
        assert restored == written, cut


def test_streamed_content_keeps_an_escaped_placeholder() -> None:
    session = _session()
    ph = _placeholder(session, EMAIL, EntityType.EMAIL)
    text = f"use {_escaped(ph)}"
    events = _run(
        SseRestorer(session), [chunk({"content": text[:9]}), chunk({"content": text[9:]})]
    )
    content = "".join(c["delta"].get("content", "") for e in events for c in e.get("choices", []))
    assert content == text


# --- Responses API -------------------------------------------------------------------------


def test_responses_whole_function_call_and_custom_input_are_restored() -> None:
    session = _session()
    command, _ = _sed_command(session)
    body = {
        "object": "response",
        "output": [
            {
                "type": "function_call",
                "call_id": "a",
                "name": "sh",
                "arguments": json.dumps({"cmd": command}),
            },
            {"type": "custom_tool_call", "call_id": "b", "name": "sh", "input": command},
            {"type": "message", "content": [{"type": "output_text", "text": command}]},
        ],
    }
    restore_response(session, body)
    literal = f'"email": "{regex_literal(EMAIL)}",'
    assert _pattern(json.loads(body["output"][0]["arguments"])["cmd"]) == literal
    assert _pattern(body["output"][1]["input"]) == literal
    # Message text keeps the escaped form (only tool input is a regex context).
    assert "\\[\\[EMAIL_" in body["output"][2]["content"][0]["text"]


@pytest.mark.parametrize(
    ("delta_type", "field", "json_args"),
    [
        ("response.function_call_arguments", "arguments", True),
        ("response.custom_tool_call_input", "input", False),
    ],
)
def test_responses_streamed_tool_input_restores_an_escaped_placeholder_split_anywhere(
    delta_type: str, field: str, json_args: bool
) -> None:
    session = _session()
    command, ph = _sed_command(session)
    text = json.dumps({"cmd": command}) if json_args else command
    needle = json.dumps(_escaped(ph))[1:-1] if json_args else _escaped(ph)
    for cut in _cuts(text, needle):
        restorer = ResponsesSseRestorer(session)
        out: list[tuple[str | None, str]] = []
        for part in (text[:cut], text[cut:]):
            event = {"type": f"{delta_type}.delta", "output_index": 0, "delta": part}
            out += restorer.process(event["type"], json.dumps(event))
        done = {"type": f"{delta_type}.done", "output_index": 0, field: text}
        out += restorer.process(done["type"], json.dumps(done))
        events = [json.loads(data) for _, data in out]
        deltas = "".join(e["delta"] for e in events if e["type"].endswith(".delta"))
        assert deltas == events[-1][field], cut
        restored = json.loads(deltas)["cmd"] if json_args else deltas
        assert _pattern(restored) == f'"email": "{regex_literal(EMAIL)}",', cut


@pytest.mark.parametrize(
    "tail",
    [
        "\\[x\\[A",
        "\\[\\[" + "A" * (MAX_PLACEHOLDER_LENGTH + 2),  # longer than any body
        "\\[\\[1",
        "\\[\\[EMAIL_ab12x",
        "\\[\\[EMAIL_ab12\\]x",
    ],
    ids=["bad_opening", "too_long", "no_type", "bad_body", "bad_closing"],
)
def test_a_tail_that_cannot_become_an_escaped_placeholder_is_not_held(tail: str) -> None:
    assert ToolInputSession.hold_from("go " + tail) == len("go " + tail)
    encoded = json.dumps(tail)[1:-1]
    assert JsonEscapingSession.hold_from("go " + encoded) == len("go " + encoded)


@pytest.mark.parametrize("tail", ["\\", "\\[\\", "\\[\\[EMAIL_ab", "\\[\\[EMAIL_ab12\\]"])
def test_a_tail_that_may_become_an_escaped_placeholder_is_held(tail: str) -> None:
    assert ToolInputSession.hold_from("go " + tail) == 3
    assert JsonEscapingSession.hold_from("go " + json.dumps(tail)[1:-1]) == 3


# --- encoded placeholder brackets (LAB-1564) ------------------------------------------------


def _encoded(placeholder: str, form: str) -> str:
    """The placeholder with its brackets in one encoded form (``unicode`` or ``percent``)."""
    if form == "unicode":
        return placeholder.replace("[", "\\u005b").replace("]", "\\u005d")
    return placeholder.replace("[", "%5B").replace("]", "%5D")


@pytest.mark.parametrize("form", ["unicode", "percent"])
def test_encoded_placeholder_in_json_arguments_is_restored(form: str) -> None:
    session = _session()
    ph = _placeholder(session, EMAIL, EntityType.EMAIL)
    arguments = '{"url": "https://x.test/?to=' + _encoded(ph, form) + '"}'
    body = completion(
        "", tool_calls=[{"type": "function", "function": {"name": "f", "arguments": arguments}}]
    )
    report = restore_completion(session, body)
    restored = body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(restored) == {"url": f"https://x.test/?to={EMAIL}"}
    assert report.unresolved == {}


@pytest.mark.parametrize("form", ["unicode", "percent"])
def test_encoded_placeholder_in_custom_tool_input_is_restored(form: str) -> None:
    session = _session()
    ph = _placeholder(session, EMAIL, EntityType.EMAIL)
    text = f"to={_encoded(ph, form)}"
    body = completion("", tool_calls=[{"type": "custom", "custom": {"name": "t", "input": text}}])
    report = restore_completion(session, body)
    assert body["choices"][0]["message"]["tool_calls"][0]["custom"]["input"] == f"to={EMAIL}"
    assert report.unresolved == {}


def test_encoded_placeholder_with_mixed_brackets_is_restored() -> None:
    session = _session()
    ph = _placeholder(session, EMAIL, EntityType.EMAIL)
    written = "%5b\\u005B" + ph[2:-2] + "]%5d"
    body = completion(
        "", tool_calls=[{"type": "custom", "custom": {"name": "t", "input": written}}]
    )
    restore_completion(session, body)
    assert body["choices"][0]["message"]["tool_calls"][0]["custom"]["input"] == EMAIL


@pytest.mark.parametrize("form", ["unicode", "percent"])
def test_unknown_encoded_placeholder_is_left_as_written_and_counted(form: str) -> None:
    session = _session()
    written = _encoded("[[EMAIL_000000]]", form)
    arguments = '{"url": "' + written + '"}'
    body = completion(
        "", tool_calls=[{"type": "function", "function": {"name": "f", "arguments": arguments}}]
    )
    report = restore_completion(session, body)
    restored = body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert restored == arguments
    assert list(report.unresolved) == ["[[EMAIL_000000]]"]


@pytest.mark.parametrize("form", ["unicode", "percent"])
def test_streamed_arguments_restore_an_encoded_placeholder_split_anywhere(form: str) -> None:
    session = _session()
    ph = _placeholder(session, EMAIL, EntityType.EMAIL)
    arguments = '{"url": "https://x.test/?to=' + _encoded(ph, form) + '"}'
    whole = completion(
        "", tool_calls=[{"type": "function", "function": {"name": "f", "arguments": arguments}}]
    )
    restore_completion(session, whole)
    expected = whole["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    for cut in _cuts(arguments, _encoded(ph, form)):
        streamed = _streamed_arguments(session, [arguments[:cut], arguments[cut:]], True)
        assert streamed == expected, cut


@pytest.mark.parametrize("form", ["unicode", "percent"])
def test_streamed_custom_input_restores_an_encoded_placeholder_split_anywhere(form: str) -> None:
    session = _session()
    ph = _placeholder(session, EMAIL, EntityType.EMAIL)
    text = f"to={_encoded(ph, form)} end"
    for cut in _cuts(text, _encoded(ph, form)):
        payloads = [
            chunk(
                {
                    "tool_calls": [
                        {"index": 0, "type": "custom", "custom": {"name": "t", "input": p}}
                    ]
                }
            )
            for p in (text[:cut], text[cut:])
        ]
        payloads.append(chunk({}, finish="tool_calls"))
        events = _run(SseRestorer(session), payloads)
        restored = "".join(
            call.get("custom", {}).get("input", "")
            for event in events
            for choice in event.get("choices", [])
            for call in choice["delta"].get("tool_calls", [])
        )
        assert restored == f"to={EMAIL} end", cut


@pytest.mark.parametrize(
    "tail", ["%", "%5", "%5B%5BEMAIL_ab", "\\u005", "\\u005b\\u005bEMAIL_ab12%5"]
)
def test_a_tail_that_may_become_an_encoded_placeholder_is_held(tail: str) -> None:
    assert ToolInputSession.hold_from("go " + tail) == 3
    assert JsonEscapingSession.hold_from("go " + tail) == 3
