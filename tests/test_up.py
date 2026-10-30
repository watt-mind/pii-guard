"""``pii-guard up``: one app with the API, the gateway and the bundled UI (LAB-1276).

Fictional data only (ADR 0005). The wheel itself is smoke-tested by scripts/ci/wheel_smoke.sh.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from pii_guard import DISTRIBUTION, __version__
from pii_guard.app_bundle import (
    MockServer,
    Status,
    UpOptions,
    _banner,
    active_detectors,
    create_bundle_app,
    image_gaps,
    launcher,
    run_up,
    ui_available,
)
from pii_guard.cli import build_parser
from pii_guard.config import Settings

TENANT_KEY = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"
EMAIL = "teszt.elek@example.com"
INDEX = '<!doctype html><html><head><title>pii-guard</title></head><body><div id="root"></div>'
INDEX += '<script type="module" src="/assets/app.js"></script></body></html>'


@pytest.fixture
def ui_dir(tmp_path: Path) -> Path:
    ui = tmp_path / "_ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text(INDEX, encoding="utf-8")
    (ui / "assets" / "app.js").write_text("console.log('ui')", encoding="utf-8")
    return ui


@pytest.fixture
def mock() -> Iterator[MockServer]:
    server = MockServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()


def _client(ui: Path, status: Status | None = None, **settings: object) -> TestClient:
    status = status or Status(upstream="mock", detectors=["rules"])
    app = create_bundle_app(status, Settings(tenant_key=TENANT_KEY, **settings), ui_dir=ui)  # type: ignore[arg-type]
    return TestClient(app)


def test_ui_served_at_root_without_a_status_strip(ui_dir: Path) -> None:
    client = _client(ui_dir)
    page = client.get("/")
    assert page.status_code == 200
    assert '<div id="root">' in page.text
    # The console reads /v1/status itself: a strip would repeat it (and "Demo mode" is the
    # console's word for its in-browser engine).
    assert "pii-guard-up-status" not in page.text
    assert "Demo mode" not in page.text
    assert "detectors:" not in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert client.get("/assets/app.js").text == "console.log('ui')"
    assert client.get("/healthz").json() == {"status": "ok", "version": __version__, "ner": "off"}


def test_ui_index_is_served_byte_for_byte(ui_dir: Path) -> None:
    client = _client(ui_dir)
    for path in ("/", "/index.html", "/traffic"):
        assert client.get(path).text == INDEX


def test_hashed_assets_are_immutable_and_gzipped_once(ui_dir: Path) -> None:
    # The Evaluation screen's benchmark index ships as hashed JSON parts (LAB-1454).
    body = json.dumps({"runs": [{"run_id": f"run-{i}", "date": "2026-10-28"} for i in range(200)]})
    (ui_dir / "assets" / "benchmarks-runs-abc123.json").write_text(body, encoding="utf-8")
    client = _client(ui_dir)
    url = "/assets/benchmarks-runs-abc123.json"
    first = client.get(url, headers={"Accept-Encoding": "gzip, br"})
    assert first.status_code == 200
    assert first.headers["content-encoding"] == "gzip"
    assert first.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert first.headers["vary"] == "Accept-Encoding"
    assert first.headers["content-type"].startswith("application/json")
    assert int(first.headers["content-length"]) < len(body) / 5
    assert first.text == body  # httpx decodes it
    again = client.get(url, headers={"Accept-Encoding": "gzip"})
    assert again.content == first.content
    plain = client.get(url, headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers
    assert plain.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert plain.text == body
    refused = client.get(url, headers={"Accept-Encoding": "gzip;q=0"})
    assert "content-encoding" not in refused.headers
    # Small files are not worth it; the page itself is never cached.
    small = client.get("/assets/app.js", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in small.headers
    assert small.headers["cache-control"] == "public, max-age=31536000, immutable"
    page = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert page.headers["cache-control"] == "no-cache"


def test_no_ui_page_says_mock_upstream_not_demo_mode(tmp_path: Path) -> None:
    text = _client(tmp_path / "none").get("/").text
    assert "Mock upstream: offline mock model" in text
    assert "Demo mode" not in text
    assert "detectors: rules" in text
    assert "images: on" in text


def test_no_ui_page_shows_configured_upstream_and_ocr_gaps(tmp_path: Path) -> None:
    status = Status(
        upstream="https://models.example.com",
        detectors=["rules", "ner"],
        image_gaps=["tesseract", "segmenter"],
    )
    text = _client(tmp_path / "none", status).get("/").text
    assert "Upstream: https://models.example.com" in text
    assert "detectors: rules, ner" in text
    assert "images: refused (no OCR, face detection)" in text
    assert "mock model" not in text


def test_spa_fallback_but_not_for_api_or_assets(ui_dir: Path) -> None:
    client = _client(ui_dir)
    assert '<div id="root">' in client.get("/traffic").text  # client-side route
    assert client.get("/assets/missing.js").status_code == 404
    api = client.get("/v1/no-such-route")
    assert api.status_code == 404
    assert "root" not in api.text


def test_without_ui_root_explains_how_to_get_it(tmp_path: Path) -> None:
    empty = tmp_path / "none"
    assert not ui_available(empty)
    client = _client(empty)
    page = client.get("/")
    assert page.status_code == 200
    assert "no web UI bundled" in page.text
    assert "make wheel" in page.text
    assert client.get("/healthz").status_code == 200


def test_chat_through_the_embedded_mock_upstream(
    ui_dir: Path, mock: MockServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PII_GUARD_GATEWAY_MODE", "fast")
    with _client(ui_dir, upstream_base_url=mock.base_url) as client:
        reply = client.post(
            "/v1/chat/completions",
            json={"model": "pii-guard-mock", "messages": [{"role": "user", "content": EMAIL}]},
        )
    assert reply.status_code == 200, reply.text
    assert reply.json()["choices"][0]["message"]["content"] == f"Echo: {EMAIL}"
    received = httpx.get(f"http://127.0.0.1:{mock.port}/_mock/received").json()
    assert received["count"] == 1
    assert EMAIL not in received["requests"][0]  # the upstream only saw a placeholder


def test_active_detectors_is_the_default_stack() -> None:
    assert active_detectors(Settings())[0] == "rules"


def test_up_parser_defaults() -> None:
    args = build_parser().parse_args(["up"])
    assert (args.host, args.port, args.no_browser, args.mock) == ("127.0.0.1", 8787, False, False)


def test_up_refuses_full_traffic_log_off_loopback(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_up(UpOptions(host="0.0.0.0", traffic_log="full", browser=False)) == 2  # noqa: S104
    assert "pii-guard up:" in capsys.readouterr().err


def test_up_refuses_unset_key_variable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PII_GUARD_TEST_NO_SUCH_KEY", raising=False)
    assert run_up(UpOptions(api_key_env="PII_GUARD_TEST_NO_SUCH_KEY", browser=False)) == 2
    assert "--api-key-env is not set" in capsys.readouterr().err


def test_up_refuses_a_port_in_use(capsys: pytest.CaptureFixture[str]) -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert run_up(UpOptions(port=port, browser=False)) == 2
    assert f"--port {port + 1}" in capsys.readouterr().err


def test_banner_hints_ner_and_image_extras() -> None:
    status = Status(upstream="mock", detectors=["rules"], image_gaps=["ocr", "segmenter"])
    text = _banner(UpOptions(port=18999), status, "masked", ui=True)
    assert "http://localhost:18999/v1" in text
    assert "free-text names need NER" in text
    assert "[ner]" in text
    assert "[ocr,local-vision]" in text
    assert "connect pi --gateway http://localhost:18999/v1 --check" in text
    full = _banner(
        UpOptions(),
        Status(upstream="https://m.example.com", detectors=["rules", "ner"]),
        "masked",
        ui=False,
    )
    assert "names need NER" not in full
    assert "images         on" in full
    assert "no UI bundled" in full


def test_launcher_names_the_distribution_with_extras() -> None:
    assert "wattmind-pii-guard[ner]" in launcher("ner")
    assert launcher().endswith("pii-guard")


def test_image_gaps_lists_what_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    gaps = image_gaps(Settings(segmenter="off"))  # "ocr" first too when pytesseract is missing
    assert gaps[-2:] == ["tesseract", "segmenter"]
    assert image_gaps(Settings(image_require_ocr=False, segmenter="off")) == ["segmenter"]


def test_distribution_name_is_the_pypi_one() -> None:
    assert DISTRIBUTION == "wattmind-pii-guard"
    assert __version__ != "0.0.0+unknown"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_until_healthy(base: str, proc: subprocess.Popen[bytes]) -> bool:
    """Poll the child's health endpoint: True once it answers, False if it exited.

    A 10 s healthz timeout (not 1 s) survives a loaded machine (LAB-1319); a child that is
    still alive but never answers fails the test at the deadline."""
    deadline = time.monotonic() + 120
    while True:
        if proc.poll() is not None:
            return False
        try:
            if httpx.get(f"{base}/healthz", timeout=10).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        if time.monotonic() >= deadline:
            pytest.fail("pii-guard up did not start")
        time.sleep(0.5)


def test_up_process_serves_everything_and_stops_on_sigint(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PII_GUARD_")}
    # Rules only (LAB-1321): never load or download the NER (1.1 GB). An empty models dir keeps a
    # cached or pinned checkpoint out too. `make smoke-fast` covers the NER-loading `up`.
    env["PII_GUARD_NER_FALLBACK"] = "off"
    env["PII_GUARD_MODELS_DIR"] = str(tmp_path / "no-models")
    # The child writes to a file, not a pipe nobody reads: a full pipe blocks it mid-request and
    # the chat call times out (the flake in LAB-1321 / LAB-1319).
    log = tmp_path / "up.log"
    log.write_bytes(b"")
    proc: subprocess.Popen[bytes] | None = None
    base = ""
    last_log = ""
    for _ in range(3):
        # The pre-picked port can be taken between pick and bind under parallel load: retry
        # with a fresh one when the child died on a busy port (LAB-1319). Anything else in
        # the log fails the test; the log accumulates every attempt.
        port = _free_port()
        with log.open("ab") as sink:
            proc = subprocess.Popen(  # noqa: S603 - fixed argument list
                [sys.executable, "-m", "pii_guard", "up", "--no-browser", "--port", str(port)],
                cwd=tmp_path,
                env=env,
                stdout=sink,
                stderr=subprocess.STDOUT,
            )
        base = f"http://127.0.0.1:{port}"
        if _wait_until_healthy(base, proc):
            break
        last_log = log.read_text(errors="replace")
        proc = None
        if "address already in use" not in last_log.lower():
            pytest.fail(f"pii-guard up exited early:\n{last_log}")
    else:
        pytest.fail(f"pii-guard up found no free port in 3 tries:\n{last_log}")
    assert proc is not None
    try:
        assert httpx.get(f"{base}/", timeout=30).status_code == 200
        reply = httpx.post(
            f"{base}/v1/chat/completions",
            json={"model": "pii-guard-mock", "messages": [{"role": "user", "content": EMAIL}]},
            timeout=60,
        )
        assert reply.json()["choices"][0]["message"]["content"] == f"Echo: {EMAIL}"
        traffic = httpx.get(f"{base}/v1/traffic", timeout=30).text
        assert "EMAIL" in traffic
        assert EMAIL not in traffic
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail(f"pii-guard up did not stop on SIGINT:\n{log.read_text(errors='replace')}")
    out = log.read_text(errors="replace")
    assert proc.returncode == 0, out
    assert "pii-guard is up" in out
    detectors = next(line for line in out.splitlines() if "detectors" in line)
    assert detectors.split()[1:2] == ["rules"] and "ner" not in detectors  # no model, no download
    assert "offline mock model" in out
    assert "pii-guard stopped" in out
    assert "Traceback" not in out


def test_banner_names_the_ner_model_or_why_there_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LAB-1192: the banner says which NER model fast mode runs."""
    from pii_guard.detect import ner_resolve

    line = "rules + NER: fictional/pii-ner@0123456789ab (public fallback, Apache-2.0)"
    status = Status(upstream="mock", detectors=["rules", "ner"], ner=line)
    text = _banner(UpOptions(port=18999), status, "masked", ui=True)
    assert "NER model      fictional/pii-ner@0123456789ab (public fallback" in text
    off = "rules only (no NER model configured and PII_GUARD_NER_FALLBACK=off)"
    monkeypatch.setattr(ner_resolve, "extra_installed", lambda: True)
    text = _banner(
        UpOptions(port=18999),
        Status(upstream="mock", detectors=["rules"], ner=off),
        "masked",
        ui=True,
    )
    assert "PII_GUARD_NER_FALLBACK=off" in text
    assert "PII_GUARD_NER_FALLBACK=download downloads the NER model once" in text
    assert "[ner]" not in text
    monkeypatch.setattr(ner_resolve, "extra_installed", lambda: False)
    text = _banner(
        UpOptions(port=18999), Status(upstream="mock", detectors=["rules"]), "masked", ui=True
    )
    assert "free-text names need NER" in text and "[ner]" in text


