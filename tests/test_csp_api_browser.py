"""The API reference page loads under the hosted CSP with no violation (LAB-1588).

A headless browser loads ``/#api`` from a hosted UI build, served with the hosted security
headers, and fails on any Content-Security-Policy console message. It needs a build and a
browser, so it is skipped unless both are there:

    cd ui && VITE_PII_GUARD_HOSTED=true pnpm build && cd ..
    PII_GUARD_UI_DIST=ui/dist uv run --with playwright pytest -q --no-cov \\
        tests/test_csp_api_browser.py

(``uv run --with playwright playwright install chromium`` once, if the browser is missing.)
Run it after every ``@scalar/api-reference-react`` upgrade: a violation names the hash of the
style that is new, for :mod:`pii_guard.security_headers`.

Fictional data only (ADR 0005): the page renders the committed docs/openapi.json.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

from starlette.applications import Starlette  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402

from pii_guard.security_headers import SecurityHeadersMiddleware  # noqa: E402

# Resolved now: the suite's fixtures may change the working directory later.
DIST = Path(os.environ.get("PII_GUARD_UI_DIST", "ui/dist")).resolve()

pytestmark = pytest.mark.skipif(
    "PII_GUARD_UI_DIST" not in os.environ or not (DIST / "index.html").is_file(),
    reason="set PII_GUARD_UI_DIST to a hosted UI build (VITE_PII_GUARD_HOSTED=true)",
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    page = (DIST / "index.html").read_text("utf-8")
    app = Starlette()
    app.mount("/", StaticFiles(directory=DIST, html=True))
    port = _free_port()
    config = uvicorn.Config(
        SecurityHeadersMiddleware(app, page=page), host="127.0.0.1", port=port, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_api_reference_has_no_csp_violation(base_url: str, scheme: str) -> None:
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(color_scheme=scheme, viewport={"width": 1400, "height": 900})
            messages: list[str] = []
            page.on("console", lambda message: messages.append(message.text))
            page.goto(f"{base_url}/#api")
            page.wait_for_selector(".scalar-app", timeout=20_000)
            page.wait_for_selector("code.hljs", timeout=20_000)  # a request example rendered
            for _ in range(20):  # scroll so more operations and their examples render
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(100)
            page.wait_for_timeout(1000)
        finally:
            browser.close()
    violations = [m for m in messages if "Content Security Policy" in m]
    assert violations == []
