"""``POST /v1/responses`` (OpenAI Responses API) and ``GET /muse-code/models``.

``POST /v1/responses`` is :class:`~pii_guard.gateway.responses.ResponsesGateway`: it masks the
request, forwards it to the upstream's own ``/responses`` and restores the (streamed) answer,
on the same detectors, cache and vault as ``/v1/chat/completions`` (``app.state.gateway``).

``GET /muse-code/models`` is the model catalog Muse Code reads first, from the root of its
configured base URL (``http://127.0.0.1:8787/v1`` -> ``http://127.0.0.1:8787/muse-code/models``).
It is the OpenAI model list plus per-model client settings under ``metadata["muse-code"]``
(captured from the Meta Model API, docs/integrations/muse-code.md):

- with ``PII_GUARD_UPSTREAM_MODELS`` set: those ids, with :data:`DEFAULT_MUSE_METADATA`;
- otherwise the upstream's own ``{scheme://host}/muse-code/models`` when it has one (the Meta
  Model API does): ``id``/``object``/``created``/``owned_by`` and the ``muse-code`` metadata
  object are passed on, nothing else;
- otherwise (the upstream answers 404) the gateway's ``GET /v1/models``, with
  :data:`DEFAULT_MUSE_METADATA`.

A catalog carries no request text, so nothing is masked; upstream error messages are never
passed on.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from pii_guard.api.deps import get_max_text_chars
from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import ensure_connected, log_extra, v1_router
from pii_guard.api.routes.chat import GatewayRoute, get_gateway
from pii_guard.api.routes.models import ModelsConfig, list_models
from pii_guard.gateway.request import InvalidChatRequestError
from pii_guard.gateway.responses import ResponsesGateway
from pii_guard.gateway.service import UpstreamError
from pii_guard.gateway.sessions import path_session

__all__ = ["DEFAULT_MUSE_METADATA", "get_responses_gateway", "muse_catalog_url", "router"]

# Same route class as chat (LAB-1566): inline image bodies get the gateway allowance,
# not just the text limit, so Responses image requests reach image validation.
router = v1_router(GatewayRoute)
_lock = threading.Lock()

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_MAX_BODY = 4 * 1024 * 1024
_MAX_MODELS = 1000
_MAX_ID = 256
_MAX_METADATA = 64 * 1024

#: Client settings for a model the upstream doesn't describe: tool calls on, text only, a
#: conservative context window. Muse Code accepts an empty object too (it then uses its own
#: defaults); these keep its context management from assuming more than most models have.
DEFAULT_MUSE_METADATA: dict[str, Any] = {
    "attachment": False,
    "reasoning": True,
    "tool_call": True,
    "temperature": True,
    "modalities": {"input": ["text"], "output": ["text"]},
    "limit": {"context": 128000, "output": 32000},
}


def get_responses_gateway(request: Request) -> ResponsesGateway:
    state = request.app.state
    gateway = get_gateway(request)
    if getattr(state, "hosted", None) is not None or getattr(
        request.state, "project_routed_endpoint", False
    ):
        return ResponsesGateway(gateway)
    responses = getattr(state, "responses_gateway", None)
    if responses is None or responses.gateway is not gateway:
        with _lock:
            responses = getattr(state, "responses_gateway", None)
            if responses is None or responses.gateway is not gateway:
                responses = ResponsesGateway(gateway)
                state.responses_gateway = responses
    return responses


@router.post(
    "/v1/responses",
    tags=["gateway"],
    responses=error_responses("detection_profile_denied", "outbound_check_failed"),
)
async def responses(request: Request) -> Response:
    await ensure_connected(request)
    gateway = get_responses_gateway(request)
    raw = await request.body()
    received_at = time.perf_counter()
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise InvalidChatRequestError("request body is not valid JSON") from None
    response, stats = await gateway.responses(
        body,
        request.headers,
        max_text_chars=get_max_text_chars(request),
        received_at=received_at,
        path_session=path_session(request.scope),
    )
    log_extra(request, **stats.log_fields())
    return response


# --- the Muse Code catalog ---------------------------------------------------------------


def muse_catalog_url(base_url: str) -> str:
    """``{scheme://host}/muse-code/models`` for an upstream base URL."""
    parts = urlsplit(base_url)
    return f"{parts.scheme}://{parts.netloc}/muse-code/models"


def _entry(model: object, metadata: object) -> dict[str, Any] | None:
    if not isinstance(model, dict):
        return None
    model_id = model.get("id")
    if not isinstance(model_id, str) or not model_id or len(model_id) > _MAX_ID:
        return None
    created = model.get("created")
    owned_by = model.get("owned_by")
    if not isinstance(metadata, dict) or len(json.dumps(metadata)) > _MAX_METADATA:
        metadata = dict(DEFAULT_MUSE_METADATA)
    return {
        "id": model_id,
        "object": "model",
        "created": created if isinstance(created, int) and not isinstance(created, bool) else 0,
        "owned_by": owned_by if isinstance(owned_by, str) and len(owned_by) <= _MAX_ID else "",
        "metadata": {"muse-code": metadata},
    }


def _with_default_metadata(models: list[Any]) -> JSONResponse:
    entries = (_entry(m, {"name": m.get("id"), **DEFAULT_MUSE_METADATA}) for m in models)
    return JSONResponse({"object": "list", "data": [e for e in entries if e is not None]})


async def _from_models_route(request: Request) -> JSONResponse:
    listing = await list_models(request)
    if listing.status_code != 200:
        return listing
    data = json.loads(bytes(listing.body)).get("data") or []
    return _with_default_metadata([m for m in data if isinstance(m, dict)])


@router.get("/muse-code/models", tags=["gateway"])
async def muse_code_models(request: Request) -> JSONResponse:
    state = request.app.state
    if getattr(state, "hosted", None) is not None or getattr(
        request.state, "project_routed_endpoint", False
    ):
        # One catalog implementation applies the same connection ownership and egress policy.
        return await _from_models_route(request)
    config = getattr(state, "models_config", None) or ModelsConfig()
    settings = state.settings
    if config.upstream_models or not settings.upstream_base_url:
        # A static list, or no upstream: /v1/models answers (or explains the 503).
        return await _from_models_route(request)
    headers = {"Accept": "application/json"}
    key = settings.upstream_api_key
    if key is not None:
        headers["Authorization"] = f"Bearer {key.get_secret_value()}"
    elif request.headers.get("authorization"):
        headers["Authorization"] = request.headers["authorization"]
    transport = getattr(state, "gateway_transport", None)
    async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport) as client:
        try:
            response = await client.get(
                muse_catalog_url(settings.upstream_base_url), headers=headers
            )
        except httpx.HTTPError as exc:
            raise UpstreamError(f"upstream model catalog failed ({type(exc).__name__})") from None
    if response.status_code in (404, 405):
        return await _from_models_route(request)
    if response.status_code >= 400:
        return JSONResponse(
            {
                "error": {
                    "code": "upstream_error",
                    "message": f"upstream returned HTTP {response.status_code} for "
                    "/muse-code/models",
                    "type": "upstream_error",
                }
            },
            status_code=response.status_code if response.status_code < 500 else 502,
        )
    if len(response.content) > _MAX_BODY:
        raise UpstreamError("upstream model catalog is too large")
    try:
        data = response.json().get("data")
    except (ValueError, AttributeError):
        raise UpstreamError("upstream model catalog is not a JSON object") from None
    if not isinstance(data, list):
        raise UpstreamError("upstream model catalog has no data array")
    entries = []
    for model in data[:_MAX_MODELS]:
        metadata = model.get("metadata") if isinstance(model, dict) else None
        muse = metadata.get("muse-code") if isinstance(metadata, dict) else None
        entry = _entry(model, muse)
        if entry is not None:
            entries.append(entry)
    return JSONResponse({"object": "list", "data": entries})
