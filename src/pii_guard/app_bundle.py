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
import logging
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

__all__ = [
    "UI_DIR",
    "MockServer",
    "Status",
    "UpOptions",
    "create_bundle_app",
    "image_gaps",
    "launcher",
    "run_up",
    "ui_available",
]

#: Where the built UI lives inside the installed package.
UI_DIR = Path(__file__).resolve().parent / "_ui"

#: Paths the SPA fallback never answers: the API's own namespace.
_API_PREFIXES = ("v1/", "healthz", "metrics", "docs", "redoc", "openapi.json")

_STRIP_ID = "pii-guard-up-status"


@dataclass
class Status:
    """What ``up`` runs, shown in the CLI banner and the strip above the UI."""

    upstream: str  # "mock" or the configured upstream's origin
    detectors: list[str] = field(default_factory=list)
    #: What images still need (empty: images work): "ocr", "tesseract", "segmenter".
    image_gaps: list[str] = field(default_factory=list)

    @property
    def mock(self) -> bool:
        return self.upstream == "mock"

    @property
    def images(self) -> str:
        if not self.image_gaps:
            return "on"
        needs = {"ocr": "OCR", "tesseract": "OCR", "segmenter": "face detection"}
        missing = ", ".join(dict.fromkeys(needs[g] for g in self.image_gaps))
        return f"refused (no {missing})"


def ui_available(ui_dir: Path = UI_DIR) -> bool:
    return (ui_dir / "index.html").is_file()


def _strip(status: Status, *, system_theme: bool = False) -> str:
    """A one-line status strip injected at the top of the UI (no UI rebuild needed).

    Light by default, dark under the UI's ``.dark`` class (``system_theme``: under a dark
    system theme, for the page without the UI).
    """
    first = (
        "Demo mode: offline mock model (echoes what it receives)"
        if status.mock
        else f"Upstream: {status.upstream}"
    )
    detectors = ", ".join(status.detectors) or "none"
    text = " · ".join([first, f"detectors: {detectors}", f"images: {status.images}"])
    light, dark = ("#7c2d12", "#ffedd5"), ("#fed7aa", "#431407")
    if not status.mock:
        light, dark = ("#1e3a8a", "#dbeafe"), ("#bfdbfe", "#172554")
    sel = f"#{_STRIP_ID}"
    style = (
        f"{sel}{{font:13px/1.4 system-ui,sans-serif;padding:6px 16px;text-align:center;"
        f"color:{light[0]};background:{light[1]}}}"
        + (
            f"@media (prefers-color-scheme:dark){{{sel}{{color:{dark[0]};background:{dark[1]}}}}}"
            if system_theme
            else f".dark {sel}{{color:{dark[0]};background:{dark[1]}}}"
        )
    )
    return f'<style>{style}</style><div id="{_STRIP_ID}" role="status">{html.escape(text)}</div>'


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
<meta name="color-scheme" content="light dark">
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:42rem;margin:3rem auto;
padding:0 16px}}</style></head>
<body>{_strip(status, system_theme=True)}
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


def install_source() -> str | None:
    """Where this install came from (PEP 610 ``direct_url.json``): a wheel URL, a git URL..."""
    import json
    from importlib.metadata import PackageNotFoundError, distribution

    from pii_guard import DISTRIBUTION

    try:
        raw = distribution(DISTRIBUTION).read_text("direct_url.json")
    except PackageNotFoundError:
        return None
    if not raw:
        return None
    info = json.loads(raw)
    url = info.get("url")
    if not isinstance(url, str) or info.get("dir_info", {}).get("editable"):
        return None
    vcs = info.get("vcs_info", {}).get("vcs")
    return f"{vcs}+{url}" if vcs and not url.startswith(f"{vcs}+") else url


def launcher(extras: str = "") -> str:
    """The command prefix that runs ``pii-guard`` the way this process was started.

    ``pii-guard`` when it is on PATH; otherwise (``uvx`` / ``uv tool run``) ``uvx --from
    <the same source>``, with ``extras`` (``ner``, ``ocr,local-vision``) as a PEP 508 requirement.
    """
    import shlex
    import shutil
    import sys

    from pii_guard import DISTRIBUTION

    # uvx runs from a throwaway environment in uv's cache: its pii-guard is on this process's
    # PATH, but not on the user's.
    ephemeral = any(part.startswith("archive-v") for part in Path(sys.prefix).parts)
    on_path = shutil.which("pii-guard")
    same = on_path is not None and Path(on_path).resolve() == Path(sys.argv[0]).resolve()
    if same and not (extras or ephemeral):
        return "pii-guard"
    source = install_source()
    if extras:
        requirement = f"{DISTRIBUTION}[{extras}]" + (f" @ {source}" if source else "")
    else:
        requirement = source or DISTRIBUTION
    return f"uvx --from {shlex.quote(requirement)} pii-guard"


