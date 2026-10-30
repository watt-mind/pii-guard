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

from pii_guard.api.errors import error_headers, error_response
from pii_guard.api.security import looks_like_endpoint_key
from pii_guard.gateway.service import UPSTREAM_PAYLOAD_LIMIT
from pii_guard.hosted.abuse import AbuseAdmissionError
from pii_guard.hosted.identity import GUEST_COOKIE_NAME, Principal, easy_auth_principal
from pii_guard.hosted.images import (
    IMAGE_COMPUTE_TOKENS,
    IMAGE_PATH,
    chat_body_limit,
    chat_image_charge,
    chat_images_enabled,
    count_chat_images,
    image_body_limit,
    require_image_capacity,
)
from pii_guard.hosted.quotas import DEMO_MAX_OUTPUT_TOKENS, upstream_payload_bound
from pii_guard.hosted.runtime import HostedService
from pii_guard.projects.middleware import (
    MUSE_CATALOG,
    endpoint_body,
    endpoint_path,
    prepare_project,
    route_to_endpoint,
)
from pii_guard.types import PiiGuardError

# The whole body (endpoint and hosted reads together) must arrive within this many seconds
# of taking an ingress slot, however it is trickled.
BODY_READ_SECONDS = 10


# Tool types a client executes itself; any other type (web search, file search, code
# interpreter, MCP) runs and bills at the provider, outside the reserved token usage.
_CLIENT_TOOL_TYPES = frozenset({"function", "custom"})


