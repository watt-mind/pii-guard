"""``pii-guard connect <tool> --print`` (LAB-1331): the Connect page's block, in a terminal."""

from __future__ import annotations

import io

import httpx
import pytest

from pii_guard.integrations import snippets
from pii_guard.integrations.cli import main
from pii_guard.integrations.e2e import SCRIPTED_MODEL, Recorder, gateway_app, serve


def run(*args: str) -> tuple[int, str]:
    out = io.StringIO()
    code = main(list(args), stdout=out)
    return code, out.getvalue()


@pytest.fixture(scope="module")
def gateway() -> object:
    recorder = Recorder()
    with serve(recorder.app) as upstream, serve(gateway_app(upstream + "/v1", [])) as url:
        yield url


@pytest.mark.parametrize("tool", ["muse-code", "pi", "codex", "opencode", "curl", "python"])
def test_print_matches_what_the_api_serves(gateway: str, tool: str) -> None:
    session = "c_print_test"
    code, out = run(tool, "--print", "--gateway", f"{gateway}/s/{session}/v1")
    assert code == 0
    api = httpx.get(f"{gateway}/v1/connect/snippets", params={"session": session}).json()
    block = next(t for t in api["tools"] if t["id"] == tool)
    assert out == snippets.printable(block) + "\n"
    assert f"{gateway}/s/{session}/v1" in out
    assert SCRIPTED_MODEL in out or tool == "muse-code"


def test_tools_without_a_config_file_print_by_default(gateway: str) -> None:
    code, out = run("codex", "--gateway", f"{gateway}/v1")
    assert code == 0 and out.startswith("codex -m ")
    assert "/s/c_" in out  # a new session for this block


def test_print_without_a_gateway_builds_the_block_locally(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out = run("opencode", "--gateway", "http://127.0.0.1:9/s/c_local/v1", "--model", "m-1")
    assert code == 0
    assert (
        out
        == snippets.tool_snippet("opencode", "http://127.0.0.1:9/s/c_local/v1", "m-1", token=False)[
            "code"
        ]
        + "\n"
    )
    assert "built locally" in capsys.readouterr().err


def test_claude_code_prints_its_launch_command(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run("claude-code", "--gateway", "http://127.0.0.1:9/v1")
    assert code == 0
    assert out.startswith("ANTHROPIC_BASE_URL=http://127.0.0.1:9/s/")
    assert "claude --model" in out
    assert "/v1/messages" in capsys.readouterr().err


def test_print_refuses_check_and_dry_run_for_printed_tools(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        run("pi", "--print", "--check")
    code, _ = run("curl", "--check", "--gateway", "http://127.0.0.1:9/v1")
    assert code == 2
    assert "--check for pi, muse-code, codex, opencode" in capsys.readouterr().err
    # Codex and OpenCode have a --check (LAB-1469): an unreachable gateway is a problem to fix.
    code, _ = run("codex", "--check", "--gateway", "http://127.0.0.1:9/v1")
    assert code == 2
    assert "could not reach the gateway" in capsys.readouterr().err


def test_print_refuses_an_unsafe_model(capsys: pytest.CaptureFixture[str]) -> None:
    code, _ = run("curl", "--print", "--model", "x'; rm", "--gateway", "http://127.0.0.1:9/v1")
    assert code == 2
