"""Tests for ``pii-guard run <client>`` (LAB-1705, LAB-1709).

Synthetic data only (ADR 0005).
"""

from __future__ import annotations

import io
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from pii_guard.cli import main as root_main
from pii_guard.integrations import run as run_module
from pii_guard.integrations.common import ConnectError
from pii_guard.integrations.login import CliProfile, load_cli_profile, save_cli_profile
from pii_guard.integrations.run import (
    DEFAULT_DASHBOARD_URL,
    ResolvedUpstream,
    _discover_model,
    _resolve_binary,
    build_agent_invocation,
    build_parser,
    child_base_env,
    main,
    prompt_first_run_dashboard,
    resolve_dashboard,
    resolve_upstream,
    run_agent,
    split_agent_argv,
)
from pii_guard.upstreams import PRESETS


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path | None = None) -> None:
    if tmp_path is not None:
        monkeypatch.setenv("PII_GUARD_CLI_CONFIG", str(tmp_path / "cli.json"))
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
    _clear_provider_env(monkeypatch, tmp_path)
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
    _clear_provider_env(monkeypatch, tmp_path)
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
    _clear_provider_env(monkeypatch, tmp_path)
    parser = build_parser()

    # No key or URL -> remote reporting off
    off_target = resolve_dashboard(parser.parse_args(["opencode"]))
    assert off_target.remote_url is None
    assert off_target.display_url is None
    assert off_target.local_ui is False

    # Scenario B: --dashboard local enables local web UI on the gateway port
    local_ui = resolve_dashboard(parser.parse_args(["opencode", "--dashboard", "local"]))
    assert local_ui.remote_url is None
    assert local_ui.local_ui is True

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


