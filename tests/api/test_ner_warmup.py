"""The NER model loads in the background at startup; detecting requests wait for it (LAB-1303).

Without ``PII_GUARD_NER_MODEL`` the resolved NER loads (and on a cold cache downloads) after the
server starts answering. ``/healthz`` and ``/v1/status`` say ``loading``; detecting requests
wait, bounded, and fail closed only if it is still loading after the wait or failed to load.
A fake load (an event the test releases): no torch, no weights. All text is fictional.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from api_helpers import TEST_TENANT_KEY
from fastapi.testclient import TestClient

from pii_guard.api.app import (
    DETECTING_PATHS,
    HOSTED_DETECTING_PATHS,
    RETRY_AFTER_SECONDS,
    create_app,
)
from pii_guard.app_bundle import Status, create_bundle_app
from pii_guard.config import Settings
from pii_guard.detect import stack
from pii_guard.detect.stack import NerWarmup
from pii_guard.types import DetectionError, EntityType, Span

TEXT = "Teszt Elek"
#: POST routes that never run a detector, so never wait for the model.
NON_DETECTING_POSTS = frozenset(
    {
        "/v1/unmask",
        "/v1/sessions",
        "/v1/sessions/{session_id}/known-values",
        "/v1/projects",
        "/v1/projects/{project_id}/policies",
        "/v1/projects/{project_id}/endpoints",
        "/v1/projects/{project_id}/endpoints/models",
        "/v1/projects/{project_id}/endpoints/{endpoint_id}/keys",
    }
)
#: POST routes hosted mode adds (``pii_guard.hosted.routes``) that never run a detector.
HOSTED_NON_DETECTING_POSTS = frozenset(
    {
        "/v1/account/api-keys",
        "/v1/account/connections",
        "/v1/account/first-run",
    }
)


class FakeAnalyzer:
    def analyze(self, text: str, language: str) -> list[Span]:
        return [Span(0, len(text), EntityType.PERSON, text, 0.9, "ner")]


class FakeLoad:
    """Stands in for loading the NER model: blocks until released, or fails."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.calls = 0
        self.error: Exception | None = None

    def __call__(self, settings: Settings) -> None:
        self.calls += 1
        if not self.release.wait(10):
            raise AssertionError("the test never released the fake load")
        if self.error is not None:
            raise self.error


@pytest.fixture
def load(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeLoad]:
    fake = FakeLoad()
    monkeypatch.setattr(stack, "_load_ner", fake)
    monkeypatch.setattr(stack, "ner_in_stack", lambda settings: True)
    yield fake
    fake.release.set()  # never leave the warm-up thread waiting


def _app(**overrides: Any) -> Any:
    settings = Settings(tenant_key=TEST_TENANT_KEY, detectors=("rules",), **overrides)
    app = create_app(settings)
    app.state.analyzer = FakeAnalyzer()
    return app


