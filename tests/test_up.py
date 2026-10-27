"""``pii-guard up``: one app with the API, the gateway and the bundled UI (LAB-1276).

Fictional data only (ADR 0005). The wheel itself is smoke-tested by scripts/ci/wheel_smoke.sh.
"""

from __future__ import annotations

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


def test_ui_served_at_root_with_status_strip(ui_dir: Path) -> None:
    client = _client(ui_dir)
    page = client.get("/")
    assert page.status_code == 200
    assert '<div id="root">' in page.text
    assert "Demo mode: offline mock model" in page.text
    assert "detectors: rules" in page.text
    assert "images: on" in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert client.get("/assets/app.js").text == "console.log('ui')"
    assert client.get("/healthz").json() == {"status": "ok", "version": __version__}


def test_configured_upstream_and_ocr_in_strip(ui_dir: Path) -> None:
    status = Status(
        upstream="https://models.example.com",
        detectors=["rules", "ner"],
        image_gaps=["tesseract", "segmenter"],
    )
    text = _client(ui_dir, status).get("/").text
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


def test_up_process_serves_everything_and_stops_on_sigint(tmp_path: Path) -> None:
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("PII_GUARD_")}
    proc = subprocess.Popen(  # noqa: S603 - fixed argument list
        [sys.executable, "-m", "pii_guard", "up", "--no-browser", "--port", str(port)],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 60
        while True:
            assert proc.poll() is None, proc.stdout.read().decode() if proc.stdout else ""
            try:
                if httpx.get(f"{base}/healthz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            assert time.monotonic() < deadline, "pii-guard up did not start"
            time.sleep(0.2)
        assert httpx.get(f"{base}/").status_code == 200
        reply = httpx.post(
            f"{base}/v1/chat/completions",
            json={"model": "pii-guard-mock", "messages": [{"role": "user", "content": EMAIL}]},
            timeout=30,
        )
        assert reply.json()["choices"][0]["message"]["content"] == f"Echo: {EMAIL}"
        traffic = httpx.get(f"{base}/v1/traffic").text
        assert "EMAIL" in traffic
        assert EMAIL not in traffic
    finally:
        proc.send_signal(signal.SIGINT)
        out, _ = proc.communicate(timeout=20)
    assert proc.returncode == 0, out.decode()
    assert "pii-guard is up" in out.decode()
    assert "offline mock model" in out.decode()
    assert "pii-guard stopped" in out.decode()
    assert "Traceback" not in out.decode()
