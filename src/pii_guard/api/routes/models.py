"""``GET /v1/models``: the models a client can ask the gateway for.

Coding agents and ``pii-guard connect`` read this list to configure themselves. It comes from:

- ``PII_GUARD_UPSTREAM_MODELS`` (comma-separated ids), when set: a static list, the upstream
  is not called. Use it for upstreams without a ``/models`` route.
- otherwise the upstream's own ``GET {PII_GUARD_UPSTREAM_BASE_URL}/models`` (a base URL that
  ends in ``/chat/completions`` loses that suffix first), sent with
  ``PII_GUARD_UPSTREAM_API_KEY`` or, without one, the client's own ``Authorization`` header,
  as the gateway does.

Only ``id``, ``object``, ``created`` and ``owned_by`` of each model are passed on: providers
attach their own metadata (prices, limits, client settings) that clients of an
OpenAI-compatible endpoint don't need. A model list carries no request text, so nothing is
masked; the upstream's error messages are still never passed on (they are not needed and the
gateway's rule is to drop them).

The upstream transport is ``app.state.gateway_transport`` when set (tests), like the gateway's.
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from pii_guard.api.routes._common import v1_router
from pii_guard.gateway.service import UpstreamError, UpstreamNotConfiguredError

__all__ = ["ModelsConfig", "models_url", "router"]

router = v1_router()

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_MAX_BODY = 4 * 1024 * 1024
_MAX_MODELS = 1000
_MAX_ID = 256


class ModelsConfig(BaseSettings):
    """``PII_GUARD_UPSTREAM_MODELS``: a static model list instead of asking the upstream."""

    model_config = SettingsConfigDict(
        env_prefix="PII_GUARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        populate_by_name=True,
    )

    upstream_models: Annotated[tuple[str, ...], NoDecode] = Field(
        default=(), validation_alias="PII_GUARD_UPSTREAM_MODELS"
    )

    @field_validator("upstream_models", mode="before")
    @classmethod
    def _split(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value


def models_url(base_url: str) -> str:
    """``{base}/models`` for an upstream base URL (with or without ``/chat/completions``)."""
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return base + "/models"


def _model(entry: object) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    model_id = entry.get("id")
    if not isinstance(model_id, str) or not model_id or len(model_id) > _MAX_ID:
        return None
    created = entry.get("created")
    owned_by = entry.get("owned_by")
    return {
        "id": model_id,
        "object": "model",
        "created": created if isinstance(created, int) and not isinstance(created, bool) else 0,
        "owned_by": owned_by if isinstance(owned_by, str) and len(owned_by) <= _MAX_ID else "",
    }


def _listing(models: list[dict[str, Any]]) -> dict[str, Any]:
    return {"object": "list", "data": models}


@router.get("/v1/models", tags=["gateway"])
async def list_models(request: Request) -> JSONResponse:
    endpoint = getattr(request.state, "project_endpoint", None)
    if endpoint is not None and getattr(request.state, "project_routed_endpoint", False):
        return JSONResponse(
            _listing([_model({"id": endpoint.model, "owned_by": endpoint.provider})])
        )
    state = request.app.state
    hosted = getattr(state, "hosted", None)
    if hosted is not None:
        return await _hosted_models(request)
    config = getattr(state, "models_config", None) or ModelsConfig()
    if config.upstream_models:
        models = [_model({"id": m, "owned_by": "pii-guard"}) for m in config.upstream_models]
        return JSONResponse(_listing([m for m in models if m is not None]))

    settings = state.settings
    if not settings.upstream_base_url:
        raise UpstreamNotConfiguredError(
            "PII_GUARD_UPSTREAM_BASE_URL is not set; set it or PII_GUARD_UPSTREAM_MODELS"
        )
    headers = {"Accept": "application/json"}
    key = settings.upstream_api_key
    if key is not None:
        headers["Authorization"] = f"Bearer {key.get_secret_value()}"
    elif request.headers.get("authorization"):
        headers["Authorization"] = request.headers["authorization"]

    transport = getattr(state, "gateway_transport", None)
    async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport) as client:
        try:
            response = await client.get(models_url(settings.upstream_base_url), headers=headers)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"upstream model list failed ({type(exc).__name__})") from None
    if response.status_code >= 400:
        # The upstream's status (401 for a bad key, 404 for no /models route), not its message.
        return JSONResponse(
            {
                "error": {
                    "code": "upstream_error",
                    "message": f"upstream returned HTTP {response.status_code} for /models; "
                    "set PII_GUARD_UPSTREAM_MODELS for a static list",
                    "type": "upstream_error",
                }
            },
            status_code=response.status_code if response.status_code < 500 else 502,
        )
    if len(response.content) > _MAX_BODY:
        raise UpstreamError("upstream model list is too large")
    try:
        data = response.json().get("data")
    except (ValueError, AttributeError):
        raise UpstreamError("upstream model list is not a JSON object") from None
    if not isinstance(data, list):
        raise UpstreamError("upstream model list has no data array")
    found = (_model(entry) for entry in data[:_MAX_MODELS])
    return JSONResponse(_listing([m for m in found if m is not None]))


async def _hosted_models(request: Request) -> JSONResponse:
    from pii_guard.hosted.egress import secure_client

    service = request.app.state.hosted
    if getattr(request.state, "hosted_connection", None) is None:
        return JSONResponse(
            _listing(
                [
                    {"id": model, "object": "model", "created": 0, "owned_by": "meta"}
                    for model in service.settings.hosted_models
                ]
            )
        )
    settings = service.provider_settings(request)
    headers = {"Authorization": f"Bearer {settings.upstream_api_key.get_secret_value()}"}
    async with secure_client(timeout=_TIMEOUT) as client:
        try:
            async with client.stream(
                "GET", models_url(settings.upstream_base_url), headers=headers
            ) as response:
                if response.status_code != 200:
                    raise UpstreamError("Provider model catalog unavailable")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_BODY:
                        raise UpstreamError("Provider model catalog is too large")
        except httpx.HTTPError:
            raise UpstreamError("Provider model catalog unavailable") from None
    import json

    try:
        data = json.loads(content).get("data")
    except (ValueError, AttributeError):
        raise UpstreamError("Provider model catalog is invalid") from None
    if not isinstance(data, list):
        raise UpstreamError("Provider model catalog is invalid")
    entries = [_model(entry) for entry in data[:_MAX_MODELS]]
    return JSONResponse(_listing([entry for entry in entries if entry is not None]))
