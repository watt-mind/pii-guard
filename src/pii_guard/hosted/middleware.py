"""Authenticate before routing; hold owner state and admission until the stream ends."""

from __future__ import annotations

import asyncio
import hmac
import json
import secrets
from collections.abc import Callable
from http.cookies import SimpleCookie
from typing import Any

import anyio.to_thread
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from pii_guard.api.errors import error_headers, error_response
from pii_guard.api.routes._common import ClientDisconnectedError
from pii_guard.api.security import looks_like_endpoint_key
from pii_guard.gateway.meter import UPSTREAM_METER, UpstreamMeter
from pii_guard.gateway.service import UPSTREAM_PAYLOAD_LIMIT
from pii_guard.hosted.abuse import AbuseAdmissionError
from pii_guard.hosted.identity import GUEST_COOKIE_NAME, Principal, easy_auth_principal
from pii_guard.hosted.images import (
    IMAGE_COMPUTE_TOKENS,
    chat_body_limit,
    chat_image_charge,
    chat_images_enabled,
    count_chat_images,
    image_body_limit,
    require_image_capacity,
)
from pii_guard.hosted.quotas import DEMO_MAX_OUTPUT_TOKENS, upstream_payload_bound
from pii_guard.hosted.runtime import HostedService
from pii_guard.hosted.settlement import (
    _ALLOWED_ROUTES as _ALLOWED_ROUTES,
)
from pii_guard.hosted.settlement import (
    _ALLOWED_TOOLS_CHOICE,
    _CLIENT_TOOL_CHOICES,
    _CLIENT_TOOL_TYPES,
    _NAMESPACE_TOOL_TYPE,
    MAX_TOOL_DEFINITIONS,
    _classify_tool_entry,
    _NestedNamespaceError,
    _provider_billed_tools,
    _provider_tool_choice,
    _Settlement,
    _ToolWalkLimitError,
    _walk_tools,
    settled_tokens,
    settlement_logger,
)
from pii_guard.hosted.settlement import (
    _BYPASS_PATHS as _BYPASS_PATHS,
)
from pii_guard.hosted.settlement import (
    _CHAT_ROUTES as _CHAT_ROUTES,
)
from pii_guard.hosted.settlement import (
    _CONSOLE_ROUTES as _CONSOLE_ROUTES,
)
from pii_guard.hosted.settlement import (
    _CREDENTIAL_ITEM_RE as _CREDENTIAL_ITEM_RE,
)
from pii_guard.hosted.settlement import (
    _CREDENTIAL_ROUTES as _CREDENTIAL_ROUTES,
)
from pii_guard.hosted.settlement import (
    _DEMO_FORBIDDEN_HEADERS as _DEMO_FORBIDDEN_HEADERS,
)
from pii_guard.hosted.settlement import (
    _HOSTED_PREFIXES as _HOSTED_PREFIXES,
)
from pii_guard.hosted.settlement import (
    _PAID_ROUTES as _PAID_ROUTES,
)
from pii_guard.hosted.settlement import (
    _PARAMETERIZED_ROUTE_RE as _PARAMETERIZED_ROUTE_RE,
)
from pii_guard.hosted.settlement import (
    _PROJECT_POLICY_VERSION_RE as _PROJECT_POLICY_VERSION_RE,
)
from pii_guard.hosted.settlement import (
    _PROJECT_SUBPATH_RE as _PROJECT_SUBPATH_RE,
)
from pii_guard.hosted.settlement import (
    _PROTECTED_HEADERS as _PROTECTED_HEADERS,
)
from pii_guard.hosted.settlement import (
    _READ_METHODS as _READ_METHODS,
)
from pii_guard.hosted.settlement import (
    _SAFE_METHODS as _SAFE_METHODS,
)
from pii_guard.hosted.settlement import (
    _SESSION_PREFIX_RE as _SESSION_PREFIX_RE,
)
from pii_guard.hosted.settlement import (
    _STRIPPED_FORWARD_HEADERS as _STRIPPED_FORWARD_HEADERS,
)
from pii_guard.hosted.settlement import (
    HostedRequestError as HostedRequestError,
)
from pii_guard.hosted.settlement import (
    HostedUnauthorizedError as HostedUnauthorizedError,
)
from pii_guard.hosted.settlement import (
    _check_access_and_origin as _check_access_and_origin,
)
from pii_guard.hosted.settlement import (
    _check_owner_only_routes as _check_owner_only_routes,
)
from pii_guard.hosted.settlement import (
    _check_unique_security_headers as _check_unique_security_headers,
)
from pii_guard.hosted.settlement import (
    _classify_route as _classify_route,
)
from pii_guard.hosted.settlement import (
    _extract_auth_token as _extract_auth_token,
)
from pii_guard.hosted.settlement import (
    _filter_forward_headers as _filter_forward_headers,
)
from pii_guard.hosted.settlement import (
    _is_credential_route as _is_credential_route,
)
from pii_guard.hosted.settlement import (
    _is_hosted_scope as _is_hosted_scope,
)
from pii_guard.hosted.settlement import (
    _is_project_management as _is_project_management,
)
from pii_guard.hosted.settlement import (
    _PayloadSpec as _PayloadSpec,
)
from pii_guard.hosted.settlement import (
    _RequestContext as _RequestContext,
)
from pii_guard.hosted.settlement import (
    _ResponseTracker as _ResponseTracker,
)
from pii_guard.hosted.settlement import (
    _RoutePlan as _RoutePlan,
)
from pii_guard.projects.middleware import (
    CLI_TOKEN_PATH,
    MUSE_CATALOG,
    endpoint_body,
    endpoint_path,
    prepare_project,
    route_to_endpoint,
)
from pii_guard.types import PiiGuardError

