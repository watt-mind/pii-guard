"""Authenticate before routing; hold owner state and admission until the stream ends."""

from __future__ import annotations

import asyncio
import json
import re
from http.cookies import SimpleCookie
from typing import Any

import anyio.to_thread
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from pii_guard.api.errors import error_response
from pii_guard.hosted.abuse import AbuseAdmissionError
from pii_guard.hosted.identity import GUEST_COOKIE_NAME, Principal, easy_auth_principal
from pii_guard.hosted.runtime import HostedService
from pii_guard.projects.middleware import endpoint_body, endpoint_path, prepare_project
from pii_guard.types import PiiGuardError


class HostedRequestError(PiiGuardError):
    status_code = 403
    code = "hosted_request_denied"


class HostedUnauthorizedError(PiiGuardError):
    status_code = 401
    code = "unauthorized"


class HostedMiddleware:
    def __init__(self, app: ASGIApp, service: HostedService) -> None:
        self.app, self.service = app, service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path in {"/healthz", "/readyz"} or (
            not path.startswith(
                ("/v1", "/e/", "/s/", "/muse-code", "/metrics", "/docs", "/redoc", "/openapi")
            )
        ):
            await self.app(scope, receive, send)
            return
        started = False
        runtime = None
        reservation = None
        entered = False
        state: dict[str, Any] = dict(scope.get("state", {}))

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message = dict(message)
                headers = list(message.get("headers", []))
                headers.append((b"cache-control", b"no-store"))
                if state.get("project_policy"):
                    headers.append(
                        (
                            b"x-pii-guard-policy-version",
                            state["project_policy"]["policy_version_id"].encode(),
                        )
                    )
                    headers.append((b"x-pii-guard-project", state["project_id"].encode()))
                if cookie_header is not None:
                    headers.append((b"set-cookie", cookie_header.encode("ascii")))
                message["headers"] = headers
            await send(message)

        cookie_header = None
        try:
            self.service.enter_ingress()
            entered = True
            headers = Headers(scope=scope)
            protected_headers = {
                "authorization",
                "x-pii-guard-token",
                "x-ms-client-principal",
                "origin",
                "x-pii-guard-connection",
                "cookie",
                "x-pii-guard-project",
                "x-pii-guard-endpoint",
            }
            for name in protected_headers:
                if len(headers.getlist(name)) > 1:
                    raise HostedRequestError("Duplicate security header")
            auth = headers.get("authorization") or headers.get("x-pii-guard-token")
            routed = endpoint_path(path)
            endpoint_snapshot = None
            if path.startswith("/e/") and routed is None:
                raise HostedRequestError("Endpoint route is unavailable")
            if auth:
                if headers.get("authorization"):
                    scheme, _, auth = auth.partition(" ")
                    if scheme.lower() != "bearer":
                        raise HostedUnauthorizedError("Invalid guard API key")
                if auth.startswith("pg_ep_"):
                    if routed is None or headers.get("x-pii-guard-token"):
                        raise HostedUnauthorizedError("Endpoint key requires its endpoint path")
                    endpoint_snapshot = await anyio.to_thread.run_sync(
                        self.service.projects.store.resolve_key, auth, routed[0]
                    )
                    principal = (
                        Principal(endpoint_snapshot.owner_id, True, "api_key")
                        if endpoint_snapshot
                        else None
                    )
                    state["endpoint_key"] = True
                else:
                    principal = self.service.keys.resolve(auth)
                if principal is None:
                    raise HostedUnauthorizedError("Invalid or expired guard API key")
            elif encoded := headers.get("x-ms-client-principal"):
                principal = easy_auth_principal(
                    encoded, master_key=self.service.master_key, trusted=True
                )
            else:
                cookies = SimpleCookie()
                try:
                    cookies.load(headers.get("cookie", ""))
                except Exception:
                    raise HostedRequestError("Invalid cookie") from None
                item = cookies.get(GUEST_COOKIE_NAME)
                principal, fresh = self.service.guests.resolve(item.value if item else None)
                if fresh:
                    cookie_header = self.service.guests.cookie_header(fresh)
            canonical = routed[1] if routed else re.sub(r"^/s/[^/]+(?=/v1/|/muse-code/)", "", path)
            allowed = {
                "/v1/account",
                "/v1/demo",
                "/v1/analyze",
                "/v1/mask",
                "/v1/unmask",
                "/v1/chat/completions",
                "/v1/responses",
                "/v1/models",
                "/muse-code/models",
                "/v1/sessions",
                "/v1/traffic",
                "/v1/traffic/stream",
                "/v1/vault/sessions",
                "/v1/account/api-keys",
                "/v1/account/connections",
                "/v1/status",
                "/v1/connect/snippets",
            }
            # The shared console's reads (ADR 0013): the owner's projection, never by key.
            console = canonical in {"/v1/status", "/v1/connect/snippets"}
            parameterized = re.fullmatch(
                r"/v1/(?:sessions/[^/]+/known-values|vault/sessions/[^/]+|"
                r"account/(?:api-keys|connections)/[^/]+)",
                canonical,
            )
            project_management = canonical == "/v1/projects" or bool(
                re.fullmatch(
                    r"/v1/projects/[A-Za-z0-9_-]+(?:/(?:policies|endpoints)"
                    r"(?:/[A-Za-z0-9_-]+(?:/keys(?:/[A-Za-z0-9_-]+)?)?)?)?",
                    canonical,
                )
            )
            project_management = project_management or bool(
                re.fullmatch(
                    r"/v1/projects/[A-Za-z0-9_-]+/policies/versions/[A-Za-z0-9_-]+", canonical
                )
            )
            if project_management and principal.auth_method != "google":
                raise HostedUnauthorizedError("Project management requires signed-in owner access")
            if console and principal.auth_method != "google":
                raise HostedUnauthorizedError("The console requires signed-in owner access")
            if canonical not in allowed and parameterized is None and not project_management:
                raise HostedRequestError("This endpoint is unavailable in hosted mode")
            if canonical not in {"/v1/account", "/v1/demo"} and not principal.authenticated:
                raise HostedUnauthorizedError("Sign in with Google to use this endpoint")
            if canonical == "/v1/demo" and (
                path != canonical
                or any(
                    headers.get(h)
                    for h in ("x-pii-guard-connection", "x-pii-guard-session", "x-pii-guard-mode")
                )
            ):
                raise HostedRequestError("Demo accepts only a curated sample selection")
            if scope.get("method") not in {"GET", "HEAD", "OPTIONS"}:
                origin = headers.get("origin")
                if (
                    principal.auth_method != "api_key" or origin is not None
                ) and origin != self.service.origin:
                    raise HostedRequestError("A same-origin request is required")
                if headers.get("sec-fetch-site") == "cross-site":
                    raise HostedRequestError("A same-origin request is required")
            account_inspection = canonical == "/v1/account" and scope.get("method") == "GET"
            if not account_inspection:
                self.service.abuse.admit(
                    headers,
                    principal_id=principal.id,
                    authenticated=principal.authenticated,
                    anonymous_sponsored=canonical == "/v1/demo" and scope.get("method") == "POST",
                    read=scope.get("method") in {"GET", "HEAD"},
                )
            if principal.authenticated and canonical not in {"/v1/account", "/v1/demo"}:
                state = await anyio.to_thread.run_sync(
                    prepare_project,
                    self.service.projects,
                    {**scope, "state": state},
                    principal.id,
                    endpoint_snapshot,
                )
                scope, receive = await endpoint_body(
                    scope, receive, state, self.service.settings.hosted_max_body_bytes
                )
                headers = Headers(scope=scope)
            raw = bytearray()
            if scope.get("method") not in {"GET", "HEAD", "OPTIONS"}:
                async with asyncio.timeout(min(10, self.service.settings.hosted_request_timeout)):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        raw.extend(message.get("body", b""))
                        if len(raw) > self.service.settings.hosted_max_body_bytes:
                            raise HostedRequestError("Hosted request body is too large")
                        if not message.get("more_body", False):
                            break
            selected_endpoint = state.get("project_endpoint")
            connection_id = headers.get("x-pii-guard-connection")
            if connection_id:
                state["hosted_connection"] = self.service.connections.get(
                    principal.id, connection_id
                )
            paid = canonical in {"/v1/chat/completions", "/v1/responses", "/v1/demo"}
            if canonical in {"/v1/chat/completions", "/v1/responses"}:
                try:
                    body = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    raise HostedRequestError("Invalid JSON request") from None
                if not isinstance(body, dict) or headers.get("x-pii-guard-mode", "fast") != "fast":
                    raise HostedRequestError("Hosted requests require fast text mode")
                if (
                    not connection_id
                    and (selected_endpoint is None or selected_endpoint.provider == "sponsored")
                    and body.get("model") not in self.service.settings.hosted_models
                ):
                    raise HostedRequestError("Model is not allowed for sponsored requests")
                if body.get("n", 1) != 1:
                    raise HostedRequestError("Hosted requests allow one completion")
                maximum = self.service.settings.hosted_max_output_tokens
                output_field = (
                    "max_output_tokens" if canonical == "/v1/responses" else "max_completion_tokens"
                )
                for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
                    value = body.pop(key, maximum)
                    if type(value) is not int or not 1 <= value <= maximum:
                        raise HostedRequestError("Output token limit is outside hosted limits")
                    maximum = min(maximum, value)
                body[output_field] = maximum
                raw = bytearray(json.dumps(body).encode())
            state["hosted_principal"] = principal
            # Account inspection remains available after exhaustion; all mutations and data
            # routes consume compute quotas. The full conservative charge survives failure.
            if not account_inspection:
                input_tokens = (max(len(raw), 1024) * 32 + 4096) if paid else len(raw)
                output_tokens = self.service.settings.hosted_max_output_tokens if paid else 0
                sponsored = (
                    paid
                    and not connection_id
                    and (selected_endpoint is None or selected_endpoint.provider == "sponsored")
                )
                reservation = self.service.quotas.admit(
                    principal.id,
                    authenticated=principal.authenticated,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    sponsored=sponsored and self.service.spend is None,
                )
                if sponsored and self.service.spend is not None:
                    await self.service.charge_spend(input_tokens, output_tokens)
                project_id = state.get("project_id")
                default = (
                    (
                        await anyio.to_thread.run_sync(
                            self.service.projects.store.default_project, principal.id
                        )
                    )["id"]
                    if project_id
                    else None
                )
                namespace = project_id if project_id != default else None
                if selected_endpoint is not None:
                    namespace = str(project_id) + ":" + selected_endpoint.id
                runtime = self.service.acquire(principal, namespace=namespace)
                state["hosted_runtime"] = runtime
            filtered = [
                (k, v)
                for k, v in scope.get("headers", [])
                if k.lower()
                not in {
                    b"authorization",
                    b"x-pii-guard-token",
                    b"cookie",
                    b"content-length",
                    b"x-forwarded-for",
                    b"forwarded",
                    b"x-real-ip",
                }
                and not k.lower().startswith(b"x-ms-")
            ]
            filtered.append((b"content-length", str(len(raw)).encode()))
            consumed = False

            async def body_receive() -> Message:
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": bytes(raw), "more_body": False}
                return await receive()

            async with asyncio.timeout(self.service.settings.hosted_request_timeout):
                await self.app(
                    {**scope, "headers": filtered, "state": state}, body_receive, tracked_send
                )
        except PiiGuardError as exc:
            if not started:
                response = error_response(exc.status_code, exc.code, exc.message)
                if isinstance(exc, AbuseAdmissionError):
                    response.headers["Retry-After"] = str(exc.retry_after)
                await response(scope, receive, tracked_send)
        except TimeoutError:
            if not started:
                await error_response(504, "hosted_timeout", "Hosted request timed out")(
                    scope, receive, tracked_send
                )
        finally:
            gateway = state.get("project_gateway") or state.get("hosted_gateway")
            try:
                if gateway is not None:
                    async with asyncio.timeout(5):
                        await gateway.aclose()
            finally:
                if runtime is not None:
                    self.service.release(runtime)
                if reservation is not None:
                    reservation.release()
                if entered:
                    self.service.leave_ingress()
