"""``pii-guard up``: the API, the gateway and the bundled web UI as one app on one port.

The UI is the Vite build of ``ui/`` (``make wheel`` copies ``ui/dist`` to ``pii_guard/_ui/``,
which git ignores and hatch ships as a wheel artifact). A wheel or checkout without it still
serves everything else, and ``/`` explains how to get the UI.

API routes win: the static mount is added last, and its SPA fallback (``index.html`` for an
unknown path) never answers under an API prefix, so a typo there is still a JSON 404.
"""

from __future__ import annotations

import contextlib
import html
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from pii_guard.api.app import create_app
from pii_guard.config import Settings

__all__ = ["UI_DIR", "Status", "create_bundle_app", "ui_available"]

#: Where the built UI lives inside the installed package.
UI_DIR = Path(__file__).resolve().parent / "_ui"

#: Paths the SPA fallback never answers: the API's own namespace.
_API_PREFIXES = ("v1/", "healthz", "metrics", "docs", "redoc", "openapi.json")

_BANNER_ID = "pii-guard-up-banner"


@dataclass
class Status:
    """What ``up`` runs, shown in the CLI banner and the strip above the UI."""

    upstream: str  # "mock" or a short description of the configured upstream
    detectors: list[str] = field(default_factory=list)
    ocr: bool = False

    @property
    def mock(self) -> bool:
        return self.upstream == "mock"


def ui_available(ui_dir: Path = UI_DIR) -> bool:
    return (ui_dir / "index.html").is_file()


def _strip(status: Status) -> str:
    """A one-line status strip injected at the top of the UI (no UI rebuild needed)."""
    upstream = (
        "mock upstream (offline: answers echo the masked text, no model is called)"
        if status.mock
        else f"upstream: {status.upstream}"
    )
    detectors = ", ".join(status.detectors) or "none"
    images = "images: OCR on" if status.ocr else "images: refused (no Tesseract)"
    text = " · ".join([upstream, f"detectors: {detectors}", images])
    tone = "#7c2d12;background:#ffedd5" if status.mock else "#1e3a8a;background:#dbeafe"
    return (
        f'<div id="{_BANNER_ID}" role="status" style="font:13px/1.4 system-ui,sans-serif;'
        f'padding:6px 16px;color:{tone};text-align:center">'
        f"pii-guard up · {html.escape(text)}</div>"
    )


class _SpaFiles(StaticFiles):
    """Static files with ``index.html`` for client-side routes, and the status strip in it."""

    def __init__(self, *, directory: Path, status: Status) -> None:
        super().__init__(directory=directory, html=True)
        index = (directory / "index.html").read_text(encoding="utf-8")
        body = index.find("<body")
        end = index.find(">", body) + 1 if body != -1 else 0
        self._index = (index[:end] + _strip(status) + index[end:]).encode("utf-8")

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path in ("", ".", "index.html"):
            return self._index_response()
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or path.startswith(_API_PREFIXES) or "." in path:
                raise
        return self._index_response()

    def _index_response(self) -> Response:
        return HTMLResponse(self._index, headers={"Cache-Control": "no-cache"})


