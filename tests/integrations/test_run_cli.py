"""Tests for ``pii-guard run <client>`` (LAB-1705).

Synthetic data only (ADR 0005).
"""

from __future__ import annotations

import io
import json
import stat
from pathlib import Path

import pytest

from pii_guard.cli import main as root_main
from pii_guard.integrations.common import ConnectError
from pii_guard.integrations.run import (
    DEFAULT_DASHBOARD_URL,
    ResolvedUpstream,
    _discover_model,
    _resolve_binary,
    build_agent_invocation,
    build_parser,
    main,
    resolve_dashboard,
    resolve_upstream,
    split_agent_argv,
)
from pii_guard.upstreams import PRESETS


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "META_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "FIREWORKS_API_KEY",
        "ANTHROPIC_API_KEY",
        "PII_GUARD_UPSTREAM_BASE_URL",
        "PII_GUARD_UPSTREAM_API_KEY",
        "PII_GUARD_DASHBOARD_URL",
        "PII_GUARD_DASHBOARD_KEY",
        "PII_GUARD_REMOTE_URL",
        "PII_GUARD_REMOTE_KEY",
        "PII_GUARD_REMOTE_LEVEL",
        "PII_GUARD_ENDPOINT_KEY",
        "PII_GUARD_ENDPOINT_ID",
        "PII_GUARD_API_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)


def test_split_agent_argv() -> None:
    own, extra = split_agent_argv(["opencode", "--mock", "--", "run", "--auto", "task"])
    assert own == ["opencode", "--mock"]
    assert extra == ["run", "--auto", "task"]

    own_no_sep, extra_no_sep = split_agent_argv(["codex", "--mock"])
    assert own_no_sep == ["codex", "--mock"]
    assert extra_no_sep == []


def test_resolve_upstream_auto_detects_provider_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_provider_env(monkeypatch)
    parser = build_parser()

    with pytest.raises(ConnectError, match="no upstream provider configured"):
        resolve_upstream(parser.parse_args(["opencode"]))

    monkeypatch.setenv("OPENAI_API_KEY", "sk-synthetic-openai")
    resolved = resolve_upstream(parser.parse_args(["opencode"]))
    assert resolved.base_url == "https://api.openai.com/v1"
    assert resolved.api_key == "sk-synthetic-openai"
    assert resolved.preset is not None and resolved.preset.id == "openai"

    # META_API_KEY is checked before OPENAI_API_KEY in AUTO_UPSTREAM_ORDER
    monkeypatch.setenv("META_API_KEY", "meta-synthetic-key")
    resolved_meta = resolve_upstream(parser.parse_args(["opencode"]))
    assert resolved_meta.base_url == "https://api.meta.ai/v1"
    assert resolved_meta.api_key == "meta-synthetic-key"

    # Explicit preset works when key is set
    explicit_openai = resolve_upstream(parser.parse_args(["opencode", "--upstream", "openai"]))
    assert explicit_openai.base_url == "https://api.openai.com/v1"


def test_resolve_upstream_claude_code_and_explicit_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_provider_env(monkeypatch)
    parser = build_parser()

    with pytest.raises(ConnectError, match="claude-code needs \\$ANTHROPIC_API_KEY"):
        resolve_upstream(parser.parse_args(["claude-code"]))

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-synthetic")
    claude_up = resolve_upstream(parser.parse_args(["claude-code"]))
    assert claude_up.base_url == "https://api.anthropic.com/v1"
    assert claude_up.api_key == "sk-ant-synthetic"

    with pytest.raises(ConnectError, match="not both"):
        resolve_upstream(
            parser.parse_args(
                ["opencode", "--upstream", "openai", "--upstream-url", "http://127.0.0.1:9999/v1"]
            )
        )

    with pytest.raises(ConnectError, match="--upstream fireworks needs"):
        resolve_upstream(parser.parse_args(["opencode", "--upstream", "fireworks"]))

    custom = resolve_upstream(
        parser.parse_args(["opencode", "--upstream-url", "http://127.0.0.1:11434/v1"])
    )
    assert custom.base_url == "http://127.0.0.1:11434/v1"

    with pytest.raises(ConnectError, match="--api-key-env is not set"):
        resolve_upstream(
            parser.parse_args(
                [
                    "opencode",
                    "--upstream-url",
                    "http://127.0.0.1:11434/v1",
                    "--api-key-env",
                    "MISSING_VAR",
                ]
            )
        )


