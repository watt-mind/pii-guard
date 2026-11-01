"""Muse Code (Meta's coding agent) behind the gateway.

Checked on Muse Code ``MUSE_VERSION_CHECKED`` (``muse --version``), installed with the
official installer into a throwaway ``HOME`` (docs/integrations/muse-code.md):

- Muse Code reads ``settings.json`` in ``$XDG_CONFIG_HOME/muse`` (default ``~/.config/muse``).
  :func:`render` sets ``endpoint_transport.base_url`` to the gateway and pins
  ``endpoint_transport.auth`` to ``"bearer"`` (without the pin Muse withholds its key from a
  non-Meta base URL); every other key of the file, and of ``endpoint_transport``
  (``proxy``, ``ca_bundle``), is kept.
- Its ``meta`` provider speaks the OpenAI **Responses API**: ``GET <host>/muse-code/models``
  (the catalog, at the root of the base URL), then streamed ``POST <base_url>/responses``. The
  gateway serves both (:mod:`pii_guard.api.routes.responses`).
- Muse sends ``META_API_KEY`` (or its saved key) as the bearer token. With
  ``PII_GUARD_UPSTREAM_API_KEY`` unset, the gateway passes that key on to the Meta Model API;
  with it set, the gateway sends its own.
- Muse can't send ``X-PII-Guard-Mode``: run the gateway with ``PII_GUARD_GATEWAY_MODE=fast``
  (rules + NER), or every agent turn waits for strict mode's LLM detector.

:func:`run_check` sends one fictional canary the way Muse does (non-streamed, so the gateway
can echo the masked boundary) and reports what the model saw and what came back.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from pii_guard.integrations.common import (
    CANARY_PROMPT,
    CANARY_VALUES,
    NOT_THE_GATEWAY,
    CheckResult,
    ConnectError,
    render_json,
)

__all__ = [
    "MUSE_VERSION_CHECKED",
    "config_path",
    "fetch_catalog",
    "load",
    "merge",
    "render",
    "run_check",
]

MUSE_VERSION_CHECKED = "1.4.14-R7309.1"
SCHEMA_VERSION = 1
MODE_NOTE = (
    "Muse Code can't send X-PII-Guard-Mode: start the gateway with PII_GUARD_GATEWAY_MODE=fast "
    "(rules + NER), or every turn waits for strict mode's LLM detector"
)

_TIMEOUT = httpx.Timeout(120.0, connect=5.0)


def config_path(config_dir: str | os.PathLike[str] | None = None) -> Path:
    """``settings.json`` in ``config_dir``, ``$XDG_CONFIG_HOME/muse`` or ``~/.config/muse``."""
    if config_dir is not None:
        return Path(config_dir).expanduser() / "settings.json"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "muse" / "settings.json"


def load(path: Path) -> tuple[dict[str, Any], str | None]:
    """The parsed file and its raw text (``({}, None)`` when it doesn't exist)."""
    if not path.exists():
        return {}, None
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}, raw
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ConnectError(
            f"{path} is not valid JSON (line {getattr(exc, 'lineno', '?')}); fix it or move it "
            "away, then run connect again"
        ) from None
    if not isinstance(data, dict):
        raise ConnectError(f"{path} must hold a JSON object")
    transport = data.get("endpoint_transport")
    if transport is not None and not isinstance(transport, dict):
        raise ConnectError(f"{path}: endpoint_transport must be an object")
    return data, raw


def merge(
    existing: Mapping[str, Any], gateway_url: str, *, model: str | None = None
) -> dict[str, Any]:
    """``existing`` with ``endpoint_transport`` pointed at the gateway (a new dict)."""
    out: dict[str, Any] = dict(existing)
    out.setdefault("schema_version", SCHEMA_VERSION)
    if model is not None:
        out["model"] = model
    transport = dict(out.get("endpoint_transport") or {})
    transport["base_url"] = gateway_url.rstrip("/")
    transport["auth"] = "bearer"
    out["endpoint_transport"] = transport
    return out


