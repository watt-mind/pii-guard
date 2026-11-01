"""What every ``pii-guard connect`` client shares.

- :func:`default_gateway_url`: ``http://127.0.0.1:<PII_GUARD_PORT>/v1`` (a wildcard bind such
  as ``0.0.0.0`` is reached on loopback).
- :func:`session_url`: that URL with a stable vault session in its path,
  ``http://127.0.0.1:8787/s/<session>/v1`` (LAB-1286), so a client that can't send
  ``X-PII-Guard-Session`` keeps its placeholders across turns; the session already in the
  client's config is kept, so ``connect`` stays idempotent.
- :func:`fetch_models`: the ids from the gateway's ``GET /v1/models``.
- :func:`write_json`: write a client's config file, with a timestamped backup of the old one,
  and only when it changes (so ``connect`` is idempotent); :func:`json_diff` for ``--dry-run``.
- :func:`run_check`: one fictional canary request through the client's configured path, with
  ``X-PII-Guard-Echo: masked``, so it shows what was sent, what the model saw and what came
  back (and appears on the Live traffic tab when the traffic log is on).

Nothing here prints keys: the canary's ``Authorization`` value is never shown.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import secrets
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from pii_guard.vault.placeholders import PLACEHOLDER_RE

__all__ = [
    "CANARY_PROMPT",
    "CANARY_VALUES",
    "DASHBOARD_URL",
    "NOT_THE_GATEWAY",
    "CheckResult",
    "ConnectError",
    "default_gateway_url",
    "fetch_models",
    "json_diff",
    "render_json",
    "run_check",
    "session_of",
    "session_url",
    "write_json",
]

#: The UI's Live traffic tab (``make demo`` / ``scripts/demo.py``; docs/operations.md).
DASHBOARD_URL = "http://localhost:5173/#traffic"

#: Fictional values the canary carries (ADR 0005); none of them may reach the model.
CANARY_VALUES = (
    "jane.placeholder@example.net",
    "+44 20 7946 0958",
    "GB82 WEST 1234 5698 7654 32",
)
CANARY_PROMPT = (
    "pii-guard connect check. Reply in one short sentence that repeats this contact "
    f"exactly: email {CANARY_VALUES[0]}, phone {CANARY_VALUES[1]}, IBAN {CANARY_VALUES[2]}."
)

_TIMEOUT = httpx.Timeout(120.0, connect=5.0)
_SESSION_PATH_RE = re.compile(r"^(.*?)/s/([A-Za-z0-9_-]{1,128})(/.*)?$")
# A project endpoint's base URL (docs/projects.md). It has no /s/<session> form: the gateway
# routes /e/<id>/v1/... only, so a session prefix would turn every call into a 401.
_ENDPOINT_PATH_RE = re.compile(r"^(?:.*/)?e/[A-Za-z0-9_-]{1,128}/v1$")


class ConnectError(Exception):
    """A problem ``connect`` reports to the user (exit code 2). Never carries a secret."""


def default_gateway_url() -> str:
    from pii_guard.config import get_settings

    settings = get_settings()
    host = settings.host
    if host in ("0.0.0.0", "::", ""):  # noqa: S104 - a wildcard bind is reached on loopback
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{settings.port}/v1"


def session_of(url: str) -> str | None:
    """The vault session in a ``.../s/<session>/v1`` gateway URL, if it has one."""
    match = _SESSION_PATH_RE.match(urlsplit(url).path)
    return match.group(2) if match else None


def _without_session(url: str) -> str:
    parts = urlsplit(url.rstrip("/"))
    match = _SESSION_PATH_RE.match(parts.path)
    path = (match.group(1) + (match.group(3) or "")) if match else parts.path
    return urlunsplit(parts._replace(path=path))


def is_endpoint_url(url: str) -> bool:
    """``url`` is a project endpoint base URL, ``{origin}/e/<endpoint>/v1``."""
    return bool(_ENDPOINT_PATH_RE.match(urlsplit(url.rstrip("/")).path))


def session_url(gateway_url: str, existing: str | None = None) -> str:
    """``gateway_url`` with a vault session in its path: ``{root}/s/<session>{path}``.

    ``gateway_url`` may already name one (kept). Otherwise the session of ``existing`` (the
    client's current base URL) is kept when it points at the same gateway, else a new random
    one (``c_`` + 32 hex) is made. The gateway creates the session on first use.
    """
    gateway_url = gateway_url.rstrip("/")
    if session_of(gateway_url) is not None:
        return gateway_url
    session = None
    if existing and _without_session(existing) == gateway_url:
        session = session_of(existing)
    session = session or f"c_{secrets.token_hex(16)}"
    parts = urlsplit(gateway_url)
    return urlunsplit(parts._replace(path=f"/s/{session}{parts.path}"))


def _auth(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def fetch_models(
    gateway_url: str, *, token: str | None = None, client: httpx.Client | None = None
) -> list[str]:
    """The model ids the gateway lists. :class:`ConnectError` if it can't be asked."""
    url = gateway_url.rstrip("/") + "/models"
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=3.0))
    try:
        response = client.get(url, headers=_auth(token))
    except httpx.HTTPError as exc:
        raise ConnectError(
            f"could not reach the gateway at {url} ({type(exc).__name__}); start it with "
            "`pii-guard serve` or pass --model"
        ) from None
    finally:
        if own:
            client.close()
    if response.status_code != 200:
        raise ConnectError(
            f"GET {url} answered HTTP {response.status_code}; check PII_GUARD_UPSTREAM_BASE_URL "
            "(or set PII_GUARD_UPSTREAM_MODELS), or pass --model"
        )
    try:
        data = response.json()["data"]
        ids = [m["id"] for m in data if isinstance(m, dict) and isinstance(m.get("id"), str)]
    except (ValueError, KeyError, TypeError):
        raise ConnectError(f"GET {url} did not return an OpenAI model list") from None
    return list(dict.fromkeys(ids))


