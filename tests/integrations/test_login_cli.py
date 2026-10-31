"""Tests for ``pii-guard login`` and ``pii-guard logout`` (LAB-1709).

The dashboard side (``POST``/``DELETE /v1/cli/token``, #437) is mocked with ``httpx.MockTransport``.
Synthetic data and fake tokens only (ADR 0005).
"""

from __future__ import annotations

import io
import json
import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from pii_guard.cli import main as root_main
from pii_guard.integrations.common import ConnectError
from pii_guard.integrations.login import (
    CliProfile,
    clear_cli_profile,
    cli_config_path,
    dashboard_origin,
    exchange_code,
    load_cli_profile,
    login_main,
    logout_main,
    run_browser_login,
    save_cli_profile,
)

ORIGIN = "https://guard.example.test"
FAKE_KEY = "pg_ep_fake_test_key_0000"
FAKE_CODE = "cli_code_fake_0000"


def _token_response(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "dashboard_url": ORIGIN,
        "project_id": "prj_demo",
        "endpoint_id": "ep_demo",
        "key": FAKE_KEY,
        "telemetry_level": "masked",
    }
    body.update(overrides)
    return body


def _dashboard(
    *,
    exchange: Callable[[httpx.Request], httpx.Response] | None = None,
    revoke_status: int = 204,
    seen: list[httpx.Request] | None = None,
) -> httpx.Client:
    """A mocked dashboard implementing the #437 ``/v1/cli/token`` contract."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path != "/v1/cli/token":
            return httpx.Response(404)
        if request.method == "POST":
            if exchange is not None:
                return exchange(request)
            if json.loads(request.content) == {"code": FAKE_CODE}:
                return httpx.Response(200, json=_token_response())
            return httpx.Response(400, json={"error": {"code": "invalid_code"}})
        if request.method == "DELETE":
            return httpx.Response(revoke_status)
        return httpx.Response(405)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _callback_base(auth_url: str) -> tuple[int, str, dict[str, list[str]]]:
    fragment = urlsplit(auth_url).fragment  # cli-auth?port=...&state=...
    route, _, query = fragment.partition("?")
    assert route == "cli-auth"
    params = parse_qs(query)
    return int(params["port"][0]), params["state"][0], params


def test_cli_profile_save_load_and_clear(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PII_GUARD_CLI_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert cli_config_path() == tmp_path / "xdg" / "pii-guard" / "cli.json"

    cfg_file = tmp_path / "config" / "cli.json"
    monkeypatch.setenv("PII_GUARD_CLI_CONFIG", str(cfg_file))
    assert cli_config_path() == cfg_file
    assert load_cli_profile() is None
    assert clear_cli_profile() is False

    remote = CliProfile(
        mode="remote",
        dashboard_url=ORIGIN,
        project_id="prj_1",
        project_name="My Project",
        endpoint_id="ep_1",
        endpoint_key=FAKE_KEY,
        telemetry_level="stats",
    )
    save_cli_profile(remote)
    assert cfg_file.is_file()
    assert load_cli_profile() == remote
    assert list(cfg_file.parent.iterdir()) == [cfg_file]  # no temp file left behind

    cfg_file.write_text("{not-json", encoding="utf-8")
    assert load_cli_profile() is None
    cfg_file.write_text("[1, 2]", encoding="utf-8")
    assert load_cli_profile() is None
    cfg_file.write_text('{"mode": "bogus"}', encoding="utf-8")
    assert load_cli_profile() is None
    cfg_file.write_text('{"mode": "remote", "dashboard_url": ""}', encoding="utf-8")
    assert load_cli_profile() is None
    cfg_file.write_text(
        '{"mode": "remote", "dashboard_url": "https://x.example", "endpoint_key": ""}',
        encoding="utf-8",
    )
    assert load_cli_profile() is None
    cfg_file.write_text('{"mode": "local", "telemetry_level": "unknown"}', encoding="utf-8")
    assert load_cli_profile() == CliProfile(mode="local", telemetry_level="masked")

    assert clear_cli_profile() is True
    assert load_cli_profile() is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_cli_json_is_written_0600(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg_file = tmp_path / "cfg" / "cli.json"
    old_umask = os.umask(0o000)  # even a permissive umask must not widen the file
    try:
        save_cli_profile(CliProfile(mode="local"), cfg_file)
        # Overwriting a file that already had loose permissions replaces it with a 0600 one.
        cfg_file.chmod(0o644)
        save_cli_profile(
            CliProfile(dashboard_url=ORIGIN, endpoint_id="ep_1", endpoint_key=FAKE_KEY),
            cfg_file,
        )
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(cfg_file.stat().st_mode) == 0o600


def test_dashboard_origin_rules() -> None:
    assert dashboard_origin("https://Guard.Example.test/") == ORIGIN
    assert dashboard_origin("https://guard.example.test:443/some/path") == ORIGIN
    assert dashboard_origin("https://guard.example.test:8443") == "https://guard.example.test:8443"
    assert dashboard_origin("http://127.0.0.1:9000") == "http://127.0.0.1:9000"
    assert dashboard_origin("http://localhost") == "http://localhost"
    with pytest.raises(ConnectError, match="https://"):
        dashboard_origin("http://guard.example.test")
    with pytest.raises(ConnectError, match="credentials"):
        dashboard_origin("https://user:pw@guard.example.test")
    with pytest.raises(ConnectError, match="must be an https"):
        dashboard_origin("ftp://guard.example.test")


def test_exchange_code_contract() -> None:
    seen: list[httpx.Request] = []
    profile = exchange_code(ORIGIN, FAKE_CODE, client=_dashboard(seen=seen))
    assert profile == CliProfile(
        mode="remote",
        dashboard_url=ORIGIN,
        project_id="prj_demo",
        endpoint_id="ep_demo",
        endpoint_key=FAKE_KEY,
        telemetry_level="masked",
    )
    assert str(seen[0].url) == f"{ORIGIN}/v1/cli/token"
    assert json.loads(seen[0].content) == {"code": FAKE_CODE}

    # The CLI may ask for less than the project allows, never more.
    assert exchange_code(ORIGIN, FAKE_CODE, telemetry_level="stats", client=_dashboard()) == (
        CliProfile(
            dashboard_url=ORIGIN,
            project_id="prj_demo",
            endpoint_id="ep_demo",
            endpoint_key=FAKE_KEY,
            telemetry_level="stats",
        )
    )

    with pytest.raises(ConnectError, match="invalid, expired or already used"):
        exchange_code(ORIGIN, "wrong", client=_dashboard())

    def respond(body: Any, status: int = 200) -> httpx.Client:
        return _dashboard(exchange=lambda _r: httpx.Response(status, json=body))

    with pytest.raises(ConnectError, match="HTTP 500"):
        exchange_code(ORIGIN, FAKE_CODE, client=respond({}, 500))
    with pytest.raises(ConnectError, match="not a JSON object"):
        exchange_code(ORIGIN, FAKE_CODE, client=respond([1]))
    with pytest.raises(ConnectError, match="missing 'key'"):
        exchange_code(ORIGIN, FAKE_CODE, client=respond(_token_response(key="")))
    with pytest.raises(ConnectError, match="missing 'endpoint_id'"):
        exchange_code(ORIGIN, FAKE_CODE, client=respond(_token_response(endpoint_id=None)))
    with pytest.raises(ConnectError, match="invalid endpoint_id"):
        exchange_code(ORIGIN, FAKE_CODE, client=respond(_token_response(endpoint_id="../x")))
    with pytest.raises(ConnectError, match="telemetry_level"):
        exchange_code(ORIGIN, FAKE_CODE, client=respond(_token_response(telemetry_level="raw")))
    # A response for another origin (or a downgrade to plain http) is refused.
    with pytest.raises(ConnectError, match=r"answered for https://evil\.example\.test"):
        exchange_code(
            ORIGIN,
            FAKE_CODE,
            client=respond(_token_response(dashboard_url="https://evil.example.test")),
        )
    with pytest.raises(ConnectError, match="https://"):
        exchange_code(
            ORIGIN,
            FAKE_CODE,
            client=respond(_token_response(dashboard_url="http://guard.example.test")),
        )


def test_browser_login_ignores_bad_callbacks_and_exchanges_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PII_GUARD_CLI_CONFIG", str(tmp_path / "cli.json"))
    results: dict[str, Any] = {}

    def browser(auth_url: str) -> None:
        port, state, params = _callback_base(auth_url)
        assert params["project"] == ["prj_demo"]
        assert "key" not in params and "telemetry" not in params
        with httpx.Client(follow_redirects=False, timeout=5) as client:
            assert client.get(f"http://127.0.0.1:{port}/other").status_code == 404
            # Wrong, missing or code-less callbacks are ignored: the login keeps waiting.
            bad = [
                {"state": "wrong", "code": "attacker_code"},
                {"code": "attacker_code"},
                {"state": state},
            ]
            for query in bad:
                res = client.get(f"http://127.0.0.1:{port}/callback?{urlencode(query)}")
                assert res.status_code == 400
            good = client.get(
                f"http://127.0.0.1:{port}/callback?{urlencode({'state': state, 'code': FAKE_CODE})}"
            )
            results["good"] = good

    seen: list[httpx.Request] = []
    profile = run_browser_login(
        ORIGIN,
        project="prj_demo",
        open_browser=lambda _url: True,
        on_listen=browser,
        stderr=io.StringIO(),
        client=_dashboard(seen=seen),
    )
    good = results["good"]
    assert good.status_code == 200
    assert "close this tab" in good.text
    assert good.headers["Cache-Control"] == "no-store"
    assert profile.endpoint_key == FAKE_KEY
    assert [json.loads(r.content) for r in seen] == [{"code": FAKE_CODE}]


def test_callback_server_binds_loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from pii_guard.integrations import login

    bound: list[tuple[str, int]] = []

    class RecordingServer(login.HTTPServer):
        def __init__(self, address: tuple[str, int], handler: Any) -> None:
            bound.append(address)
            super().__init__(address, handler)

    monkeypatch.setattr(login, "HTTPServer", RecordingServer)

    def browser(auth_url: str) -> None:
        port, state, _ = _callback_base(auth_url)
        query = urlencode({"state": state, "code": FAKE_CODE})
        httpx.get(f"http://127.0.0.1:{port}/callback?{query}", timeout=5)

    run_browser_login(
        ORIGIN,
        open_browser=lambda _url: True,
        on_listen=browser,
        stderr=io.StringIO(),
        client=_dashboard(),
    )
    assert bound == [("127.0.0.1", 0)]


def test_browser_login_times_out_and_rejects_bad_urls() -> None:
    with pytest.raises(ConnectError, match="timed out"):
        run_browser_login(
            ORIGIN, open_browser=lambda _url: True, timeout_seconds=0.05, stderr=io.StringIO()
        )
    with pytest.raises(ConnectError, match="must be an https"):
        run_browser_login("ftp://example.test")
    with pytest.raises(ConnectError, match="https://"):
        run_browser_login("http://guard.example.test")


def test_login_paste_modes_and_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg_file = tmp_path / "cli.json"
    monkeypatch.setenv("PII_GUARD_CLI_CONFIG", str(cfg_file))

    out = io.StringIO()
    assert login_main(["--status"], stdout=out) == 0
    assert "not logged in" in out.getvalue()

    # --no-browser: print the URL, prompt for the code, show the destination before saving.
    out, err = io.StringIO(), io.StringIO()
    prompts: list[str] = []

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return f"  {FAKE_CODE}\n"

    code = login_main(
        ["--no-browser", "--dashboard", ORIGIN],
        stdout=out,
        stderr=err,
        input_fn=answer,
        client=_dashboard(),
    )
    assert code == 0, err.getvalue()
    assert f"{ORIGIN}/#cli-auth\n" in err.getvalue()
    assert f"will be sent to {ORIGIN}" in err.getvalue()
    assert prompts and "one-time code" in prompts[0]
    assert load_cli_profile() is not None
    assert FAKE_KEY not in out.getvalue() + err.getvalue()

    out_status = io.StringIO()
    assert login_main(["--status"], stdout=out_status) == 0
    assert "prj_demo" in out_status.getvalue()
    assert FAKE_KEY not in out_status.getvalue()

    # --code - reads stdin.
    cfg_file.unlink()
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{FAKE_CODE}\n"))
    assert (
        login_main(
            ["--code", "-", "--dashboard", ORIGIN],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            client=_dashboard(),
        )
        == 0
    )
    assert load_cli_profile() is not None

    # A bad code saves nothing.
    cfg_file.unlink()
    err_bad = io.StringIO()
    assert (
        login_main(["--code", "nope", "--dashboard", ORIGIN], stderr=err_bad, client=_dashboard())
        == 2
    )
    assert "invalid, expired or already used" in err_bad.getvalue()
    assert not cfg_file.exists()

    # An origin mismatch saves nothing.
    evil = _dashboard(
        exchange=lambda _r: httpx.Response(
            200, json=_token_response(dashboard_url="https://evil.example.test")
        )
    )
    assert (
        login_main(["--code", FAKE_CODE, "--dashboard", ORIGIN], stderr=io.StringIO(), client=evil)
        == 2
    )
    assert not cfg_file.exists()

    # Empty code and Ctrl-C.
    assert login_main(["--no-browser"], stderr=io.StringIO(), input_fn=lambda _p: "") == 2

    def interrupt(_prompt: str) -> str:
        raise KeyboardInterrupt

    assert login_main(["--no-browser"], stderr=io.StringIO(), input_fn=interrupt) == 130

    # --help warns that a literal --code lands in shell history.
    assert "shell history" in " ".join(
        login_main.__globals__["build_login_parser"]().format_help().split()
    )


def test_login_local_and_logout_revokes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg_file = tmp_path / "cli.json"
    monkeypatch.setenv("PII_GUARD_CLI_CONFIG", str(cfg_file))

    out_local = io.StringIO()
    assert login_main(["--local"], stdout=out_local) == 0
    assert "local-only preference" in out_local.getvalue()
    out_status_local = io.StringIO()
    assert login_main(["--status"], stdout=out_status_local) == 0
    assert "local-only mode" in out_status_local.getvalue()
    # A local profile has no key to revoke.
    assert logout_main([], stdout=io.StringIO(), client=_dashboard(revoke_status=500)) == 0

    remote = CliProfile(dashboard_url=ORIGIN, endpoint_id="ep_demo", endpoint_key=FAKE_KEY)
    save_cli_profile(remote)
    seen: list[httpx.Request] = []
    out = io.StringIO()
    assert logout_main([], stdout=out, client=_dashboard(seen=seen)) == 0
    assert "revoked the CLI key" in out.getvalue()
    assert not cfg_file.exists()
    assert seen[0].method == "DELETE"
    assert str(seen[0].url) == f"{ORIGIN}/v1/cli/token"
    assert seen[0].headers["Authorization"] == f"Bearer {FAKE_KEY}"

    # Revoke fails: the file is still removed and the user is told to revoke it themselves.
    save_cli_profile(remote)
    err = io.StringIO()
    assert (
        logout_main([], stdout=io.StringIO(), stderr=err, client=_dashboard(revoke_status=500)) == 1
    )
    assert "revoke it in the dashboard" in err.getvalue()
    assert not cfg_file.exists()

    def unreachable(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    save_cli_profile(remote)
    offline = httpx.Client(transport=httpx.MockTransport(unreachable))
    assert logout_main([], stdout=io.StringIO(), stderr=io.StringIO(), client=offline) == 1
    assert not cfg_file.exists()

    # A tampered profile pointing at plain http never receives the key.
    save_cli_profile(
        CliProfile(
            dashboard_url="http://guard.example.test", endpoint_id="e", endpoint_key=FAKE_KEY
        )
    )
    seen_http: list[httpx.Request] = []
    assert (
        logout_main(
            [], stdout=io.StringIO(), stderr=io.StringIO(), client=_dashboard(seen=seen_http)
        )
        == 1
    )
    assert seen_http == []

    out_none = io.StringIO()
    assert logout_main([], stdout=out_none) == 0
    assert "no saved profile" in out_none.getvalue()


def test_root_cli_dispatches_login_and_logout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PII_GUARD_CLI_CONFIG", str(tmp_path / "cli.json"))
    assert root_main(["login", "--local"]) == 0
    assert root_main(["logout"]) == 0
