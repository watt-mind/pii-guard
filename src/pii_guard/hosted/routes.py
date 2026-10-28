"""Hosted account metadata, ephemeral credentials and the curated public walkthrough.

Only middleware-established principals reach these handlers. The demo constructs all
upstream text on the server; callers choose a sample, never supply a prompt or model.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import Path, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from starlette.responses import Response

from pii_guard.api.deps import get_max_text_chars, get_vault
from pii_guard.api.routes._common import ephemeral_session, v1_router
from pii_guard.api.routes.chat import get_gateway
from pii_guard.gateway.service import (
    ECHO_HEADER,
    LANGUAGE_HEADER,
    MODE_HEADER,
    REQUEST_ID_HEADER,
    SESSION_HEADER,
    UpstreamError,
)
from pii_guard.hosted.connections import PROVIDERS
from pii_guard.hosted.identity import IdentityError, Principal
from pii_guard.types import PiiGuardError
from pii_guard.vault import PLACEHOLDER_RE, VaultSession

router = v1_router()
router.tags = ["hosted"]

# Fictional names and reserved example domains only (ADR 0005). Keep the UI's static
# walkthrough in sync when these server-curated samples change.
DEMO_SAMPLES: dict[str, tuple[str, str]] = {
    "hu-support": (
        "hu",
        "Kérlek, írj rövid választ erre az ügyfélszolgálati kérésre: Teszt Elek vagyok, "
        "az e-mail-címem teszt.elek@example.com. Szeretném módosítani a szállítás időpontját.",
    ),
    "en-support": (
        "en",
        "Please write a short reply to this support request: I am Jane Placeholder, "
        "my email is jane.placeholder@example.com. I would like to change the delivery date.",
    ),
}


class _StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ApiKeyRequest(_StrictBody):
    name: str = Field(min_length=1, max_length=64, repr=False)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("invalid key name")
        return value.strip()


class ConnectionRequest(_StrictBody):
    provider: Literal["meta", "openai", "fireworks", "openrouter", "custom"]
    api_key: SecretStr = Field(min_length=1, max_length=4096, repr=False)
    base_url: str | None = Field(default=None, max_length=2048, repr=False)


class DemoRequest(_StrictBody):
    sample_id: Literal["hu-support", "en-support"]
    language: Literal["hu", "en"] | None = None


class _NotFoundError(PiiGuardError):
    code = "not_found"
    status_code = 404


class _InvalidDemoError(PiiGuardError):
    code = "invalid_request"
    status_code = 422


def _principal(request: Request, *, authenticated: bool = False) -> Principal:
    principal = getattr(request.state, "hosted_principal", None)
    if not isinstance(principal, Principal) or (authenticated and not principal.authenticated):
        raise IdentityError()
    return principal


@router.get("/v1/account")
def account(request: Request) -> dict[str, Any]:
    principal = _principal(request)
    hosted = request.app.state.hosted
    limits = hosted.quotas.limits
    authenticated = principal.authenticated
    return {
        "mode": "hosted",
        "authenticated": authenticated,
        "principal": {"id": principal.id, "provider": "google"} if authenticated else None,
        "login_url": "/.auth/login/google",
        "logout_url": "/.auth/logout",
        "tier": "standard" if authenticated else "anonymous",
        "providers": list(PROVIDERS),
        "limits": {
            "requests_per_day": limits.user_requests if authenticated else limits.guest_requests,
            "tokens_per_day": limits.user_tokens if authenticated else limits.guest_tokens,
            "concurrent_requests": limits.principal_concurrency,
            "max_output_tokens": hosted.settings.hosted_max_output_tokens,
            "sponsored_enabled": hosted.sponsored_enabled,
        },
        "usage": hosted.quotas.usage(principal.id),
        "state": {"persistence": "ephemeral", "restart_loses_sessions": True},
        "connections": hosted.connections.list(principal.id) if authenticated else [],
    }


@router.post("/v1/account/api-keys", status_code=201)
def create_api_key(body: ApiKeyRequest, request: Request) -> dict[str, str]:
    return request.app.state.hosted.keys.issue(_principal(request, authenticated=True), body.name)


@router.get("/v1/account/api-keys")
def list_api_keys(request: Request) -> list[dict[str, str]]:
    return request.app.state.hosted.keys.list(_principal(request, authenticated=True))


@router.delete("/v1/account/api-keys/{key_id}", status_code=204)
def delete_api_key(request: Request, key_id: str = Path(min_length=1, max_length=128)) -> Response:
    if not request.app.state.hosted.keys.revoke(_principal(request, authenticated=True), key_id):
        raise _NotFoundError("API key is unknown or expired")
    return Response(status_code=204)


@router.post("/v1/account/connections", status_code=201)
async def create_connection(body: ConnectionRequest, request: Request) -> dict[str, str]:
    principal = _principal(request, authenticated=True)
    connection = await request.app.state.hosted.connections.create(
        principal.id, body.provider, body.api_key, body.base_url
    )
    return connection.metadata()


@router.delete("/v1/account/connections/{connection_id}", status_code=204)
def delete_connection(
    request: Request, connection_id: str = Path(min_length=1, max_length=128)
) -> Response:
    principal = _principal(request, authenticated=True)
    request.app.state.hosted.connections.delete(principal.id, connection_id)
    return Response(status_code=204)


def _demo_entities(original: str, masked: str, session: VaultSession) -> list[dict[str, Any]]:
    """Offsets of actual replacements, without another detector pass.

    A fresh demo session has no pre-existing values or suffix variants. Checking the
    exact reconstruction prevents the UI from displaying guessed or mismatched offsets.
    """
    if session.unmask(masked) != original:
        raise UpstreamError("demo masking did not round-trip")
    entities: list[dict[str, Any]] = []
    cursor = original_cursor = 0
    for match in PLACEHOLDER_RE.finditer(masked):
        original_cursor += len(masked[cursor : match.start()])
        value = session.unmask(match.group())
        end = original_cursor + len(value)
        if original[original_cursor:end] != value:
            raise UpstreamError("demo masking offsets are inconsistent")
        entities.append({"start": original_cursor, "end": end, "type": match.group(1)})
        original_cursor, cursor = end, match.end()
    return entities


@router.post("/v1/demo")
async def demo(body: DemoRequest, request: Request) -> dict[str, Any]:
    _principal(request)
    language, original = DEMO_SAMPLES[body.sample_id]
    if body.language is not None and body.language != language:
        raise _InvalidDemoError("sample language does not match the selected sample")
    hosted = request.app.state.hosted
    model = hosted.settings.hosted_models[0]
    gateway = get_gateway(request)
    vault = get_vault(request)
    with ephemeral_session(vault, None, request) as session:
        response, _ = await gateway.chat_completions(
            {
                "model": model,
                "messages": [{"role": "user", "content": original}],
                "stream": False,
                "max_completion_tokens": hosted.settings.hosted_max_output_tokens,
            },
            {
                ECHO_HEADER: "masked",
                MODE_HEADER: "fast",
                LANGUAGE_HEADER: language,
                SESSION_HEADER: session.session_id,
            },
            max_text_chars=get_max_text_chars(request),
        )
        if response.status_code != 200:
            raise UpstreamError("the demo upstream could not complete the request")
        try:
            payload = json.loads(bytes(response.body))
            masked = payload["pii_guard"]["masked_messages"][0]["content"]
            answer = payload["pii_guard"]["masked_answer"][0]["content"]
            restored = payload["choices"][0]["message"]["content"]
            request_id = response.headers[REQUEST_ID_HEADER]
        except (AttributeError, KeyError, IndexError, TypeError, ValueError):
            raise UpstreamError("the demo upstream returned an invalid answer") from None
        if not all(isinstance(text, str) and text.strip() for text in (masked, answer, restored)):
            raise UpstreamError("the demo upstream returned an empty or invalid answer")
        return {
            "sample_id": body.sample_id,
            "language": language,
            "original": original,
            "masked": masked,
            "answer": answer,
            "restored": restored,
            "entities": _demo_entities(original, masked, session),
            "model": model,
            "session_id": session.session_id,
            "request_id": request_id,
        }
