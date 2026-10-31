"""Remote traffic telemetry ingestion and local-to-remote exporter (LAB-1704).

All values are synthetic (ADR 0005).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.detect.rules import RuleDetector
from pii_guard.gateway.config import Mode
from pii_guard.gateway.detection import ModeDetector
from pii_guard.gateway.service import Gateway
from pii_guard.observability import (
    Observability,
    ObservabilitySettings,
    RemoteTrafficExporter,
    RemoteTrafficLevel,
    TrafficLevel,
    resolve_ingest_url,
    sanitize_for_remote,
)
from pii_guard.policy import PolicySet
from pii_guard.vault import Vault

TEST_TENANT_KEY = "37" * 32
SYNTHETIC_EMAIL = "jane.placeholder@example.com"
SYNTHETIC_KEY = "sk-synthetic-value-0001"
HOSTED_ORIGIN = "https://guard.example"


def _sample_event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": "req_1122334455667788",
        "seq": 99,
        "time": "2026-10-31T12:00:00.000+00:00",
        "route": "/v1/chat/completions",
        "level": "full",
        "outcome": "ok",
        "error": None,
        "mode": "fast",
        "language": "en",
        "stream": False,
        "model": "synthetic-model",
        "session_ref": "abcdef0123456789",
        "session_new": True,
        "session_source": "path",
        "detectors": ["rules"],
        "entities": {
            "detected": {"EMAIL": 1},
            "masked": {"EMAIL": 1},
            "forced_masks": {},
            "texts": 1,
        },
        "outbound_check": {
            "result": "passed",
            "texts": 1,
            "hits": {},
            "short": {},
            "ms": 0.1,
        },
        "cache": {"hits": 0, "misses": 1, "seeded": 1},
        "upstream": {
            "status": 200,
            "model": "synthetic-model",
            "unresolved_placeholders": 0,
        },
        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        "timing": {
            "total_ms": 25.0,
            "upstream_ms": 20.0,
            "overhead_ms": 5.0,
            "ttft_ms": None,
            "upstream_ttft_ms": None,
            "added_ttft_ms": None,
            "stages_ms": {"parse": 0.2, "detect": 1.5, "mask": 0.3, "upstream": 20.0},
            "detectors_ms": {"rules": 1.2},
        },
        "request": {
            "masked": {
                "model": "synthetic-model",
                "messages": [{"role": "user", "content": "Reach [[EMAIL_abc12345]]"}],
            },
            "original": {
                "model": "synthetic-model",
                "messages": [{"role": "user", "content": f"Reach {SYNTHETIC_EMAIL}"}],
            },
            "thumbnails": [{"index": 0, "omitted": "limit"}],
        },
        "response": {
            "masked": {
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Ack [[EMAIL_abc12345]]",
                        },
                    }
                ]
            },
            "chunks": 3,
            "unmasked": {
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"Ack {SYNTHETIC_EMAIL}",
                        },
                    }
                ]
            },
        },
    }
    event.update(overrides)
    return event


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        ("https://guard.watt-mind.com", "https://guard.watt-mind.com/v1/traffic"),
        ("https://guard.watt-mind.com/", "https://guard.watt-mind.com/v1/traffic"),
        ("https://guard.watt-mind.com/v1", "https://guard.watt-mind.com/v1/traffic"),
        ("https://guard.watt-mind.com/v1/traffic", "https://guard.watt-mind.com/v1/traffic"),
        (
            "https://guard.watt-mind.com/e/ep_synthetic_1/v1",
            "https://guard.watt-mind.com/e/ep_synthetic_1/v1/traffic",
        ),
        (
            "http://127.0.0.1:8787/e/ep_synthetic_1",
            "http://127.0.0.1:8787/e/ep_synthetic_1/v1/traffic",
        ),
    ],
)
def test_resolve_ingest_url_normalizes_origins_and_endpoint_paths(
    raw_url: str, expected: str
) -> None:
    assert resolve_ingest_url(raw_url) == expected


@pytest.mark.parametrize("bad_url", ["", "   ", "ftp://guard.example", "not-a-url"])
def test_resolve_ingest_url_rejects_invalid_urls(bad_url: str) -> None:
    with pytest.raises(ValueError, match="remote_url"):
        resolve_ingest_url(bad_url)


def test_sanitize_for_remote_strips_original_unmasked_and_supports_stats_level() -> None:
    event = _sample_event(endpoint={"id": "forged", "name": "Forged"})
    masked = sanitize_for_remote(event, level=RemoteTrafficLevel.MASKED)
    assert masked["level"] == "masked"
    assert "seq" not in masked
    assert "endpoint" not in masked
    assert masked["request"] == {
        "masked": {
            "model": "synthetic-model",
            "messages": [{"role": "user", "content": "Reach [[EMAIL_abc12345]]"}],
        },
        "thumbnails": [{"index": 0, "omitted": "limit"}],
    }
    assert masked["response"] == {
        "masked": {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Ack [[EMAIL_abc12345]]",
                    },
                }
            ]
        },
        "chunks": 3,
    }
    assert SYNTHETIC_EMAIL not in json.dumps(masked)

    stats = sanitize_for_remote(event, level=RemoteTrafficLevel.STATS)
    assert stats["level"] == "masked"
    assert stats["request"] is None
    assert stats["response"] is None
    assert stats["entities"]["masked"] == {"EMAIL": 1}
    assert stats["usage"]["total_tokens"] == 20


def test_exporter_handles_http_errors_transport_failures_and_observability_settings() -> None:
    attempts = 0

    def flaky_remote(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": {"code": "unavailable", "message": "busy"}})
        raise httpx.ConnectError("connection refused")

    obs = Observability(
        ObservabilitySettings(
            traffic_log=TrafficLevel.OFF,
            remote_url="https://guard.example/v1",
            remote_key=SecretStr(SYNTHETIC_KEY),
            remote_level=RemoteTrafficLevel.STATS,
        )
    )
    assert obs.remote is not None
    assert "RemoteTrafficExporter" in repr(obs.remote)
    assert obs.recording is True
    assert obs.payloads is False
    obs.close(timeout=1.0)

    exporter = RemoteTrafficExporter(
        "https://guard.example",
        api_key=SYNTHETIC_KEY,
        level=RemoteTrafficLevel.STATS,
        queue_size=2,
        batch_size=1,
        client=httpx.Client(transport=httpx.MockTransport(flaky_remote)),
    )
    assert exporter.enqueue(_sample_event()) is True
    exporter.flush(timeout=2.0)
    assert exporter.enqueue(_sample_event()) is True
    exporter.close(timeout=2.0)
    assert exporter.failed == 2
    assert exporter.enqueue(_sample_event()) is False


def test_ingest_traffic_accepts_masked_and_stats_and_rejects_unmasked() -> None:
    settings = Settings(
        _env_file=None,
        detectors=("rules",),
        ner_fallback="off",
        tenant_key=TEST_TENANT_KEY,
    )
    app = create_app(
        settings,
        observability=ObservabilitySettings(traffic_log=TrafficLevel.MASKED),
    )
    with TestClient(app) as client:
        # Reject full event or event carrying original/unmasked fields or malformed bodies.
        full_event = _sample_event()
        r_full = client.post("/v1/traffic", json={"events": [full_event]})
        assert r_full.status_code == 422
        assert r_full.json()["error"]["code"] == "invalid_request"

        with_original = sanitize_for_remote(_sample_event())
        with_original["request"]["original"] = {"messages": []}
        assert client.post("/v1/traffic", json=with_original).status_code == 422

        with_unmasked = sanitize_for_remote(_sample_event())
        with_unmasked["response"]["unmasked"] = {"choices": []}
        assert client.post("/v1/traffic", json=with_unmasked).status_code == 422

        assert client.post("/v1/traffic", json={"original": "bad"}).status_code == 422
        assert client.post("/v1/traffic", json={"events": []}).status_code == 422
        assert client.post("/v1/traffic", json=["not-an-object"]).status_code == 422
        assert client.post("/v1/traffic", json={"events": ["not-a-dict"]}).status_code == 422
        assert (
            client.post(
                "/v1/traffic",
                content=b"{bad json",
                headers={"Content-Type": "application/json"},
            ).status_code
            == 422
        )

        assert client.get("/v1/traffic").json()["events"] == []

        # Valid masked event and valid stats-only event (plus minimal defaults event).
        clean_masked = sanitize_for_remote(_sample_event(), level=RemoteTrafficLevel.MASKED)
        clean_stats = sanitize_for_remote(
            _sample_event(id="req_stats_0001"), level=RemoteTrafficLevel.STATS
        )
        clean_stats["level"] = "stats"
        minimal = {"level": "masked"}
        r_ok = client.post("/v1/traffic", json={"events": [clean_masked, clean_stats, minimal]})
        assert r_ok.status_code == 200, r_ok.text
        assert r_ok.json()["accepted"] == 3

        feed = client.get("/v1/traffic").json()
        assert len(feed["events"]) == 3
        first, second, third = feed["events"]
        assert first["seq"] == 1
        assert first["id"] == "req_1122334455667788"
        assert first["request"]["masked"]["messages"][0]["content"] == ("Reach [[EMAIL_abc12345]]")
        assert second["seq"] == 2
        assert second["id"] == "req_stats_0001"
        assert second["request"] is None
        assert second["response"] is None
        assert third["seq"] == 3
        assert third["id"].startswith("req_")
        assert third["route"] == "/v1/chat/completions"
        assert third["outcome"] == "ok"


def test_ingest_traffic_returns_404_when_traffic_log_is_off() -> None:
    settings = Settings(
        _env_file=None,
        detectors=("rules",),
        ner_fallback="off",
        tenant_key=TEST_TENANT_KEY,
    )
    app = create_app(
        settings,
        observability=ObservabilitySettings(traffic_log=TrafficLevel.OFF),
    )
    with TestClient(app) as client:
        clean = sanitize_for_remote(_sample_event())
        res = client.post("/v1/traffic", json={"events": [clean]})
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "traffic_log_disabled"


def test_endpoint_key_can_post_traffic_to_its_endpoint_and_cannot_read_it(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        detectors=("rules",),
        ner_fallback="off",
        tenant_key=TEST_TENANT_KEY,
        project_state_path=str(tmp_path / "state" / "projects.sqlite3"),
    )
    app = create_app(
        settings,
        observability=ObservabilitySettings(traffic_log=TrafficLevel.MASKED),
    )
    with TestClient(app) as client:
        project = client.get("/v1/projects").json()["projects"][0]
        policy = client.get(f"/v1/projects/{project['id']}/policies").json()["policies"][0]
        ep_res = client.post(
            f"/v1/projects/{project['id']}/endpoints",
            json={
                "name": "Local OpenCode",
                "provider": "openai",
                "model": "synthetic-model",
                "api_key": SYNTHETIC_KEY,
                "policy_version_id": policy["policy_version_id"],
            },
        )
        assert ep_res.status_code == 201, ep_res.text
        endpoint = ep_res.json()
        key_res = client.post(
            f"/v1/projects/{project['id']}/endpoints/{endpoint['id']}/keys",
            json={"name": "laptop"},
        )
        assert key_res.status_code == 201
        ep_key = key_res.json()["key"]

        clean = sanitize_for_remote(_sample_event())
        # Endpoint key can POST to its own /e/<id>/v1/traffic route.
        ingest = client.post(
            f"{endpoint['base_path']}/traffic",
            headers={"Authorization": f"Bearer {ep_key}"},
            json={"events": [clean]},
        )
        assert ingest.status_code == 200, ingest.text
        assert ingest.json()["accepted"] == 1

        # Endpoint key cannot GET /e/<id>/v1/traffic or POST /v1/traffic.
        assert (
            client.get(
                f"{endpoint['base_path']}/traffic",
                headers={"Authorization": f"Bearer {ep_key}"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/v1/traffic",
                headers={"Authorization": f"Bearer {ep_key}"},
                json={"events": [clean]},
            ).status_code
            == 403
        )

        # Owner can inspect the endpoint's ingested traffic with endpoint label attached.
        feed = client.get(
            "/v1/traffic",
            headers={
                "X-PII-Guard-Project": project["id"],
                "X-PII-Guard-Endpoint": endpoint["id"],
            },
        )
        assert feed.status_code == 200, feed.text
        events = feed.json()["events"]
        assert len(events) == 1
        assert events[0]["id"] == "req_1122334455667788"
        assert events[0]["endpoint"] == {"id": endpoint["id"], "name": "Local OpenCode"}


def test_hosted_endpoint_traffic_ingest_merges_into_project_logs_without_spending_quota(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        hosted=True,
        hosted_public_origin=HOSTED_ORIGIN,
        hosted_trust_easy_auth=True,
        hosted_single_process=True,
        hosted_images=False,
        tenant_key=TEST_TENANT_KEY,
        allowed_hosts=("guard.example",),
        detectors=("rules",),
        ner_fallback="off",
        upstream_api_key=SYNTHETIC_KEY,
        project_state_path=str(tmp_path / "hosted-projects.sqlite3"),
    )
    app = create_app(settings)
    principal = {"auth_typ": "google", "claims": [{"typ": "sub", "val": "owner-synthetic-1"}]}
    owner_headers = {
        "x-ms-client-principal": base64.b64encode(json.dumps(principal).encode()).decode(),
        "origin": HOSTED_ORIGIN,
    }
    with TestClient(app, base_url=HOSTED_ORIGIN) as client:
        first_run = client.post(
            "/v1/account/first-run",
            headers=owner_headers,
            json={"issue_key": True},
        )
        assert first_run.status_code == 200, first_run.text
        data = first_run.json()
        ep_key = data["key"]["key"]
        endpoint_id = data["endpoint"]["id"]

        before_account = client.get("/v1/account", headers=owner_headers).json()
        used_before = before_account["usage"]["requests_today"]

        clean = sanitize_for_remote(_sample_event())
        ingest = client.post(
            f"/e/{endpoint_id}/v1/traffic",
            headers={"Authorization": f"Bearer {ep_key}"},
            json={"events": [clean]},
        )
        assert ingest.status_code == 200, ingest.text
        assert ingest.json()["accepted"] == 1

        # GET on /e/<id>/v1/traffic is refused in hosted mode too.
        assert (
            client.get(
                f"/e/{endpoint_id}/v1/traffic",
                headers={"Authorization": f"Bearer {ep_key}"},
            ).status_code
            == 403
        )

        # Quota was not charged by telemetry ingestion.
        after_account = client.get("/v1/account", headers=owner_headers).json()
        assert after_account["usage"]["requests_today"] == used_before

        # Project-wide Logs merge the endpoint's ingested event and tag its endpoint.
        merged = client.get("/v1/traffic", headers=owner_headers)
        assert merged.status_code == 200, merged.text
        events = merged.json()["events"]
        assert len(events) == 1
        assert events[0]["id"] == "req_1122334455667788"
        assert events[0]["endpoint"]["id"] == endpoint_id


@pytest.mark.anyio
async def test_local_gateway_exports_scrubbed_telemetry_to_remote_dashboard() -> None:
    remote_settings = Settings(
        _env_file=None,
        detectors=("rules",),
        ner_fallback="off",
        tenant_key=TEST_TENANT_KEY,
        api_token=SYNTHETIC_KEY,
    )
    remote_app = create_app(
        remote_settings,
        observability=ObservabilitySettings(traffic_log=TrafficLevel.MASKED),
    )

    with TestClient(remote_app) as remote_client:

        def forward_to_remote(request: httpx.Request) -> httpx.Response:
            res = remote_client.request(
                request.method,
                request.url.path,
                content=request.content,
                headers=dict(request.headers),
            )
            return httpx.Response(res.status_code, content=res.content, headers=dict(res.headers))

        exporter = RemoteTrafficExporter(
            "http://localhost/v1",
            api_key=SYNTHETIC_KEY,
            level=RemoteTrafficLevel.MASKED,
            client=httpx.Client(transport=httpx.MockTransport(forward_to_remote)),
        )
        # Local gateway has traffic_log=OFF locally, but remote exporter attached!
        local_obs = Observability(
            ObservabilitySettings(traffic_log=TrafficLevel.OFF),
            remote=exporter,
        )

        upstream_seen: list[dict[str, Any]] = []

        def fake_upstream(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            upstream_seen.append(body)
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-synthetic",
                    "object": "chat.completion",
                    "model": "synthetic-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": f"Reply to {body['messages'][-1]['content']}",
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16},
                },
            )

        local_settings = Settings(
            _env_file=None,
            detectors=("rules",),
            ner_fallback="off",
            tenant_key=TEST_TENANT_KEY,
            upstream_base_url="https://models.example.com/v1",
            upstream_api_key="sk-upstream-synthetic",
        )
        pipeline = DetectionPipeline([RuleDetector()])
        gateway = Gateway(
            settings=local_settings,
            vault=Vault.from_settings(local_settings),
            detectors={Mode.FAST: ModeDetector(Mode.FAST, pipeline, "rules", PolicySet())},
            transport=httpx.MockTransport(fake_upstream),
            observability=local_obs,
        )
        try:
            result, _ = await gateway.chat_completions(
                body={
                    "model": "synthetic-model",
                    "messages": [{"role": "user", "content": f"Email {SYNTHETIC_EMAIL}"}],
                },
                headers={},
            )
            local_obs.close(timeout=5.0)
        finally:
            await gateway.aclose()

        # Local client gets the unmasked response back.
        restored = json.loads(bytes(result.body))
        assert restored["choices"][0]["message"]["content"] == f"Reply to Email {SYNTHETIC_EMAIL}"
        # Upstream never saw the raw email.
        assert SYNTHETIC_EMAIL not in json.dumps(upstream_seen)

        # Remote dashboard received the scrubbed masked telemetry event.
        feed = remote_client.get(
            "/v1/traffic",
            headers={"Authorization": f"Bearer {SYNTHETIC_KEY}"},
        )
        assert feed.status_code == 200, feed.text
        events = feed.json()["events"]
        assert len(events) == 1
        ev = events[0]
        assert ev["level"] == "masked"
        assert ev["entities"]["masked"] == {"EMAIL": 1}
        assert SYNTHETIC_EMAIL not in json.dumps(ev)
        assert "[[EMAIL_" in json.dumps(ev["request"]["masked"])
        assert "original" not in ev["request"]
        assert "unmasked" not in (ev["response"] or {})
