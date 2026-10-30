"""``GET /v1/connect/snippets`` (LAB-1331): the Connect quickstart's blocks, never a key."""

from __future__ import annotations

import json
import shlex
import tomllib
from pathlib import Path
from typing import Any

import httpx
import pytest
from api_helpers import TEST_TENANT_KEY
from fastapi.testclient import TestClient
from pydantic import SecretStr

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.integrations import snippets
from pii_guard.observability import Observability, ObservabilitySettings, TrafficLevel

UPSTREAM_KEY = "fictional-upstream-key-0000"
API_TOKEN = "fictional-api-token-0000"  # noqa: S105 - fictional


def _client(settings: Settings, models: list[str] | None = None) -> TestClient:
    app = create_app(settings)
    listed = [{"id": m} for m in (models or [])]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"object": "list", "data": listed})

    app.state.gateway_transport = httpx.MockTransport(handler)
    return TestClient(app, base_url="http://127.0.0.1:8899")


def _meta(**extra: Any) -> Settings:
    return Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url="https://api.meta.ai/v1",
        upstream_api_key=SecretStr(UPSTREAM_KEY),
        **extra,
    )


def _tool(body: dict[str, Any], tool: str) -> dict[str, Any]:
    return next(t for t in body["tools"] if t["id"] == tool)


def test_every_tool_gets_the_session_url_and_the_preset_model() -> None:
    client = _client(_meta(), ["sam-3.1", "muse-spark-1.2", "muse-spark-1.3"])
    body = client.get("/v1/connect/snippets", params={"session": "c_abc"}).json()
    url = "http://127.0.0.1:8899/s/c_abc/v1"
    assert body["session_url"] == url and body["gateway_url"] == "http://127.0.0.1:8899/v1"
    assert body["model"] == "muse-spark-1.3"  # the preset's suggestion, not the first listed
    assert body["models"] == ["muse-spark-1.2", "muse-spark-1.3"]  # no segmentation model
    assert body["upstream"] == {
        "connected": True,
        "mock": False,
        "origin": "https://api.meta.ai",
        "preset": "meta",
        "label": "Meta Model API",
    }
    assert [t["id"] for t in body["tools"]] == list(snippets.TOOL_IDS)
    for tool in body["tools"]:
        if tool["supported"]:
            # Claude Code's base URL is the session root: its SDK appends /v1/messages.
            expected = url.removesuffix("/v1") if tool["id"] == "claude-code" else url
            assert expected in tool["code"], tool["id"]
    # The Meta Model API has no Messages API: Claude Code is labelled, not offered (LAB-1605).
    claude = _tool(body, "claude-code")
    assert not claude["supported"] and claude["kind"] == "unsupported"
    assert "Anthropic Messages upstream" in claude["note"]
    assert _tool(body, "codex")["tested_version"] == snippets.CODEX_VERSION
    assert "muse-spark-1.3" in _tool(body, "codex")["code"]


def test_blocks_parse_as_the_tools_read_them() -> None:
    body = _client(_meta(), ["muse-spark-1.3"]).get("/v1/connect/snippets?session=c_x").json()
    url = body["session_url"]
    # Codex: a shell command whose -c values are TOML.
    words = shlex.split(_tool(body, "codex")["code"].replace("\\\n", " "))
    overrides = [words[i + 1] for i, w in enumerate(words) if w == "-c"]
    assert "model_provider=pii-guard" in overrides and "web_search=disabled" in overrides
    provider = next(o for o in overrides if o.startswith("model_providers."))
    table = tomllib.loads(provider.replace("model_providers.pii-guard=", "p="))["p"]
    assert table == {"name": "pii-guard", "base_url": url, "wire_api": "responses"}
    # OpenCode: OPENCODE_CONFIG_CONTENT is JSON.
    export = _tool(body, "opencode")["code"].split("\n")[0]
    config = json.loads(shlex.split(export.removeprefix("export "))[0].split("=", 1)[1])
    assert config["provider"]["pii-guard"]["options"] == {"baseURL": url}
    assert config["model"] == "pii-guard/muse-spark-1.3"
    # cURL: a valid JSON body.
    curl = shlex.split(_tool(body, "curl")["code"].replace("\\\n", " "))
    assert json.loads(curl[curl.index("-d") + 1])["model"] == "muse-spark-1.3"
    # Python: compiles.
    compile(_tool(body, "python")["code"], "<snippet>", "exec")


def test_never_a_key_or_token() -> None:
    settings = _meta(api_token=SecretStr(API_TOKEN))
    client = _client(settings, ["muse-spark-1.3"])
    res = client.get(
        "/v1/connect/snippets",
        params={"session": "c_x"},
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    )
    text = res.text
    assert res.status_code == 200
    assert UPSTREAM_KEY not in text and API_TOKEN not in text
    body = res.json()
    assert body["auth"] == {"token_required": True, "token_env": "PII_GUARD_API_TOKEN"}
    assert "$PII_GUARD_API_TOKEN" in _tool(body, "curl")["code"]
    assert 'env_key="PII_GUARD_API_TOKEN"' in _tool(body, "codex")["code"]
    assert "{env:PII_GUARD_API_TOKEN}" in _tool(body, "opencode")["code"]
    assert all("<your-key>" in p["command"] for p in body["presets"])