def _provider_billed_tools(body: dict[str, Any]) -> bool:
    """Whether a chat or Responses body asks the provider for separately billed tool work."""
    if "web_search_options" in body:
        return True
    tools = body.get("tools")
    if tools is None:
        return False
    if not isinstance(tools, list):
        return True
    return any(
        not isinstance(tool, dict) or tool.get("type", "function") not in _CLIENT_TOOL_TYPES
        for tool in tools
    )


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
        if path in {"/healthz", "/readyz", "/readyz/serving"} or (
            not path.startswith(
                ("/v1", "/e/", "/s/", "/muse-code", "/metrics", "/docs", "/redoc", "/openapi")
            )
        ):
            await self.app(scope, receive, send)
            return
        started = False
        runtime = None
        reservation = None
        # The principal holding an ingress slot; set only once identity and admission pass.
        ingress: Principal | None = None
        streaming: str | None = None
        payload_limit = None
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
                if looks_like_endpoint_key(auth):
                    # Muse reads its catalog at the root of an endpoint base URL (LAB-1462).
                    root_catalog = routed is None and path == MUSE_CATALOG
                    if (routed is None and not root_catalog) or headers.get("x-pii-guard-token"):
                        raise HostedUnauthorizedError("Endpoint key requires its endpoint path")
                    # The only pre-authentication await: bounded by its own small pool,
                    # and no body is read while it is held.
                    self.service.enter_preauth()
                    try:
                        if root_catalog:
                            owner = await anyio.to_thread.run_sync(
                                self.service.projects.store.key_endpoint, auth
                            )
                            if owner is None:
                                raise HostedUnauthorizedError("Invalid or expired guard API key")
                            scope = route_to_endpoint(scope, owner)
                            path = scope["path"]
                            routed = endpoint_path(path)
                        if routed is None:
                            raise HostedRequestError("Endpoint route is unavailable")
                        endpoint_snapshot = await anyio.to_thread.run_sync(
                            self.service.projects.store.resolve_key, auth, routed[0]
                        )
                    finally:
                        self.service.leave_preauth()
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
                "/v1/account/first-run",
                "/v1/status",
                "/v1/connect/snippets",
            }
            # Hosted images (ADR 0014): signed-in Google owners only, never by key or as a
            # guest, never through an endpoint path, and only while the operator offers them.
            image = canonical == IMAGE_PATH and self.service.settings.hosted_images
            if image:
                allowed.add(IMAGE_PATH)
                if principal.auth_method != "google":
                    raise HostedUnauthorizedError("Image masking requires signed-in owner access")
                if routed is not None or scope.get("method") != "POST":
                    raise HostedRequestError("Image masking accepts a direct POST only")
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
            # First run (LAB-1455) provisions the owner's default endpoint and its first key:
            # a signed-in owner's, like key management, and free like the account itself.
            first_run = canonical == "/v1/account/first-run"
            credentials = canonical in {
                "/v1/account/api-keys",
                "/v1/account/connections",
                "/v1/account/first-run",
            } or bool(re.fullmatch(r"/v1/account/(?:api-keys|connections)/[^/]+", canonical))
            if credentials and principal.auth_method != "google":
                # A guard API key must never mint keys or connections that outlive it.
                raise HostedUnauthorizedError(
                    "Key and connection management requires a signed-in session"
                )
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
            method = scope.get("method")
            read = method in {"GET", "HEAD"}
            preflight = method == "OPTIONS"
            # /v1/account is free under every method: it never admits, reserves budget or
            # takes a runtime, so cookieless calls cannot exhaust capacity (LAB-1412).
            account = canonical == "/v1/account"
            if not principal.authenticated:
                # A guest's only work is the curated demo itself.
                needs_runtime = work = canonical == "/v1/demo" and method == "POST"
            else:
                # Key and connection management uses the account stores, never a runtime.
                needs_runtime = not (account or preflight or credentials)
                # Reads (the console polls them) spend no daily request or token budget and
                # hold no inference concurrency; the abuse read bucket bounds them instead.
                work = not (account or preflight or read or first_run)
            if not account:
                self.service.abuse.admit(
                    headers,
                    principal_id=principal.id,
                    authenticated=principal.authenticated,
                    anonymous_sponsored=canonical == "/v1/demo" and scope.get("method") == "POST",
                    read=read or first_run,
                )
            # Only now, with identity, path, origin and abuse admission settled, does the
            # request take an ingress slot: from the guest or the signed-in pool, and within
            # its principal's share (LAB-1442). One deadline then bounds every body read.
            self.service.enter_ingress(principal)
            ingress = principal
            deadline = asyncio.get_running_loop().time() + min(
                BODY_READ_SECONDS, self.service.settings.hosted_request_timeout
            )
            if principal.authenticated and canonical not in {"/v1/account", "/v1/demo"}:
                state = await anyio.to_thread.run_sync(
                    prepare_project,
                    self.service.projects,
                    {**scope, "state": state},
                    principal.id,
                    endpoint_snapshot,
                )
                async with asyncio.timeout_at(deadline):
                    scope, receive = await endpoint_body(
                        scope, receive, state, self.service.settings.hosted_max_body_bytes
                    )
                headers = Headers(scope=scope)
            # Text routes stay text-sized; the image route gets its own bounded limit, and
            # so does a signed-in owner's direct chat while the operator offers chat images
            # (LAB-1439). The non-image bytes of a chat body are held to the text limit below.
            chat_images = (
                chat_images_enabled(self.service.settings)
                and canonical in {"/v1/chat/completions", "/v1/responses"}
                and principal.auth_method == "google"
                and routed is None
            )
            text_limit = self.service.settings.hosted_max_body_bytes
            if image:
                body_limit = image_body_limit(self.service.settings)
            elif chat_images:
                body_limit = chat_body_limit(self.service.settings)
            else:
                body_limit = text_limit
            raw = bytearray()
            if scope.get("method") not in {"GET", "HEAD", "OPTIONS"}:
                async with asyncio.timeout_at(deadline):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        raw.extend(message.get("body", b""))
                        if len(raw) > body_limit:
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
            image_charge = None
            inline_images = image_bytes = 0
            if canonical in {"/v1/chat/completions", "/v1/responses"}:
                try:
                    body = json.loads(raw)
                except (ValueError, UnicodeDecodeError, RecursionError):
                    raise HostedRequestError("Invalid JSON request") from None
                if not isinstance(body, dict) or headers.get("x-pii-guard-mode", "fast") != "fast":
                    raise HostedRequestError("Hosted requests require fast text mode")
                sponsored_route = not connection_id and (
                    selected_endpoint is None or selected_endpoint.provider == "sponsored"
                )
                if sponsored_route and body.get("model") not in self.service.settings.hosted_models:
                    raise HostedRequestError("Model is not allowed for sponsored requests")
                if sponsored_route and _provider_billed_tools(body):
                    # Provider-side tools (Meta web search grounding: USD 2.50 per 1,000
                    # queries, LAB-1372) are billed outside the token usage the reservation
                    # bounds, so the sponsored route never asks for them.
                    raise HostedRequestError(
                        "Provider-side tools are not allowed for sponsored requests"
                    )
                if body.get("n", 1) != 1:
                    raise HostedRequestError("Hosted requests allow one completion")
                inline_images, image_bytes = (
                    count_chat_images(canonical, body) if chat_images else (0, 0)
                )
                # The text limit holds with or without images: only the inline images' own
                # base64 (the encoded length of their decoded bytes, never more than their
                # data URLs take in ``raw``) is left out, so ``len(raw) - image_bytes`` is an
                # upper bound on everything else in the body.
                if len(raw) - image_bytes > text_limit:
                    raise HostedRequestError("Hosted request body is too large")
                if inline_images:
                    # Images go to the owner's own provider only: the sponsored allowance
                    # has no reconciled image price, so it never pays for image input.
                    if not connection_id:
                        raise HostedRequestError(
                            "Images in hosted chat need your own connection; the sponsored "
                            "route accepts text only"
                        )
                    if inline_images > self.service.settings.hosted_chat_max_images:
                        raise HostedRequestError(
                            "A hosted request may carry at most "
                            f"{self.service.settings.hosted_chat_max_images} inline images"
                        )
                    # Before admission: a busy replica costs the owner nothing.
                    require_image_capacity(self.service.image_workers)
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
                output_limit = maximum
            else:
                output_limit = DEMO_MAX_OUTPUT_TOKENS
            state["hosted_principal"] = principal
            # The account remains available after exhaustion; mutations and data work consume
            # compute quotas. The full conservative charge survives failure.
            if work:
                if paid:
                    # Sized from this request: the gateway refuses a masked payload beyond
                    # the bound, and output is the request's own (capped) token limit.
                    payload_limit = upstream_payload_bound(len(raw))
                    input_tokens, output_tokens = payload_limit, output_limit
                    if inline_images:
                        # The text bound leaves the image bytes out; each image adds its
                        # transcript room and a fixed provider input charge (LAB-1439).
                        image_charge = chat_image_charge(
                            self.service.settings,
                            inline_images,
                            upstream_payload_bound(len(raw) - image_bytes),
                        )
                        payload_limit = image_charge.payload_bytes
                        input_tokens = image_charge.input_tokens
                else:
                    input_tokens, output_tokens = len(raw), 0
                if image:
                    # A fixed compute charge plus one from the separate daily image count:
                    # reserved here, before any decoding or OCR, and never refunded.
                    input_tokens = IMAGE_COMPUTE_TOKENS
                sponsored = (
                    paid
                    and not connection_id
                    and (selected_endpoint is None or selected_endpoint.provider == "sponsored")
                )
                if sponsored:
                    self.service.check_kill_switch()
                reservation = self.service.quotas.admit(
                    principal.id,
                    authenticated=principal.authenticated,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    sponsored=sponsored and self.service.spend is None,
                    images=1 if image else (image_charge.images if image_charge else 0),
                )
                if sponsored and self.service.spend is not None:
                    await self.service.charge_spend(input_tokens, output_tokens)
            # What the gateway may mask: only the images this admission charged for.
            state["hosted_chat_images"] = image_charge.images if image_charge else 0
            if needs_runtime and canonical == "/v1/traffic/stream":
                # A live stream trades its ingress slot for a bounded stream slot.
                self.service.enter_stream(principal.id)
                streaming = principal.id
                self.service.leave_ingress(principal)
                ingress = None
            if needs_runtime:
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
                if selected_endpoint is not None:
                    # Each stored event names the endpoint it went through, so the project's
                    # merged Logs can tell them apart (the name as of this request).
                    runtime.observability.traffic.labels = {
                        "endpoint": {"id": selected_endpoint.id, "name": selected_endpoint.name}
                    }
                elif canonical in {"/v1/traffic", "/v1/traffic/stream"}:
                    # No endpoint selected: the project's own runtime plus its endpoints'
                    # (LAB-1492). Vault and session routes stay on one runtime.
                    state["hosted_traffic"] = self.service.project_traffic(runtime, project_id)
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

            limit_token = UPSTREAM_PAYLOAD_LIMIT.set(payload_limit)
            try:
                async with asyncio.timeout(self.service.settings.hosted_request_timeout):
                    await self.app(
                        {**scope, "headers": filtered, "state": state}, body_receive, tracked_send
                    )
            finally:
                UPSTREAM_PAYLOAD_LIMIT.reset(limit_token)
        except PiiGuardError as exc:
            if not started:
                response = error_response(
                    exc.status_code, exc.code, exc.message, error_headers(exc)
                )
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
                if ingress is not None:
                    self.service.leave_ingress(ingress)
                if streaming is not None:
                    self.service.leave_stream(streaming)