_UP_ENV = (
    "PII_GUARD_HOST",
    "PII_GUARD_PORT",
    "PII_GUARD_METRICS",
    "PII_GUARD_SERVER_TIMING",
    "PII_GUARD_GATEWAY_MODE",
    "PII_GUARD_TRAFFIC_LOG",
    "PII_GUARD_TENANT_KEY",
    "PII_GUARD_UPSTREAM_BASE_URL",
    "PII_GUARD_UPSTREAM_API_KEY",
)


def _settings_up_serves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dotenv: str | None
) -> Settings:
    """The settings `up` would serve with, from ``tmp_path`` with ``dotenv`` as its .env."""
    import pii_guard.app_bundle as bundle
    from pii_guard.config import get_settings

    class Served(Exception):
        pass

    captured: list[Settings] = []

    def capture(status: Status, settings: Settings) -> None:
        captured.append(settings)
        raise Served

    for name in _UP_ENV:  # set first so teardown restores the absence, then clear
        monkeypatch.setenv(name, "x")
        monkeypatch.delenv(name)
    monkeypatch.setenv("PII_GUARD_NER_FALLBACK", "off")
    if dotenv is not None:
        (tmp_path / ".env").write_text(dotenv, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bundle, "create_bundle_app", capture)
    try:
        assert run_up(UpOptions(port=_free_port(), browser=False)) == 2
    finally:
        get_settings.cache_clear()
    assert len(captured) == 1
    return captured[0]


