"""Start the local demo stack: mock upstream, pii-guard API (+ gateway), optionally the UI.

Used by ``scripts/demo.py`` (``make demo``) and ``scripts/smoke.py`` (``make smoke``). Every
process binds to 127.0.0.1. Nothing here prints a key: the decision "mock or real upstream" is
made from whether variables are set, never from their values.

Mode: ``fast`` (default) runs rules + the NER model that :mod:`pii_guard.detect.ner_resolve`
picks (``PII_GUARD_NER_MODEL``, else the published checkpoint, else the public fallback,
downloaded once into ``~/.cache/pii-guard/models``); it needs the ``ner`` extra (``make demo``
installs it). ``rules`` runs the rules only, offline, nothing downloaded (``make demo
MODE=rules``, ``make smoke``).

Upstream, in order:

1. ``--mock`` (the smoke test): always the mock upstream;
2. ``PII_GUARD_UPSTREAM_BASE_URL`` set (environment or ``.env``): that upstream, with
   ``PII_GUARD_UPSTREAM_API_KEY``;
3. ``BASETEN_API_KEY`` set: Baseten's OpenAI-compatible Model APIs;
4. otherwise the mock upstream (offline, free).
"""

from __future__ import annotations

import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from pii_guard.detect.ner_resolve import NerChoice, describe, ensure, extra_installed, resolve
from pii_guard.types import DetectionError

ROOT = Path(__file__).resolve().parent.parent
BASETEN_URL = "https://inference.baseten.co/v1"
BASETEN_MODEL = "meta-models/muse-spark-open-1026"
MOCK_MODEL = "pii-guard-mock"
MODES = ("fast", "rules")


