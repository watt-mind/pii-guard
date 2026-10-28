"""``GET /v1/connect/snippets``: the Connect quickstart's copy-paste blocks.

The web UI's Connect page and ``pii-guard connect <tool> --print`` both show this JSON's
``code`` (:mod:`pii_guard.integrations.snippets`), so the text a user pastes is the same in both.

- ``?session=<id>``: the vault session the blocks put in the gateway URL
  (``/s/<session>/v1``); a new random one (``c_`` + 32 hex) when missing. The page keeps one per
  tool, so it can tell that tool's first request apart.
- ``?model=<id>``: the model the blocks name; otherwise one from ``GET /v1/models``
  (:func:`~pii_guard.integrations.snippets.pick_model`: a Meta Model API model such as
  ``muse-spark-1.3``, never a re-hosted id), falling back to ``muse-spark-1.3``.

``session_ref`` is the session's handle in the traffic log (``null`` while the log is off): the
page watches the live traffic stream for an event with that ``session_ref`` to confirm the
tool's first request ("first request from Codex: 3 values masked"). It's the same
non-reversible handle every traffic event already carries; the session id itself never appears
in the log.

Never a key: the upstream is reported by origin and preset name, keys only as variable names.
"""

from __future__ import annotations

import json
import re
import secrets
from typing import Any

from fastapi import Query, Request

from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import v1_router
from pii_guard.api.routes.models import list_models
from pii_guard.api.routes.status import upstream_origin
from pii_guard.bench.mock_upstream import MODEL as MOCK_MODEL
from pii_guard.integrations import snippets
from pii_guard.types import PiiGuardError
from pii_guard.upstreams import by_url

__all__ = ["router"]

router = v1_router()
router.tags = ["connect"]

_SESSION_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_MODEL_MAX = 256


class InvalidConnectQueryError(PiiGuardError):
    code = "invalid_request"
    status_code = 422


async def _models(request: Request) -> list[str]:
    """The gateway's own ``GET /v1/models`` ids; empty when the upstream can't be asked."""
    try:
        response = await list_models(request)
    except PiiGuardError:
        return []
    if response.status_code != 200:
        return []
    try:
        data = json.loads(bytes(response.body))["data"]
    except (ValueError, KeyError, TypeError):
        return []
    return [m["id"] for m in data if isinstance(m, dict) and isinstance(m.get("id"), str)]


@router.get(
    "/v1/connect/snippets",
    summary="The Connect quickstart: how to start with a model and each tool's copy-paste block",
    responses=error_responses("invalid_request"),
)
async def connect_snippets(
    request: Request,
    session: str | None = Query(
        default=None,
        max_length=128,
        description="The vault session the blocks put in the URL (`/s/<session>/v1`); "
        "new and random when missing.",
    ),
    model: str | None = Query(
        default=None,
        max_length=_MODEL_MAX,
        description="The model the blocks name; default: the gateway's `GET /v1/models`, "
        "preferring a Meta Model API model, else `muse-spark-1.3`.",
    ),
) -> dict[str, Any]:
    """Every tool's paste-and-run block with this gateway's session URL and a model filled in.

    Keys never appear: blocks name them as ``$VARIABLE`` or ``<your-key>``, and the upstream
    is reported by origin and preset name only."""
    if session is not None and not _SESSION_RE.fullmatch(session):
        raise InvalidConnectQueryError("session: letters, digits, '_' and '-' only (1-128)")
    if model is not None and snippets.safe_model(model) is None:
        raise InvalidConnectQueryError("model: not a model id")
    state = request.app.state
    settings = state.settings
    session = session or f"c_{secrets.token_hex(16)}"
    base = str(request.base_url).rstrip("/")
    gateway_url = f"{base}/v1"
    session_url = f"{base}/s/{session}/v1"
    mock = bool(getattr(getattr(state, "up_status", None), "mock", False))
    configured = settings.upstream_base_url
    origin = None if mock else upstream_origin(configured)
    preset = None if mock else by_url(configured)
    models = await _models(request) if (mock or configured) else []
    if model is None:
        model = snippets.pick_model(models, preset, mock_model=MOCK_MODEL if mock else None)
    body = snippets.build(
        gateway_url=gateway_url,
        session_url=session_url,
        session=session,
        models=models,
        model=model,
        token=settings.api_token is not None,
        mock=mock,
        origin=origin,
        preset=preset,
    )
    traffic = getattr(getattr(state, "observability", None), "traffic", None)
    enabled = bool(getattr(traffic, "enabled", False))
    body["traffic_log"] = getattr(getattr(traffic, "level", None), "value", "off")
    body["session_ref"] = traffic.session_ref(session) if enabled and traffic else None
    return body
