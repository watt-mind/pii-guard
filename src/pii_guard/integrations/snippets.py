"""The Connect quickstart's copy-paste blocks: one source for the web UI and the CLI.

``GET /v1/connect/snippets`` (:mod:`pii_guard.api.routes.connect`) serves :func:`build`'s JSON
to the web UI's Connect page; ``pii-guard connect <tool> --print`` prints the same ``code``.

Every block is filled in with the gateway's session URL (``http://127.0.0.1:8787/s/<session>/v1``,
LAB-1286: the same value keeps the same placeholder across turns, and Connect recognises the
tool's first request by that session) and a model id from ``GET /v1/models``.

How each tool is pointed at the gateway (each checked on the version in :data:`TESTED`):

- **Codex**: a launch command, no config file. ``-c`` overrides define a ``pii-guard`` model
  provider (``base_url``, ``wire_api = "responses"``) and select it; ``web_search`` is off,
  because the hosted search tool runs at the provider on text the gateway never sees (the
  gateway refuses it).
- **OpenCode**: one environment variable, ``OPENCODE_CONFIG_CONTENT``, holding an inline config
  with a ``pii-guard`` provider (``@ai-sdk/openai-compatible``, Chat Completions).
- **Muse Code** and **pi** read their endpoint only from a config file, so their block runs
  ``pii-guard connect <tool>`` first (backup, idempotent) and then starts the tool.
- **cURL** and **Python** (OpenAI SDK): one fictional request; cURL also through the Responses
  API (``POST /responses`` with ``input_text`` parts, the masked view echoed back).
- **Claude Code** speaks the Anthropic Messages API, which the gateway doesn't serve yet.

No block carries a secret: keys appear as ``$VARIABLE`` names or ``<your-key>``.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from typing import Any

from pii_guard.integrations.muse_code import MUSE_VERSION_CHECKED
from pii_guard.upstreams import PRESETS, Upstream

__all__ = [
    "CODEX_VERSION",
    "OPENCODE_VERSION",
    "PI_VERSION",
    "TESTED",
    "TOOL_IDS",
    "build",
    "chat_models",
    "pick_model",
    "printable",
    "safe_model",
    "tool_snippet",
]

PI_VERSION = "1.4.0"
CODEX_VERSION = "0.163.0"
OPENCODE_VERSION = "1.19.3"
#: Tool id -> the version its e2e test pins (docs/integrations/README.md).
TESTED = {
    "muse-code": MUSE_VERSION_CHECKED,
    "pi": PI_VERSION,
    "codex": CODEX_VERSION,
    "opencode": OPENCODE_VERSION,
}
TOKEN_ENV = "PII_GUARD_API_TOKEN"  # noqa: S105 - the variable's name, not a token
MODEL_PLACEHOLDER = "<model-id>"
#: The fictional request the cURL and Python blocks send (ADR 0005).
#: No free-text name: on a rules-only server (no NER) a name would reach the model as written.
SAMPLE_PROMPT = (
    "Write a two-line note to jane.placeholder@example.net (phone +44 20 7946 0958) "
    "confirming the appointment."
)

_DOCS = "https://github.com/watt-mind/pii-guard/blob/develop/docs/integrations/"


@dataclass(frozen=True)
class _Tool:
    id: str
    label: str
    api: str  # "responses", "chat" or "messages"
    #: ``launch`` (env/flags only), ``connect`` (writes a config file first), ``request`` (one
    #: request by hand) or ``unsupported``.
    kind: str
    docs: str | None = None


_TOOLS = (
    _Tool("muse-code", "Muse Code", "responses", "connect", "muse-code.md"),
    _Tool("pi", "pi", "chat", "connect", "pi.md"),
    _Tool("codex", "Codex", "responses", "launch", "codex.md"),
    _Tool("opencode", "OpenCode", "chat", "launch", "opencode.md"),
    _Tool("curl", "cURL", "chat", "request"),
    _Tool("python", "Python", "chat", "request"),
    _Tool("claude-code", "Claude Code", "messages", "unsupported"),
)
TOOL_IDS = tuple(t.id for t in _TOOLS)


def _q(value: str) -> str:
    return shlex.quote(value)


def _muse(url: str, model: str, token: bool) -> tuple[str, str]:
    code = (
        "# Muse needs META_API_KEY set (any value works when the gateway holds the key)\n"
        f"pii-guard connect muse-code --gateway {_q(url)}\n"
        "muse"
    )
    note = (
        "Muse Code reads its endpoint only from settings.json, so this writes it first "
        "(endpoint_transport, backup kept, --dry-run to preview). It can't send a masking mode: "
        "pii-guard up runs fast mode already."
    )
    return code, note


def _pi(url: str, model: str, token: bool) -> tuple[str, str]:
    code = (
        f"pii-guard connect pi --gateway {_q(url)} --model {_q(model)}\n"
        f"pi --provider pii-guard --model {_q(model)}"
    )
    note = (
        "pi reads custom providers only from ~/.pi/agent/models.json, so this adds a pii-guard "
        "provider there first (backup kept, --dry-run to preview)."
        + (f" It writes ${TOKEN_ENV} as the key: export it first." if token else "")
    )
    return code, note


def _codex(url: str, model: str, token: bool) -> tuple[str, str]:
    provider = f'name="pii-guard", base_url="{url}", wire_api="responses"'
    if token:
        provider += f', env_key="{TOKEN_ENV}"'
    code = (
        f"codex -m {_q(model)} \\\n"
        "  -c model_provider=pii-guard \\\n"
        f"  -c {_q('model_providers.pii-guard={' + provider + '}')} \\\n"
        "  -c web_search=disabled"
    )
    note = (
        "No config file: the -c flags define a pii-guard provider for this run (Responses API). "
        "Web search stays off: it runs at the provider on text the gateway never sees. "
        'For one task without the UI, add exec "<task>" at the end.'
    )
    return code, note


def _opencode(url: str, model: str, token: bool) -> tuple[str, str]:
    options: dict[str, Any] = {"baseURL": url}
    if token:
        options["apiKey"] = "{env:" + TOKEN_ENV + "}"
    config = {
        "provider": {
            "pii-guard": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "pii-guard",
                "options": options,
                "models": {model: {}},
            }
        },
        "model": f"pii-guard/{model}",
    }
    code = (
        f"export OPENCODE_CONFIG_CONTENT={_q(json.dumps(config, separators=(',', ':')))}\nopencode"
    )
    note = (
        "No config file: OpenCode merges OPENCODE_CONFIG_CONTENT into its config, adding a "
        "pii-guard provider (Chat Completions) and making it the default model."
    )
    return code, note


def _curl(url: str, model: str, token: bool) -> tuple[str, str]:
    body = {"model": model, "messages": [{"role": "user", "content": SAMPLE_PROMPT}]}
    auth = f' \\\n  -H "Authorization: Bearer ${TOKEN_ENV}"' if token else ""
    code = (
        f"curl -si {url}/chat/completions \\\n"
        f'  -H "Content-Type: application/json"{auth} \\\n'
        f"  -d {_q(json.dumps(body))}"
    )
    note = (
        "-i shows the headers: X-PII-Guard-Masked counts the values masked before the request "
        "left this machine."
    )
    return code, note


def _curl_responses(url: str, model: str, token: bool) -> str:
    """The same request through the Responses API (``POST /responses``, as Muse and Codex
    send), with ``X-PII-Guard-Echo: masked``: the answer's ``pii_guard`` field shows the
    ``masked_input`` the model saw and its ``masked_output``."""
    body = {
        "model": model,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": SAMPLE_PROMPT}]}],
        "stream": False,
    }
    auth = f' \\\n  -H "Authorization: Bearer ${TOKEN_ENV}"' if token else ""
    return (
        f"curl -s {url}/responses \\\n"
        f'  -H "Content-Type: application/json" -H "X-PII-Guard-Echo: masked"{auth} \\\n'
        f"  -d {_q(json.dumps(body))}"
    )


#: Further blocks a tab shows under its main one: ``(tool, title, render)``.
_MORE = {"curl": (("Responses API", _curl_responses),)}


def _python(url: str, model: str, token: bool) -> tuple[str, str]:
    key = f'os.environ["{TOKEN_ENV}"]' if token else '"unused"'
    code = (
        ("import os\n" if token else "") + "from openai import OpenAI\n\n"
        f'client = OpenAI(base_url="{url}", api_key={key})\n'
        "reply = client.chat.completions.create(\n"
        f'    model="{model}",\n'
        f'    messages=[{{"role": "user", "content": "{SAMPLE_PROMPT}"}}],\n'
        ")\n"
        "print(reply.choices[0].message.content)"
    )
    note = "pip install openai. " + (
        "The gateway checks the token."
        if token
        else "The gateway holds the upstream key, so the client's key is not used."
    )
    return code, note


def _claude(url: str, model: str, token: bool) -> tuple[str, str]:
    note = (
        "Coming soon. Claude Code speaks the Anthropic Messages API (POST /v1/messages); the "
        "gateway serves the OpenAI APIs, so pointing ANTHROPIC_BASE_URL at it would fail every "
        "request rather than mask it."
    )
    return "", note


_RENDER = {
    "muse-code": _muse,
    "pi": _pi,
    "codex": _codex,
    "opencode": _opencode,
    "curl": _curl,
    "python": _python,
    "claude-code": _claude,
}


_MODEL_RE = re.compile(r"[A-Za-z0-9._:/@+-]{1,256}")


def safe_model(model: str | None) -> str | None:
    """``model`` when it can go into a shell, TOML, JSON and Python string as is, else ``None``."""
    return model if model is not None and _MODEL_RE.fullmatch(model) else None


def tool_snippet(tool_id: str, url: str, model: str | None, *, token: bool) -> dict[str, Any]:
    """One tool's block for the session URL ``url``."""
    tool = next(t for t in _TOOLS if t.id == tool_id)
    url = url.rstrip("/")
    name = safe_model(model) or MODEL_PLACEHOLDER
    code, note = _RENDER[tool.id](url, name, token)
    more = [
        {"title": title, "code": render(url, name, token)}
        for title, render in _MORE.get(tool.id, ())
    ]
    return {
        "id": tool.id,
        "label": tool.label,
        "api": tool.api,
        "kind": tool.kind,
        "supported": tool.kind != "unsupported",
        "code": code,
        "note": note,
        "tested_version": TESTED.get(tool.id),
        "docs": _DOCS + tool.docs if tool.docs else None,
        "more": more,
    }