__all__ = [
    "BODY_READ_SECONDS",
    "MAX_TOOL_DEFINITIONS",
    "_ALLOWED_TOOLS_CHOICE",
    "_CLIENT_TOOL_CHOICES",
    "_CLIENT_TOOL_TYPES",
    "_NAMESPACE_TOOL_TYPE",
    "HostedMiddleware",
    "HostedRequestError",
    "HostedUnauthorizedError",
    "_NestedNamespaceError",
    "_Settlement",
    "_ToolWalkLimitError",
    "_classify_tool_entry",
    "_provider_billed_tools",
    "_provider_tool_choice",
    "_walk_tools",
    "settled_tokens",
    "settlement_logger",
]

# The whole body (endpoint and hosted reads together) must arrive within this many seconds
# of taking an ingress slot, however it is trickled.
BODY_READ_SECONDS = 10
# The CLI login exchange (LAB-1708): a one-code JSON body, rate limited as anonymous work,
# held in the guest ingress pool under one shared principal, never charged inference quota.
CLI_TOKEN_MAX_BODY = 1024
_CLI_TOKEN_PRINCIPAL = Principal("cli-token-exchange", False, "guest")


def _extract_metrics_token(headers: Headers) -> str | None:
    auth = headers.get("authorization")
    header_token = headers.get("x-pii-guard-token")
    if auth and header_token:
        return None
    if auth:
        scheme, _, credential = auth.partition(" ")
        return credential.strip() if scheme.lower() == "bearer" else None
    return header_token.strip() if header_token else None