def test_resolve_dashboard_with_saved_profile_and_interactive_first_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_provider_env(monkeypatch, tmp_path)
    parser = build_parser()

    fake_remote = CliProfile(
        mode="remote",
        dashboard_url="https://guard.watt-mind.com",
        project_id="prj_1",
        project_name="Team Alpha",
        endpoint_id="ep_999",
        endpoint_key="pg_ep_aaa",
        telemetry_level="stats",
    )

    # First-run interactive choice [1] Hosted dashboard
    target_hosted = resolve_dashboard(
        parser.parse_args(["opencode"]),
        interactive=True,
        input_fn=lambda _p: "1",
        login_fn=lambda url, **_kw: fake_remote,
        stderr=io.StringIO(),
    )
    assert target_hosted.remote_url == "https://guard.watt-mind.com/e/ep_999/v1"
    assert target_hosted.remote_key == "pg_ep_aaa"
    assert target_hosted.remote_level == "stats"
    assert target_hosted.project_name == "Team Alpha"
    assert load_cli_profile() == fake_remote

    # Subsequent non-interactive run automatically uses the saved profile
    target_saved = resolve_dashboard(parser.parse_args(["opencode"]))
    assert target_saved.remote_url == "https://guard.watt-mind.com/e/ep_999/v1"

    # First-run interactive choice [2] Local only
    save_cli_profile(CliProfile(mode="local"))
    target_local = resolve_dashboard(parser.parse_args(["opencode"]))
    assert target_local.remote_url is None

    # First-run interactive choice [3] Self-hosted URL
    prompts = iter(["3", "https://guard.internal.example.com"])
    self_profile = prompt_first_run_dashboard(
        input_fn=lambda _p: next(prompts),
        login_fn=lambda url, **_kw: CliProfile(
            mode="remote",
            dashboard_url=url,
            project_id="prj_sh",
            project_name="Self Hosted",
            endpoint_id="ep_sh",
            endpoint_key="pg_ep_bbb",
            telemetry_level="masked",
        ),
        stderr=io.StringIO(),
    )
    assert self_profile.dashboard_url == "https://guard.internal.example.com"


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
    _clear_provider_env(monkeypatch, tmp_path)

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

    # Scenario B: --dashboard local in --print-env
    out_local = io.StringIO()
    assert (
        main(
            ["opencode", "--mock", "--dashboard", "local", "--print-env"],
            stdout=out_local,
            stderr=io.StringIO(),
        )
        == 0
    )
    local_payload = json.loads(out_local.getvalue())
    assert local_payload["local_ui"] is True
    assert local_payload["dashboard_url"].endswith("/#traffic")

    # Missing binary returns exit code 2
    err_missing = io.StringIO()
    code_missing = main(
        ["opencode", "--mock", "--agent-bin", str(tmp_path / "does-not-exist")],
        stdout=io.StringIO(),
        stderr=err_missing,
        interactive=False,
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
        "root = base_url.split('/s/')[0]\n"
        "with urllib.request.urlopen(root + '/v1/traffic', timeout=10) as resp:\n"
        "    traffic = json.loads(resp.read().decode('utf-8'))\n"
        f"with open({str(out_file)!r}, 'w', encoding='utf-8') as f:\n"
        "    json.dump({'argv': sys.argv[1:], 'reply': reply, 'traffic': traffic,\n"
        "               'env': sorted(os.environ)}, f)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    fake_agent.chmod(fake_agent.stat().st_mode | stat.S_IEXEC)

    # Secrets in the parent's environment must not reach the agent (LAB-1705).
    monkeypatch.setenv("OPENAI_API_KEY", "sk-synthetic-openai-0001")
    monkeypatch.setenv("META_API_KEY", "synthetic-meta-0001")
    monkeypatch.setenv("PII_GUARD_DASHBOARD_KEY", "synthetic-dashboard-0001")
    exit_code = root_main(
        [
            "run",
            "opencode",
            "--mock",
            "--dashboard",
            "off",
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
    assert "jane.placeholder@example.net" in content
    # What was forwarded upstream held a placeholder, never the email.
    [event] = recorded["traffic"]["events"]
    forwarded = json.dumps(event["request"]["masked"])
    assert "jane.placeholder@example.net" not in forwarded
    assert "[[EMAIL_" in forwarded
    leaked = {"OPENAI_API_KEY", "META_API_KEY", "PII_GUARD_DASHBOARD_KEY", "PII_GUARD_REMOTE_KEY"}
    assert leaked.isdisjoint(recorded["env"])


def test_resolve_dashboard_refuses_plaintext_remote() -> None:
    args = build_parser().parse_args(["opencode", "--dashboard", "http://dash.example"])
    with pytest.raises(ConnectError, match="https"):
        resolve_dashboard(args)


def test_saved_profile_is_validated_like_a_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_provider_env(monkeypatch, tmp_path)
    args = build_parser().parse_args(["opencode"])
    fake_key = "pg_ep_fake_profile_key"

    plain = CliProfile(
        dashboard_url="http://dash.example", endpoint_id="ep_1", endpoint_key=fake_key
    )
    with pytest.raises(ConnectError, match="https"):
        resolve_dashboard(args, profile=plain)
    creds = CliProfile(
        dashboard_url="https://u:p@dash.example", endpoint_id="ep_1", endpoint_key=fake_key
    )
    with pytest.raises(ConnectError, match="credentials"):
        resolve_dashboard(args, profile=creds)
    # No endpoint: refused instead of posting to the dashboard root.
    no_endpoint = CliProfile(dashboard_url="https://dash.example", endpoint_key=fake_key)
    with pytest.raises(ConnectError, match="run `pii-guard login` again"):
        resolve_dashboard(args, profile=no_endpoint)
    save_cli_profile(no_endpoint)
    with pytest.raises(ConnectError, match="run `pii-guard login` again"):
        resolve_dashboard(args)
    bad_endpoint = CliProfile(
        dashboard_url="https://dash.example", endpoint_id="../admin", endpoint_key=fake_key
    )
    with pytest.raises(ConnectError, match="not a valid endpoint id"):
        resolve_dashboard(args, profile=bad_endpoint)

    loopback = CliProfile(
        dashboard_url="http://127.0.0.1:9", endpoint_id="ep_1", endpoint_key=fake_key
    )
    assert resolve_dashboard(args, profile=loopback).remote_url == "http://127.0.0.1:9/e/ep_1/v1"

    # A login whose result run would refuse is never saved.
    (tmp_path / "cli.json").unlink()
    with pytest.raises(ConnectError, match="https"):
        resolve_dashboard(
            args,
            interactive=True,
            input_fn=lambda _p: "1",
            login_fn=lambda _url, **_kw: plain,
            stderr=io.StringIO(),
        )
    assert load_cli_profile() is None

    # An explicit --dashboard uses the saved profile only for the same origin.
    good = CliProfile(
        dashboard_url="https://dash.example", endpoint_id="ep_1", endpoint_key=fake_key
    )
    same = build_parser().parse_args(["opencode", "--dashboard", "https://DASH.example/"])
    assert resolve_dashboard(same, profile=good).remote_key == fake_key
    other = build_parser().parse_args(["opencode", "--dashboard", "https://other.example"])
    target = resolve_dashboard(other, profile=good)
    assert target.remote_key is None
    assert target.remote_url == "https://other.example"


def test_run_ctrl_c_at_first_run_prompt_exits_130(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_provider_env(monkeypatch, tmp_path)

    def interrupt(_prompt: str) -> str:
        raise KeyboardInterrupt

    err = io.StringIO()
    code = main(["opencode", "--mock"], stderr=err, interactive=True, input_fn=interrupt)
    assert code == 130
    assert "cancelled" in err.getvalue()


def test_gateway_env_and_agent_never_hold_upstream_tenant_or_profile_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_provider_env(monkeypatch, tmp_path)
    monkeypatch.delenv("PII_GUARD_TENANT_KEY", raising=False)
    fake_upstream = "sk-fake-upstream-0000"
    fake_profile_key = "pg_ep_fake_profile_key"
    monkeypatch.setenv("OPENAI_API_KEY", fake_upstream)
    save_cli_profile(
        CliProfile(
            dashboard_url="https://dash.example", endpoint_id="ep_1", endpoint_key=fake_profile_key
        )
    )
    seen: dict[str, Any] = {}

    def fake_run_agent(cmd: list[str], env: dict[str, str]) -> int:
        seen["environ"] = dict(os.environ)
        seen["child"] = dict(env)
        return 0

    monkeypatch.setattr(run_module, "run_agent", fake_run_agent)
    monkeypatch.setattr(run_module, "_resolve_binary", lambda _c, _o: "opencode")
    code = main(
        ["opencode", "--upstream", "openai", "--model", "m"],
        stderr=io.StringIO(),
        interactive=False,
    )
    assert code == 0
    environ = seen["environ"]
    assert "PII_GUARD_UPSTREAM_API_KEY" not in environ
    assert "PII_GUARD_TENANT_KEY" not in environ
    assert "PII_GUARD_UPSTREAM_BASE_URL" not in environ
    # The telemetry key only feeds the in-process gateway's remote exporter.
    assert environ["PII_GUARD_REMOTE_KEY"] == fake_profile_key
    assert environ["PII_GUARD_REMOTE_URL"] == "https://dash.example/e/ep_1/v1"
    child_values = " ".join(seen["child"].values())
    assert fake_upstream not in child_values
    assert fake_profile_key not in child_values
    assert not any(k.startswith("PII_GUARD_REMOTE") for k in seen["child"])
    assert "PII_GUARD_REMOTE_KEY" not in os.environ


def test_child_base_env_drops_provider_and_dashboard_secrets() -> None:
    env = child_base_env(
        {
            "PATH": "/usr/bin",
            "HOME": "/home/synthetic",
            "OPENAI_API_KEY": "x",
            "ANTHROPIC_API_KEY": "x",
            "META_API_KEY": "x",
            "MY_PROVIDER_KEY": "x",
            "PII_GUARD_REMOTE_KEY": "x",
            "PII_GUARD_UPSTREAM_API_KEY": "x",
            "PII_GUARD_TENANT_KEY": "x",
            "PII_GUARD_API_TOKEN": "gateway-token",
        },
        extra_secret_envs=("MY_PROVIDER_KEY", None),
    )
    assert env == {
        "PATH": "/usr/bin",
        "HOME": "/home/synthetic",
        "PII_GUARD_API_TOKEN": "gateway-token",
    }
    _cmd, muse_env = build_agent_invocation(
        "muse-code", "muse", "http://127.0.0.1:1/s/c_x/v1", "m", [], base_env={}, configure=False
    )
    assert muse_env["META_API_KEY"] == "pii-guard-local"
    _cmd, claude_env = build_agent_invocation(
        "claude-code",
        "claude",
        "http://127.0.0.1:1/s/c_x/v1",
        "m",
        [],
        base_env={"ANTHROPIC_API_KEY": "real"},
        token="gateway-token",  # noqa: S106 - fictional
    )
    assert "ANTHROPIC_API_KEY" not in claude_env
    assert claude_env["ANTHROPIC_AUTH_TOKEN"] == "gateway-token"  # noqa: S105 - fictional


def test_run_restores_muse_settings_and_leaves_no_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_provider_env(monkeypatch)
    muse_dir = tmp_path / "muse"
    muse_dir.mkdir()
    settings = muse_dir / "settings.json"
    original = b'{"theme": "dark"}\n'
    settings.write_bytes(original)
    seen = tmp_path / "seen.json"
    fake = tmp_path / "fake-muse"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"cfg = json.loads(pathlib.Path({str(settings)!r}).read_text())\n"
        f"pathlib.Path({str(seen)!r}).write_text(json.dumps(cfg))\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    code = main(
        [
            "muse-code",
            "--mock",
            "--dashboard",
            "off",
            "--muse-dir",
            str(muse_dir),
            "--agent-bin",
            str(fake),
        ],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert code == 0
    # The agent ran against the local gateway...
    assert "127.0.0.1" in json.loads(seen.read_text())["endpoint_transport"]["base_url"]
    # ...and the user's file is back, byte for byte, with no backup left behind.
    assert settings.read_bytes() == original
    assert sorted(p.name for p in muse_dir.iterdir()) == ["settings.json"]

    # --print-env writes nothing.
    main(
        ["muse-code", "--mock", "--dashboard", "off", "--muse-dir", str(muse_dir), "--print-env"],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert settings.read_bytes() == original


def test_run_agent_survives_ctrl_c_and_forwards_sigterm(tmp_path: Path) -> None:
    import os
    import signal
    import threading
    import time

    ready = tmp_path / "ready"
    child = (
        "import pathlib, signal, sys, time\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(7))\n"
        f"pathlib.Path({str(ready)!r}).touch()\n"
        "time.sleep(20)\n"
    )

    def signal_parent() -> None:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        os.kill(os.getpid(), signal.SIGINT)  # ignored: the agent decides what Ctrl-C means
        time.sleep(0.2)
        os.kill(os.getpid(), signal.SIGTERM)  # forwarded to the agent

    threading.Thread(target=signal_parent, daemon=True).start()
    assert run_agent([sys.executable, "-c", child], dict(os.environ)) == 7