def test_up_keeps_the_tenant_key_from_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # LAB-1356: `up` generated a key whenever the process env had none, and that env value
    # beat the PII_GUARD_TENANT_KEY in .env (pseudonyms changed on every run).
    settings = _settings_up_serves(tmp_path, monkeypatch, f"PII_GUARD_TENANT_KEY={TENANT_KEY}\n")
    assert settings.tenant_key is not None
    assert settings.tenant_key.get_secret_value() == TENANT_KEY
    assert "PII_GUARD_TENANT_KEY" not in os.environ


def test_up_generates_a_tenant_key_when_none_is_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings_up_serves(tmp_path, monkeypatch, None)
    assert settings.tenant_key is not None
    key = settings.tenant_key.get_secret_value()
    assert len(bytes.fromhex(key)) == 32
    assert key != TENANT_KEY


def test_up_honours_gateway_mode_from_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LAB-1365: a .env-only PII_GUARD_GATEWAY_MODE survives `up`'s defaults."""
    import os

    from pii_guard.gateway.config import GatewayConfig

    dotenv = f"PII_GUARD_TENANT_KEY={TENANT_KEY}\nPII_GUARD_GATEWAY_MODE=audit\n"
    _settings_up_serves(tmp_path, monkeypatch, dotenv)
    assert os.environ["PII_GUARD_GATEWAY_MODE"] == "audit"
    assert GatewayConfig().mode.value == "audit"
