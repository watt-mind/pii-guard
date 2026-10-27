"""What every ``pii-guard connect`` client shares.

- :func:`default_gateway_url`: ``http://127.0.0.1:<PII_GUARD_PORT>/v1`` (a wildcard bind such
  as ``0.0.0.0`` is reached on loopback).
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
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from pii_guard.vault.placeholders import PLACEHOLDER_RE

__all__ = [
    "CANARY_PROMPT",
    "CANARY_VALUES",
    "DASHBOARD_URL",
    "CheckResult",
    "ConnectError",
    "default_gateway_url",
    "fetch_models",
    "json_diff",
    "render_json",
    "run_check",
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


def write_json(path: Path, new: str, *, now: datetime | None = None) -> Path | None:
    """Write ``new`` to ``path``; back up an existing file first. Returns the backup's path.

    Does nothing (and returns ``None``) when the file already has exactly this content.
    """
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == new:
        return None
    backup = None
    if old is not None:
        stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.pii-guard-backup-{stamp}")
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".pii-guard-tmp")
    tmp.write_text(new, encoding="utf-8")
    tmp.replace(path)
    return backup


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