def render_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def json_diff(path: Path, old: str | None, new: str) -> str:
    """A unified diff of a config file (empty when nothing changes)."""
    lines = difflib.unified_diff(
        (old or "").splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=str(path) if old is not None else "/dev/null",
        tofile=str(path),
    )
    return "".join(lines)


def _atomic_write(path: Path, data: bytes, *, mode: int = 0o600, gid: int | None = None) -> None:
    """Publish complete bytes atomically; the unpredictable staging file starts private."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.pii-guard-", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            # Restore the authorized group before enabling any group permission. Failure
            # leaves the original intact and the staging file private until cleanup.
            if gid is not None and os.fstat(stream.fileno()).st_gid != gid:
                os.fchown(stream.fileno(), -1, gid)
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _backup(path: Path, data: bytes, stamp: str) -> Path:
    """Create a private backup exclusively: never overwrite or follow an existing name."""
    base = path.with_name(f"{path.name}.pii-guard-backup-{stamp}")
    backup = base
    while True:
        try:
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            backup = base.with_name(f"{base.name}-{secrets.token_hex(8)}")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    return backup


def write_json(path: Path, new: str, *, now: datetime | None = None) -> Path | None:
    """Atomically update config, preserving its mode and group; new files and backups are private.

    Does nothing (and returns ``None``) when the file already has exactly this content.
    Temporary files are created exclusively with unpredictable names and mode 0600;
    backups are also 0600 from creation, including when the original was more permissive.
    """
    try:
        old = path.read_bytes()
        metadata = path.stat()
        mode, gid = stat.S_IMODE(metadata.st_mode), metadata.st_gid
    except FileNotFoundError:
        old, mode, gid = None, 0o600, None
    data = new.encode("utf-8")
    if old == data:
        return None
    backup = None
    if old is not None:
        stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
        backup = _backup(path, old, stamp)
    _atomic_write(path, data, mode=mode, gid=gid)
    return backup


#: A non-200 answer without pii-guard's headers: the URL is something else (the model itself).
NOT_THE_GATEWAY = "no pii-guard headers: is this URL the pii-guard gateway, not the model?"

_SOURCE_NOTES = {
    "header": "X-PII-Guard-Session",
    "path": "the session in the base URL: placeholders stay the same across conversations",
    "prompt_cache_key": "one session per conversation, from its prompt_cache_key",
    "default": "this client's default session",
}


@dataclass
class CheckResult:
    """One canary round trip (``--check``)."""

    url: str
    model: str
    sent: str
    status: int
    model_saw: str = ""
    model_said: str = ""
    received: str = ""
    request_id: str = ""
    error: str = ""
    leaked: list[str] = field(default_factory=list)
    #: ``X-PII-Guard-Session-Source``: which step chose the vault session (LAB-1286).
    session_source: str = ""

    @property
    def masked(self) -> int:
        return len(set(PLACEHOLDER_RE.findall(self.model_saw)))

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.leaked and not self.error and self.masked > 0

    def lines(self) -> list[str]:
        out = [
            f"gateway      : {self.url}",
            f"model        : {self.model}",
            f"sent         : {self.sent}",
        ]
        if self.status != 200 or self.error:
            out.append(f"result       : HTTP {self.status} {self.error}".rstrip())
            return out
        out += [
            f"model saw    : {self.model_saw}",
            f"model said   : {self.model_said}",
            f"you got back : {self.received}",
            f"request id   : {self.request_id}",
        ]
        if self.session_source:
            note = _SOURCE_NOTES.get(self.session_source, "")
            out.append(f"session      : {self.session_source} ({note})")
        if self.leaked:
            out.append(f"LEAK         : {len(self.leaked)} canary value(s) reached the model")
        elif self.masked == 0:
            out.append("WARNING      : nothing was masked (is the gateway in front of the model?)")
        else:
            out.append(
                f"ok           : {self.masked} value(s) masked, none reached the model, "
                "answer restored"
            )
        return out


def run_check(
    base_url: str,
    model: str,
    *,
    headers: Mapping[str, str] | None = None,
    token: str | None = None,
    client: httpx.Client | None = None,
    prompt: str = CANARY_PROMPT,
    values: Sequence[str] = CANARY_VALUES,
) -> CheckResult:
    """Send the canary to ``{base_url}/chat/completions`` as the client would."""
    url = base_url.rstrip("/") + "/chat/completions"
    result = CheckResult(url=url, model=model, sent=prompt, status=0)
    sent_headers = {**(headers or {}), **_auth(token), "X-PII-Guard-Echo": "masked"}
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
    own = client is None
    client = client or httpx.Client(timeout=_TIMEOUT)
    try:
        response = client.post(url, json=body, headers=sent_headers)
    except httpx.HTTPError as exc:
        result.error = f"could not reach {url} ({type(exc).__name__})"
        return result
    finally:
        if own:
            client.close()
    result.status = response.status_code
    result.request_id = response.headers.get("x-pii-guard-request-id", "")
    result.session_source = response.headers.get("x-pii-guard-session-source", "")
    if response.status_code != 200 and not result.request_id:
        result.error = NOT_THE_GATEWAY
        return result
    try:
        answer = response.json()
    except ValueError:
        result.error = "the answer is not JSON"
        return result
    if response.status_code != 200:
        error = answer.get("error") if isinstance(answer, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        result.error = " ".join(str(p) for p in (code, message) if p)
        return result
    echo = answer.get("pii_guard") if isinstance(answer, dict) else None
    if not isinstance(echo, dict):
        result.error = (
            "the answer has no pii_guard echo: is this URL the pii-guard gateway, not the model?"
        )
        return result
    saw = [m.get("content", "") for m in echo.get("masked_messages") or [] if isinstance(m, dict)]
    said = [a.get("content", "") for a in echo.get("masked_answer") or [] if isinstance(a, dict)]
    result.model_saw = " / ".join(str(s) for s in saw)
    result.model_said = " / ".join(str(s) for s in said)
    try:
        result.received = str(answer["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        result.received = ""
    upstream_view = result.model_saw + "\n" + result.model_said
    result.leaked = [v for v in values if v in upstream_view]
    return result
