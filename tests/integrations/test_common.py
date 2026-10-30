"""Tests for common integration helpers: gateway URLs, check runner, model fetching, diffing."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from pii_guard.config import Settings
from pii_guard.integrations import common
from pii_guard.integrations.common import (
    CheckResult,
    ConnectError,
    default_gateway_url,
    fetch_models,
    is_endpoint_url,
    json_diff,
    run_check,
    session_of,
    session_url,
)


def test_default_gateway_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # 0.0.0.0 maps to 127.0.0.1
    monkeypatch.setattr(
        "pii_guard.config.get_settings",
        lambda: Settings(host="0.0.0.0", port=8787),  # noqa: S104
    )
    assert default_gateway_url() == "http://127.0.0.1:8787/v1"

    # IPv6 host gets brackets
    monkeypatch.setattr(
        "pii_guard.config.get_settings",
        lambda: Settings(host="2001:db8::1", port=8787),
    )
    assert default_gateway_url() == "http://[2001:db8::1]:8787/v1"


def test_session_and_endpoint_urls() -> None:
    gw = "http://127.0.0.1:8787/v1"
    # Create new session url
    url1 = session_url(gw)
    assert session_of(url1) is not None
    # Re-passing existing session url keeps it
    assert session_url(url1) == url1

    # Reusing session from matching existing client URL
    url2 = session_url(gw, existing=url1)
    assert session_of(url2) == session_of(url1)

    # Endpoint URLs
    assert is_endpoint_url("http://127.0.0.1:8787/e/my-endpoint/v1")
    assert not is_endpoint_url("http://127.0.0.1:8787/v1")


def test_json_diff(tmp_path: Path) -> None:
    p = tmp_path / "config.json"
    diff = json_diff(p, '{"a": 1}\n', '{"a": 2}\n')
    assert '-{"a": 1}' in diff
    assert '+{"a": 2}' in diff


def test_fetch_models_errors_and_success() -> None:
    # HTTP error
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")))
    )
    with pytest.raises(ConnectError, match="could not reach the gateway"):
        fetch_models("http://gw.test/v1", client=client)

    # HTTP 500
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(ConnectError, match="answered HTTP 500"):
        fetch_models("http://gw.test/v1", client=client)

    # Malformed data (not a JSON dict or missing "data")
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=["not", "dict"]))
    )
    with pytest.raises(ConnectError, match="did not return an OpenAI model list"):
        fetch_models("http://gw.test/v1", client=client)

    # Success (deduplicated)
    data = {"data": [{"id": "m1"}, {"id": "m2"}, {"id": "m1"}, "bad"]}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data)))
    assert fetch_models("http://gw.test/v1", client=client) == ["m1", "m2"]


def test_check_result_lines() -> None:
    r = CheckResult(url="http://gw.test/v1/chat/completions", model="m", sent="s", status=200)
    r.session_source = "header"
    # masked == 0
    lines = r.lines()
    assert any("WARNING      : nothing was masked" in line for line in lines)

    # masked > 0
    r.model_saw = "[[PERSON_1234]] and [[EMAIL_abcd]]"
    assert r.masked == 2
    lines = r.lines()
    assert any("ok           : 2 value(s) masked" in line for line in lines)

    # leaked
    r.leaked = ["secret"]
    lines = r.lines()
    assert any("LEAK         : 1 canary value(s)" in line for line in lines)


def test_run_check_branches() -> None:
    # HTTP Error
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")))
    )
    res = run_check("http://gw.test/v1", "m", client=client)
    assert "could not reach" in (res.error or "")

    # Not the gateway (no request id)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(502)))
    res = run_check("http://gw.test/v1", "m", client=client)
    assert res.error == common.NOT_THE_GATEWAY

    # Not JSON
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, text="not json", headers={"x-pii-guard-request-id": "r1"})
        )
    )
    res = run_check("http://gw.test/v1", "m", client=client)
    assert res.error == "the answer is not JSON"

    # Error payload
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                400,
                json={"error": {"code": "bad", "message": "msg"}},
                headers={"x-pii-guard-request-id": "r1"},
            )
        )
    )
    res = run_check("http://gw.test/v1", "m", client=client)
    assert res.error == "bad msg"

    # Missing echo
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={}, headers={"x-pii-guard-request-id": "r1"})
        )
    )
    res = run_check("http://gw.test/v1", "m", client=client)
    assert "the answer has no pii_guard echo" in (res.error or "")

    # Success run_check with leak check
    success_body = {
        "choices": [{"message": {"content": "Hello user"}}],
        "pii_guard": {
            "masked_messages": [{"content": "masked input"}],
            "masked_answer": [{"content": "masked output"}],
        },
    }
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json=success_body, headers={"x-pii-guard-request-id": "r1"}
            )
        )
    )
    res = run_check("http://gw.test/v1", "m", client=client, values=["masked input", "other"])
    assert res.received == "Hello user"
    assert res.leaked == ["masked input"]