def render(
    existing: Mapping[str, Any],
    raw: str | None,
    gateway_url: str,
    *,
    model: str | None = None,
) -> str:
    """The new ``settings.json`` text (unchanged text when it already points at the gateway)."""
    merged = merge(existing, gateway_url, model=model)
    if raw is not None and raw.strip() and json.loads(raw) == merged:
        return raw
    return render_json(merged)


def catalog_url(base_url: str) -> str:
    """Where Muse reads its catalog: ``{scheme://host}/muse-code/models``."""
    parts = urlsplit(base_url)
    return f"{parts.scheme}://{parts.netloc}/muse-code/models"


def fetch_catalog(
    base_url: str, *, token: str | None = None, client: httpx.Client | None = None
) -> list[str]:
    """The visible model ids of the catalog Muse would read. :class:`ConnectError` if none."""
    url = catalog_url(base_url)
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=3.0))
    try:
        response = client.get(url, headers=_auth(token))
    except httpx.HTTPError as exc:
        raise ConnectError(f"could not reach {url} ({type(exc).__name__})") from None
    finally:
        if own:
            client.close()
    if response.status_code != 200:
        raise ConnectError(f"GET {url} answered HTTP {response.status_code}")
    try:
        data = response.json()["data"]
    except (ValueError, KeyError, TypeError):
        raise ConnectError(f"GET {url} did not return a model catalog") from None
    ids = []
    for model in data if isinstance(data, list) else []:
        if not isinstance(model, dict) or not isinstance(model.get("id"), str):
            continue
        metadata = (model.get("metadata") or {}).get("muse-code") or {}
        if isinstance(metadata, dict) and metadata.get("is_hidden"):
            continue
        ids.append(model["id"])
    if not ids:
        raise ConnectError(f"GET {url} lists no visible models; pass --model")
    return ids


def _auth(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return ""


def run_check(
    base_url: str,
    model: str,
    *,
    token: str | None = None,
    client: httpx.Client | None = None,
    prompt: str = CANARY_PROMPT,
    values: Sequence[str] = CANARY_VALUES,
) -> tuple[CheckResult, str]:
    """The canary through ``{base_url}/responses``; also the gateway mode that served it."""
    url = base_url.rstrip("/") + "/responses"
    result = CheckResult(url=url, model=model, sent=prompt, status=0)
    body = {
        "model": model,
        "input": [{"type": "message", "role": "user", "content": prompt}],
        "store": False,
        "stream": False,
    }
    headers = {**_auth(token), "X-PII-Guard-Echo": "masked"}
    own = client is None
    client = client or httpx.Client(timeout=_TIMEOUT)
    try:
        response = client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        result.error = f"could not reach {url} ({type(exc).__name__})"
        return result, ""
    finally:
        if own:
            client.close()
    result.status = response.status_code
    result.request_id = response.headers.get("x-pii-guard-request-id", "")
    result.session_source = response.headers.get("x-pii-guard-session-source", "")
    mode = response.headers.get("x-pii-guard-mode", "")
    if response.status_code != 200 and not result.request_id:
        result.error = NOT_THE_GATEWAY
        return result, mode
    try:
        answer = response.json()
    except ValueError:
        result.error = "the answer is not JSON"
        return result, mode
    if response.status_code != 200:
        error = answer.get("error") if isinstance(answer, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        result.error = " ".join(str(p) for p in (code, message) if p)
        return result, mode
    echo = answer.get("pii_guard") if isinstance(answer, dict) else None
    if not isinstance(echo, dict):
        result.error = (
            "the answer has no pii_guard echo: is this URL the pii-guard gateway, not the model?"
        )
        return result, mode
    saw = [i.get("content", "") for i in echo.get("masked_input") or [] if isinstance(i, dict)]
    said = [o.get("content", "") for o in echo.get("masked_output") or [] if isinstance(o, dict)]
    result.model_saw = " / ".join(str(s) for s in saw)
    result.model_said = " / ".join(str(s) for s in said)
    result.received = " / ".join(
        _text(item.get("content"))
        for item in answer.get("output") or []
        if isinstance(item, dict) and item.get("type") == "message"
    )
    upstream_view = result.model_saw + "\n" + result.model_said
    result.leaked = [v for v in values if v in upstream_view]
    return result, mode
