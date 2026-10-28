"""Project selection and endpoint bearer confinement before routing or processing."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import urlsplit

import anyio.to_thread
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from pii_guard.api.errors import error_response
from pii_guard.api.security import _addr_is_loopback
from pii_guard.projects.runtime import ProjectAccessError, ProjectService
from pii_guard.types import PiiGuardError

ENDPOINT_PATH = re.compile(
    r"^/e/([A-Za-z0-9_-]{1,128})(/v1/(?:chat/completions|responses|models))$"
)


class EndpointModelRequiredError(PiiGuardError):
    """A pass-through endpoint (no pinned model) got a request that names no model."""

    code = "invalid_request"
    status_code = 400


def endpoint_path(path: str) -> tuple[str, str] | None:
    match = ENDPOINT_PATH.fullmatch(path)
    return (match[1], match[2]) if match else None


def prepare_project(
    service: ProjectService, scope: Scope, owner: str, snapshot: Any = None
) -> dict[str, Any]:
    headers = Headers(scope=scope)
    for name in ("x-pii-guard-project", "x-pii-guard-endpoint"):
        if len(headers.getlist(name)) > 1:
            raise ProjectAccessError("Duplicate project selection header")
    selected = headers.get("x-pii-guard-project")
    selected_endpoint = headers.get("x-pii-guard-endpoint")
    if (
        selected_endpoint
        and endpoint_path(scope.get("path", "")) is None
        and not scope.get("path", "").startswith(
            ("/v1/vault/", "/v1/traffic", "/v1/sessions", "/v1/unmask")
        )
    ):
        raise ProjectAccessError("Endpoint inspection selector is unavailable on this route")
    if snapshot is not None:
        if headers.get("x-pii-guard-endpoint") not in (None, snapshot.id):
            raise ProjectAccessError("Endpoint key cannot select another endpoint")
        if selected and selected != snapshot.project_id:
            raise ProjectAccessError("Endpoint key cannot select another project")
        selected = snapshot.project_id
    state = dict(scope.get("state", {}))
    routed = endpoint_path(scope.get("path", ""))
    service.prepare(state, owner, selected, snapshot)
    endpoint_id = routed[0] if routed else headers.get("x-pii-guard-endpoint")
    if endpoint_id and snapshot is None:
        snapshot = service.store.endpoint_snapshot(owner, state["project_id"], endpoint_id)
        service.prepare(state, owner, state["project_id"], snapshot)
    if snapshot is not None and (not snapshot.enabled or (routed and snapshot.id != routed[0])):
        raise ProjectAccessError("Endpoint is disabled or outside this request")
    state["project_routed_endpoint"] = bool(routed)
    return state


async def endpoint_body(
    scope: Scope, receive: Receive, state: dict[str, Any], maximum: int
) -> tuple[Scope, Receive]:
    """Fix model/mode/language from the immutable endpoint snapshot, never caller overrides."""
    routed = endpoint_path(scope.get("path", ""))
    if routed is None:
        return scope, receive
    endpoint, canonical = state["project_endpoint"], routed[1]
    headers = Headers(scope=scope)
    for name in ("x-pii-guard-mode", "x-pii-guard-language", "x-pii-guard-connection"):
        if len(headers.getlist(name)) > 1:
            raise ProjectAccessError("Duplicate endpoint control header")
    if headers.get("x-pii-guard-connection"):
        raise ProjectAccessError("Endpoint upstream cannot be overridden")
    policy = state["project_policy"]
    if headers.get("x-pii-guard-mode", policy["mode"]) != policy["mode"]:
        raise ProjectAccessError("Endpoint detection mode cannot be overridden")
    if headers.get("x-pii-guard-language", policy["language"]) != policy["language"]:
        raise ProjectAccessError("Endpoint language cannot be overridden")
    raw = bytearray()
    if scope.get("method") not in {"GET", "HEAD", "OPTIONS"}:
        async with asyncio.timeout(10):
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    raise ProjectAccessError("Request disconnected")
                raw.extend(message.get("body", b""))
                if len(raw) > maximum:
                    raise ProjectAccessError("Endpoint request body is too large")
                if not message.get("more_body", False):
                    break
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise ProjectAccessError("Invalid endpoint JSON request") from None
        if not isinstance(body, dict):
            raise ProjectAccessError("Endpoint request must be an object")
        if endpoint.model is not None:
            # Pinned: the configured model, whatever the client sends.
            if "model" in body and body["model"] != endpoint.model:
                raise ProjectAccessError("Endpoint allows only its configured model")
            body["model"] = endpoint.model
        else:
            # Pass-through (BYOK only; sponsored always pins): the client's model, unchanged.
            model = body.get("model")
            if (
                not isinstance(model, str)
                or not model.strip()
                or len(model) > 256
                or any(ord(c) < 32 or ord(c) == 127 for c in model)
            ):
                raise EndpointModelRequiredError(
                    "This endpoint has no pinned model: the request must name one in 'model'"
                )
        raw = bytearray(json.dumps(body).encode())
    filtered = [
        (k, v)
        for k, v in scope.get("headers", [])
        if k.lower()
        not in {
            b"authorization",
            b"x-pii-guard-token",
            b"x-pii-guard-mode",
            b"x-pii-guard-language",
            b"content-length",
        }
    ]
    filtered.extend(
        [
            (b"x-pii-guard-mode", policy["mode"].encode()),
            (b"x-pii-guard-language", policy["language"].encode()),
            (b"content-length", str(len(raw)).encode()),
        ]
    )
    consumed = False

    async def body_receive() -> Message:
        nonlocal consumed
        if not consumed:
            consumed = True
            return {"type": "http.request", "body": bytes(raw), "more_body": False}
        return await receive()

    return {
        **scope,
        "path": canonical,
        "raw_path": canonical.encode(),
        "headers": filtered,
    }, body_receive


class ProjectMiddleware:
    """Local owner management; hosted authentication and admission run in HostedMiddleware."""

    def __init__(self, app: ASGIApp, service: ProjectService) -> None:
        self.app, self.service = app, service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.service.settings.hosted:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        headers = Headers(scope=scope)
        routed = endpoint_path(path)
        runtime = None
        started = False
        state: dict[str, Any] = {}
        try:
            auth = headers.get("authorization", "")
            if (
                len(headers.getlist("authorization")) > 1
                or len(headers.getlist("x-pii-guard-token")) > 1
            ):
                raise ProjectAccessError("Duplicate authorization header")
            scheme, _, credential = auth.partition(" ")
            credential = credential.strip()
            snapshot = None
            if credential.startswith("pg_ep_") or headers.get("x-pii-guard-token", "").startswith(
                "pg_ep_"
            ):
                if routed is None or scheme.lower() != "bearer" or headers.get("x-pii-guard-token"):
                    raise ProjectAccessError(
                        "Endpoint keys are accepted only on their endpoint path"
                    )
                snapshot = await anyio.to_thread.run_sync(
                    self.service.store.resolve_key, credential, routed[0]
                )
                if snapshot is None:
                    raise ProjectAccessError("Invalid or revoked endpoint key")
            elif routed is not None:
                # Local owner calls use the authenticated/trusted-local management boundary.
                if self.service.settings.api_token is None and not _addr_is_loopback(
                    scope.get("client")
                ):
                    raise ProjectAccessError(
                        "Local owner access requires a trusted local connection"
                    )
            if path.startswith("/e/") and routed is None:
                raise ProjectAccessError("Endpoint key cannot access this route")
            management = path == "/v1/projects" or path.startswith("/v1/projects/")
            selected = bool(
                headers.get("x-pii-guard-project") or headers.get("x-pii-guard-endpoint")
            )
            if not (management or selected or routed):
                # Preserve the original single local owner's default namespace.
                await self.app(scope, receive, send)
                return
            if snapshot is None and self.service.settings.api_token is None:
                if not (
                    _addr_is_loopback(scope.get("client"))
                    and _addr_is_loopback(scope.get("server"))
                ):
                    raise ProjectAccessError("Project management requires local owner access")
                origin = headers.get("origin")
                if origin and urlsplit(origin).netloc != headers.get("host"):
                    raise ProjectAccessError("Project requests require the same origin")
            state = await anyio.to_thread.run_sync(
                prepare_project, self.service, scope, "local-owner", snapshot
            )
            if not management:
                default = await anyio.to_thread.run_sync(
                    self.service.store.default_project, "local-owner"
                )
                if state["project_id"] != default["id"] or state["project_endpoint"] is not None:
                    runtime = self.service.acquire(state)
                    state["hosted_runtime"] = runtime
            scope, receive = await endpoint_body(scope, receive, state, 8 * 1024 * 1024)

            async def scoped_send(message: Message) -> None:
                nonlocal started
                if message["type"] == "http.response.start":
                    started = True
                    message = {
                        **message,
                        "headers": [
                            *message.get("headers", []),
                            (b"cache-control", b"no-store"),
                            (b"x-pii-guard-project", state["project_id"].encode()),
                            (
                                b"x-pii-guard-policy-version",
                                state["project_policy"]["policy_version_id"].encode(),
                            ),
                        ],
                    }
                await send(message)

            await self.app({**scope, "state": state}, receive, scoped_send)
        except PiiGuardError as exc:
            if not started:
                await error_response(exc.status_code, exc.code, exc.message)(scope, receive, send)
        except TimeoutError:
            if started:
                return
            await error_response(408, "project_request_timeout", "Request body timed out")(
                scope, receive, send
            )
        finally:
            gateway = state.get("project_gateway")
            if gateway is not None:
                await gateway.aclose()
            if runtime is not None:
                self.service.release(runtime)