def printable(tool: dict[str, Any]) -> str:
    """What ``connect <tool> --print`` prints: the main block, then each further one under a
    ``# <title>`` line."""
    parts = [str(tool.get("code") or "")]
    for extra in tool.get("more") or []:
        if isinstance(extra, dict) and extra.get("code"):
            parts.append(f"# {extra.get('title')}\n{extra['code']}")
    return "\n\n".join(p for p in parts if p)


#: The model a block names when the gateway lists nothing usable (the owner's choice: the
#: Meta Model API's chat model, never a re-hosted id such as Baseten's ``meta-models/...``).
FALLBACK_MODEL = "muse-spark-1.3"
#: Meta Model API ids a coding agent can chat with (not ``muse-image``/``muse-voice``/``sam``).
_META_CHAT_RE = re.compile(r"muse-(spark|wonder)-[0-9.]+")


_NOT_FOR_CHAT = ("meta-models/", "muse-image-", "muse-voice-", "sam-")


def chat_models(models: list[str]) -> list[str]:
    """The ids a block may name: safe to paste, and not a Meta image, voice or segmentation
    model nor a re-hosted ``meta-models/...`` copy (the owner's rule: Meta Model API ids)."""
    return [m for m in models if safe_model(m) and not m.startswith(_NOT_FOR_CHAT)]


