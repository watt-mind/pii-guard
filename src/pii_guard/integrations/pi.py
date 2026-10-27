"""pi (``@earendil-works/pi-coding-agent``) behind the gateway.

pi reads custom providers from ``models.json`` in its agent directory (``$PI_CODING_AGENT_DIR``,
default ``~/.pi/agent``). :func:`provider_entry` builds a ``pii-guard`` provider:

- ``baseUrl``: the gateway (``http://127.0.0.1:8787/v1``), ``api: "openai-completions"``;
- ``apiKey``: ``$PII_GUARD_API_TOKEN`` when the gateway requires a token (pi resolves ``$NAME``
  from the environment at request time), else a placeholder pi needs to list the models; the
  gateway sends its own ``PII_GUARD_UPSTREAM_API_KEY`` upstream;
- ``headers``: ``X-PII-Guard-Mode: fast`` (rules + NER: agent turns are many and long, audit
  mode's LLM detector would add its latency to every one) and ``X-PII-Guard-Language``;
- ``compat``: ``supportsDeveloperRole: false`` (system prompts go as ``system``, which every
  OpenAI-compatible server accepts) and ``supportsStore: false`` (pi otherwise sends
  ``store``, which only OpenAI itself understands). The gateway forwards both fields; the flags
  are for the upstreams behind it;
- ``models``: the gateway's ``GET /v1/models``, or ``--model``.

:func:`merge` replaces only ``providers["pii-guard"]``; every other provider and top-level key
of the file is kept as is. :func:`render` writes that back while keeping the rest of the file's
text byte for byte (hand-formatted files stay hand-formatted): it splices the provider into the
``providers`` object, and falls back to re-serialising the whole file only when it can't.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pii_guard.integrations.common import ConnectError, render_json

__all__ = [
    "PROVIDER_ID",
    "SCHEMA_URL",
    "config_path",
    "load",
    "merge",
    "provider_entry",
    "render",
    "resolve_value",
]

PROVIDER_ID = "pii-guard"
SCHEMA_URL = "https://pi.dev/schemas/models.schema.json"
PLACEHOLDER_KEY = "pii-guard"


def config_path(agent_dir: str | os.PathLike[str] | None = None) -> Path:
    """``models.json`` in ``agent_dir``, ``$PI_CODING_AGENT_DIR`` or ``~/.pi/agent``."""
    if agent_dir is not None:
        return Path(agent_dir).expanduser() / "models.json"
    env = os.environ.get("PI_CODING_AGENT_DIR")
    base = Path(env).expanduser() if env else Path.home() / ".pi" / "agent"
    return base / "models.json"


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
    providers = data.get("providers")
    if providers is not None and not isinstance(providers, dict):
        raise ConnectError(f"{path}: providers must be an object")
    return data, raw


def provider_entry(
    gateway_url: str,
    models: Sequence[str],
    *,
    mode: str = "fast",
    language: str = "en",
    api_key: str | None = None,
) -> dict[str, Any]:
    return {
        "name": "pii-guard",
        "baseUrl": gateway_url.rstrip("/"),
        "api": "openai-completions",
        "apiKey": api_key or PLACEHOLDER_KEY,
        "headers": {"X-PII-Guard-Mode": mode, "X-PII-Guard-Language": language},
        "compat": {"supportsDeveloperRole": False, "supportsStore": False},
        "models": [{"id": model, "name": f"{model} (pii-guard)"} for model in models],
    }


def merge(existing: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    """``existing`` with ``providers["pii-guard"]`` set to ``entry`` (a new dict)."""
    out: dict[str, Any] = dict(existing) if existing else {"$schema": SCHEMA_URL}
    providers = dict(out.get("providers") or {})
    providers[PROVIDER_ID] = dict(entry)
    out["providers"] = providers
    return out


def resolve_value(value: str | None) -> str | None:
    """pi's ``$NAME`` / ``${NAME}`` interpolation for ``apiKey`` and header values.

    ``!command`` values are not run here (``--check`` never executes config): ``None``.
    """
    if value is None:
        return None
    if value.startswith("!"):
        return None
    if value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1])
    if value.startswith("$") and not value.startswith("$$"):
        return os.environ.get(value[1:])
    return value.replace("$$", "$")


# --- format-preserving write -------------------------------------------------------------


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return i


def _string_end(text: str, i: int) -> int:
    """``text[i]`` is ``"``: the index after the closing quote."""
    i += 1
    while text[i] != '"':
        i += 2 if text[i] == "\\" else 1
    return i + 1


def _value_end(text: str, i: int) -> int:
    """The index after the JSON value that starts at ``i``."""
    if text[i] == '"':
        return _string_end(text, i)
    if text[i] not in "{[":
        while i < len(text) and text[i] not in ",}] \t\r\n":
            i += 1
        return i
    depth = 0
    while True:
        char = text[i]
        if char == '"':
            i = _string_end(text, i)
            continue
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1


def _members(text: str, start: int) -> tuple[list[tuple[str, int, int, int]], int]:
    """Members of the object at ``start``: ``(key, key_start, value_start, value_end)``, and
    the index of its closing brace."""
    members = []
    i = _skip_ws(text, start + 1)
    while text[i] != "}":
        key_end = _string_end(text, i)
        key = json.loads(text[i:key_end])
        colon = _skip_ws(text, key_end)
        value_start = _skip_ws(text, colon + 1)
        value_end = _value_end(text, value_start)
        members.append((key, i, value_start, value_end))
        i = _skip_ws(text, value_end)
        if text[i] == ",":
            i = _skip_ws(text, i + 1)
    return members, i


def _indent_of(text: str, i: int) -> str:
    line_start = text.rfind("\n", 0, i) + 1
    prefix = text[line_start:i]
    return prefix if not prefix.strip() else ""


def _block(entry: Mapping[str, Any], indent: str) -> str:
    return json.dumps(entry, indent=2, ensure_ascii=False).replace("\n", "\n" + indent)


def _splice(raw: str, entry: Mapping[str, Any]) -> str:
    top = _skip_ws(raw, 0)
    if raw[top] != "{":
        raise ValueError("not an object")
    members, _ = _members(raw, top)
    providers = next((m for m in members if m[0] == "providers"), None)
    if providers is None or raw[providers[2]] != "{":
        raise ValueError("no providers object")
    inner, close = _members(raw, providers[2])
    ours = next((m for m in inner if m[0] == PROVIDER_ID), None)
    if ours is not None:
        indent = _indent_of(raw, ours[1])
        return raw[: ours[2]] + _block(entry, indent) + raw[ours[3] :]
    outer = _indent_of(raw, providers[1])
    if not inner:
        indent = outer + "  "
        text = f"\n{indent}{json.dumps(PROVIDER_ID)}: {_block(entry, indent)}\n{outer}"
        return raw[: providers[2] + 1] + text + raw[close:]
    last_end = inner[-1][3]
    indent = _indent_of(raw, inner[-1][1]) or outer + "  "
    text = f",\n{indent}{json.dumps(PROVIDER_ID)}: {_block(entry, indent)}"
    return raw[:last_end] + text + raw[last_end:]


def render(existing: Mapping[str, Any], raw: str | None, entry: Mapping[str, Any]) -> str:
    """The new ``models.json`` text: ``raw`` with the provider spliced in, else re-rendered."""
    merged = merge(existing, entry)
    if raw is not None and raw.strip():
        try:
            spliced = _splice(raw, entry)
            if json.loads(spliced) == merged:
                return spliced
        except (ValueError, IndexError):
            pass
    return render_json(merged)
