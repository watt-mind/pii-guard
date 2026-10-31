"""``pii-guard login`` and ``pii-guard logout``: authorize the CLI's telemetry on a dashboard.

Login is a one-time-code exchange (LAB-1709):

1. The CLI opens ``<dashboard>/#cli-auth?port=<p>&state=<s>[&project=<id>]`` and listens on
   ``127.0.0.1:<p>``. After the owner approves in the browser, the dashboard sends the browser to
   ``http://127.0.0.1:<p>/callback?state=<s>&code=<code>``: a short-lived, single-use code, never
   the key itself. ``--no-browser`` prints the URL instead and reads the code from stdin.
2. The CLI redeems the code with ``POST <dashboard>/v1/cli/token`` and gets back the project's
   endpoint and a **telemetry-only** key (the server refuses it everywhere else). The response's
   ``dashboard_url`` must have the origin the CLI opened, or nothing is saved.
3. The profile goes to ``cli.json`` (``0600``), which only feeds ``PII_GUARD_REMOTE_URL`` /
   ``PII_GUARD_REMOTE_KEY`` / ``PII_GUARD_REMOTE_LEVEL`` for ``pii-guard run``.

``pii-guard logout`` revokes the key server-side (``DELETE <dashboard>/v1/cli/token``) and then
deletes ``cli.json``. ``pii-guard login --local`` saves a local-only preference so ``pii-guard
run`` never prompts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import threading
import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from pii_guard.integrations.common import ConnectError
from pii_guard.observability import is_loopback, resolve_ingest_url

__all__ = [
    "DEFAULT_DASHBOARD_URL",
    "CliProfile",
    "build_login_parser",
    "build_logout_parser",
    "clear_cli_profile",
    "cli_config_path",
    "dashboard_origin",
    "exchange_code",
    "load_cli_profile",
    "login_main",
    "logout_main",
    "revoke_key",
    "run_browser_login",
    "save_cli_profile",
]

DEFAULT_DASHBOARD_URL = "https://guard.watt-mind.com"
TOKEN_PATH = "/v1/cli/token"  # noqa: S105 - a URL path, not a secret
ProfileMode = Literal["remote", "local"]
TelemetryLevel = Literal["masked", "stats"]
_ENDPOINT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_HTTP_TIMEOUT = 15.0
_DONE_PAGE = (
    b"<!doctype html><html><head><meta charset='utf-8'><title>PII Guard CLI</title></head>"
    b"<body style='font-family:system-ui,sans-serif;margin:3rem'>"
    b"<h1>PII Guard CLI authorized</h1><p>You can close this tab and return to the terminal.</p>"
    b"</body></html>"
)
_BAD_PAGE = (
    b"<!doctype html><html><head><meta charset='utf-8'><title>PII Guard CLI</title></head>"
    b"<body style='font-family:system-ui,sans-serif;margin:3rem'>"
    b"<h1>Not a valid login callback</h1><p>Return to the terminal and try again.</p>"
    b"</body></html>"
)


@dataclass(frozen=True)
class CliProfile:
    """Saved CLI telemetry preference and remote endpoint credentials."""

    mode: ProfileMode = "remote"
    dashboard_url: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    endpoint_id: str | None = None
    endpoint_key: str | None = None
    telemetry_level: TelemetryLevel = "masked"


def cli_config_path() -> Path:
    """Return the path to ``cli.json`` (respecting ``$PII_GUARD_CLI_CONFIG`` and XDG)."""
    explicit = os.environ.get("PII_GUARD_CLI_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "pii-guard" / "cli.json"


def save_cli_profile(profile: CliProfile, path: Path | None = None) -> Path:
    """Write ``profile`` to ``cli.json``: created ``0600``, then atomically replaced."""
    target = path or cli_config_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
    payload = json.dumps(asdict(profile), indent=2, sort_keys=True) + "\n"
    # O_EXCL: never reuse a file someone else created (with looser permissions) at that name.
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def load_cli_profile(path: Path | None = None) -> CliProfile | None:
    """Load the saved :class:`CliProfile` from ``cli.json``, or ``None`` if absent/invalid.

    A remote profile missing its ``endpoint_id`` still loads, so ``pii-guard run`` can refuse it
    with a clear error instead of silently posting to the dashboard root.
    """
    target = path or cli_config_path()
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    mode = raw.get("mode", "remote")
    if mode not in ("remote", "local"):
        return None
    level = raw.get("telemetry_level", "masked")
    if level not in ("masked", "stats"):
        level = "masked"
    if mode == "local":
        return CliProfile(mode="local", telemetry_level=level)
    dashboard_url = raw.get("dashboard_url")
    endpoint_key = raw.get("endpoint_key")
    if not isinstance(dashboard_url, str) or not dashboard_url.strip():
        return None
    if not isinstance(endpoint_key, str) or not endpoint_key.strip():
        return None
    return CliProfile(
        mode="remote",
        dashboard_url=dashboard_url.strip().rstrip("/"),
        project_id=str(raw["project_id"]).strip() if raw.get("project_id") else None,
        project_name=str(raw["project_name"]).strip() if raw.get("project_name") else None,
        endpoint_id=str(raw["endpoint_id"]).strip() if raw.get("endpoint_id") else None,
        endpoint_key=endpoint_key.strip(),
        telemetry_level=level,
    )


def clear_cli_profile(path: Path | None = None) -> bool:
    """Delete ``cli.json`` if it exists; return ``True`` when a file was removed."""
    target = path or cli_config_path()
    if not target.exists():
        return False
    target.unlink(missing_ok=True)
    return True


def dashboard_origin(url: str) -> str:
    """Normalize ``url`` to its origin, refusing anything a key must not be sent to.

    https only (http only for a loopback host), no ``user:pass@``: the same rules as
    :func:`pii_guard.observability.resolve_ingest_url`.
    """
    cleaned = url.strip().rstrip("/")
    parts = urlsplit(cleaned)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConnectError(f"dashboard URL {url!r} must be an https:// URL")
    if parts.username is not None or parts.password is not None:
        raise ConnectError("dashboard URL must not carry credentials")
    if parts.scheme == "http" and not is_loopback(parts.hostname):
        raise ConnectError("dashboard URL must use https:// (http:// only for a loopback host)")
    try:
        port = parts.port
    except ValueError:
        raise ConnectError(f"dashboard URL {url!r} has an invalid port") from None
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    default_port = 443 if parts.scheme == "https" else 80
    suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parts.scheme}://{host}{suffix}"


def _make_callback_handler(
    expected_state: str,
    result_box: dict[str, str],
    done_event: threading.Event,
) -> type[BaseHTTPRequestHandler]:
    class CallbackHandler(BaseHTTPRequestHandler):
        def _page(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path != "/callback":
                self._page(404, _BAD_PAGE)
                return
            params = parse_qs(parsed.query)
            state = (params.get("state") or [""])[0]
            code = (params.get("code") or [""])[0].strip()
            valid_state = secrets.compare_digest(state.encode(), expected_state.encode())
            if not valid_state or not code or done_event.is_set():
                # A stray or forged request: ignore it and keep waiting for the real one.
                self._page(400, _BAD_PAGE)
                return
            result_box["code"] = code
            done_event.set()
            self._page(200, _DONE_PAGE)

        def log_message(self, format: str, *args: object) -> None:
            return  # the request line carries the one-time code: never log it

    return CallbackHandler


def _wait_for_callback(
    origin: str,
    query: dict[str, str],
    *,
    timeout_seconds: float,
    open_browser: Callable[[str], Any],
    on_listen: Callable[[str], None] | None,
    err: Any,
) -> str:
    state = secrets.token_urlsafe(24)
    result_box: dict[str, str] = {}
    done_event = threading.Event()
    server = HTTPServer(("127.0.0.1", 0), _make_callback_handler(state, result_box, done_event))
    port = int(server.server_port)
    auth_url = f"{origin}/#cli-auth?" + urlencode({"port": str(port), "state": state, **query})
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        print(
            f"Opening your browser to authorize the CLI on {origin} ...\n"
            f"  If it does not open, visit:\n  {auth_url}",
            file=err,
        )
        open_browser(auth_url)
        if on_listen is not None:
            on_listen(auth_url)
        if not done_event.wait(timeout=timeout_seconds):
            raise ConnectError(
                "timed out waiting for browser authorization; try `pii-guard login --no-browser`"
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
    return result_box["code"]


def _str_field(data: dict[str, Any], name: str, *, required: bool = True) -> str | None:
    val = data.get(name)
    if isinstance(val, str) and val.strip():
        return val.strip()
    if required:
        raise ConnectError(f"the dashboard's login response is missing {name!r}")
    return None


def _profile_from_exchange(
    data: object, origin: str, telemetry_level: TelemetryLevel | None
) -> CliProfile:
    if not isinstance(data, dict):
        raise ConnectError("the dashboard's login response is not a JSON object")
    dashboard_url = _str_field(data, "dashboard_url") or ""
    returned_origin = dashboard_origin(dashboard_url)
    if returned_origin != origin:
        raise ConnectError(
            f"the dashboard answered for {returned_origin}, not {origin}; nothing was saved"
        )
    endpoint_id = _str_field(data, "endpoint_id") or ""
    if not _ENDPOINT_ID_RE.fullmatch(endpoint_id):
        raise ConnectError("the dashboard's login response has an invalid endpoint_id")
    key = _str_field(data, "key") or ""
    level = data.get("telemetry_level", "masked")
    if level not in ("masked", "stats"):
        raise ConnectError("the dashboard's login response has an invalid telemetry_level")
    if telemetry_level == "stats":
        level = "stats"  # the CLI may only ask for less than the project allows
    try:
        resolve_ingest_url(f"{origin}/e/{endpoint_id}/v1")
    except ValueError as exc:
        raise ConnectError(f"dashboard URL: {exc}") from None
    return CliProfile(
        mode="remote",
        dashboard_url=origin,
        project_id=_str_field(data, "project_id", required=False),
        project_name=_str_field(data, "project_name", required=False),
        endpoint_id=endpoint_id,
        endpoint_key=key,
        telemetry_level=level,
    )


def exchange_code(
    origin: str,
    code: str,
    *,
    telemetry_level: TelemetryLevel | None = None,
    client: httpx.Client | None = None,
) -> CliProfile:
    """Redeem a one-time login ``code`` at ``origin`` for a telemetry profile."""
    origin = dashboard_origin(origin)
    owned = client is None
    http = client or httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=False)
    try:
        res = http.post(f"{origin}{TOKEN_PATH}", json={"code": code})
    except httpx.HTTPError as exc:
        raise ConnectError(f"could not reach {origin} ({type(exc).__name__})") from None
    finally:
        if owned:
            http.close()
    if res.status_code == 400:
        try:
            err_code = res.json().get("error", {}).get("code")
        except (ValueError, AttributeError):
            err_code = None
        if err_code == "invalid_code":
            raise ConnectError(
                "the login code is invalid, expired or already used; run `pii-guard login` again"
            )
    if res.status_code != 200:
        raise ConnectError(f"{origin} refused the login code (HTTP {res.status_code})")
    try:
        data = res.json()
    except ValueError:
        raise ConnectError("the dashboard's login response is not JSON") from None
    return _profile_from_exchange(data, origin, telemetry_level)


def revoke_key(origin: str, key: str, *, client: httpx.Client | None = None) -> bool:
    """Revoke the CLI's telemetry ``key`` at ``origin``; ``True`` when the server confirmed it."""
    try:
        origin = dashboard_origin(origin)
    except ConnectError:
        return False
    owned = client is None
    http = client or httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=False)
    try:
        res = http.delete(f"{origin}{TOKEN_PATH}", headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError:
        return False
    finally:
        if owned:
            http.close()
    return res.status_code in (200, 204)


def _read_code(code_arg: str | None, input_fn: Callable[[str], str]) -> str:
    if code_arg is None:
        code = input_fn("Paste the one-time code shown in the browser: ").strip()
    elif code_arg == "-":
        code = sys.stdin.readline().strip()
    else:
        code = code_arg.strip()
    if not code:
        raise ConnectError("no login code was entered")
    return code


def run_browser_login(
    dashboard_url: str = DEFAULT_DASHBOARD_URL,
    *,
    project: str | None = None,
    telemetry_level: TelemetryLevel | None = None,
    no_browser: bool = False,
    code: str | None = None,
    timeout_seconds: float = 180.0,
    open_browser: Callable[[str], Any] = webbrowser.open,
    input_fn: Callable[[str], str] = input,
    stderr: Any = None,
    on_listen: Callable[[str], None] | None = None,
    client: httpx.Client | None = None,
) -> CliProfile:
    """Authorize the CLI on ``dashboard_url`` and return the (unsaved) profile.

    The browser flow catches the code on a loopback callback. With ``no_browser`` (or ``code``)
    the URL is printed and the code is read from the prompt, from stdin (``code="-"``) or taken
    as given.
    """
    err = stderr or sys.stderr
    origin = dashboard_origin(dashboard_url)
    query = {"project": project} if project else {}
    paste = no_browser or code is not None
    if paste:
        auth_url = f"{origin}/#cli-auth" + (f"?{urlencode(query)}" if query else "")
        print(
            f"Open this URL in a browser, approve the CLI, and copy the one-time code:\n"
            f"  {auth_url}",
            file=err,
        )
        one_time = _read_code(code, input_fn)
    else:
        one_time = _wait_for_callback(
            origin,
            query,
            timeout_seconds=timeout_seconds,
            open_browser=open_browser,
            on_listen=on_listen,
            err=err,
        )
    profile = exchange_code(origin, one_time, telemetry_level=telemetry_level, client=client)
    if paste:
        print(f"Telemetry for this CLI will be sent to {origin}", file=err)
    return profile


def build_login_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pii-guard login",
        description=(
            "Authorize `pii-guard run` to send scrubbed telemetry to a PII Guard dashboard. "
            "The saved key is telemetry-only."
        ),
    )
    parser.add_argument(
        "--dashboard",
        default=DEFAULT_DASHBOARD_URL,
        metavar="URL",
        help=f"dashboard to sign in to (https; default: {DEFAULT_DASHBOARD_URL})",
    )
    parser.add_argument(
        "--project",
        default=None,
        metavar="ID",
        help="project to preselect in the browser",
    )
    parser.add_argument(
        "--telemetry-level",
        choices=("masked", "stats"),
        default=None,
        help="send only counts/timings (stats) even if the project allows masked bodies",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="print the authorization URL and read the one-time code from the prompt",
    )
    parser.add_argument(
        "--code",
        default=None,
        metavar="CODE",
        help=(
            "the one-time code from the browser; '-' reads it from stdin. A literal value "
            "lands in your shell history: prefer '-' or --no-browser"
        ),
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="save a local-only preference (no remote dashboard telemetry)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="print the currently saved CLI telemetry profile and exit",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="seconds to wait for the browser callback (default: 180)",
    )
    return parser