def test_resolve_dashboard_defaults_to_hosted_and_supports_self_hosted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_provider_env(monkeypatch)
    parser = build_parser()

    # No key or URL -> remote reporting off
    off_target = resolve_dashboard(parser.parse_args(["opencode"]))
    assert off_target.remote_url is None
    assert off_target.display_url is None

    # Key only -> defaults to https://guard.watt-mind.com
    hosted = resolve_dashboard(
        parser.parse_args(
            [
                "opencode",
                "--dashboard-key",
                "pg_ep_aaa",
                "--endpoint",
                "ep_abc123",
                "--telemetry-level",
                "stats",
            ]
        )
    )
    assert hosted.remote_url == f"{DEFAULT_DASHBOARD_URL}/e/ep_abc123/v1"
    assert hosted.remote_key == "pg_ep_aaa"
    assert hosted.remote_level == "stats"
    assert hosted.display_url == f"{DEFAULT_DASHBOARD_URL}/#traffic"

    # Self-hosted URL
    self_hosted = resolve_dashboard(
        parser.parse_args(
            [
                "opencode",
                "--dashboard",
                "https://pii-guard.internal.example.com",
                "--dashboard-key",
                "tok-synthetic",
            ]
        )
    )
    assert self_hosted.remote_url == "https://pii-guard.internal.example.com"
    assert self_hosted.display_url == "https://pii-guard.internal.example.com/#traffic"
    assert self_hosted.remote_level == "masked"

    # Explicit opt-out even when key is in env
    monkeypatch.setenv("PII_GUARD_DASHBOARD_KEY", "pg_ep_aaa")
    disabled = resolve_dashboard(parser.parse_args(["opencode", "--dashboard", "off"]))
    assert disabled.remote_url is None

    # Invalid endpoint or dashboard URL errors
    with pytest.raises(ConnectError, match="not a valid endpoint id"):
        resolve_dashboard(parser.parse_args(["opencode", "--endpoint", "bad/ep/path/extra"]))
    with pytest.raises(ConnectError, match="must be an http:// or https:// URL"):
        resolve_dashboard(parser.parse_args(["opencode", "--dashboard", "ftp://example.com"]))
    with pytest.raises(ConnectError, match="--dashboard-key-env is not set"):
        resolve_dashboard(
            parser.parse_args(["opencode", "--dashboard-key-env", "MISSING_DASH_KEY"])
        )


def test_build_agent_invocation_all_clients(tmp_path: Path) -> None:
    session_url = "http://127.0.0.1:8787/s/c_0123456789abcdef0123456789abcdef/v1"
    gateway_auth = "synthetic-gateway-token"

    # 1. opencode merges existing OPENCODE_CONFIG_CONTENT (and handles malformed JSON)
    existing = json.dumps({"theme": "dark", "provider": {"other": {"name": "other"}}})
    cmd, env = build_agent_invocation(
        "opencode",
        "/usr/local/bin/opencode",
        session_url,
        "muse-spark-1.3",
        ["run", "hello"],
        base_env={"OPENCODE_CONFIG_CONTENT": existing},
        token=gateway_auth,
    )
    assert cmd == ["/usr/local/bin/opencode", "run", "hello"]
    cfg = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert cfg["theme"] == "dark"
    assert cfg["provider"]["other"] == {"name": "other"}
    assert cfg["provider"]["pii-guard"]["options"]["baseURL"] == session_url
    assert cfg["provider"]["pii-guard"]["options"]["apiKey"] == "{env:PII_GUARD_API_TOKEN}"
    assert cfg["model"] == "pii-guard/muse-spark-1.3"

    _, env_malformed = build_agent_invocation(
        "opencode",
        "/usr/local/bin/opencode",
        session_url,
        "muse-spark-1.3",
        [],
        base_env={"OPENCODE_CONFIG_CONTENT": "{not-json"},
    )
    assert json.loads(env_malformed["OPENCODE_CONFIG_CONTENT"])["model"] == (
        "pii-guard/muse-spark-1.3"
    )

    # 2. codex
    cmd_codex, _ = build_agent_invocation(
        "codex",
        "/usr/local/bin/codex",
        session_url,
        "gpt-5",
        ["exec", "fix bug"],
        base_env={},
        token=gateway_auth,
    )
    assert cmd_codex[:3] == ["/usr/local/bin/codex", "-m", "gpt-5"]
    assert "model_provider=pii-guard" in cmd_codex
    assert "web_search=disabled" in cmd_codex
    assert cmd_codex[-2:] == ["exec", "fix bug"]

    # 3. claude-code (with and without token)
    cmd_claude, env_claude = build_agent_invocation(
        "claude-code",
        "/usr/local/bin/claude",
        session_url,
        "claude-sonnet-4-5",
        ["-p", "hi"],
        base_env={},
    )
    assert cmd_claude == ["/usr/local/bin/claude", "--model", "claude-sonnet-4-5", "-p", "hi"]
    assert env_claude["ANTHROPIC_BASE_URL"] == session_url.removesuffix("/v1")
    assert env_claude["ANTHROPIC_API_KEY"] == "unused"

    _, env_claude_tok = build_agent_invocation(
        "claude-code",
        "/usr/local/bin/claude",
        session_url,
        "claude-sonnet-4-5",
        [],
        base_env={},
        token=gateway_auth,
    )
    assert env_claude_tok["ANTHROPIC_AUTH_TOKEN"] == gateway_auth

    # 4. pi
    pi_dir = tmp_path / "pi"
    cmd_pi, _ = build_agent_invocation(
        "pi",
        "/usr/local/bin/pi",
        session_url,
        "muse-spark-1.3",
        ["--print"],
        base_env={},
        agent_dir=str(pi_dir),
    )
    assert cmd_pi == [
        "/usr/local/bin/pi",
        "--provider",
        "pii-guard",
        "--model",
        "muse-spark-1.3",
        "--print",
    ]
    assert (pi_dir / "models.json").is_file()

    # 5. muse-code
    muse_dir = tmp_path / "muse"
    cmd_muse, env_muse = build_agent_invocation(
        "muse-code",
        "/usr/local/bin/muse",
        session_url,
        "muse-spark-1.3",
        ["exec", "hi"],
        base_env={},
        muse_dir=str(muse_dir),
    )
    assert cmd_muse == ["/usr/local/bin/muse", "exec", "hi"]
    assert env_muse["META_API_KEY"] == "pii-guard-local"
    assert (muse_dir / "settings.json").is_file()


