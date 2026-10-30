"""Muse Code behind the gateway: ``connect muse-code`` (settings.json), ``--check`` through
``/v1/responses``, and the ``/muse-code/models`` catalog. Fictional values only (ADR 0005)."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.integrations import muse_code
from pii_guard.integrations.cli import main
from pii_guard.integrations.common import CANARY_VALUES
from pii_guard.integrations.e2e import SCRIPTED_MODEL, Recorder, gateway_app, serve

TENANT = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"
EXISTING = """{
  "schema_version": 1,
  "telemetry": {"enabled": false},
  "endpoint_transport": {"proxy": "http://proxy.test:3128", "base_url": "https://api.meta.ai/v1"}
}
"""


def run(*args: str) -> tuple[int, str]:
    out = io.StringIO()
    code = main(list(args), stdout=out)
    return code, out.getvalue()


def test_write_new_settings_then_idempotent(tmp_path: Path) -> None:
    args = ("muse-code", "--gateway", "http://127.0.0.1:8787/v1/", "--muse-dir", str(tmp_path))
    code, out = run(*args, "--dry-run")
    assert code == 0 and "+++ " in out
    assert not (tmp_path / "settings.json").exists()

    code, out = run(*args)
    assert code == 0 and "wrote" in out and "PII_GUARD_GATEWAY_MODE=fast" in out
    data = json.loads((tmp_path / "settings.json").read_text())
    base_url = data["endpoint_transport"]["base_url"]
    assert re.fullmatch(r"http://127\.0\.0\.1:8787/s/c_[0-9a-f]{32}/v1", base_url)
    assert data == {
        "schema_version": 1,
        "endpoint_transport": {"base_url": base_url, "auth": "bearer"},
    }
    code, out = run(*args)
    assert code == 0 and "already up to date" in out
    assert list(tmp_path.glob("*.pii-guard-backup-*")) == []


def test_existing_settings_are_kept_and_backed_up(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(EXISTING)
    code, out = run(
        "muse-code", "--gateway", "http://127.0.0.1:8787/v1", "--muse-dir", str(tmp_path)
    )
    assert code == 0 and "backup:" in out
    data = json.loads(path.read_text())
    assert data["telemetry"] == {"enabled": False}
    assert data["endpoint_transport"] == {
        "proxy": "http://proxy.test:3128",
        "base_url": data["endpoint_transport"]["base_url"],
        "auth": "bearer",
    }
    assert data["endpoint_transport"]["base_url"].startswith("http://127.0.0.1:8787/s/c_")
    (backup,) = tmp_path.glob("settings.json.pii-guard-backup-*")
    assert backup.read_text() == EXISTING
    run(
        "muse-code",
        "--gateway",
        "http://127.0.0.1:8787/v1",
        "--muse-dir",
        str(tmp_path),
        "--no-session-path",
    )
    plain = json.loads(path.read_text())["endpoint_transport"]["base_url"]
    assert plain == "http://127.0.0.1:8787/v1"


def test_bad_settings_are_refused(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text('{"endpoint_transport": []}')
    code, _ = run("muse-code", "--gateway", "http://x.test/v1", "--muse-dir", str(tmp_path))
    assert code == 2
    (tmp_path / "settings.json").write_text("{nope")
    code, _ = run("muse-code", "--gateway", "http://x.test/v1", "--muse-dir", str(tmp_path))
    assert code == 2


def test_config_path_follows_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert muse_code.config_path() == tmp_path / "muse" / "settings.json"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert muse_code.config_path() == tmp_path / ".config" / "muse" / "settings.json"


def test_check_without_settings(tmp_path: Path) -> None:
    code, _ = run("muse-code", "--check", "--muse-dir", str(tmp_path))
    assert code == 2


def test_connect_and_check_through_a_real_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The canary the way Muse sends it: /muse-code/models, then POST /v1/responses."""
    monkeypatch.setenv("META_API_KEY", "not-a-real-key")
    recorder = Recorder()
    statuses: list[int] = []
    with serve(recorder.app) as upstream:
        app = gateway_app(upstream + "/v1", statuses, mode="fast")
        with serve(app) as gw:
            code, out = run("muse-code", "--gateway", gw + "/v1", "--muse-dir", str(tmp_path))
            assert code == 0, out
            code, out = run("muse-code", "--check", "--muse-dir", str(tmp_path))
    assert code == 0, out
    assert f"model        : {SCRIPTED_MODEL}" in out
    assert "ok           : 3 value(s) masked" in out
    assert "gateway mode : fast" in out
    assert "session      : path " in out
    received = out.split("you got back : ")[1].splitlines()[0]
    model_saw = out.split("model saw    : ")[1].splitlines()[0]
    for value in CANARY_VALUES:
        assert value in received
        assert value not in model_saw
    assert all(value not in "".join(recorder.bodies) for value in CANARY_VALUES)
    assert statuses == [200]


def test_check_notes_strict_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = muse_code.CheckResult(url="u", model="m", sent="s", status=200)
    monkeypatch.setattr(muse_code, "run_check", lambda *a, **k: (result, "strict"))
    run("muse-code", "--gateway", "http://x.test/v1", "--muse-dir", str(tmp_path))
    code, out = run("muse-code", "--check", "--muse-dir", str(tmp_path), "--model", "m")
    assert code == 1  # nothing masked: not ok
    assert "gateway mode : strict" in out and "PII_GUARD_GATEWAY_MODE=fast" in out


# --- GET /muse-code/models ----------------------------------------------------------------

