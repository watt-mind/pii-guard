"""A restored value fits the shell quoting it lands in, inside a command argument (LAB-1483).

A plain placeholder in the ``command``/``cmd`` of JSON tool-call arguments, inside a
single-quoted shell string or a ``sed`` ``s`` replacement, is restored escaped for that context
(``'`` -> ``'\\''``; ``\\``, ``&``, the delimiter and newline backslashed in a replacement).
Everywhere else (other keys, double quotes, heredocs, custom tool input, message text) the value
stays byte-exact. Whole and streamed restores agree (chat and Responses).

Commands that run are executed with ``bash`` and ``sed`` to prove the value comes out intact.
Every value is fictional (ADR 0005).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

import pytest
from gateway_helpers import TEST_TENANT_KEY, chunk, completion

from pii_guard.gateway.responses_restore import ResponsesSseRestorer, restore_response
from pii_guard.gateway.restore import restore_completion
from pii_guard.gateway.shell_context import ArgumentsContext, ShellContext
from pii_guard.gateway.stream import DONE, SseRestorer
from pii_guard.types import EntityType, Span
from pii_guard.vault import Vault, VaultSession

#: Fictional values with characters a shell or sed treats as syntax.
VALUES = [
    "O'Brien Teszt",
    "Fő utca 1/A",
    'Minta $HOME `id` "Kft" \\ & társa',
    "a'b'/&\\c",
]

BASH = shutil.which("bash")
needs_shell = pytest.mark.skipif(
    BASH is None or shutil.which("sed") is None, reason="needs bash and sed"
)


def _session() -> VaultSession:
    return Vault(bytes.fromhex(TEST_TENANT_KEY)).session()


def _placeholder(session: VaultSession, value: str) -> str:
    text = f"v {value}"
    return session.mask(text, [Span(2, len(text), EntityType.PERSON, value, 1.0, "test")])[2:]


def _escaped(placeholder: str) -> str:
    return placeholder.replace("[", "\\[").replace("]", "\\]")


def _whole_arguments(session: VaultSession, arguments: str) -> str:
    body = completion(
        "", tool_calls=[{"type": "function", "function": {"name": "sh", "arguments": arguments}}]
    )
    restore_completion(session, body)
    return body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]


def _restored_command(session: VaultSession, command: str, key: str = "command") -> str:
    return json.loads(_whole_arguments(session, json.dumps({key: command})))[key]


def _bash(command: str) -> str:
    assert BASH is not None
    # A fixed command line built by the test itself (fictional values only).
    done = subprocess.run(  # noqa: S603
        [BASH, "-c", command], capture_output=True, text=True, check=True, timeout=10
    )
    return done.stdout


# --- the bug: single quotes and sed replacements ------------------------------------------


@needs_shell
@pytest.mark.parametrize("value", VALUES)
def test_value_in_a_single_quoted_string_comes_out_intact(value: str) -> None:
    session = _session()
    ph = _placeholder(session, value)
    command = _restored_command(session, f"printf '%s' '{ph}'")
    assert _bash(command) == value


@needs_shell
@pytest.mark.parametrize("value", VALUES)
@pytest.mark.parametrize(
    "template",
    [
        "printf 'x\\n' | sed 's/x/{ph}/'",
        "printf 'x\\n' | sed -e 's|x|{ph}|g'",
        "printf 'x\\n' | sed -n -e '1p;s#x#{ph}#p' | tail -n 1",
        "printf 'x\\n' | LC_ALL=C sed -E 's/(x)/{ph}/'",
        "cd /tmp && printf 'x\\n' | /usr/bin/sed 's,x,{ph},'",
    ],
    ids=["slash", "pipe_g", "after_p", "assignment", "path_comma"],
)
def test_value_in_a_sed_replacement_comes_out_intact(value: str, template: str) -> None:
    session = _session()
    command = _restored_command(session, template.format(ph=_placeholder(session, value)))
    assert _bash(command) == value + "\n"


@needs_shell
def test_a_value_with_a_newline_in_a_sed_replacement() -> None:
    session = _session()
    value = "Teszt Elek\n1/A"
    ph = _placeholder(session, value)
    command = _restored_command(session, f"printf 'x\\n' | sed 's/x/{ph}/'")
    assert _bash(command) == value + "\n"


@needs_shell
def test_escaped_placeholder_in_a_sed_pattern_with_a_quote_still_matches() -> None:
    session = _session()
    value = "O'Brien Teszt"
    ph = _placeholder(session, value)
    command = _restored_command(
        session, f"printf '%s\\n' '{ph}' | sed 's/{_escaped(ph)}/ok/;s#{_escaped(ph)}#no#'"
    )
    assert _bash(command) == "ok\n"


@needs_shell
def test_script_after_dash_c_in_a_command_array() -> None:
    session = _session()
    value = VALUES[0]
    ph = _placeholder(session, value)
    arguments = json.dumps({"command": ["bash", "-lc", f"printf '%s' '{ph}'"]})
    command = json.loads(_whole_arguments(session, arguments))["command"]
    assert _bash(command[2]) == value


# --- byte-exact everywhere else -----------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "template"),
    [
        ("content", "name = '{ph}'"),  # file content, not a command
        ("command", 'echo "{ph}"'),  # double quotes: not modeled
        ("command", "cat <<'EOF'\n'{ph}'\nEOF"),  # heredoc body
        ("command", "echo $'{ph}'"),  # ANSI-C quoting
        ("command", "# '{ph}'"),  # a comment
        ("command", "echo \"$(echo '{ph}')\""),  # command substitution in double quotes
        ("command", "echo {ph}"),  # unquoted
    ],
)
def test_value_stays_byte_exact_where_the_context_is_not_known(key: str, template: str) -> None:
    session = _session()
    value = VALUES[0]
    ph = _placeholder(session, value)
    restored = _restored_command(session, template.format(ph=ph), key)
    assert restored == template.format(ph=value)


@pytest.mark.parametrize(
    "template",
    [
        "printf x | sed 'y/x/{ph}/'",  # another sed command
        "printf x | sed 's/[[:alpha:]]/{ph}/'",  # a bracket expression
        "printf x | env sed 's/x/{ph}/'",  # sed is not the command word
        "sed 's/a/b/' '{ph}'",  # a file name after the script
    ],
)
def test_single_quotes_only_where_the_sed_script_is_not_known(template: str) -> None:
    session = _session()
    value = VALUES[1]  # "/" but no quote: only a sed replacement would change it
    restored = _restored_command(session, template.format(ph=_placeholder(session, value)))
    assert restored == template.format(ph=value)


def test_nested_command_keys_and_argv_arrays_stay_byte_exact() -> None:
    session = _session()
    value = VALUES[0]
    ph = _placeholder(session, value)
    arguments = {
        "steps": [{"command": f"echo '{ph}'"}],
        "command": ["echo", f"'{ph}'"],
        "note": {"cmd": f"echo '{ph}'"},
    }
    restored = json.loads(_whole_arguments(session, json.dumps(arguments)))
    assert restored["steps"][0]["command"] == f"echo '{value}'"
    assert restored["command"] == ["echo", f"'{value}'"]
    assert restored["note"]["cmd"] == f"echo '{value}'"


def test_custom_tool_input_and_message_text_stay_byte_exact() -> None:
    session = _session()
    value = VALUES[0]
    ph = _placeholder(session, value)
    text = f"echo '{ph}' && sed 's/x/{ph}/'"
    body = completion(
        text, tool_calls=[{"type": "custom", "custom": {"name": "sh", "input": text}}]
    )
    restore_completion(session, body)
    message = body["choices"][0]["message"]
    expected = text.replace(ph, value)
    assert message["content"] == expected
    assert message["tool_calls"][0]["custom"]["input"] == expected


def test_a_later_key_after_the_command_is_byte_exact() -> None:
    session = _session()
    value = VALUES[0]
    ph = _placeholder(session, value)
    arguments = json.dumps({"command": "echo 'a'", "description": f"'{ph}'"})
    assert json.loads(_whole_arguments(session, arguments))["description"] == f"'{value}'"


# --- the context reader -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ('{"command": "echo \'', ShellContext(True)),
        ("{\"cmd\": \"sed -i '' 's/a/", ShellContext(True, sed_replacement="/")),
        ('{"command": "sed \'s/a', ShellContext(True, sed_pattern="/")),
        ("{\"command\": \"sed -e 'p' -e 's|a|", ShellContext(True, sed_replacement="|")),
        ("{\"command\": \"sed 's/a/b/' '", ShellContext(True)),  # a file name, not a script
        ('{"command": "sed \'s/a/\\u0027', ShellContext()),  # \\u0027 closed the quote
        ('{"command": "echo \\"it\'s \'', ShellContext()),  # ' inside double quotes
        ("{\"command\": \"echo 'a' '", ShellContext(True)),
        ('{"command": "x", "other": "\'', ShellContext()),
        ('{"command": "echo \'a\'', ShellContext()),
        ("not json '", ShellContext()),
    ],
)
def test_arguments_context(prefix: str, expected: ShellContext) -> None:
    whole = ArgumentsContext()
    whole.feed(prefix)
    assert whole.context() == expected
    split = ArgumentsContext()
    for char in prefix:
        split.feed(char)
    assert split.context() == expected


# --- streamed: the same as whole -----------------------------------------------------------


def _streamed_chat(session: VaultSession, pieces: list[str]) -> str:
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
    payloads.append(chunk({}, finish="tool_calls"))
    restorer = SseRestorer(session)
    out: list[str] = []
    for payload in payloads:
        out += restorer.process(json.dumps(payload))
    out += restorer.process(DONE)
    events: list[dict[str, Any]] = [json.loads(item) for item in out if item != DONE]
    return "".join(
        call.get("function", {}).get("arguments", "")
        for event in events
        for choice in event.get("choices", [])
        for call in choice["delta"].get("tool_calls", [])
    )


def _command_with_all_contexts(ph: str) -> str:
    return f"echo '{ph}' \"{ph}\" && printf x | sed 's/{_escaped(ph)}/{ph}/'"


def test_streamed_chat_arguments_split_anywhere_equal_the_whole_restore() -> None:
    session = _session()
    ph = _placeholder(session, VALUES[3])
    arguments = json.dumps({"command": _command_with_all_contexts(ph), "content": f"'{ph}'"})
    expected = _whole_arguments(session, arguments)
    assert "'\\\\''" in expected  # escaped for the single quotes (JSON-encoded)
    for cut in range(len(arguments) + 1):
        assert _streamed_chat(session, [arguments[:cut], arguments[cut:]]) == expected, cut
    assert _streamed_chat(session, list(arguments)) == expected


def test_two_streamed_tool_calls_keep_separate_contexts() -> None:
    session = _session()
    ph = _placeholder(session, VALUES[0])
    first = json.dumps({"command": "echo 'open"})[:-2]  # stops inside a single quote
    second = json.dumps({"content": f"'{ph}'"})
    payloads = [
        chunk(
            {
                "tool_calls": [
                    {"index": i, "id": f"c{i}", "type": "function", "function": {"name": "sh"}}
                    for i in (0, 1)
                ]
            }
        ),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": first}}]}),
        chunk({"tool_calls": [{"index": 1, "function": {"arguments": second}}]}),
        chunk({}, finish="tool_calls"),
    ]
    restorer = SseRestorer(session)
    out: list[str] = []
    for payload in payloads:
        out += restorer.process(json.dumps(payload))
    out += restorer.process(DONE)
    args = "".join(
        call.get("function", {}).get("arguments", "")
        for item in out
        if item != DONE
        for choice in json.loads(item).get("choices", [])
        for call in choice["delta"].get("tool_calls", [])
        if call["index"] == 1
    )
    assert json.loads(args) == {"content": f"'{VALUES[0]}'"}


def test_responses_whole_and_streamed_function_call_arguments() -> None:
    session = _session()
    ph = _placeholder(session, VALUES[2])
    arguments = json.dumps({"cmd": _command_with_all_contexts(ph)})
    body = {
        "object": "response",
        "output": [{"type": "function_call", "call_id": "a", "name": "sh", "arguments": arguments}],
    }
    restore_response(session, body)
    whole = body["output"][0]["arguments"]
    assert whole == _whole_arguments(session, arguments)
    kind = "response.function_call_arguments"
    for cut in range(0, len(arguments) + 1, 3):
        restorer = ResponsesSseRestorer(session)
        out: list[tuple[str | None, str]] = []
        for part in (arguments[:cut], arguments[cut:]):
            event = {"type": f"{kind}.delta", "output_index": 0, "delta": part}
            out += restorer.process(event["type"], json.dumps(event))
        done = {"type": f"{kind}.done", "output_index": 0, "arguments": arguments}
        out += restorer.process(done["type"], json.dumps(done))
        events = [json.loads(data) for _, data in out]
        deltas = "".join(e["delta"] for e in events if e["type"].endswith(".delta"))
        assert deltas == events[-1]["arguments"] == whole, cut