def test_discover_model_and_resolve_binary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    parser = build_parser()
    meta_up = ResolvedUpstream(
        base_url="https://api.meta.ai/v1",
        api_key="k",
        label="meta",
        preset=PRESETS["meta"],
    )
    assert (
        _discover_model(
            parser.parse_args(["opencode", "--model", "gpt-5"]),
            meta_up,
            "http://127.0.0.1:9/v1",
            None,
        )
        == "gpt-5"
    )
    with pytest.raises(ConnectError, match="not a valid model id"):
        _discover_model(
            parser.parse_args(["opencode", "--model", "bad model!"]),
            meta_up,
            "http://127.0.0.1:9/v1",
            None,
        )
    assert (
        _discover_model(parser.parse_args(["claude-code"]), meta_up, "http://127.0.0.1:9/v1", None)
        == "claude-sonnet-4-5"
    )
    # Unreachable gateway falls back to preset default model
    assert (
        _discover_model(parser.parse_args(["opencode"]), meta_up, "http://127.0.0.1:9/v1", None)
        == "muse-spark-1.3"
    )

    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(ConnectError, match="opencode executable"):
        _resolve_binary("opencode", None)
    fake_bin = tmp_path / "opencode"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(fake_bin.stat().st_mode | stat.S_IEXEC)
    assert Path(_resolve_binary("opencode", None)).resolve() == fake_bin.resolve()


def test_run_print_env_and_end_to_end_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_provider_env(monkeypatch)

    out = io.StringIO()
    err = io.StringIO()
    code = main(
        [
            "opencode",
            "--mock",
            "--dashboard-key",
            "pg_ep_synthetic",
            "--endpoint",
            "ep_demo",
            "--print-env",
            "--",
            "run",
            "task",
        ],
        stdout=out,
        stderr=err,
    )
    assert code == 0
    payload = json.loads(out.getvalue())
    assert payload["client"] == "opencode"
    assert payload["model"] == "pii-guard-mock"
    assert payload["remote_url"] == f"{DEFAULT_DASHBOARD_URL}/e/ep_demo/v1"
    assert payload["dashboard_url"] == f"{DEFAULT_DASHBOARD_URL}/#traffic"
    assert payload["command"] == ["dry-run", "run", "task"]

    # Missing binary returns exit code 2
    err_missing = io.StringIO()
    code_missing = main(
        ["opencode", "--mock", "--agent-bin", str(tmp_path / "does-not-exist")],
        stdout=io.StringIO(),
        stderr=err_missing,
    )
    assert code_missing == 2
    assert "was not found" in err_missing.getvalue()

    # Create a fake opencode executable that calls the local in-process gateway
    out_file = tmp_path / "agent_result.json"
    fake_agent = tmp_path / "fake-opencode"
    fake_agent.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, urllib.request\n"
        "cfg = json.loads(os.environ['OPENCODE_CONFIG_CONTENT'])\n"
        "base_url = cfg['provider']['pii-guard']['options']['baseURL']\n"
        "body = json.dumps({\n"
        "    'model': 'pii-guard-mock',\n"
        "    'messages': [{'role': 'user', 'content': 'Email jane.placeholder@example.net'}],\n"
        "}).encode('utf-8')\n"
        "req = urllib.request.Request(\n"
        "    base_url + '/chat/completions',\n"
        "    data=body,\n"
        "    headers={'Content-Type': 'application/json'},\n"
        ")\n"
        "with urllib.request.urlopen(req, timeout=10) as resp:\n"
        "    reply = json.loads(resp.read().decode('utf-8'))\n"
        f"with open({str(out_file)!r}, 'w', encoding='utf-8') as f:\n"
        "    json.dump({'argv': sys.argv[1:], 'reply': reply}, f)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    fake_agent.chmod(fake_agent.stat().st_mode | stat.S_IEXEC)

    exit_code = root_main(
        [
            "run",
            "opencode",
            "--mock",
            "--agent-bin",
            str(fake_agent),
            "--",
            "run",
            "--auto",
        ]
    )
    assert exit_code == 0
    recorded = json.loads(out_file.read_text(encoding="utf-8"))
    assert recorded["argv"] == ["run", "--auto"]
    content = recorded["reply"]["choices"][0]["message"]["content"]
    # The mock upstream echoed the masked placeholder, and the local gateway restored the email
    assert "jane.placeholder@example.net" in content
