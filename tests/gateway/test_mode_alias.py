"""``audit`` mode, formerly ``strict``: the old name still works, with a warning (LAB-1186)."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from gateway_helpers import MockUpstream, conversation_turn_one, make_app

from pii_guard.bench import cli as bench_cli
from pii_guard.eval.baselines import suite
from pii_guard.gateway import GatewayConfig, Mode
from pii_guard.gateway import config as gateway_config
from pii_guard.gateway.config import cli_mode, parse_mode
from pii_guard.integrations import cli as connect_cli

CHAT = "/v1/chat/completions"


@pytest.fixture(autouse=True)
def _fresh_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test sees the one-time deprecation warning as if it were the first."""
    monkeypatch.setattr(gateway_config, "_warned", set())
    monkeypatch.delenv("PII_GUARD_GATEWAY_MODE", raising=False)


def test_fast_is_the_code_default() -> None:
    assert GatewayConfig(_env_file=None).mode is Mode.FAST  # type: ignore[call-arg]


def test_mode_values_are_fast_and_audit() -> None:
    assert [m.value for m in Mode] == ["fast", "audit"]


@pytest.mark.parametrize("raw", ["strict", "STRICT", " Strict "])
def test_strict_parses_as_audit_and_says_it_is_deprecated(raw: str) -> None:
    assert parse_mode(raw) == (Mode.AUDIT, True)
    assert parse_mode("audit") == (Mode.AUDIT, False)
    assert parse_mode("fast") == (Mode.FAST, False)


def test_unknown_mode_is_still_rejected() -> None:
    with pytest.raises(ValueError):
        parse_mode("paranoid")


def test_env_strict_selects_audit_and_warns_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("PII_GUARD_GATEWAY_MODE", "strict")
    with caplog.at_level(logging.WARNING, logger="pii_guard.gateway"):
        assert GatewayConfig(_env_file=None).mode is Mode.AUDIT  # type: ignore[call-arg]
        assert GatewayConfig(_env_file=None).mode is Mode.AUDIT  # type: ignore[call-arg]
    warnings = [r for r in caplog.records if "deprecated" in r.getMessage()]
    assert len(warnings) == 1
    assert "'strict'" in warnings[0].getMessage() and "'audit'" in warnings[0].getMessage()


def test_header_strict_runs_audit_with_deprecation_headers() -> None:
    upstream = MockUpstream()
    app = make_app(upstream, config=GatewayConfig(mode=Mode.FAST))
    body = {"model": "m", "messages": conversation_turn_one()}
    with TestClient(app) as http:
        old = http.post(CHAT, json=body, headers={"X-PII-Guard-Mode": "strict"})
        new = http.post(CHAT, json=body, headers={"X-PII-Guard-Mode": "audit"})
        default = http.post(CHAT, json=body)
    assert old.status_code == new.status_code == default.status_code == 200
    assert old.headers["x-pii-guard-mode"] == "audit"
    assert old.headers["deprecation"] == "true"
    assert "strict is deprecated" in old.headers["warning"]
    assert old.headers["warning"].startswith("299 ")
    # Audit mode ran: the fake LLM detector found the name the rules can't.
    assert "Teszt Elek" not in upstream.requests[0].content.decode()
    assert new.headers["x-pii-guard-mode"] == "audit"
    assert "deprecation" not in new.headers and "warning" not in new.headers
    assert default.headers["x-pii-guard-mode"] == "fast"
    assert "deprecation" not in default.headers


def test_unknown_header_mode_lists_the_current_names() -> None:
    with TestClient(make_app(MockUpstream())) as http:
        r = http.post(
            CHAT,
            json={"model": "m", "messages": conversation_turn_one()},
            headers={"X-PII-Guard-Mode": "paranoid"},
        )
    assert r.status_code == 400
    assert "fast, audit" in r.text


def test_cli_mode_maps_strict_with_a_stderr_warning(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_mode("strict", "prog") == "audit"
    assert "prog: mode 'strict' is deprecated, use 'audit'" in capsys.readouterr().err
    assert cli_mode("audit", "prog") == "audit"
    assert cli_mode("fast", "prog") == "fast"
    assert capsys.readouterr().err == ""


def test_connect_accepts_strict_as_audit(capsys: pytest.CaptureFixture[str]) -> None:
    args = connect_cli.build_parser().parse_args(["pi", "--mode", "strict"])
    assert args.mode == "audit"
    assert "deprecated" in capsys.readouterr().err
    assert connect_cli.build_parser().parse_args(["pi", "--mode", "audit"]).mode == "audit"


def test_suite_accepts_strict_as_audit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert suite.SYSTEMS["audit"] == ["rules", "ner", "llm"]
    assert "strict" not in suite.SYSTEMS
    with pytest.raises(SystemExit):  # --fixtures is missing: the --system value parsed first
        suite.main(["--system", "strict"])
    err = capsys.readouterr().err
    assert "mode 'strict' is deprecated, use 'audit'" in err
    assert "invalid choice" not in err


def test_bench_maps_strict_mode_and_requests_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}

    def fake_run(**kwargs: object) -> list[object]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr("pii_guard.bench.latency.run_benchmark", fake_run)
    assert bench_cli.main(["latency", "--modes", "fast,strict", "--strict-requests", "3"]) == 0
    assert seen["modes"] == ["fast", "audit"]
    assert seen["mode_requests"] == {"audit": 3}
    err = capsys.readouterr().err
    assert "mode 'strict' is deprecated" in err
    assert "--strict-requests is deprecated, use --audit-requests" in err

    assert bench_cli.main(["latency", "--modes", "audit", "--audit-requests", "5"]) == 0
    assert seen["mode_requests"] == {"audit": 5}
    assert capsys.readouterr().err == ""