def dotenv(path: Path = ROOT / ".env") -> dict[str, str]:
    """``KEY=value`` lines of ``.env`` (no interpolation); missing file -> empty."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip().removeprefix("export ").strip()] = value.strip().strip("'\"")
    return out


def setting(name: str, env: Mapping[str, str]) -> str:
    return os.environ.get(name) or env.get(name) or ""


@dataclass
class Plan:
    """What the stack will run; printed as the banner (never with values of keys)."""

    api_port: int = 8787
    mock_port: int = 8790
    ui_port: int = 5173
    upstream: str = "mock"  # mock | configured | baseten
    model: str = MOCK_MODEL
    mode: str = "fast"  # fast | rules
    ner: str | None = None
    audit: bool = False
    #: Why fast mode runs without the NER (banner hint), when it does.
    ner_missing: str = ""
    ner_choice: NerChoice | None = None
    traffic_log: str = "masked"
    ui: bool = True
    env: dict[str, str] = field(default_factory=dict)

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def mock_url(self) -> str:
        return f"http://127.0.0.1:{self.mock_port}"


def plan(
    *,
    force_mock: bool = False,
    ui: bool = True,
    traffic_log: str | None = None,
    api_port: int = 8787,
    mock_port: int = 8790,
    mode: str = "fast",
) -> Plan:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    env_file = dotenv()
    p = Plan(api_port=api_port, mock_port=mock_port, ui=ui, mode=mode)
    p.traffic_log = traffic_log or setting("PII_GUARD_TRAFFIC_LOG", env_file) or "masked"
    if p.traffic_log == "off":
        p.traffic_log = "masked"  # the demo is about watching traffic
    env = {
        "PII_GUARD_HOST": "127.0.0.1",
        "PII_GUARD_PORT": str(api_port),
        "PII_GUARD_TRAFFIC_LOG": p.traffic_log,
        "PII_GUARD_SERVER_TIMING": "true",
        "PII_GUARD_METRICS": "true",
        "PII_GUARD_GATEWAY_MODE": setting("PII_GUARD_GATEWAY_MODE", env_file) or "fast",
    }
    if not setting("PII_GUARD_TENANT_KEY", env_file):
        env["PII_GUARD_TENANT_KEY"] = secrets.token_hex(32)  # this run only
    if force_mock:
        p.upstream = "mock"
        # Offline by contract (LAB-1255): the smoke API must not see a SAM key, whether it
        # comes from the environment or the repo .env (Settings would otherwise configure
        # SAM and flip hu-image from refused to masked). Empty counts as unset.
        env["PII_GUARD_SAM_API_KEY"] = ""
        env["META_API_KEY"] = ""
    elif setting("PII_GUARD_UPSTREAM_BASE_URL", env_file):
        p.upstream = "configured"
    elif setting("BASETEN_API_KEY", env_file):
        p.upstream = "baseten"
    if p.upstream == "mock":
        env["PII_GUARD_UPSTREAM_BASE_URL"] = p.mock_url + "/v1"
        env["PII_GUARD_UPSTREAM_API_KEY"] = ""
        # The API runs as plain `serve` (no up_status): mark the upstream as the mock so
        # /v1/status and Connect report it as the mock (LAB-1311).
        env["PII_GUARD_UPSTREAM_MOCK"] = "true"
    elif p.upstream == "baseten":
        env["PII_GUARD_UPSTREAM_BASE_URL"] = BASETEN_URL
        env["PII_GUARD_UPSTREAM_API_KEY"] = setting("BASETEN_API_KEY", env_file)
        p.model = BASETEN_MODEL
    if p.upstream != "mock":
        p.model = os.environ.get("PII_GUARD_DEMO_MODEL") or p.model
    # Audit mode works when an LLM detector key is there (Baseten is the default endpoint).
    if setting("PII_GUARD_LLM_DETECTOR_API_KEY", env_file):
        p.audit = True
    elif setting("BASETEN_API_KEY", env_file) and not force_mock:
        env["PII_GUARD_LLM_DETECTOR_API_KEY"] = setting("BASETEN_API_KEY", env_file)
        env.setdefault("PII_GUARD_LLM_DETECTOR_REASONING_EFFORT", "low")
        p.audit = True
    if mode == "rules":
        # Rules only: no configured model, no fallback, nothing downloaded.
        env["PII_GUARD_NER_MODEL"] = ""
        env["PII_GUARD_NER_FALLBACK"] = "off"
    else:
        choice = resolve(
            configured=setting("PII_GUARD_NER_MODEL", env_file) or None,
            revision=setting("PII_GUARD_NER_REVISION", env_file) or None,
            published=setting("PII_GUARD_NER_PUBLISHED_MODEL", env_file) or None,
            fallback=setting("PII_GUARD_NER_FALLBACK", env_file) or None,
        )
        if not extra_installed():
            p.ner_missing = "the 'ner' extra is not installed: `make demo` installs it"
            env["PII_GUARD_NER_MODEL"] = ""
            env["PII_GUARD_NER_FALLBACK"] = "off"
        elif choice.model is None:
            p.ner_missing = choice.reason
        else:
            p.ner = describe(choice).removeprefix("rules + NER: ")
            p.ner_choice = choice
    p.env = env
    return p


def prepare_ner(p: Plan) -> None:
    """Download a missing pinned NER model before the API starts (progress on stderr)."""
    if p.ner_choice is not None and not p.ner_choice.ready:
        try:
            ensure(p.ner_choice)
        except DetectionError as exc:
            raise RuntimeError(exc.message) from None
        p.ner = p.ner.replace(", downloads on first run", "")


def ocr_status() -> str:
    """The banner's image line: OCR on, or why images will be refused (LAB-1209)."""
    from pii_guard.visual.ocr import tesseract_available

    if tesseract_available():
        return "OCR on (Tesseract): text in images is masked"
    if os.environ.get("PII_GUARD_IMAGE_REQUIRE_OCR", "true").strip().lower() in (
        "false",
        "0",
        "no",
        "off",
    ):
        return "OCR off and not required: text in images is NOT checked"
    return (
        "OCR off: image parts are refused (503 ocr_unavailable); install Tesseract and "
        "`uv sync --extra ocr` (docs/operations.md)"
    )