def _wait_for(predicate: Any, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_server_answers_while_the_model_loads_and_reports_loading(load: FakeLoad) -> None:
    app = _app()
    with TestClient(app) as client:
        started = time.monotonic()
        health = client.get("/healthz")
        status = client.get("/v1/status").json()
        assert time.monotonic() - started < 2  # not blocked by the load
        assert health.status_code == 200
        assert health.json()["status"] == "ok"  # liveness: the UI needs "ok"
        assert health.json()["ner"] == "loading"
        assert status["ner"]["state"] == "loading"
        assert status["ner"]["error"] is None
        load.release.set()
        _wait_for(lambda: app.state.ner_warmup.state == "ready")
        assert client.get("/healthz").json()["ner"] == "ready"
        assert client.get("/v1/status").json()["ner"]["state"] == "ready"
    assert load.calls == 1


def test_detecting_requests_wait_for_the_load_then_succeed(load: FakeLoad) -> None:
    app = _app()
    with TestClient(app) as client, ThreadPoolExecutor(4) as pool:
        futures = [
            pool.submit(client.post, "/v1/analyze", json={"text": TEXT, "language": "hu"})
            for _ in range(4)
        ]
        time.sleep(0.3)
        assert not any(f.done() for f in futures)  # waiting, not refused
        # The event loop is free while they wait.
        assert client.get("/healthz").json()["ner"] == "loading"
        load.release.set()
        responses = [f.result(timeout=10) for f in futures]
    assert [r.status_code for r in responses] == [200] * 4
    assert all(r.json()["spans"][0]["entity_type"] == "PERSON" for r in responses)
    assert load.calls == 1


def test_still_loading_after_the_timeout_is_503_detector_loading(load: FakeLoad) -> None:
    app = _app(ner_warmup_timeout=0.2)
    with TestClient(app) as client:
        started = time.monotonic()
        r = client.post("/v1/analyze", json={"text": TEXT, "language": "hu"})
        assert 0.2 <= time.monotonic() - started < 3
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "detector_loading"
        assert "still loading" in r.json()["error"]["message"]
        assert r.headers["Retry-After"] == str(RETRY_AFTER_SECONDS)
        # The gateway, also through a session path, refuses the same way: nothing is sent.
        for path in ("/v1/chat/completions", "/s/demo/v1/chat/completions", "/v1/responses"):
            g = client.post(path, json={"model": "m", "messages": []})
            assert g.status_code == 503, path
            assert g.json()["error"]["code"] == "detector_loading", path


def test_a_failed_load_fails_closed_with_detection_unavailable(load: FakeLoad) -> None:
    load.error = DetectionError("ner model download failed (ConnectionError)")
    app = _app()
    with TestClient(app) as client:
        load.release.set()
        _wait_for(lambda: app.state.ner_warmup.state == "failed")
        r = client.post("/v1/mask", json={"text": TEXT, "language": "hu"})
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "detection_unavailable"
        assert r.json()["error"]["message"] == (
            "ner model unavailable: ner model download failed (ConnectionError)"
        )
        assert "Retry-After" not in r.headers
        health = client.get("/healthz").json()
        assert health["status"] == "ok" and health["ner"] == "failed"
        assert health["ocr"] in ("on", "off") and "image_require_ocr" in health
        status = client.get("/v1/status").json()["ner"]
        assert status["state"] == "failed"
        assert status["error"] == "ner model download failed (ConnectionError)"


def test_an_unexpected_load_error_reports_its_type_only(load: FakeLoad) -> None:
    load.error = OSError("/fictional/path/model.safetensors: secret detail")
    app = _app()
    with TestClient(app) as client:
        load.release.set()
        _wait_for(lambda: app.state.ner_warmup.state == "failed")
        error = client.get("/v1/status").json()["ner"]["error"]
        assert error == "ner model could not be loaded (OSError)"


def test_non_detecting_routes_never_wait(load: FakeLoad) -> None:
    app = _app(ner_warmup_timeout=30)
    with TestClient(app) as client:
        started = time.monotonic()
        assert client.get("/v1/status").status_code == 200
        assert client.post("/v1/sessions", json={}).status_code == 201
        assert client.post("/v1/unmask", json={"text": "x", "session_id": "nope"}).status_code in (
            404,
            422,
        )
        assert time.monotonic() - started < 5


def test_every_post_route_is_classified() -> None:
    """A new POST route must say whether it detects (and so waits for a loading model)."""
    app = create_app(Settings(tenant_key=TEST_TENANT_KEY, detectors=("rules",)))
    posts = {path for path, ops in app.openapi()["paths"].items() if "post" in ops}
    assert posts == DETECTING_PATHS | NON_DETECTING_POSTS


def test_every_hosted_post_route_is_classified(tmp_path: Any) -> None:
    """Hosted mode adds its own POST routes; each must detect (and wait) or be listed (LAB-1601)."""
    app = _hosted_app(tmp_path)
    posts = {path for path, ops in app.openapi()["paths"].items() if "post" in ops}
    detecting = DETECTING_PATHS | HOSTED_DETECTING_PATHS
    assert detecting.isdisjoint(NON_DETECTING_POSTS | HOSTED_NON_DETECTING_POSTS)
    assert posts == detecting | NON_DETECTING_POSTS | HOSTED_NON_DETECTING_POSTS


def test_no_ner_in_the_stack_means_no_warm_up(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Settings] = []
    monkeypatch.setattr(stack, "_load_ner", calls.append)
    app = _app()  # rules only: the test environment has no cached NER model
    with TestClient(app) as client:
        assert client.get("/healthz").json()["ner"] == "off"
        r = client.post("/v1/analyze", json={"text": TEXT, "language": "hu"})
        assert r.status_code == 200
    assert calls == []


def test_a_configured_model_loads_before_serving(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[bool] = []
    monkeypatch.setattr(stack, "warm_up", lambda settings: True)
    monkeypatch.setattr(NerWarmup, "start", lambda self: started.append(True) or True)
    app = _app()
    with TestClient(app) as client:
        assert client.get("/healthz").json()["ner"] == "ready"
    assert started == []  # no background load on top of the LAB-1274 warm-up


def test_warmup_object_states(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stack, "ner_in_stack", lambda settings: False)
    warmup = NerWarmup(Settings())
    assert warmup.start() is False
    assert warmup.state == "off" and not warmup.pending
    warmup.wait(0.01)  # off: never raises

    monkeypatch.setattr(stack, "ner_in_stack", lambda settings: True)
    release = threading.Event()
    monkeypatch.setattr(stack, "_load_ner", lambda settings: release.wait(5))
    warmup = NerWarmup(Settings())
    assert warmup.start() is True
    assert warmup.start() is False  # once
    assert warmup.pending
    with pytest.raises(stack.DetectorLoadingError, match=r"still loading after waiting 0\.05s"):
        warmup.wait(0.05)
    release.set()
    warmup.wait(5)
    assert warmup.state == "ready" and warmup.seconds is not None


# --- Hosted: the bundled model (PII_GUARD_NER_MODEL) loads in the background (LAB-1548) -------

ORIGIN = "https://guard.example"
LANDING = "<!doctype html><title>PII Guard</title><p>Fictional landing page</p>"


def _signed_in() -> dict[str, str]:
    principal = {"auth_typ": "google", "claims": [{"typ": "sub", "val": "synthetic-one"}]}
    encoded = base64.b64encode(json.dumps(principal).encode()).decode()
    return {"x-ms-client-principal": encoded, "origin": ORIGIN}


def _hosted_app(tmp_path: Any, **overrides: Any) -> Any:
    """The hosted layout (deploy/azure/entrypoint.py): bundled UI, explicit local NER model."""
    settings = Settings(
        _env_file=None,
        **{
            "hosted": True,
            "hosted_public_origin": ORIGIN,
            "hosted_trust_easy_auth": True,
            "hosted_single_process": True,
            "hosted_images": False,
            "tenant_key": TEST_TENANT_KEY,
            "allowed_hosts": ("guard.example",),
            "detectors": ("rules",),
            "ner_fallback": "off",
            "ner_model": "./models/fictional-ner",
            "upstream_api_key": "synthetic-sponsored-key",
            **overrides,
        },
    )
    (tmp_path / "index.html").write_text(LANDING, encoding="utf-8")
    app = create_bundle_app(Status(upstream="mock"), settings, ui_dir=tmp_path)
    app.state.analyzer = FakeAnalyzer()
    return app


@pytest.fixture
def no_blocking_warm_up(monkeypatch: pytest.MonkeyPatch) -> None:
    def warm_up(settings: Settings) -> bool:
        raise AssertionError("hosted must not load the model before serving")

    monkeypatch.setattr(stack, "warm_up", warm_up)


@pytest.mark.usefixtures("no_blocking_warm_up")
def test_hosted_serves_the_landing_page_while_the_configured_model_loads(
    load: FakeLoad, tmp_path: Any
) -> None:
    app = _hosted_app(tmp_path, ner_warmup_timeout=0.2)
    with TestClient(app, base_url=ORIGIN) as client:
        started = time.monotonic()
        landing = client.get("/")
        health = client.get("/healthz")
        assert time.monotonic() - started < 2  # not blocked by the load
        assert landing.status_code == 200
        assert "Fictional landing page" in landing.text
        assert health.json()["status"] == "ok"
        assert health.json()["ner"] == "loading"
        assert client.get("/v1/status", headers=_signed_in()).json()["ner"]["state"] == "loading"
        # Full readiness (deploy smoke) still refuses; serving readiness (the platform's
        # Readiness probe) admits the replica so the landing page reaches the visitor.
        full = client.get("/readyz")
        assert full.status_code == 503
        assert full.json()["error"]["code"] == "detector_loading"
        assert client.get("/readyz/serving").json() == {"status": "ready"}
        # Detecting requests still fail closed: nothing ran, nothing was sent.
        r = client.post("/v1/analyze", json={"text": TEXT, "language": "hu"}, headers=_signed_in())
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "detector_loading"
        assert r.headers["Retry-After"] == str(RETRY_AFTER_SECONDS)
        load.release.set()
        _wait_for(lambda: app.state.ner_warmup.state == "ready")
        assert client.get("/readyz").json() == {"status": "ready"}
        assert client.get("/healthz").json()["ner"] == "ready"
    assert load.calls == 1


@pytest.mark.usefixtures("no_blocking_warm_up")
def test_hosted_failed_load_keeps_the_landing_page_and_fails_detection_closed(
    load: FakeLoad, tmp_path: Any
) -> None:
    load.error = OSError("/app/models/ner/model.safetensors: fictional detail")
    app = _hosted_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        load.release.set()
        _wait_for(lambda: app.state.ner_warmup.state == "failed")
        assert client.get("/").status_code == 200
        assert client.get("/healthz").json()["ner"] == "failed"
        # Neither readiness admits a replica whose model failed to load.
        for path in ("/readyz", "/readyz/serving"):
            ready = client.get(path)
            assert ready.status_code == 503
            # A failed load is unavailable, not loading: retrying will not help.
            assert ready.json()["error"]["code"] == "detection_unavailable"
            assert "fictional detail" not in ready.text
        r = client.post("/v1/mask", json={"text": TEXT, "language": "hu"}, headers=_signed_in())
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "detection_unavailable"
        assert "fictional detail" not in r.text  # the exception type only (ADR 0006)


def test_hosted_serving_readiness_passes_once_the_model_is_ready(
    load: FakeLoad, tmp_path: Any
) -> None:
    load.release.set()
    app = _hosted_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        _wait_for(lambda: app.state.ner_warmup.state == "ready")
        assert client.get("/readyz").json() == {"status": "ready"}
        assert client.get("/readyz/serving").json() == {"status": "ready"}
