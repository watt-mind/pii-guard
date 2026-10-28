"""Authenticate before routing; hold owner state and admission until the stream ends."""

from __future__ import annotations

import asyncio
import json
import re
from http.cookies import SimpleCookie
from typing import Any

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from pii_guard.api.errors import error_response
from pii_guard.hosted.abuse import AbuseAdmissionError
from pii_guard.hosted.identity import GUEST_COOKIE_NAME, easy_auth_principal
from pii_guard.hosted.runtime import HostedService
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
                ("/v1", "/s/", "/muse-code", "/metrics", "/docs", "/redoc", "/openapi")
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
            }
            for name in protected_headers:
                if len(headers.getlist(name)) > 1:
                    raise HostedRequestError("Duplicate security header")
            auth = headers.get("authorization") or headers.get("x-pii-guard-token")
            if auth:
                if headers.get("authorization"):
                    scheme, _, auth = auth.partition(" ")
                    if scheme.lower() != "bearer":
                        raise HostedUnauthorizedError("Invalid guard API key")
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
            canonical = re.sub(r"^/s/[^/]+(?=/v1/|/muse-code/)", "", path)
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
            }
            parameterized = re.fullmatch(
                r"/v1/(?:sessions/[^/]+/known-values|vault/sessions/[^/]+|"
                r"account/(?:api-keys|connections)/[^/]+)",
                canonical,
            )
            if canonical not in allowed and parameterized is None:
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
                )
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
                reservation = self.service.quotas.admit(
                    principal.id,
                    authenticated=principal.authenticated,
                    input_tokens=(max(len(raw), 1024) * 32 + 4096) if paid else len(raw),
                    output_tokens=self.service.settings.hosted_max_output_tokens if paid else 0,
                    sponsored=paid and not connection_id,
                )
                runtime = self.service.acquire(principal)
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
            gateway = state.get("hosted_gateway")
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