class HostedMiddleware:
    def __init__(self, app: ASGIApp, service: HostedService) -> None:
        self.app, self.service = app, service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not _is_hosted_scope(scope):
            await self.app(scope, receive, send)
            return
        state: dict[str, Any] = dict(scope.get("state", {}))
        tracker = _ResponseTracker(send=send, state=state)
        ctx = _RequestContext(scope=scope, receive=receive, state=state, tracker=tracker)
        try:
            await self._execute(ctx, key_predicate=looks_like_endpoint_key)
        except PiiGuardError as exc:
            if not tracker.started:
                response = error_response(
                    exc.status_code, exc.code, exc.message, error_headers(exc)
                )
                if isinstance(exc, AbuseAdmissionError):
                    response.headers["Retry-After"] = str(exc.retry_after)
                await response(ctx.scope, ctx.receive, tracker)
        except TimeoutError:
            if not tracker.started:
                await error_response(504, "hosted_timeout", "Hosted request timed out")(
                    ctx.scope, ctx.receive, tracker
                )
        finally:
            await self._cleanup(ctx)

    async def _execute(self, ctx: _RequestContext, *, key_predicate: Callable[[str], bool]) -> None:
        headers = Headers(scope=ctx.scope)
        _check_unique_security_headers(headers)
        path = ctx.scope.get("path", "")
        if path == CLI_TOKEN_PATH:
            await self._execute_cli_token(ctx, headers)
            return
        if path == "/metrics":
            await self._execute_metrics(ctx, headers)
            return
        principal, path, routed, endpoint_snapshot = await self._authenticate(
            ctx, headers, path, key_predicate=key_predicate
        )
        method = ctx.scope.get("method")
        plan = _classify_route(
            path,
            routed,
            headers,
            principal,
            method=method,
            hosted_images=self.service.settings.hosted_images,
            expected_origin=self.service.origin,
            key_scope=getattr(endpoint_snapshot, "key_scope", "full"),
        )
        if not plan.account:
            self.service.abuse.admit(
                headers,
                principal_id=principal.id,
                authenticated=principal.authenticated,
                anonymous_sponsored=plan.canonical == "/v1/demo" and method == "POST",
                read=plan.read_or_first_run,
            )
        headers, raw, chat_images, text_limit = await self._enter_and_read_body(
            ctx, principal, plan, endpoint_snapshot
        )
        selected_endpoint = ctx.state.get("project_endpoint")
        connection_id = headers.get("x-pii-guard-connection")
        if connection_id:
            ctx.state["hosted_connection"] = self.service.connections.get(
                principal.id, connection_id
            )
        payload = self._prepare_payload(
            plan.canonical,
            headers,
            raw,
            chat_images=chat_images,
            text_limit=text_limit,
            connection_id=connection_id,
            selected_endpoint=selected_endpoint,
        )
        ctx.state["hosted_principal"] = principal
        await self._admit_work(
            ctx,
            principal,
            plan,
            payload,
            connection_id=connection_id,
            selected_endpoint=selected_endpoint,
        )
        await self._acquire_runtime(ctx, principal, plan, selected_endpoint)
        await self._forward(ctx, payload.raw)

    async def _execute_cli_token(self, ctx: _RequestContext, headers: Headers) -> None:
        """``POST``/``DELETE /v1/cli/token`` without a session (LAB-1708).

        The route authenticates by the one-time code (``POST``) or by the telemetry key
        itself (``DELETE``). Here: no browser cross-site request, JSON only, the anonymous
        abuse bucket, a guest ingress slot, a small bounded body and no quota or runtime."""
        method = ctx.scope.get("method")
        if method not in {"POST", "DELETE"}:
            raise HostedRequestError("The CLI token route accepts POST and DELETE only")
        origin = headers.get("origin")
        if (origin is not None and origin != self.service.origin) or headers.get(
            "sec-fetch-site"
        ) == "cross-site":
            raise HostedRequestError("A same-origin request is required")
        if method == "POST":
            media = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media != "application/json":
                raise HostedRequestError("The CLI token exchange takes application/json only")
        self.service.abuse.admit(
            headers,
            principal_id=_CLI_TOKEN_PRINCIPAL.id,
            authenticated=False,
            anonymous_sponsored=True,
        )
        self.service.enter_ingress(_CLI_TOKEN_PRINCIPAL)
        ctx.ingress = _CLI_TOKEN_PRINCIPAL
        deadline = asyncio.get_running_loop().time() + min(
            BODY_READ_SECONDS, self.service.settings.hosted_request_timeout
        )
        raw = await self._read_bounded_body(ctx.receive, deadline, CLI_TOKEN_MAX_BODY)
        await self._forward(ctx, raw, keep_authorization=method == "DELETE")

    async def _execute_metrics(self, ctx: _RequestContext, headers: Headers) -> None:
        """``GET``/``HEAD /metrics`` in hosted mode when ``PII_GUARD_METRICS_TOKEN`` is set."""
        if ctx.scope.get("method") not in _READ_METHODS:
            raise HostedRequestError("This endpoint is unavailable in hosted mode")
        app = ctx.scope.get("app")
        obs = getattr(getattr(app, "state", None), "observability", None)
        token_secret = getattr(getattr(obs, "settings", None), "metrics_token", None)
        expected = token_secret.get_secret_value().strip() if token_secret is not None else ""
        provided = _extract_metrics_token(headers)
        if (
            obs is None
            or getattr(obs, "metrics", None) is None
            or not expected
            or not provided
            or not hmac.compare_digest(provided.encode(), expected.encode())
        ):
            raise HostedRequestError("This endpoint is unavailable in hosted mode")
        ctx.state["metrics_authenticated"] = True
        await self._forward(ctx, bytearray())

    async def _authenticate(
        self,
        ctx: _RequestContext,
        headers: Headers,
        path: str,
        *,
        key_predicate: Callable[[str], bool],
    ) -> tuple[Principal, str, tuple[str, str] | None, Any]:
        routed = endpoint_path(path)
        if path.startswith("/e/") and routed is None:
            raise HostedRequestError("Endpoint route is unavailable")
        auth = _extract_auth_token(headers)
        endpoint_snapshot = None
        if auth:
            if key_predicate(auth):
                principal, path, routed, endpoint_snapshot = await self._resolve_endpoint_key(
                    ctx, headers, auth, path, routed
                )
            else:
                principal = self.service.keys.resolve(auth)
            if principal is None:
                raise HostedUnauthorizedError("Invalid or expired guard API key")
            return principal, path, routed, endpoint_snapshot
        if encoded := headers.get("x-ms-client-principal"):
            principal = easy_auth_principal(
                encoded, master_key=self.service.master_key, trusted=True
            )
            return principal, path, routed, None
        return self._resolve_guest(headers, ctx.tracker), path, routed, None

    async def _resolve_endpoint_key(
        self,
        ctx: _RequestContext,
        headers: Headers,
        auth: str,
        path: str,
        routed: tuple[str, str] | None,
    ) -> tuple[Principal | None, str, tuple[str, str] | None, Any]:
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
                ctx.scope = route_to_endpoint(ctx.scope, owner)
                path = ctx.scope["path"]
                routed = endpoint_path(path)
            if routed is None:
                raise HostedRequestError("Endpoint route is unavailable")
            endpoint_snapshot = await anyio.to_thread.run_sync(
                self.service.projects.store.resolve_key, auth, routed[0]
            )
        finally:
            self.service.leave_preauth()
        principal = (
            Principal(endpoint_snapshot.owner_id, True, "api_key") if endpoint_snapshot else None
        )
        ctx.state["endpoint_key"] = True
        return principal, path, routed, endpoint_snapshot

    def _resolve_guest(self, headers: Headers, tracker: _ResponseTracker) -> Principal:
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get("cookie", ""))
        except Exception:
            raise HostedRequestError("Invalid cookie") from None
        item = cookies.get(GUEST_COOKIE_NAME)
        principal, fresh = self.service.guests.resolve(item.value if item else None)
        if fresh:
            tracker.cookie_header = self.service.guests.cookie_header(fresh)
        return principal

    async def _enter_and_read_body(
        self,
        ctx: _RequestContext,
        principal: Principal,
        plan: _RoutePlan,
        endpoint_snapshot: Any,
    ) -> tuple[Headers, bytearray, bool, int]:
        # Only now, with identity, path, origin and abuse admission settled, does the
        # request take an ingress slot: from the guest or the signed-in pool, and within
        # its principal's share (LAB-1442). One deadline then bounds every body read.
        self.service.enter_ingress(principal)
        ctx.ingress = principal
        deadline = asyncio.get_running_loop().time() + min(
            BODY_READ_SECONDS, self.service.settings.hosted_request_timeout
        )
        endpoint_limit = (
            self.service.settings.hosted_max_body_bytes
            if plan.canonical == "/v1/traffic"
            else self.service.settings.hosted_endpoint_max_body_bytes
        )
        if principal.authenticated and plan.canonical not in {"/v1/account", "/v1/demo"}:
            ctx.state = await anyio.to_thread.run_sync(
                prepare_project,
                self.service.projects,
                {**ctx.scope, "state": ctx.state},
                principal.id,
                endpoint_snapshot,
            )
            ctx.tracker.state = ctx.state
            async with asyncio.timeout_at(deadline):
                ctx.scope, ctx.receive = await endpoint_body(
                    ctx.scope,
                    ctx.receive,
                    ctx.state,
                    endpoint_limit,
                )
        headers = Headers(scope=ctx.scope)
        # Text routes stay text-sized; the image route gets its own bounded limit, and
        # so does a signed-in owner's direct chat while the operator offers chat images
        # (LAB-1439). The non-image bytes of a chat body are held to the text limit below.
        chat_images = (
            chat_images_enabled(self.service.settings)
            and plan.canonical in _CHAT_ROUTES
            and principal.auth_method == "google"
            and plan.routed is None
        )
        # Endpoint routes carry coding agents' prompts and tool schemas: their own limit
        # (LAB-1651); the console, guard API keys and traffic telemetry keep the text limit.
        text_limit = (
            self.service.settings.hosted_endpoint_max_body_bytes
            if plan.routed is not None and plan.canonical != "/v1/traffic"
            else self.service.settings.hosted_max_body_bytes
        )
        if plan.image:
            body_limit = image_body_limit(self.service.settings)
        elif chat_images:
            body_limit = chat_body_limit(self.service.settings)
        else:
            body_limit = text_limit
        raw = (
            bytearray()
            if ctx.scope.get("method") in _SAFE_METHODS
            else await self._read_bounded_body(ctx.receive, deadline, body_limit)
        )
        return headers, raw, chat_images, text_limit

    async def _read_bounded_body(
        self, receive: Receive, deadline: float, body_limit: int
    ) -> bytearray:
        raw = bytearray()
        async with asyncio.timeout_at(deadline):
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    # The client is gone: stop reading without sending anything.
                    # Raised, not returned, so uvicorn does not log "ASGI callable
                    # returned without completing response" (LAB-1468); the
                    # PiiGuardError handler answers 499 and the finally block
                    # still releases the reservation and leaves ingress.
                    raise ClientDisconnectedError("client disconnected during body read")
                raw.extend(message.get("body", b""))
                if len(raw) > body_limit:
                    raise HostedRequestError("Hosted request body is too large")
                if not message.get("more_body", False):
                    return raw

    def _prepare_payload(
        self,
        canonical: str,
        headers: Headers,
        raw: bytearray,
        *,
        chat_images: bool,
        text_limit: int,
        connection_id: str | None,
        selected_endpoint: Any,
    ) -> _PayloadSpec:
        if canonical not in _CHAT_ROUTES:
            return _PayloadSpec(raw=raw, output_limit=DEMO_MAX_OUTPUT_TOKENS)
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise HostedRequestError("Invalid JSON request") from None
        if not isinstance(body, dict) or headers.get("x-pii-guard-mode", "fast") != "fast":
            raise HostedRequestError("Hosted requests require fast text mode")
        sponsored_route = not connection_id and (
            selected_endpoint is None or selected_endpoint.provider == "sponsored"
        )
        if sponsored_route:
            self._validate_sponsored_chat_body(canonical, body)
        if body.get("n", 1) != 1:
            raise HostedRequestError("Hosted requests allow one completion")
        inline_images, image_bytes = self._validate_chat_images(
            canonical,
            body,
            len(raw),
            text_limit,
            chat_images=chat_images,
            connection_id=connection_id,
        )
        output_limit, strip_usage = self._clamp_output_and_stream_usage(
            canonical, body, sponsored_route=sponsored_route
        )
        return _PayloadSpec(
            raw=bytearray(json.dumps(body).encode()),
            output_limit=output_limit,
            inline_images=inline_images,
            image_bytes=image_bytes,
            strip_usage=strip_usage,
        )

    def _validate_sponsored_chat_body(self, canonical: str, body: dict[str, Any]) -> None:
        if body.get("model") not in self.service.settings.hosted_models:
            raise HostedRequestError("Model is not allowed for sponsored requests")
        try:
            provider_tools = _provider_billed_tools(body, namespaces=canonical == "/v1/responses")
        except _ToolWalkLimitError:
            raise HostedRequestError(
                f"Hosted requests allow at most {MAX_TOOL_DEFINITIONS} tool definitions"
            ) from None
        except _NestedNamespaceError:
            raise HostedRequestError(
                "Namespace tools cannot hold other namespaces in sponsored requests"
            ) from None
        if provider_tools:
            # Provider-side tools (Meta web search grounding: USD 2.50 per 1,000
            # queries, LAB-1372) are billed outside the token usage the reservation
            # bounds, so the sponsored route never asks for them.
            raise HostedRequestError("Provider-side tools are not allowed for sponsored requests")

    def _validate_chat_images(
        self,
        canonical: str,
        body: dict[str, Any],
        raw_len: int,
        text_limit: int,
        *,
        chat_images: bool,
        connection_id: str | None,
    ) -> tuple[int, int]:
        inline_images, image_bytes = count_chat_images(canonical, body) if chat_images else (0, 0)
        # The text limit holds with or without images: only the inline images' own
        # base64 (the encoded length of their decoded bytes, never more than their
        # data URLs take in ``raw``) is left out, so ``len(raw) - image_bytes`` is an
        # upper bound on everything else in the body.
        if raw_len - image_bytes > text_limit:
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
        return inline_images, image_bytes

    def _clamp_output_and_stream_usage(
        self, canonical: str, body: dict[str, Any], *, sponsored_route: bool
    ) -> tuple[int, bool]:
        maximum = self.service.settings.hosted_max_output_tokens
        output_field = (
            "max_output_tokens" if canonical == "/v1/responses" else "max_completion_tokens"
        )
        # A limit above the hosted cap is clamped to it, not refused (LAB-1651): coding
        # agents ask for 16k-32k (OpenCode 32000, pi 16384, Muse 32000) and can't be
        # told otherwise. Every field is only an upper bound on the reply, so the
        # smallest one wins and the reservation below charges that, never more. A
        # value that isn't a positive integer is still refused.
        for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
            value = body.pop(key, maximum)
            if type(value) is not int or value < 1:
                raise HostedRequestError("Output token limit is outside hosted limits")
            maximum = min(maximum, value)
        body[output_field] = maximum
        strip_usage = False
        if sponsored_route and canonical == "/v1/chat/completions" and body.get("stream") is True:
            # Sponsored chat streams always ask for the usage chunk (api.meta.ai
            # accepts it: eval/results/2026-10-28-lab-1372-meta-reasoning), so they
            # settle to real usage; the gateway hides it unless the client asked.
            options = body.get("stream_options", {})
            if isinstance(options, dict):
                strip_usage = options.get("include_usage") is not True
                body["stream_options"] = {**options, "include_usage": True}
        return maximum, strip_usage

    def _compute_work_tokens(
        self, plan: _RoutePlan, payload: _PayloadSpec
    ) -> tuple[int, int, int | None, Any]:
        image_charge = None
        payload_limit = None
        if plan.paid:
            # Sized from this request: the gateway refuses a masked payload beyond
            # the bound, and output is the request's own (capped) token limit.
            payload_limit = upstream_payload_bound(len(payload.raw))
            input_tokens, output_tokens = payload_limit, payload.output_limit
            if payload.inline_images:
                # The text bound leaves the image bytes out; each image adds its
                # transcript room and a fixed provider input charge (LAB-1439).
                image_charge = chat_image_charge(
                    self.service.settings,
                    payload.inline_images,
                    upstream_payload_bound(len(payload.raw) - payload.image_bytes),
                )
                payload_limit = image_charge.payload_bytes
                input_tokens = image_charge.input_tokens
        else:
            input_tokens, output_tokens = len(payload.raw), 0
        if plan.image:
            # A fixed compute charge plus one from the separate daily image count:
            # reserved here, before any decoding or OCR, and never refunded.
            input_tokens = IMAGE_COMPUTE_TOKENS
        return input_tokens, output_tokens, payload_limit, image_charge

    async def _admit_work(
        self,
        ctx: _RequestContext,
        principal: Principal,
        plan: _RoutePlan,
        payload: _PayloadSpec,
        *,
        connection_id: str | None,
        selected_endpoint: Any,
    ) -> None:
        # The account remains available after exhaustion; mutations and data work consume
        # compute quotas. The full conservative charge survives failure.
        if not plan.work:
            ctx.state["hosted_chat_images"] = 0
            return
        input_tokens, output_tokens, ctx.payload_limit, image_charge = self._compute_work_tokens(
            plan, payload
        )
        sponsored = (
            plan.paid
            and not connection_id
            and (selected_endpoint is None or selected_endpoint.provider == "sponsored")
        )
        if sponsored:
            self.service.check_kill_switch()
        images = 1 if plan.image else (image_charge.images if image_charge else 0)
        ctx.reservation = self.service.quotas.admit(
            principal.id,
            authenticated=principal.authenticated,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            sponsored=sponsored and self.service.spend is None,
            images=images,
        )
        if plan.paid:
            # From here on the reservation is settled once the response has closed:
            # to the upstream's real usage, or nothing if no upstream call happened.
            ctx.settlement = _Settlement(
                request_id=secrets.token_hex(16),
                route=plan.canonical,
                user=hmac.digest(
                    self.service.master_key,
                    b"settlement\0" + principal.id.encode(),
                    "sha256",
                ).hex()[:16],
                reservation=ctx.reservation,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                durable=sponsored and self.service.spend is not None,
                fixed_input=bool(payload.inline_images),
                meter=UpstreamMeter(strip_usage=payload.strip_usage),
            )
        if sponsored and self.service.spend is not None:
            try:
                await self.service.charge_spend(
                    input_tokens,
                    output_tokens,
                    ctx.settlement.request_id if ctx.settlement else None,
                )
            except BaseException:
                # Nothing ran: give the in-memory tokens back now (settlement in
                # ``finally`` then refunds a durable charge that committed late).
                ctx.reservation.settle(0, 0)
                raise
        # What the gateway may mask: only the images this admission charged for.
        ctx.state["hosted_chat_images"] = image_charge.images if image_charge else 0

    async def _acquire_runtime(
        self,
        ctx: _RequestContext,
        principal: Principal,
        plan: _RoutePlan,
        selected_endpoint: Any,
    ) -> None:
        if not plan.needs_runtime:
            return
        if plan.canonical == "/v1/traffic/stream":
            # A live stream trades its ingress slot for a bounded stream slot.
            self.service.enter_stream(principal.id)
            ctx.streaming = principal.id
            self.service.leave_ingress(principal)
            ctx.ingress = None
        project_id = ctx.state.get("project_id")
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
        ctx.runtime = self.service.acquire(principal, namespace=namespace)
        ctx.state["hosted_runtime"] = ctx.runtime
        if selected_endpoint is not None:
            # Each stored event names the endpoint it went through, so the project's
            # merged Logs can tell them apart (the name as of this request).
            ctx.runtime.observability.traffic.labels = {
                "endpoint": {"id": selected_endpoint.id, "name": selected_endpoint.name}
            }
        elif (
            plan.canonical in {"/v1/traffic", "/v1/traffic/stream"}
            and ctx.scope.get("method") in _READ_METHODS
        ):
            # No endpoint selected: the project's own runtime plus its endpoints'
            # (LAB-1492). Vault and session routes stay on one runtime.
            ctx.state["hosted_traffic"] = self.service.project_traffic(ctx.runtime, project_id)

    async def _forward(
        self, ctx: _RequestContext, raw: bytearray, *, keep_authorization: bool = False
    ) -> None:
        filtered = _filter_forward_headers(ctx.scope.get("headers", []), len(raw))
        if keep_authorization:
            # Only the CLI logout: the route revokes the very key it is shown.
            filtered.extend(
                (k, v) for k, v in ctx.scope.get("headers", []) if k.lower() == b"authorization"
            )
        consumed = False

        async def body_receive() -> Message:
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(raw), "more_body": False}
            return await ctx.receive()

        limit_token = UPSTREAM_PAYLOAD_LIMIT.set(ctx.payload_limit)
        meter_token = UPSTREAM_METER.set(ctx.settlement.meter if ctx.settlement else None)
        try:
            async with asyncio.timeout(self.service.settings.hosted_request_timeout):
                await self.app(
                    {**ctx.scope, "headers": filtered, "state": ctx.state},
                    body_receive,
                    ctx.tracker,
                )
        finally:
            UPSTREAM_METER.reset(meter_token)
            UPSTREAM_PAYLOAD_LIMIT.reset(limit_token)

    async def _cleanup(self, ctx: _RequestContext) -> None:
        gateway = ctx.state.get("project_gateway") or ctx.state.get("hosted_gateway")
        try:
            if gateway is not None:
                async with asyncio.timeout(5):
                    await gateway.aclose()
        finally:
            try:
                if ctx.settlement is not None:
                    await self._settle(ctx.settlement)
            finally:
                if ctx.runtime is not None:
                    self.service.release(ctx.runtime)
                if ctx.reservation is not None:
                    ctx.reservation.release()
                if ctx.ingress is not None:
                    self.service.leave_ingress(ctx.ingress)
                if ctx.streaming is not None:
                    self.service.leave_stream(ctx.streaming)

    async def _settle(self, settlement: _Settlement) -> None:
        """Settle one paid reservation down to its usage and log one line.

        Raises no ``Exception``: a failed refund leaves the charge in full. A cancellation
        (``CancelledError``) during the durable refund still propagates, after the log line
        (``refund_outcome=cancelled``; the refund may or may not have committed).
        """
        tokens_in, tokens_out, outcome = settled_tokens(
            settlement.input_tokens,
            settlement.output_tokens,
            settlement.meter,
            fixed_input=settlement.fixed_input,
        )
        reservation = settlement.reservation
        refunded_tokens, refunded_spend = reservation.settle(
            tokens_in + tokens_out,
            self.service.spend_cost(tokens_in, tokens_out) if reservation.spend else 0,
        )
        reserved = reservation.spend
        settled = reservation.spend - refunded_spend
        refund_outcome = "memory" if reservation.spend else "none"
        try:
            if settlement.durable:
                reserved = self.service.spend_cost(
                    settlement.input_tokens, settlement.output_tokens
                )
                settled, refund_outcome = reserved, "cancelled"
                refunded_spend, refund_outcome = await self.service.refund_spend(
                    settlement.request_id, tokens_in, tokens_out
                )
                settled = reserved - refunded_spend
        finally:
            # Counts and an opaque per-user digest only: no payload text, identity or key.
            settlement_logger.info(
                "settlement route=%s user=%s outcome=%s sponsored=%s refund_outcome=%s "
                "reserved_tokens=%d settled_tokens=%d refunded_tokens=%d "
                "reserved_microdollars=%d settled_microdollars=%d refunded_microdollars=%d",
                settlement.route,
                settlement.user,
                outcome,
                "durable" if settlement.durable else ("memory" if reservation.spend else "no"),
                refund_outcome,
                settlement.input_tokens + settlement.output_tokens,
                tokens_in + tokens_out,
                refunded_tokens,
                reserved,
                settled,
                refunded_spend if refund_outcome != "cancelled" else 0,
            )