def test_no_upstream_lists_presets_and_names_no_model() -> None:
    body = _client(Settings(tenant_key=TEST_TENANT_KEY)).get("/v1/connect/snippets").json()
    assert body["upstream"]["connected"] is False and body["models"] == []
    assert body["model"] == "muse-spark-1.3"  # the owner's fallback: a Meta Model API model
    assert "--model muse-spark-1.3" in _tool(body, "pi")["code"]
    assert body["session"].startswith("c_") and len(body["session"]) == 34
    assert [p["id"] for p in body["presets"]] == ["meta", "openai", "fireworks", "openrouter"]


def test_the_model_query_wins_and_an_unlisted_preset_model_falls_back() -> None:
    client = _client(_meta(), ["sam-3.1", "muse-spark-1.2"])
    assert client.get("/v1/connect/snippets").json()["model"] == "muse-spark-1.2"
    picked = client.get("/v1/connect/snippets", params={"model": "muse-wonder-1.0"}).json()
    assert picked["model"] == "muse-wonder-1.0"
    assert "muse-wonder-1.0" in _tool(picked, "codex")["code"]


@pytest.mark.parametrize(
    ("models", "expected"),
    [
        (["meta-models/muse-spark-open-1026"], "muse-spark-1.3"),  # never a re-hosted id
        (["meta-models/muse-spark-open-1026", "muse-wonder-1.0"], "muse-wonder-1.0"),
        (["muse-image-1.0", "muse-voice-transcribe-1.0"], "muse-spark-1.3"),
        ([], "muse-spark-1.3"),
        (["qwen2.5-coder:7b"], "qwen2.5-coder:7b"),  # a local model of its own
    ],
)
def test_a_non_preset_upstream_names_a_meta_model(models: list[str], expected: str) -> None:
    settings = Settings(tenant_key=TEST_TENANT_KEY, upstream_base_url="https://models.test/v1")
    assert _client(settings, models).get("/v1/connect/snippets").json()["model"] == expected


def test_curl_also_shows_the_responses_api() -> None:
    body = _client(_meta(), ["muse-wonder-1.0"]).get("/v1/connect/snippets?session=c_r").json()
    (more,) = _tool(body, "curl")["more"]
    assert more["title"] == "Responses API"
    words = shlex.split(more["code"].replace("\\\n", " "))
    assert words[2] == "http://127.0.0.1:8899/s/c_r/v1/responses"
    assert "X-PII-Guard-Echo: masked" in words
    sent = json.loads(words[words.index("-d") + 1])
    assert sent["model"] == "muse-wonder-1.0" and sent["stream"] is False
    assert sent["input"][0]["content"][0]["type"] == "input_text"


@pytest.mark.parametrize(
    "query", [{"session": "bad session"}, {"session": "x" * 129}, {"model": 'a"; rm -rf /'}]
)
def test_bad_queries_are_refused(query: dict[str, str]) -> None:
    res = _client(_meta(), []).get("/v1/connect/snippets", params=query)
    assert res.status_code == 422


def test_an_unsafe_upstream_model_id_is_not_pasted() -> None:
    body = _client(_meta(), ["evil'$(id)"]).get("/v1/connect/snippets").json()
    assert body["model"] == "muse-spark-1.3"
    assert "$(id)" not in json.dumps(body["tools"])


def test_session_ref_matches_the_traffic_log() -> None:
    settings = _meta()
    app = create_app(settings)
    app.state.observability = Observability(ObservabilitySettings(traffic_log=TrafficLevel.MASKED))
    app.state.gateway_transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"data": []})
    )
    client = TestClient(app, base_url="http://127.0.0.1:8899")
    body = client.get("/v1/connect/snippets", params={"session": "c_ref"}).json()
    assert body["traffic_log"] == "masked"
    assert body["session_ref"] == app.state.observability.traffic.session_ref("c_ref")
    off = _client(settings).get("/v1/connect/snippets").json()
    assert off["session_ref"] is None and off["traffic_log"] == "off"


# --- ?endpoint=<id> (LAB-1431, ADR 0013): the same blocks for one owned project endpoint ----

PROVIDER_KEY = "fictional-provider-key-0000"