def _no_ui_page(status: Status) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pii-guard</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:42rem;margin:3rem auto;padding:0 16px}}
code{{background:#f1f5f9;padding:1px 4px;border-radius:4px}}</style></head>
<body>{_strip(status)}
<h1>pii-guard is running</h1>
<p>The API and the OpenAI-compatible gateway are up, but this install has no web UI bundled
(it was built from source, not from a release wheel).</p>
<ul>
<li>Release wheel with the UI: see the README, "Try it".</li>
<li>From a checkout: <code>make wheel</code>, or <code>make demo</code> (UI with Node).</li>
</ul>
<p>Everything else works: <a href="/healthz">/healthz</a>, <a href="/docs">/docs</a>,
<a href="/v1/traffic">/v1/traffic</a>, gateway base URL <code>/v1</code>.</p>
</body></html>"""


def create_bundle_app(
    status: Status, settings: Settings | None = None, *, ui_dir: Path = UI_DIR
) -> FastAPI:
    """:func:`~pii_guard.api.app.create_app` plus the UI (or a fallback page) at ``/``."""
    app = create_app(settings)
    app.state.up_status = status
    if ui_available(ui_dir):
        app.mount("/", _SpaFiles(directory=ui_dir, status=status), name="ui")
    else:
        page = _no_ui_page(status)

        @app.get("/", include_in_schema=False)
        def no_ui() -> HTMLResponse:
            return HTMLResponse(page)

    return app


# --- the ``up`` command -------------------------------------------------------------------


def active_detectors(settings: Settings) -> list[str]:
    """The fast-mode detectors (:func:`pii_guard.detect.stack.default_detector_names`)."""
    from pii_guard.detect.stack import default_detector_names

    return list(default_detector_names(settings))


class MockServer:
    """The mock upstream on an ephemeral loopback port, in a background thread."""

    def __init__(self) -> None:
        import socket

        import uvicorn

        from pii_guard.bench.mock_upstream import create_mock_upstream

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self.port: int = self._sock.getsockname()[1]
        config = uvicorn.Config(create_mock_upstream(), log_level="warning", lifespan="off")
        self._server = uvicorn.Server(config)
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self, timeout: float = 10.0) -> None:
        self._thread = threading.Thread(
            target=self._server.run, kwargs={"sockets": [self._sock]}, daemon=True
        )
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._server.started:
            if time.monotonic() > deadline or not self._thread.is_alive():
                raise RuntimeError("the mock upstream did not start")
            time.sleep(0.02)

    def stop(self) -> None:
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._sock.close()


@dataclass
class UpOptions:
    host: str = "127.0.0.1"
    port: int = 8787
    browser: bool = True
    upstream_url: str | None = None
    api_key_env: str | None = None
    mock: bool = False
    traffic_log: str | None = None


OCR_HINT = (
    "image parts are refused (503 ocr_unavailable) until Tesseract is installed: "
    "`brew install tesseract` / `apt install tesseract-ocr`, and the `ocr` extra "
    "(`uvx --from '<wheel>[ocr]' pii-guard up`)"
)


def _banner(opts: UpOptions, status: Status, traffic_log: str, *, ui: bool) -> str:
    browse_host = "localhost" if opts.host in ("127.0.0.1", "::1", "localhost") else opts.host
    url = f"http://{browse_host}:{opts.port}"
    upstream = (
        "mock (offline, echoes the masked text; set --upstream-url for a real model)"
        if status.mock
        else status.upstream
    )
    images = "OCR on (Tesseract)" if status.ocr else OCR_HINT
    lines = [
        "",
        "  pii-guard is up",
        "",
        f"  open           {url}/" + ("" if ui else "   (no UI bundled: see the page there)"),
        f"  gateway        {url}/v1   (OpenAI-compatible base URL)",
        f"  upstream       {upstream}",
        f"  mode           fast · detectors: {', '.join(status.detectors)}",
        f"  traffic log    {traffic_log}   (live: {url}/v1/traffic/stream)",
        f"  images         {images}",
        "",
        f"  connect pi:     pii-guard connect pi --gateway {url}/v1",
        f"  check it:       pii-guard connect pi --gateway {url}/v1 --check",
        "  stop:           Ctrl-C",
        "",
    ]
    return "\n".join(lines)


def run_up(opts: UpOptions) -> int:
    """Run ``pii-guard up`` in the foreground until Ctrl-C (or SIGTERM)."""
    import os
    import secrets
    import sys
    import webbrowser

    import uvicorn

    from pii_guard.config import get_settings
    from pii_guard.observability import TrafficLevel, TrafficLogConfigError, check_bind
    from pii_guard.visual.ocr import tesseract_available

    env: dict[str, str] = {
        "PII_GUARD_HOST": opts.host,
        "PII_GUARD_PORT": str(opts.port),
        "PII_GUARD_METRICS": os.environ.get("PII_GUARD_METRICS") or "true",
        "PII_GUARD_SERVER_TIMING": os.environ.get("PII_GUARD_SERVER_TIMING") or "true",
        "PII_GUARD_GATEWAY_MODE": os.environ.get("PII_GUARD_GATEWAY_MODE") or "fast",
    }
    traffic_log = opts.traffic_log or os.environ.get("PII_GUARD_TRAFFIC_LOG") or "masked"
    if traffic_log == "off":
        traffic_log = "masked"  # the dashboard is the point of `up`
    env["PII_GUARD_TRAFFIC_LOG"] = traffic_log
    if not os.environ.get("PII_GUARD_TENANT_KEY"):
        env["PII_GUARD_TENANT_KEY"] = secrets.token_hex(32)  # this run only
    if opts.upstream_url:
        env["PII_GUARD_UPSTREAM_BASE_URL"] = opts.upstream_url
    if opts.api_key_env:
        key = os.environ.get(opts.api_key_env)
        if not key:
            print(f"pii-guard up: ${opts.api_key_env} is not set", file=sys.stderr)
            return 2
        env["PII_GUARD_UPSTREAM_API_KEY"] = key

    try:
        check_bind(TrafficLevel(traffic_log), opts.host)
    except (TrafficLogConfigError, ValueError) as exc:
        print(f"pii-guard up: {exc}", file=sys.stderr)
        return 2

    os.environ.update(env)
    get_settings.cache_clear()
    configured = get_settings().upstream_base_url  # flag, environment or .env
    mock: MockServer | None = None
    if opts.mock or not configured:
        mock = MockServer()
        mock.start()
        os.environ["PII_GUARD_UPSTREAM_BASE_URL"] = mock.base_url
        os.environ["PII_GUARD_UPSTREAM_API_KEY"] = ""
        get_settings.cache_clear()
        upstream = "mock"
    else:
        parts = urlsplit(configured)
        upstream = f"{parts.scheme}://{parts.hostname or ''}" + (
            f":{parts.port}" if parts.port else ""
        )
    try:
        try:
            settings = get_settings()
            status = Status(
                upstream=upstream, detectors=active_detectors(settings), ocr=tesseract_available()
            )
            app = create_bundle_app(status, settings)
        except Exception as exc:  # configuration errors: say so, don't dump a traceback
            print(f"pii-guard up: {exc}", file=sys.stderr)
            return 2
        # The UI holds the live traffic stream open: without a graceful-shutdown timeout,
        # Ctrl-C would wait for the browser tab to close.
        config = uvicorn.Config(
            app, host=opts.host, port=opts.port, log_level="warning", timeout_graceful_shutdown=2
        )
        server = uvicorn.Server(config)
        banner = _banner(opts, status, traffic_log, ui=ui_available())

        def announce() -> None:
            while not server.started and not server.should_exit:
                time.sleep(0.05)
            if not server.started:
                return
            print(banner, flush=True)
            if opts.browser:
                webbrowser.open(f"http://localhost:{opts.port}/")

        threading.Thread(target=announce, daemon=True).start()
        # uvicorn re-raises the Ctrl-C it already handled: that is a clean stop.
        with contextlib.suppress(KeyboardInterrupt):
            server.run()
        return 0 if server.started else 1
    finally:
        if mock is not None:
            mock.stop()