CATALOG = {
    "object": "list",
    "data": [
        {
            "id": "muse-spark-1.3",
            "object": "model",
            "created": 1,
            "owned_by": "meta",
            "price_note": "dropped",
            "metadata": {"muse-code": {"limit": {"context": 1000}}, "other": {"x": 1}},
        },
        {"id": "", "object": "model"},
    ],
}


def catalog_app(handler: Any, **settings: Any) -> TestClient:
    app = create_app(
        Settings(
            tenant_key=TENANT,
            upstream_base_url="https://upstream.test/v1",
            upstream_api_key="sk-test-upstream-key-0000",
            **settings,
        )
    )
    app.state.gateway_transport = httpx.MockTransport(handler)
    return TestClient(app)


def test_catalog_is_passed_through_from_the_upstream() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=CATALOG)

    with catalog_app(handler) as http:
        response = http.get("/muse-code/models")
    assert response.status_code == 200
    assert str(seen[0].url) == "https://upstream.test/muse-code/models"
    assert seen[0].headers["authorization"] == "Bearer sk-test-upstream-key-0000"
    assert response.json() == {
        "object": "list",
        "data": [
            {
                "id": "muse-spark-1.3",
                "object": "model",
                "created": 1,
                "owned_by": "meta",
                "metadata": {"muse-code": {"limit": {"context": 1000}}},
            }
        ],
    }


def test_catalog_is_synthesised_when_the_upstream_has_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/muse-code/models":
            return httpx.Response(404)
        return httpx.Response(200, json={"data": [{"id": "llama-local", "owned_by": "me"}]})

    with catalog_app(handler) as http:
        response = http.get("/muse-code/models")
    (model,) = response.json()["data"]
    assert model["id"] == "llama-local"
    assert model["metadata"]["muse-code"]["tool_call"] is True
    assert model["metadata"]["muse-code"]["name"] == "llama-local"


def test_catalog_from_static_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_UPSTREAM_MODELS", "a, b")

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - not called
        raise AssertionError("the upstream must not be asked")

    with catalog_app(handler) as http:
        response = http.get("/muse-code/models")
    assert [m["id"] for m in response.json()["data"]] == ["a", "b"]


def test_catalog_upstream_errors_keep_no_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "key for Teszt Elek"}})

    with catalog_app(handler) as http:
        response = http.get("/muse-code/models")
    assert response.status_code == 401
    assert "Teszt" not in response.text


def test_muse_code_load_and_render_edge_cases(tmp_path: Path) -> None:
    empty_file = tmp_path / "empty.json"
    empty_file.write_text("   \n")
    assert muse_code.load(empty_file) == ({}, "   \n")

    not_dict = tmp_path / "list.json"
    not_dict.write_text("[1, 2, 3]")
    with pytest.raises(muse_code.ConnectError, match="must hold a JSON object"):
        muse_code.load(not_dict)

    bad_transport = tmp_path / "bad_transport.json"
    bad_transport.write_text('{"endpoint_transport": "not-an-object"}')
    with pytest.raises(muse_code.ConnectError, match="endpoint_transport must be an object"):
        muse_code.load(bad_transport)

    merged = muse_code.merge({}, "http://127.0.0.1:8787/v1")
    raw = json.dumps(merged)
    assert muse_code.render({}, raw, "http://127.0.0.1:8787/v1") == raw


def test_muse_code_fetch_catalog_edge_cases() -> None:
    def err_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("cannot connect")

    client = httpx.Client(transport=httpx.MockTransport(err_handler))
    with pytest.raises(muse_code.ConnectError, match="could not reach"):
        muse_code.fetch_catalog("http://gw.test/v1", client=client)

    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(muse_code.ConnectError, match="answered HTTP 500"):
        muse_code.fetch_catalog("http://gw.test/v1", client=client)

    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": "not a list"}))
    )
    with pytest.raises(muse_code.ConnectError, match="lists no visible models"):
        muse_code.fetch_catalog("http://gw.test/v1", client=client)

    catalog = {
        "data": [
            "not a dict",
            {"id": 123},
            {"id": "hidden-model", "metadata": {"muse-code": {"is_hidden": True}}},
            {"id": "good-model", "metadata": {"muse-code": {"is_hidden": False}}},
        ]
    }
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=catalog))
    )
    assert muse_code.fetch_catalog("http://gw.test/v1", client=client) == ["good-model"]


def test_muse_code_text_helper() -> None:
    assert muse_code._text("plain") == "plain"
    assert muse_code._text([{"text": "hello "}, {"text": "world"}, "ignored"]) == "hello world"
    assert muse_code._text(12345) == ""


def test_muse_code_run_check_edge_cases() -> None:
    def raise_err(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = httpx.Client(transport=httpx.MockTransport(raise_err))
    res, _ = muse_code.run_check("http://gw.test/v1", "m", client=client)
    assert "could not reach" in (res.error or "")

    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(404, text="Not Found"))
    )
    res, _ = muse_code.run_check("http://gw.test/v1", "m", client=client)
    assert res.error == muse_code.NOT_THE_GATEWAY

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, text="not json", headers={"x-pii-guard-request-id": "r1"})
        )
    )
    res, _ = muse_code.run_check("http://gw.test/v1", "m", client=client)
    assert res.error == "the answer is not JSON"

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                400,
                json={"error": {"code": "bad_req", "message": "bad"}},
                headers={"x-pii-guard-request-id": "r1"},
            )
        )
    )
    res, _ = muse_code.run_check("http://gw.test/v1", "m", client=client)
    assert res.error == "bad_req bad"

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"output": []}, headers={"x-pii-guard-request-id": "r1"}
            )
        )
    )
    res, _ = muse_code.run_check("http://gw.test/v1", "m", client=client)
    assert "the answer has no pii_guard echo" in (res.error or "")
