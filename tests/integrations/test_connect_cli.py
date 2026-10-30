"""``pii-guard connect``: pi config merge (dry-run, idempotent, backup), --check.

Muse Code: tests/integrations/test_muse_code.py."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from pii_guard.cli import main as root_main
from pii_guard.integrations import pi, snippets
from pii_guard.integrations.cli import main
from pii_guard.integrations.common import (
    CANARY_VALUES,
    is_endpoint_url,
    session_of,
    session_url,
    write_json,
)
from pii_guard.integrations.e2e import SCRIPTED_MODEL, Recorder, gateway_app, serve

# A hand-formatted file with another provider: connect must keep its text byte for byte.
EXISTING = """{
  "providers": {
    "ollama": {"baseUrl": "http://localhost:11434/v1", "api": "openai-completions",
               "apiKey": "ollama", "models": [{"id": "qwen2.5-coder:7b"}]}
  },
  "extra": [1, 2]
}
"""


def run(*args: str) -> tuple[int, str]:
    out = io.StringIO()
    code = main(list(args), stdout=out)
    return code, out.getvalue()


@pytest.fixture
def unreachable() -> str:
    return "http://127.0.0.1:9/v1"  # discard port: nothing listens


def test_dry_run_without_gateway_writes_nothing(
    tmp_path: Path, unreachable: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run("pi", "--dry-run", "--gateway", unreachable, "--agent-dir", str(tmp_path))
    assert code == 0
    assert "+++ " in out and '"pii-guard"' in out and '"models": []' in out
    assert "could not reach the gateway" in capsys.readouterr().err
    assert not (tmp_path / "models.json").exists()


def test_write_new_file_then_idempotent(tmp_path: Path, unreachable: str) -> None:
    args = ("pi", "--gateway", unreachable, "--agent-dir", str(tmp_path), "--model", "m1")
    code, out = run(*args)
    assert code == 0 and "wrote" in out
    data = json.loads((tmp_path / "models.json").read_text())
    entry = data["providers"]["pii-guard"]
    # A stable vault session in the path (LAB-1286): pi can't send X-PII-Guard-Session.
    assert re.fullmatch(r"http://127\.0\.0\.1:9/s/c_[0-9a-f]{32}/v1", entry["baseUrl"])
    assert f"gateway: {entry['baseUrl']}" in out
    assert entry["api"] == "openai-completions"
    assert entry["headers"] == {"X-PII-Guard-Mode": "fast", "X-PII-Guard-Language": "en"}
    assert entry["compat"] == {"supportsDeveloperRole": False, "supportsStore": False}
    assert entry["models"] == [{"id": "m1", "name": "m1 (pii-guard)"}]
    assert data["$schema"] == pi.SCHEMA_URL

    code, out = run(*args)
    assert code == 0 and "already up to date" in out  # the session is kept
    assert list(tmp_path.glob("*.pii-guard-backup-*")) == []
    code, out = run(*args, "--dry-run")
    assert "already up to date" in out


def test_session_path_kept_replaced_or_off(tmp_path: Path, unreachable: str) -> None:
    def base_url() -> str:
        data = json.loads((tmp_path / "models.json").read_text())
        return str(data["providers"]["pii-guard"]["baseUrl"])

    args = ("pi", "--agent-dir", str(tmp_path), "--model", "m1")
    run(*args, "--gateway", unreachable)
    first = base_url()
    run(*args, "--gateway", unreachable, "--model", "m2")
    assert base_url() == first  # same gateway: same session
    run(*args, "--gateway", "http://127.0.0.1:10/v1")
    assert session_of(base_url()) not in (None, session_of(first))  # another gateway
    run(*args, "--gateway", "http://127.0.0.1:9/s/mine/v1")
    assert base_url() == "http://127.0.0.1:9/s/mine/v1"  # given in --gateway: as is
    run(*args, "--gateway", unreachable, "--no-session-path")
    assert base_url() == unreachable


def test_session_url_helpers() -> None:
    assert session_of("http://h:1/s/abc/v1") == "abc"
    assert session_of("http://h:1/v1") is None
    assert session_url("http://h:1/v1", "http://h:1/s/abc/v1") == "http://h:1/s/abc/v1"
    assert session_url("http://h:1/v1/", "http://h:1/s/abc/v1/") == "http://h:1/s/abc/v1"
    assert session_url("http://h:1/s/x/v1", "http://h:1/s/abc/v1") == "http://h:1/s/x/v1"
    fresh = session_url("http://h:1/v1", "http://other:1/s/abc/v1")
    assert re.fullmatch(r"http://h:1/s/c_[0-9a-f]{32}/v1", fresh)
    assert session_url("http://h:1/v1") != session_url("http://h:1/v1")  # random


def test_endpoint_url_is_written_without_a_session_path(tmp_path: Path) -> None:
    # LAB-1614: /s/<session>/e/<id>/v1 is no route; the hosted gateway 401s every call on it.
    endpoint = "http://127.0.0.1:9/e/ep_synthetic/v1"
    code, _ = run("pi", "--agent-dir", str(tmp_path), "--model", "m1", "--gateway", endpoint)
    assert code == 0
    data = json.loads((tmp_path / "models.json").read_text())
    assert data["providers"]["pii-guard"]["baseUrl"] == endpoint
    muse = tmp_path / "muse"
    code, _ = run("muse-code", "--muse-dir", str(muse), "--gateway", endpoint + "/")
    assert code == 0
    settings = json.loads((muse / "settings.json").read_text())
    assert settings["endpoint_transport"]["base_url"] == endpoint


#: Headers a project endpoint fixes from its policy and refuses from a client (LAB-1651).
ENDPOINT_FIXED = ("x-pii-guard-mode", "x-pii-guard-language", "x-pii-guard-connection")


def test_endpoint_connect_writes_no_policy_headers(tmp_path: Path) -> None:
    # LAB-1651: pi sent X-PII-Guard-Mode/-Language from its config and the endpoint refused
    # every turn ("Endpoint language cannot be overridden"), even --language en.
    endpoint = "http://127.0.0.1:9/e/ep_synthetic/v1"
    stale = {
        "providers": {"pii-guard": {"baseUrl": endpoint, "headers": {"X-PII-Guard-Mode": "x"}}}
    }
    (tmp_path / "models.json").write_text(json.dumps(stale))
    args = ("--agent-dir", str(tmp_path), "--model", "m1", "--gateway", endpoint)
    code, _ = run("pi", *args, "--mode", "audit", "--language", "de")
    assert code == 0
    entry = json.loads((tmp_path / "models.json").read_text())["providers"]["pii-guard"]
    assert "headers" not in entry
    assert entry["baseUrl"] == endpoint and entry["models"] == [
        {"id": "m1", "name": "m1 (pii-guard)"}
    ]
    muse = tmp_path / "muse"
    assert run("muse-code", "--muse-dir", str(muse), "--gateway", endpoint)[0] == 0
    for written in (tmp_path / "models.json", muse / "settings.json"):
        text = written.read_text().lower()
        assert not any(name in text for name in ENDPOINT_FIXED), written


def test_local_gateway_connect_keeps_its_headers(tmp_path: Path, unreachable: str) -> None:
    args = ("--agent-dir", str(tmp_path), "--model", "m1", "--gateway", unreachable)
    assert run("pi", *args, "--mode", "audit", "--language", "de")[0] == 0
    entry = json.loads((tmp_path / "models.json").read_text())["providers"]["pii-guard"]
    assert entry["headers"] == {"X-PII-Guard-Mode": "audit", "X-PII-Guard-Language": "de"}


def test_endpoint_blocks_send_no_policy_headers() -> None:
    # Every Connect page block and `connect --print` for an endpoint (the same document).
    for model in ("muse-spark-1.3", None):
        doc = snippets.build_endpoint(
            gateway_url="https://guard.example/e/ep_synthetic/v1",
            endpoint="ep_synthetic",
            name="Synthetic",
            model=model,
            preset=None,
        )
        assert {t["id"] for t in doc["tools"]} == set(snippets.TOOL_IDS)
        for tool in doc["tools"]:
            text = json.dumps(tool).lower()
            assert not any(name in text for name in ENDPOINT_FIXED), tool["id"]


def test_is_endpoint_url() -> None:
    assert is_endpoint_url("https://guard.example/e/ep_1/v1")
    assert is_endpoint_url("https://guard.example/e/ep_1/v1/")
    assert is_endpoint_url("https://guard.example/prefix/e/ep-1/v1")
    assert not is_endpoint_url("https://guard.example/v1")
    assert not is_endpoint_url("https://guard.example/s/c_1/v1")
    assert not is_endpoint_url("https://guard.example/e/ep_1/v1/responses")
    assert not is_endpoint_url("https://guard.example/e//v1")


def test_existing_file_kept_and_backed_up(tmp_path: Path, unreachable: str) -> None:
    path = tmp_path / "models.json"
    path.write_text(EXISTING)
    code, out = run("pi", "--gateway", unreachable, "--agent-dir", str(tmp_path), "--model", "m1")
    assert code == 0 and "backup:" in out
    text = path.read_text()
    assert text.startswith(EXISTING.split('\n  },\n  "extra"')[0])  # ollama block untouched
    assert '"extra": [1, 2]' in text
    data = json.loads(text)
    assert set(data["providers"]) == {"ollama", "pii-guard"}
    assert "$schema" not in data
    (backup,) = tmp_path.glob("models.json.pii-guard-backup-*")
    assert backup.read_text() == EXISTING

    # A second model replaces our provider in place; the rest still byte for byte.
    code, _ = run("pi", "--gateway", unreachable, "--agent-dir", str(tmp_path), "--model", "m2")
    data = json.loads(path.read_text())
    assert [m["id"] for m in data["providers"]["pii-guard"]["models"]] == ["m2"]
    assert path.read_text().count('"pii-guard": {') == 1
    assert '"apiKey": "ollama", "models": [{"id": "qwen2.5-coder:7b"}]}' in path.read_text()


def test_empty_providers_and_fallback_render() -> None:
    entry = pi.provider_entry("http://g/v1", ["m"])
    spliced = pi.render({"providers": {}}, '{"providers": {}}\n', entry)
    assert json.loads(spliced)["providers"]["pii-guard"] == entry
    # No providers key: re-rendered as a whole, still a correct merge.
    rendered = pi.render({"a": 1}, '{"a": 1}', entry)
    assert json.loads(rendered) == {"a": 1, "providers": {"pii-guard": entry}}


def test_invalid_json_is_refused(tmp_path: Path, unreachable: str) -> None:
    (tmp_path / "models.json").write_text("{ nope")
    code, _ = run("pi", "--gateway", unreachable, "--agent-dir", str(tmp_path), "--model", "m")
    assert code == 2
    assert (tmp_path / "models.json").read_text() == "{ nope"


def test_no_models_without_dry_run_fails(tmp_path: Path, unreachable: str) -> None:
    code, _ = run("pi", "--gateway", unreachable, "--agent-dir", str(tmp_path))
    assert code == 2
    assert not (tmp_path / "models.json").exists()


def test_api_token_becomes_env_reference(
    tmp_path: Path, unreachable: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PII_GUARD_API_TOKEN", "t0ken-for-tests")
    run("pi", "--gateway", unreachable, "--agent-dir", str(tmp_path), "--model", "m")
    text = (tmp_path / "models.json").read_text()
    assert '"apiKey": "$PII_GUARD_API_TOKEN"' in text
    assert "t0ken-for-tests" not in text


def test_agent_dir_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
    assert pi.config_path() == tmp_path / "agent" / "models.json"


def test_resolve_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOME_KEY", "v")
    assert pi.resolve_value("$SOME_KEY") == "v"
    assert pi.resolve_value("${SOME_KEY}") == "v"
    assert pi.resolve_value("!cat secret") is None
    assert pi.resolve_value("$$literal") == "$literal"
    assert pi.resolve_value("plain") == "plain"


def test_write_json_no_change_no_backup(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    assert write_json(path, "{}\n") is None
    assert write_json(path, "{}\n") is None
    backup = write_json(path, '{"a": 1}\n')
    assert backup is not None and backup.read_text() == "{}\n"


def test_connect_and_check_through_a_real_gateway(tmp_path: Path) -> None:
    """Models from GET /v1/models, then the canary: masked upstream, restored for the user."""
    recorder = Recorder()
    statuses: list[int] = []
    with serve(recorder.app) as upstream, serve(gateway_app(upstream + "/v1", statuses)) as gw:
        code, out = run("pi", "--gateway", gw + "/v1", "--agent-dir", str(tmp_path))
        assert code == 0, out
        models = json.loads((tmp_path / "models.json").read_text())["providers"]["pii-guard"]
        assert [m["id"] for m in models["models"]] == [SCRIPTED_MODEL]

        code, out = run("pi", "--check", "--agent-dir", str(tmp_path))
    assert code == 0, out
    assert "ok           : 3 value(s) masked" in out
    assert "session      : path " in out
    assert "#traffic" in out
    received = out.split("you got back : ")[1].splitlines()[0]
    model_saw = out.split("model saw    : ")[1].splitlines()[0]
    for value in CANARY_VALUES:
        assert value in received
        assert value not in model_saw
    assert all(value not in "".join(recorder.bodies) for value in CANARY_VALUES)
    # The canary went the way pi goes: fast mode, en.
    assert statuses == [200]


def test_check_with_gateway_flag_keeps_the_configured_session(tmp_path: Path) -> None:
    """``pii-guard up`` prints ``connect pi --gateway URL --check`` (LAB-1469): the check must
    go through the session in pi's baseUrl, not the gateway's default session."""
    recorder = Recorder()
    with serve(recorder.app) as upstream, serve(gateway_app(upstream + "/v1", [])) as gw:
        run("pi", "--gateway", gw + "/v1", "--agent-dir", str(tmp_path))
        configured = json.loads((tmp_path / "models.json").read_text())
        base_url = configured["providers"]["pii-guard"]["baseUrl"]
        code, out = run("pi", "--check", "--gateway", gw + "/v1", "--agent-dir", str(tmp_path))
        assert code == 0, out
        assert f"gateway      : {base_url}/chat/completions" in out
        assert "session      : path " in out
        # Another gateway URL is still taken as given.
        code, out = run(
            "pi", "--check", "--gateway", upstream + "/v1", "--agent-dir", str(tmp_path)
        )
    assert code == 1
    assert "is this URL the pii-guard gateway" in out


@pytest.mark.parametrize(
    ("client", "route"), [("codex", "/responses"), ("opencode", "/chat/completions")]
)
def test_check_for_tools_without_a_config_file(client: str, route: str) -> None:
    """``connect codex|opencode --check`` (LAB-1469): the canary the way the block sends it,
    through a path session, masked upstream and restored for the user."""
    recorder = Recorder()
    statuses: list[int] = []
    with serve(recorder.app) as upstream, serve(gateway_app(upstream + "/v1", statuses)) as gw:
        code, out = run(client, "--check", "--gateway", gw + "/v1")
    assert code == 0, out
    assert re.search(rf"gateway      : {re.escape(gw)}/s/c_[0-9a-f]{{32}}/v1{route}\n", out)
    assert f"model        : {SCRIPTED_MODEL}" in out
    assert "session      : path " in out
    assert "ok           : 3 value(s) masked" in out
    received = out.split("you got back : ")[1].splitlines()[0]
    for value in CANARY_VALUES:
        assert value in received
    assert all(value not in "".join(recorder.bodies) for value in CANARY_VALUES)
    assert statuses == [200]


def test_dry_run_is_still_refused_for_tools_without_a_config_file(unreachable: str) -> None:
    code, _ = run("codex", "--dry-run", "--gateway", unreachable)
    assert code == 2


def test_check_fails_when_url_is_not_the_gateway(tmp_path: Path) -> None:
    recorder = Recorder()
    with serve(recorder.app) as upstream:
        run("pi", "--gateway", upstream + "/v1", "--agent-dir", str(tmp_path), "--model", "m")
        code, out = run("pi", "--check", "--agent-dir", str(tmp_path))
    assert code == 1
    # The recorder answers /s/<session>/v1/... with 404 and no pii-guard headers.
    assert "is this URL the pii-guard gateway" in out


def test_check_without_provider(tmp_path: Path) -> None:
    code, _ = run("pi", "--check", "--agent-dir", str(tmp_path))
    assert code == 2


def test_check_and_dry_run_exclusive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        run("pi", "--check", "--dry-run", "--agent-dir", str(tmp_path))


def test_root_cli_dispatches_connect(
    tmp_path: Path, unreachable: str, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["connect", "muse-code", "--dry-run", "--gateway", unreachable]
    assert root_main([*args, "--muse-dir", str(tmp_path)]) == 0
    assert "endpoint_transport" in capsys.readouterr().out