def banner(p: Plan) -> str:
    upstream = {
        "mock": f"mock upstream (offline, echoes the masked text) at {p.mock_url}/v1",
        "configured": "PII_GUARD_UPSTREAM_BASE_URL from your environment / .env",
        "baseten": f"Baseten Model APIs ({p.model}), key from BASETEN_API_KEY",
    }[p.upstream]
    if p.ner:
        fast = f"rules + NER: {p.ner}"
    elif p.mode == "rules":
        fast = "rules only (MODE=rules: offline, no NER model; `make demo` for rules + NER)"
    else:
        fast = f"rules only: {p.ner_missing}"
    audit = (
        "rules + NER + LLM detector, opt in with X-PII-Guard-Mode: audit (quality checks)"
        if p.audit
        else "unavailable (no LLM detector key)"
    )
    lines = [
        "",
        "  pii-guard demo is up",
        "",
        *([f"  open http://localhost:{p.ui_port}   (UI)"] if p.ui else []),
        f"  API + gateway  {p.api_url}   (OpenAI base URL: {p.api_url}/v1)",
        f"  traffic log    {p.api_url}/v1/traffic  (live: /v1/traffic/stream), "
        f"level {p.traffic_log}",
        f"  metrics        {p.api_url}/metrics",
        f"  upstream       {upstream}",
        f"  fast mode      {fast}  (default)",
        *(
            []
            if p.ner
            else [
                "                 demo traffic: names are pre-loaded known values; the one call",
                '                 labelled "needs fast mode (NER)" is an expected miss',
            ]
        ),
        f"  audit mode     {audit}",
        f"  images         {ocr_status()}",
        "",
        "  send demo traffic:  make demo-traffic      stop: Ctrl-C",
        "",
    ]
    return "\n".join(lines)


class Stack:
    """The processes of a plan; a context manager that stops them all on exit."""

    def __init__(self, p: Plan, *, quiet: bool = False) -> None:
        self.plan = p
        self.quiet = quiet
        self.procs: list[tuple[str, subprocess.Popen[bytes]]] = []

    def _spawn(self, name: str, args: list[str], env: Mapping[str, str], cwd: Path = ROOT) -> None:
        out = subprocess.DEVNULL if self.quiet else None
        proc = subprocess.Popen(  # noqa: S603 - fixed argument lists
            args, cwd=cwd, env={**os.environ, **env}, stdout=out, stderr=out
        )
        self.procs.append((name, proc))

    def __enter__(self) -> Stack:
        p = self.plan
        py = sys.executable
        try:
            if p.upstream == "mock":
                self._spawn(
                    "mock-upstream",
                    [py, "-m", "pii_guard", "bench", "mock-upstream", "--port", str(p.mock_port)],
                    {},
                )
                wait_healthy(p.mock_url + "/healthz", "mock upstream", self.procs[-1][1])
            self._spawn("api", [py, "-m", "pii_guard", "serve"], p.env)
            wait_healthy(p.api_url + "/healthz", "pii-guard API", self.procs[-1][1], timeout=90)
            if p.ui:
                self._start_ui()
        except BaseException:
            self.stop()
            raise
        return self

    def _start_ui(self) -> None:
        p = self.plan
        ui = ROOT / "ui"
        pnpm = shutil.which("pnpm")
        if pnpm is None:
            print("  (pnpm not found: the UI is skipped; see ui/README.md)", file=sys.stderr)
            p.ui = False
            return
        if not (ui / "node_modules").is_dir():
            print("  installing UI dependencies (first run only)...", file=sys.stderr)
            subprocess.run([pnpm, "install", "--frozen-lockfile"], cwd=ui, check=True)  # noqa: S603
        self._spawn(
            "ui",
            [pnpm, "dev", "--host", "127.0.0.1", "--port", str(p.ui_port)],
            {"PII_GUARD_API_URL": p.api_url, "VITE_PII_GUARD_MODE": "api"},
            cwd=ui,
        )
        wait_healthy(f"http://127.0.0.1:{p.ui_port}/", "UI", self.procs[-1][1], timeout=60)

    def stop(self) -> None:
        for _, proc in reversed(self.procs):
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
        deadline = time.monotonic() + 10
        for _, proc in reversed(self.procs):
            try:
                proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.kill()
        self.procs.clear()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def wait(self) -> int:
        """Block until a process exits (or Ctrl-C); returns its exit code."""
        try:
            while True:
                for name, proc in self.procs:
                    if proc.poll() is not None:
                        print(f"{name} exited with {proc.returncode}", file=sys.stderr)
                        return proc.returncode or 1
                time.sleep(0.5)
        except KeyboardInterrupt:
            return 0


def wait_healthy(
    url: str, name: str, proc: subprocess.Popen[bytes], *, timeout: float = 30
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{name} exited with {proc.returncode} during startup")
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"{name} did not become healthy at {url} within {timeout:g}s")
