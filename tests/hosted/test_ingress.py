"""Hosted ingress slots (LAB-1442): slow or unauthenticated clients cannot hold them.

The 32 ingress slots used to be taken before identity and kept through a ten-second body
read, so 32 slow anonymous uploads answered every signed-in user with 429. Slots are now
taken only after identity, path, origin and abuse checks, from separate guest and
signed-in pools with a per-principal share, and one deadline bounds the whole body read.
All identities, keys and addresses are synthetic.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import threading
from typing import Any

import httpx

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.hosted import runtime as hosted_runtime
from pii_guard.hosted.abuse import AbuseAdmission, AbuseAdmissionError

ORIGIN = "https://guard.example"
EMAIL = "synthetic.one@example.com"


def settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        **{
            "hosted": True,
            "hosted_public_origin": ORIGIN,
            "hosted_trust_easy_auth": True,
            "hosted_single_process": True,
            "tenant_key": bytes(range(32)).hex(),
            "allowed_hosts": ("guard.example",),
            "detectors": ("rules",),
            "ner_fallback": "off",
            **overrides,
        },
    )


def principal_header(subject: str) -> bytes:
    return base64.b64encode(
        json.dumps({"auth_typ": "google", "claims": [{"typ": "sub", "val": subject}]}).encode()
    )


def auth(subject: str = "synthetic-signed-in") -> dict[str, str]:
    return {"x-ms-client-principal": principal_header(subject).decode(), "origin": ORIGIN}


def raw_scope(
    path: str, *, method: str = "POST", headers: list[tuple[bytes, bytes]] | None = None
) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"guard.example"),
            (b"content-type", b"application/json"),
            *(headers if headers is not None else [(b"origin", ORIGIN.encode())]),
        ],
        "server": ("guard.example", 443),
        "client": ("192.0.2.10", 40000),
    }


def signed_in(subject: str) -> list[tuple[bytes, bytes]]:
    return [(b"origin", ORIGIN.encode()), (b"x-ms-client-principal", principal_header(subject))]


class SlowClient:
    """An ASGI client that opens a request and trickles (or never sends) its body."""

    def __init__(self, app: Any, scope: dict[str, Any], *, trickle: float | None = None):
        self.app, self.scope, self.trickle = app, scope, trickle
        self.reading = asyncio.Event()
        self.messages: list[dict[str, Any]] = []

    async def receive(self) -> dict[str, Any]:
        self.reading.set()
        if self.trickle is None:
            await asyncio.Event().wait()
        await asyncio.sleep(self.trickle)
        return {"type": "http.request", "body": b" ", "more_body": True}

    async def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    async def run(self) -> None:
        await self.app(self.scope, self.receive, self.send)

    def status(self) -> int | None:
        return next(
            (m["status"] for m in self.messages if m["type"] == "http.response.start"), None
        )

    def code(self) -> str | None:
        body = b"".join(
            m.get("body", b"") for m in self.messages if m["type"] == "http.response.body"
        )
        return json.loads(body)["error"]["code"] if body else None


def build(monkeypatch: Any, **overrides: Any) -> Any:
    monkeypatch.setattr(
        "pii_guard.hosted.runtime.SecureTransport",
        lambda: httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    app = create_app(settings(**overrides))
    counter = itertools.count(100)
    # A clock that advances a second per call, so no abuse bucket empties in these tests.
    app.state.hosted.abuse = AbuseAdmission(clock=lambda: float(next(counter)))
    return app


async def park(clients: list[SlowClient]) -> list[asyncio.Task[None]]:
    """Start every slow client and wait until each is either reading or answered."""
    tasks = [asyncio.create_task(client.run()) for client in clients]
    for client, task in zip(clients, tasks, strict=True):
        reading = asyncio.create_task(client.reading.wait())
        await asyncio.wait({reading, task}, timeout=2, return_when=asyncio.FIRST_COMPLETED)
        reading.cancel()
    return tasks


async def stop(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def mask(app: Any, subject: str = "synthetic-signed-in") -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as c:
        return await c.post("/v1/mask", json={"text": EMAIL}, headers=auth(subject))


def test_slow_anonymous_uploads_cannot_lock_out_a_signed_in_user(monkeypatch: Any) -> None:
    # The reproduction: 32 cookieless clients open a demo or account POST and never finish
    # the body. They used to hold all 32 slots, so the signed-in mask below got 429.
    app = build(monkeypatch)
    service = app.state.hosted

    async def scenario() -> None:
        guests = [
            SlowClient(app, raw_scope("/v1/demo" if i % 2 else "/v1/account")) for i in range(32)
        ]
        tasks = await park(guests)
        try:
            reading = [g for g in guests if g.reading.is_set()]
            refused = [g for g in guests if g.status() is not None]
            # Guests draw only on their own pool; the rest are refused without a body read.
            assert len(reading) == hosted_runtime.GUEST_INGRESS_SLOTS
            assert len(refused) == 32 - hosted_runtime.GUEST_INGRESS_SLOTS
            assert {(g.status(), g.code()) for g in refused} == {(429, "hosted_capacity")}
            assert service._guest_ingress == hosted_runtime.GUEST_INGRESS_SLOTS
            for index in range(3):
                response = await mask(app, f"synthetic-signed-in-{index}")
                assert response.status_code == 200, response.text
        finally:
            await stop(tasks)
        assert service._ingress == service._guest_ingress == 0
        assert service._ingress_held == {}
        await service.close()

    asyncio.run(scenario())


def test_requests_refused_before_identity_or_admission_take_no_slot(monkeypatch: Any) -> None:
    app = build(monkeypatch)
    service = app.state.hosted
    taken: list[Any] = []
    enter = service.enter_ingress
    monkeypatch.setattr(service, "enter_ingress", lambda p: (taken.append(p), enter(p)))
    cases = [
        # Invalid guard key, wrong scheme, guest on a signed-in route, cross-site POST,
        # a route hosted mode does not serve, and a signed-in user over abuse admission.
        (raw_scope("/v1/mask", headers=[(b"authorization", b"Bearer pg_synthetic_bad")]), 401),
        (raw_scope("/v1/mask", headers=[(b"authorization", b"Basic synthetic")]), 401),
        (raw_scope("/v1/mask"), 401),
        (raw_scope("/v1/demo", headers=[(b"origin", b"https://elsewhere.example")]), 403),
        (raw_scope("/v1/projects/../admin", headers=signed_in("synthetic-a")), 403),
    ]

    async def scenario() -> None:
        clients = [SlowClient(app, case) for case, _ in cases]
        tasks = await park(clients)
        try:
            for client, (_, expected) in zip(clients, cases, strict=True):
                assert client.status() == expected, client.messages
                assert not client.reading.is_set()
            # Abuse admission is checked before the slot too.
            monkeypatch.setattr(service.abuse, "admit", _refuse)
            refused = SlowClient(app, raw_scope("/v1/mask", headers=signed_in("synthetic-b")))
            await asyncio.wait_for(refused.run(), 2)
            assert refused.status() == 429 and not refused.reading.is_set()
        finally:
            await stop(tasks)
        assert taken == []
        assert service._ingress == 0
        await service.close()

    asyncio.run(scenario())


def _refuse(*args: Any, **kwargs: Any) -> None:
    raise AbuseAdmissionError(1)


def test_one_principal_cannot_hold_every_signed_in_slot(monkeypatch: Any) -> None:
    app = build(monkeypatch)
    service = app.state.hosted
    share = hosted_runtime.INGRESS_PER_PRINCIPAL

    async def scenario() -> None:
        hogs = [
            SlowClient(app, raw_scope("/v1/mask", headers=signed_in("synthetic-hog")))
            for _ in range(share + 4)
        ]
        tasks = await park(hogs)
        try:
            assert sum(h.reading.is_set() for h in hogs) == share
            refused = [h for h in hogs if h.status() is not None]
            assert {(h.status(), h.code()) for h in refused} == {(429, "hosted_capacity")}
            assert len(refused) == 4
            response = await mask(app, "synthetic-other")
            assert response.status_code == 200, response.text
        finally:
            await stop(tasks)
        assert service._ingress == 0 and service._ingress_held == {}
        await service.close()

    asyncio.run(scenario())


def test_signed_in_pool_still_bounds_many_slow_principals(monkeypatch: Any) -> None:
    # The global signed-in bound stays: 32 principals each with one slow upload fill it,
    # and a guest demo is still served from its own pool.
    app = build(monkeypatch)
    service = app.state.hosted

    async def scenario() -> None:
        slow = [
            SlowClient(app, raw_scope("/v1/mask", headers=signed_in(f"synthetic-slow-{i}")))
            for i in range(hosted_runtime.INGRESS_SLOTS)
        ]
        tasks = await park(slow)
        try:
            assert all(s.reading.is_set() for s in slow)
            response = await mask(app, "synthetic-late")
            assert response.status_code == 429
            assert response.json()["error"]["code"] == "hosted_capacity"
            assert service._guest_ingress == 0
            guest = SlowClient(app, raw_scope("/v1/demo"))
            guest_task = await park([guest])
            assert guest.reading.is_set()
            await stop(guest_task)
        finally:
            await stop(tasks)
        assert service._ingress == 0 and service._ingress_held == {}
        await service.close()

    asyncio.run(scenario())


def test_trickled_body_times_out_at_the_deadline_and_frees_its_slot(monkeypatch: Any) -> None:
    # Slow-loris: a byte every 50 ms keeps each read alive, but one deadline bounds the
    # whole body, however it is trickled.
    app = build(monkeypatch, hosted_request_timeout=0.4)
    service = app.state.hosted

    async def scenario() -> None:
        clients = [
            SlowClient(app, raw_scope("/v1/demo"), trickle=0.05),
            SlowClient(app, raw_scope("/v1/mask", headers=signed_in("synthetic-a")), trickle=0.05),
        ]
        started = asyncio.get_running_loop().time()
        await asyncio.wait_for(asyncio.gather(*(c.run() for c in clients)), 3)
        assert asyncio.get_running_loop().time() - started < 2
        for client in clients:
            assert (client.status(), client.code()) == (504, "hosted_timeout")
        assert service._ingress == service._guest_ingress == 0
        assert service._ingress_held == {}
        assert service.quotas._requests == 0
        await service.close()

    asyncio.run(scenario())


def test_endpoint_key_lookup_has_its_own_small_bound(monkeypatch: Any) -> None:
    # Resolving an endpoint key is the one await before identity is known. It holds no
    # ingress slot and has its own bound, released whatever the lookup returns.
    app = build(monkeypatch)
    service = app.state.hosted
    gate = threading.Event()

    def slow_lookup(key: str, endpoint: str) -> None:
        gate.wait(5)
        return None

    monkeypatch.setattr(service.projects.store, "resolve_key", slow_lookup)
    headers = [(b"authorization", b"Bearer pg_ep_synthetic")]

    async def scenario() -> None:
        lookups = [
            SlowClient(app, raw_scope("/e/synthetic/v1/chat/completions", headers=headers))
            for _ in range(hosted_runtime.PREAUTH_SLOTS)
        ]
        tasks = [asyncio.create_task(c.run()) for c in lookups]
        for _ in range(100):
            if service._preauth == hosted_runtime.PREAUTH_SLOTS:
                break
            await asyncio.sleep(0.01)
        assert service._preauth == hosted_runtime.PREAUTH_SLOTS
        extra = SlowClient(app, raw_scope("/e/synthetic/v1/chat/completions", headers=headers))
        await asyncio.wait_for(extra.run(), 2)
        assert (extra.status(), extra.code()) == (429, "hosted_capacity")
        # Signed-in work is untouched by a full lookup pool.
        response = await mask(app)
        assert response.status_code == 200, response.text
        gate.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
        assert {c.status() for c in lookups} == {401}
        assert service._preauth == service._ingress == 0
        await service.close()

    asyncio.run(scenario())