def build_logout_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="pii-guard logout",
        description=(
            "Revoke the CLI's telemetry key on its dashboard and remove the saved profile "
            "(~/.config/pii-guard/cli.json)."
        ),
    )


def _print_status(stdout: Any) -> int:
    profile = load_cli_profile()
    path = cli_config_path()
    if profile is None:
        print(f"pii-guard login: not logged in (no profile at {path})", file=stdout)
        return 0
    if profile.mode == "local":
        print(
            "pii-guard login: local-only mode "
            f"(telemetry={profile.telemetry_level}, config={path})",
            file=stdout,
        )
        return 0
    print(
        f"pii-guard login: connected to {profile.dashboard_url} "
        f"(project={profile.project_name or profile.project_id!r}, "
        f"endpoint={profile.endpoint_id}, telemetry={profile.telemetry_level}, config={path})",
        file=stdout,
    )
    return 0


def login_main(
    argv: Sequence[str] | None = None,
    *,
    stdout: Any = None,
    stderr: Any = None,
    open_browser: Callable[[str], Any] = webbrowser.open,
    input_fn: Callable[[str], str] = input,
    client: httpx.Client | None = None,
) -> int:
    """CLI entry point for ``pii-guard login``."""
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    parser = build_login_parser()
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.status:
        return _print_status(out)
    try:
        if args.local:
            profile = CliProfile(mode="local", telemetry_level=args.telemetry_level or "masked")
            path = save_cli_profile(profile)
            print(
                f"pii-guard login: saved local-only preference ({path}); "
                "no telemetry will be sent to a remote dashboard.",
                file=out,
            )
            return 0
        profile = run_browser_login(
            args.dashboard,
            project=args.project,
            telemetry_level=args.telemetry_level,
            no_browser=args.no_browser,
            code=args.code,
            timeout_seconds=args.timeout,
            open_browser=open_browser,
            input_fn=input_fn,
            stderr=err,
            client=client,
        )
        path = save_cli_profile(profile)
        print(
            f"pii-guard login: connected to {profile.dashboard_url} "
            f"(project={profile.project_name or profile.project_id!r}, "
            f"endpoint={profile.endpoint_id}, telemetry={profile.telemetry_level}, "
            f"saved to {path})",
            file=out,
        )
        return 0
    except ConnectError as exc:
        print(f"pii-guard login: {exc}", file=err)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("\npii-guard login: cancelled", file=err)
        return 130


def logout_main(
    argv: Sequence[str] | None = None,
    *,
    stdout: Any = None,
    stderr: Any = None,
    client: httpx.Client | None = None,
) -> int:
    """CLI entry point for ``pii-guard logout``: revoke the key, then delete ``cli.json``.

    Returns 1 when the server did not confirm the revocation (the file is still removed).
    """
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    parser = build_logout_parser()
    parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    path = cli_config_path()
    profile = load_cli_profile(path)
    revoked: bool | None = None
    where = ""
    if profile is not None and profile.mode == "remote" and profile.endpoint_key:
        where = profile.dashboard_url or ""
        revoked = revoke_key(where, profile.endpoint_key, client=client)
    removed = clear_cli_profile(path)
    if removed:
        print(f"pii-guard logout: removed saved profile at {path}", file=out)
    else:
        print(f"pii-guard logout: no saved profile at {path}", file=out)
    if revoked is True:
        print(f"pii-guard logout: revoked the CLI key on {where}", file=out)
    elif revoked is False:
        print(
            f"pii-guard logout: could not revoke the CLI key on {where}; "
            "revoke it in the dashboard to stop it working",
            file=err,
        )
        return 1
    return 0
