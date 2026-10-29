"""Project Logs aggregate the owner's endpoint runtimes (LAB-1492).

A call through ``/e/<endpoint>/v1/...`` is logged in that endpoint's runtime. With no endpoint
selected, ``/v1/traffic`` reads the project runtime plus every endpoint runtime of that
project for the same owner, merged under one owner-wide ``seq``. Selecting an endpoint still
filters to it; vault inspection stays per runtime. Identities, keys and hosts are synthetic
(ADR 0005).
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.hosted.quotas import QuotaLedger, QuotaLimits
from pii_guard.observability import TrafficLevel, TrafficLog
from pii_guard.observability.traffic import TrafficFeed

ORIGIN = "https://guard.example"
PROVIDER_KEY = "synthetic-own-provider-key"
EMAIL = "jane.placeholder@example.com"


def auth(subject: str = "synthetic-one", **extra: str) -> dict[str, str]:
    encoded = base64.b64encode(
        json.dumps({"auth_typ": "google", "claims": [{"typ": "sub", "val": subject}]}).encode()
    ).decode()
    return {"x-ms-client-principal": encoded, "origin": ORIGIN, **extra}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    def echo(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": body["messages"][0]["content"]},
                    }
                ],
            },
        )

    async def public(url: str) -> str:
        return url

    monkeypatch.setattr("pii_guard.api.routes.projects.validate_destination", public)
    monkeypatch.setattr(
        "pii_guard.hosted.runtime.SecureTransport", lambda: httpx.MockTransport(echo)
    )
    monkeypatch.setattr(
        "pii_guard.hosted.egress.SecureTransport", lambda: httpx.MockTransport(echo)
    )
    monkeypatch.setattr(
        "pii_guard.hosted.egress.secure_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(echo), **kwargs),
    )
    app = create_app(
        Settings(
            _env_file=None,
            hosted=True,
            hosted_public_origin=ORIGIN,
            hosted_trust_easy_auth=True,
            hosted_single_process=True,
            tenant_key=bytes(range(32)).hex(),
            allowed_hosts=("guard.example",),
            detectors=("rules",),
            ner_fallback="off",
            upstream_api_key="synthetic-sponsored-key",
        )
    )
    app.state.hosted.quotas = QuotaLedger(
        QuotaLimits(global_daily_microdollars=1_000_000_000),
        sponsored_allocation_microdollars=1_000_000_000,
        allocation_expires_at=time.time() + 3600,
        claim_allocation=lambda: True,
    )
    # These tests make many calls in a burst; the abuse buckets are covered elsewhere.
    monkeypatch.setattr(app.state.hosted.abuse, "admit", lambda *args, **kwargs: None)
    with TestClient(app, base_url=ORIGIN) as test_client:
        yield test_client


def _project(client: TestClient, subject: str = "synthetic-one") -> tuple[str, str]:
    projects = client.get("/v1/projects", headers=auth(subject))
    assert projects.status_code == 200, projects.text
    project = projects.json()["projects"][0]
    return project["id"], project["default_policy_version_id"]


def _endpoint(
    client: TestClient, name: str, subject: str = "synthetic-one", project: str | None = None
) -> tuple[dict[str, Any], str]:
    default, policy = _project(client, subject)
    project = project or default
    if project != default:
        policy = client.get(f"/v1/projects/{project}", headers=auth(subject)).json()[
            "default_policy_version_id"
        ]
    created = client.post(
        f"/v1/projects/{project}/endpoints",
        json={
            "name": name,
            "policy_version_id": policy,
            "provider": "openai",
            "api_key": PROVIDER_KEY,
            "model": "synthetic-model",
        },
        headers=auth(subject),
    )
    assert created.status_code == 201, created.text
    endpoint = created.json()
    issued = client.post(
        f"/v1/projects/{project}/endpoints/{endpoint['id']}/keys",
        json={"name": "Synthetic client"},
        headers=auth(subject),
    )
    assert issued.status_code == 201, issued.text
    return endpoint, str(issued.json()["key"])


def _call(client: TestClient, endpoint: dict[str, Any], key: str) -> str:
    result = client.post(
        endpoint["base_path"] + "/chat/completions",
        json={"messages": [{"role": "user", "content": EMAIL}]},
        headers={"authorization": "Bearer " + key},
    )
    assert result.status_code == 200, result.text
    return str(result.headers["x-pii-guard-request-id"])


def _direct(client: TestClient, subject: str = "synthetic-one") -> str:
    """A console call on the project itself (no endpoint), logged in the project runtime."""
    result = client.post(
        "/v1/chat/completions",
        json={"model": "muse-spark-1.3", "messages": [{"role": "user", "content": EMAIL}]},
        headers=auth(subject),
    )
    assert result.status_code == 200, result.text
    return str(result.headers["x-pii-guard-request-id"])


def _traffic(client: TestClient, subject: str = "synthetic-one", **params: Any) -> dict[str, Any]:
    extra = {}
    if "endpoint" in params:
        extra["x-pii-guard-endpoint"] = params.pop("endpoint")
    if "project" in params:
        extra["x-pii-guard-project"] = params.pop("project")
    page = client.get("/v1/traffic", params=params, headers=auth(subject, **extra))
    assert page.status_code == 200, page.text
    return dict(page.json())


def test_endpoint_key_call_appears_in_project_logs_with_nothing_selected(client):
    endpoint, key = _endpoint(client, "Synthetic CLI")
    request_id = _call(client, endpoint, key)
    events = _traffic(client)["events"]
    assert [e["id"] for e in events] == [request_id]
    assert events[0]["endpoint"] == {"id": endpoint["id"], "name": "Synthetic CLI"}
    assert EMAIL not in json.dumps(events)


def test_aggregate_merges_project_and_endpoints_by_seq_and_tags_each_event(client):
    first, first_key = _endpoint(client, "Synthetic A")
    second, second_key = _endpoint(client, "Synthetic B")
    ids = [
        _call(client, first, first_key),
        _direct(client),
        _call(client, second, second_key),
        _call(client, first, first_key),
    ]
    page = _traffic(client)
    events = page["events"]
    assert [e["id"] for e in events] == ids
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert [(e.get("endpoint") or {}).get("name") for e in events] == [
        "Synthetic A",
        None,
        "Synthetic B",
        "Synthetic A",
    ]
    # One boot for the whole aggregate; the size covers every runtime read.
    assert page["boot"].startswith("b_") and page["size"] >= 50 * 3


def test_selected_endpoint_filters_to_that_endpoint(client):
    first, first_key = _endpoint(client, "Synthetic A")
    second, second_key = _endpoint(client, "Synthetic B")
    a1 = _call(client, first, first_key)
    _call(client, second, second_key)
    _direct(client)
    a2 = _call(client, first, first_key)
    only = _traffic(client, endpoint=first["id"])
    assert [e["id"] for e in only["events"]] == [a1, a2]
    # The same cursor space: a filtered page and the aggregate share boot and seq.
    assert only["boot"] == _traffic(client)["boot"]
    after = _traffic(client, endpoint=first["id"], after=only["events"][0]["seq"])
    assert [e["id"] for e in after["events"]] == [a2]


def test_cursor_pages_have_no_duplicates_or_gaps_across_runtimes(client):
    first, first_key = _endpoint(client, "Synthetic A")
    second, second_key = _endpoint(client, "Synthetic B")
    calls = [(first, first_key), (second, second_key), (None, None)]
    expected: list[str] = []
    seen: list[str] = []
    cursor = 0
    for round_ in range(4):
        for endpoint, key in calls[round_ % 3 :] + calls[: round_ % 3]:
            expected.append(_direct(client) if endpoint is None else _call(client, endpoint, key))
        page = _traffic(client, after=cursor, limit=200)
        seen.extend(e["id"] for e in page["events"])
        if page["events"]:
            cursor = page["events"][-1]["seq"]
        assert _traffic(client, after=cursor)["events"] == []
    assert seen == expected
    # A small `limit` keeps the newest events of the merged view.
    assert [e["id"] for e in _traffic(client, limit=2)["events"]] == expected[-2:]


def test_another_project_and_another_owner_are_never_aggregated(client):
    own, own_key = _endpoint(client, "Synthetic own")
    other_project = client.post(
        "/v1/projects", json={"name": "Synthetic second"}, headers=auth()
    ).json()["id"]
    elsewhere, elsewhere_key = _endpoint(client, "Synthetic elsewhere", project=other_project)
    foreign, foreign_key = _endpoint(client, "Synthetic foreign", subject="synthetic-two")
    mine = _call(client, own, own_key)
    second = _call(client, elsewhere, elsewhere_key)
    theirs = _call(client, foreign, foreign_key)
    assert [e["id"] for e in _traffic(client)["events"]] == [mine]
    assert [e["id"] for e in _traffic(client, project=other_project)["events"]] == [second]
    assert [e["id"] for e in _traffic(client, "synthetic-two")["events"]] == [theirs]
    # Selecting another owner's endpoint is refused, not read.
    denied = client.get("/v1/traffic", headers=auth(**{"x-pii-guard-endpoint": foreign["id"]}))
    assert denied.status_code in (403, 404), denied.text
    assert theirs not in denied.text
    service = client.app.state.hosted
    feeds = service._feeds
    assert len(feeds) == 2
    for owner, feed in feeds.items():
        assert all(source.split(":", 1)[0] == owner for source in feed.sources())


def test_vault_inspection_is_not_aggregated(client):
    endpoint, key = _endpoint(client, "Synthetic A")
    _call(client, endpoint, key)
    assert client.get("/v1/vault/sessions", headers=auth()).json()["sessions"] == []
    scoped = client.get(
        "/v1/vault/sessions", headers=auth(**{"x-pii-guard-endpoint": endpoint["id"]})
    )
    assert len(scoped.json()["sessions"]) == 1


# --- The shared sequence itself -------------------------------------------------------------


def _event(n: int) -> dict[str, Any]:
    return {"id": f"r_{n}", "mode": "fast", "outcome": "ok", "timing": {}}


def test_feed_concurrent_publish_and_poll_never_skips_or_repeats() -> None:
    feed = TrafficFeed()
    logs = [
        TrafficLog(TrafficLevel.MASKED, 10_000, feed=feed, source=f"owner:p:e{i}") for i in range(4)
    ]
    total = 4 * 400
    stop = threading.Event()
    seen: list[int] = []

    def writer(log: TrafficLog, start: int) -> None:
        for n in range(start, start + 400):
            log.publish(_event(n))
            if n % 17 == 0:  # yield now and then, so the writers interleave
                time.sleep(0)

    def poller() -> None:
        cursor = 0
        while True:
            done = stop.is_set()
            for event in feed.recent(lambda _s: True, after=cursor):
                assert event["seq"] > cursor
                cursor = event["seq"]
                seen.append(event["seq"])
            if done:
                return

    reader = threading.Thread(target=poller)
    reader.start()
    writers = [threading.Thread(target=writer, args=(log, i * 400)) for i, log in enumerate(logs)]
    for thread in writers:
        thread.start()
    for thread in writers:
        thread.join()
    stop.set()
    reader.join()
    assert seen == list(range(1, total + 1))
    assert {log.boot for log in logs} == {feed.boot}


def test_feed_subscription_sees_only_its_sources() -> None:
    feed = TrafficFeed()
    project = TrafficLog(TrafficLevel.MASKED, 10, feed=feed, source="o")
    endpoint = TrafficLog(TrafficLevel.MASKED, 10, feed=feed, source="o:p:e")
    endpoint.labels = {"endpoint": {"id": "e", "name": "Synthetic"}}
    other = TrafficLog(TrafficLevel.MASKED, 10, feed=feed, source="o:q:e")

    async def run() -> list[dict[str, Any]]:
        async with feed.subscribe(lambda s: s == "o" or s.startswith("o:p:")) as queue:
            for log in (project, other, endpoint):
                log.publish(_event(len(feed.sources())))
            await asyncio.sleep(0)
            return [queue.get_nowait() for _ in range(queue.qsize())]

    got = asyncio.run(run())
    assert [e["seq"] for e in got] == [1, 3]
    assert got[1]["endpoint"] == {"id": "e", "name": "Synthetic"}
    feed.detach("o:p:e")
    assert feed.sources() == ["o", "o:q:e"]


def test_a_log_without_a_feed_keeps_its_own_sequence() -> None:
    log = TrafficLog(TrafficLevel.MASKED, 10)
    assert [log.publish(_event(n))["seq"] for n in range(3)] == [1, 2, 3]
    assert "endpoint" not in log.recent()[0]