def pick_model(models: list[str], preset: Upstream | None, *, mock_model: str | None) -> str:
    """The model a block names, from the gateway's ``GET /v1/models``.

    In order: the preset's suggestion when listed; the mock's model (offline mock); for an
    OpenAI, Fireworks or OpenRouter preset, the first listed; else a Meta Model API chat model
    listed (``muse-spark-*``, ``muse-wonder-*``); else the first other model, never a re-hosted
    ``meta-models/...`` id; else :data:`FALLBACK_MODEL`.
    """
    models = chat_models(models)
    if preset is not None and preset.default_model in models:
        return preset.default_model
    if mock_model is not None and mock_model in models:
        return mock_model
    if preset is not None and preset.default_model is None and models:
        return models[0]
    meta = [m for m in models if _META_CHAT_RE.fullmatch(m)]
    if meta:
        return FALLBACK_MODEL if FALLBACK_MODEL in meta else meta[0]
    # Another upstream (a local model, say): its own first model, but never a re-hosted copy of
    # a Meta model (``meta-models/...``) nor one of Meta's non-chat models.
    other = [m for m in models if not m.startswith("muse-")]
    return other[0] if other else FALLBACK_MODEL


def build(
    *,
    gateway_url: str,
    session_url: str,
    session: str,
    models: list[str],
    model: str | None,
    token: bool,
    mock: bool,
    origin: str | None,
    preset: Upstream | None,
) -> dict[str, Any]:
    """The whole quickstart: how to start the gateway with a model, and every tool's block."""
    return {
        "gateway_url": gateway_url,
        "session": session,
        "session_url": session_url,
        "models": chat_models(models),
        "model": safe_model(model),
        "auth": {"token_required": token, "token_env": TOKEN_ENV},
        "upstream": {
            "connected": not mock and origin is not None,
            "mock": mock,
            "origin": origin,
            "preset": preset.id if preset is not None else None,
            "label": preset.label if preset is not None else None,
        },
        "presets": [p.public() for p in PRESETS.values()],
        "tools": [tool_snippet(t, session_url, model, token=token) for t in TOOL_IDS],
    }