def _endpoint_client(tmp_path: Path, **extra: Any) -> tuple[TestClient, str]:
    settings = Settings(
        _env_file=None,
        tenant_key=TEST_TENANT_KEY,
        project_state_path=str(tmp_path / "projects.sqlite3"),
        **extra,
    )
    client = _client(settings)
    project = client.get("/v1/projects").json()["projects"][0]
    policy = client.get(f"/v1/projects/{project['id']}/policies").json()["policies"][0]
    created = client.post(
        f"/v1/projects/{project['id']}/endpoints",
        json={
            "name": "Synthetic endpoint",
            "provider": "openai",
            "model": "synthetic-model",
            "api_key": PROVIDER_KEY,
            "policy_version_id": policy["policy_version_id"],
        },
    )
    assert created.status_code == 201, created.text
    return client, created.json()["id"]


def test_endpoint_blocks_use_the_endpoint_url_model_and_key(tmp_path: Path) -> None:
    client, endpoint = _endpoint_client(tmp_path)
    res = client.get("/v1/connect/snippets", params={"endpoint": endpoint})
    assert res.status_code == 200, res.text
    body = res.json()
    url = f"http://127.0.0.1:8899/e/{endpoint}/v1"
    assert body["gateway_url"] == url
    assert body["session"] is None and body["session_url"] is None
    assert body["endpoint"] == {
        "id": endpoint,
        "name": "Synthetic endpoint",
        "model": "synthetic-model",
        "enabled": True,
    }
    assert body["model"] == "synthetic-model" and body["models"] == ["synthetic-model"]
    assert body["auth"] == {"token_required": True, "token_env": "PII_GUARD_ENDPOINT_KEY"}
    assert body["upstream"]["origin"] is None and body["upstream"]["preset"] == "openai"
    assert body["presets"] == [] and body["session_ref"] is None
    for tool in body["tools"]:
        if tool["supported"]:
            assert url in tool["code"], tool["id"]
            assert "/s/" not in tool["code"], tool["id"]
    assert "$PII_GUARD_ENDPOINT_KEY" in _tool(body, "curl")["code"]
    assert 'env_key="PII_GUARD_ENDPOINT_KEY"' in _tool(body, "codex")["code"]
    assert "{env:PII_GUARD_ENDPOINT_KEY}" in _tool(body, "opencode")["code"]
    assert not _tool(body, "claude-code")["supported"]  # endpoint upstreams are OpenAI-only
    assert "--no-session-path" in _tool(body, "pi")["code"]
    assert "--api-key '$PII_GUARD_ENDPOINT_KEY'" in _tool(body, "pi")["code"]
    # Muse Code reads its catalog at the root; the endpoint key gets its own there (LAB-1462).
    assert _tool(body, "muse-code")["supported"]
    assert 'META_API_KEY="$PII_GUARD_ENDPOINT_KEY" muse' in _tool(body, "muse-code")["code"]
    # LAB-1614: no /s/<session> in front of /e/<id>/v1, which would 401 every call.
    assert "--no-session-path" in _tool(body, "muse-code")["code"]
    compile(_tool(body, "python")["code"], "<snippet>", "exec")
    for secret in (PROVIDER_KEY, "api.openai.com", "pg_ep_"):
        assert secret not in res.text


def test_unknown_endpoint_is_404_and_bad_endpoint_queries_are_refused(tmp_path: Path) -> None:
    client, endpoint = _endpoint_client(tmp_path)
    missing = client.get("/v1/connect/snippets", params={"endpoint": "synthetic-unknown"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "project_not_found"
    for query in (
        {"endpoint": "bad endpoint"},
        {"endpoint": endpoint, "session": "c_x"},
        {"endpoint": endpoint, "model": "muse-spark-1.3"},
    ):
        assert client.get("/v1/connect/snippets", params=query).status_code == 422, query


def test_endpoint_blocks_need_local_owner_access(tmp_path: Path) -> None:
    client, endpoint = _endpoint_client(tmp_path)
    remote = TestClient(client.app, base_url="http://127.0.0.1:8899", client=("192.0.2.7", 5000))
    res = remote.get("/v1/connect/snippets", params={"endpoint": endpoint})
    assert res.status_code == 403
    assert "Synthetic endpoint" not in res.text
    # The session blocks are unchanged for the same caller.
    assert remote.get("/v1/connect/snippets").status_code == 200


def test_claude_code_is_offered_only_with_an_anthropic_upstream() -> None:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url="https://api.anthropic.com/v1",
        upstream_api_key=SecretStr(UPSTREAM_KEY),
    )
    body = _client(settings, ["claude-test-model"]).get("/v1/connect/snippets?session=c_x").json()
    url = body["session_url"]
    claude = _tool(body, "claude-code")
    assert claude["supported"] and claude["kind"] == "launch"
    assert f"ANTHROPIC_BASE_URL={url.removesuffix('/v1')} " in claude["code"]
    assert claude["tested_version"] == snippets.CLAUDE_CODE_VERSION
    assert UPSTREAM_KEY not in json.dumps(body)


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("https://api.anthropic.com", True),
        ("https://api.meta.ai", False),
        ("https://api.anthropic.com.example.test", False),
        (None, False),
    ],
)
def test_messages_upstream(origin: str | None, expected: bool) -> None:
    assert snippets.messages_upstream(origin) is expected