def image_gaps(settings: Settings) -> list[str]:
    """What image masking still needs: ``ocr`` (the extra), ``tesseract``, ``segmenter``."""
    import importlib.util
    import shutil

    from pii_guard.types import DetectionError
    from pii_guard.visual.segmenters import OffSegmenter, build_segmenter

    gaps = []
    if settings.image_require_ocr:
        if importlib.util.find_spec("pytesseract") is None:
            gaps.append("ocr")
        if shutil.which("tesseract") is None:
            gaps.append("tesseract")
    try:
        if isinstance(build_segmenter(settings), OffSegmenter):
            gaps.append("segmenter")  # PII_GUARD_SEGMENTER=off refuses every image
    except (DetectionError, ValueError):
        gaps.append("segmenter")
    return gaps


def _image_hints(gaps: list[str]) -> list[str]:
    extras = []
    if "ocr" in gaps:
        extras.append("ocr")
    if "segmenter" in gaps:
        extras.append("local-vision")
    hints = []
    if "tesseract" in gaps:
        hints.append("install Tesseract: brew install tesseract / apt install tesseract-ocr")
    if extras:
        hints.append(f"restart with: {launcher(','.join(extras))} up")
    if "segmenter" in gaps:
        hints.append(
            "faces also need the YuNet model (python -m pii_guard.visual.segment fetch) or "
            "META_API_KEY for SAM 3.1 (docs/operations.md)"
        )
    return hints


@dataclass
class UpOptions:
    host: str = "127.0.0.1"
    port: int = 8787
    browser: bool = True
    upstream_url: str | None = None
    api_key_env: str | None = None
    mock: bool = False
    traffic_log: str | None = None


def _banner(opts: UpOptions, status: Status, traffic_log: str, *, ui: bool) -> str:
    browse_host = "localhost" if opts.host in ("127.0.0.1", "::1", "localhost") else opts.host
    url = f"http://{browse_host}:{opts.port}"
    upstream = (
        "offline mock model: echoes the masked text it receives (--upstream-url for a real one)"
        if status.mock
        else status.upstream
    )
    pad = "                 "
    detectors = ", ".join(status.detectors)
    lines = [
        "",
        "  pii-guard is up",
        "",
        f"  open           {url}/" + ("" if ui else "   (no UI bundled: the page says why)"),
        f"  gateway        {url}/v1   (OpenAI-compatible base URL)",
        f"  upstream       {upstream}",
        f"  detectors      {detectors}   (gateway fast mode)",
    ]
    if "ner" not in status.detectors:
        lines.append(f"{pad}free-text names need NER (pulls torch, ~1 GB):")
        lines.append(f"{pad}{launcher('ner')} up")
    lines.append(f"  traffic log    {traffic_log}   (live: {url}/v1/traffic/stream)")
    lines.append(f"  images         {status.images}")
    lines += [f"{pad}{hint}" for hint in _image_hints(status.image_gaps)]
    run = launcher()
    lines += [
        "",
        f"  connect pi     {run} connect pi --gateway {url}/v1",
        f"  check it       {run} connect pi --gateway {url}/v1 --check",
        "  stop           Ctrl-C",
        "",
    ]
    return "\n".join(lines)


def _port_free(host: str, port: int) -> bool:
    import socket

    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


class _QuietShutdown(logging.Filter):
    """Drops uvicorn's errors about cancelling open streams once Ctrl-C was pressed."""

    def __init__(self, server: object) -> None:
        super().__init__()
        self.server = server

    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(self.server, "should_exit", False)


def run_up(opts: UpOptions) -> int:
    """Run ``pii-guard up`` in the foreground until Ctrl-C (or SIGTERM)."""
    import os
    import secrets
    import sys
    import webbrowser

    import uvicorn

    from pii_guard.config import get_settings
    from pii_guard.observability import TrafficLevel, TrafficLogConfigError, check_bind

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
    if not _port_free(opts.host, opts.port):
        print(
            f"pii-guard up: port {opts.port} on {opts.host} is in use; "
            f"pick another with --port {opts.port + 1}",
            file=sys.stderr,
        )
        return 2

    os.environ.update(env)
    get_settings.cache_clear()
    # The banner says which detectors run and how to add NER: no startup warning about it.
    logging.getLogger("pii_guard.detect.stack").setLevel(logging.ERROR)
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
                upstream=upstream,
                detectors=active_detectors(settings),
                image_gaps=image_gaps(settings),
            )
            app = create_bundle_app(status, settings)
        except Exception as exc:  # configuration errors: say so, don't dump a traceback
            print(f"pii-guard up: {exc}", file=sys.stderr)
            return 2
        # The UI holds the live traffic stream open: without a graceful-shutdown timeout,
        # Ctrl-C would wait for the browser tab to close.
        config = uvicorn.Config(
            app, host=opts.host, port=opts.port, log_level="warning", timeout_graceful_shutdown=1
        )
        server = uvicorn.Server(config)
        quiet = _QuietShutdown(server)
        logging.getLogger("uvicorn.error").addFilter(quiet)
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
        logging.getLogger("uvicorn.error").removeFilter(quiet)
        if server.started:
            print("  pii-guard stopped", flush=True)
        return 0 if server.started else 1
    finally:
        if mock is not None:
            mock.stop()
