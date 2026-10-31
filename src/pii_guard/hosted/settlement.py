"""Hosted admission settlement and provider-billed tool inspection."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from starlette.datastructures import Headers
from starlette.types import Message, Receive, Scope, Send

from pii_guard.gateway.meter import UpstreamMeter
from pii_guard.hosted.identity import Principal
from pii_guard.hosted.images import IMAGE_PATH
from pii_guard.hosted.quotas import Reservation
from pii_guard.types import PiiGuardError

__all__ = [
    "MAX_TOOL_DEFINITIONS",
    "_ALLOWED_TOOLS_CHOICE",
    "_CLIENT_TOOL_CHOICES",
    "_CLIENT_TOOL_TYPES",
    "_NAMESPACE_TOOL_TYPE",
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

settlement_logger = logging.getLogger("pii_guard.hosted.settlement")


@dataclass(slots=True)
class _Settlement:
    """One paid admission, settled once its response has closed (LAB-1662)."""

    request_id: str
    route: str
    user: str
    reservation: Reservation
    input_tokens: int
    output_tokens: int
    #: The durable sponsored ledger holds a charge for this request.
    durable: bool
    #: Inline images: the input reservation is a fixed provider price, not payload bytes.
    fixed_input: bool
    meter: UpstreamMeter


def settled_tokens(
    reserved_input: int, reserved_output: int, meter: UpstreamMeter, *, fixed_input: bool
) -> tuple[int, int, str]:
    """The (input, output) tokens a finished request is settled to, and how they were found.

    Never above the reservation. No upstream call: nothing. Reported usage: that usage.
    Otherwise (an aborted stream, an error answer, a timeout or transport error after the
    send) the masked payload's bytes as input (a byte-level tokenizer never emits more tokens
    than bytes, so this never underestimates the real input) and the full output reservation:
    muse-spark-1.3 bills hidden reasoning inside its output tokens and streams nothing for
    it, so no output seen is no evidence of no output billed.
    """
    if not meter.forwarded:
        return 0, 0, "no_upstream"
    if meter.input_tokens is not None and meter.output_tokens is not None:
        tokens_in, tokens_out, outcome = meter.input_tokens, meter.output_tokens, "usage"
    else:
        tokens_in, tokens_out, outcome = meter.payload_bytes, reserved_output, "estimated"
    if fixed_input:
        tokens_in = reserved_input
    return min(tokens_in, reserved_input), min(tokens_out, reserved_output), outcome


# Tool types a client executes itself; any other type (web search, file search, code
# interpreter, MCP) runs and bills at the provider, outside the reserved token usage.
_CLIENT_TOOL_TYPES = frozenset({"function", "custom"})
# Responses API only: a ``namespace`` groups client tools under one name (Codex's
# ``multi_agent_v1``, Muse Code's ``muse``, LAB-1658). It is client-side only when every tool
# it holds is; the upstream (api.meta.ai) takes it as is and calls the tools
# ``<namespace>.<name>``, so nothing is flattened. Namespaces appear only in the top-level
# array: masking refuses a nested one after admission, so it is refused here first (LAB-1659).
_NAMESPACE_TOOL_TYPE = "namespace"
# ``tool_choice`` strings and object types that only steer client tools; any other object
# (``{"type": "web_search_preview"}``, ``{"type": "mcp", ...}``) asks for a provider tool.
_CLIENT_TOOL_CHOICES = frozenset({"auto", "none", "required"})
_ALLOWED_TOOLS_CHOICE = "allowed_tools"
# Bound on the tool walk: tool definitions counted across both levels. Clients send a few
# dozen; past the bound the request is refused rather than walked.
MAX_TOOL_DEFINITIONS = 512


class _ToolWalkLimitError(Exception):
    """The tool array counts past the walk bound."""


class _NestedNamespaceError(Exception):
    """A namespace tool holds another namespace."""


def _provider_tool_choice(choice: Any) -> bool:
    """Whether ``tool_choice`` names anything but a client tool or a plain mode."""
    if isinstance(choice, str):
        return choice not in _CLIENT_TOOL_CHOICES
    if not isinstance(choice, dict):
        return True
    choice_type = choice.get("type")
    if not isinstance(choice_type, str):
        return True
    if choice_type in _CLIENT_TOOL_TYPES:
        return False
    if choice_type != _ALLOWED_TOOLS_CHOICE:
        return True
    allowed = choice.get("tools")
    if not isinstance(allowed, list):
        return True
    return not all(
        isinstance(entry, dict)
        and isinstance(entry.get("type"), str)
        and entry["type"] in _CLIENT_TOOL_TYPES
        for entry in allowed
    )


def _classify_tool_entry(
    tool: Any, *, namespaces: bool, nested: bool
) -> tuple[bool, list[Any] | None]:
    """Classify one tool entry as ``(is_provider_tool, namespace_children)``."""
    if not isinstance(tool, dict):
        return True, None
    tool_type = tool.get("type", "function")
    if not isinstance(tool_type, str):
        return True, None
    if tool_type in _CLIENT_TOOL_TYPES:
        return False, None
    if not namespaces or tool_type != _NAMESPACE_TOOL_TYPE:
        return True, None
    if nested:
        raise _NestedNamespaceError
    inner = tool.get("tools")
    if not isinstance(inner, list):
        return True, None
    return False, inner


def _walk_tools(
    entries: list[Any], *, namespaces: bool, nested: bool = False, seen: int = 0
) -> tuple[bool, int]:
    """Walk tool definitions up to :data:`MAX_TOOL_DEFINITIONS`."""
    for tool in entries:
        seen += 1
        if seen > MAX_TOOL_DEFINITIONS:
            raise _ToolWalkLimitError
        is_provider, children = _classify_tool_entry(tool, namespaces=namespaces, nested=nested)
        if is_provider:
            return True, seen
        if children is not None:
            child_provider, seen = _walk_tools(
                children, namespaces=namespaces, nested=True, seen=seen
            )
            if child_provider:
                return True, seen
    return False, seen


def _provider_billed_tools(body: dict[str, Any], *, namespaces: bool = False) -> bool:
    """Whether a chat or Responses body asks the provider for separately billed tool work.

    ``namespaces`` (Responses API): accept top-level ``namespace`` tools whose tools are all
    client-side. Raises :class:`_NestedNamespaceError` for a namespace inside a namespace and
    :class:`_ToolWalkLimitError` past the count bound.
    """
    if "web_search_options" in body:
        return True
    if "tool_choice" in body and _provider_tool_choice(body["tool_choice"]):
        return True
    tools = body.get("tools")
    if tools is None:
        return False
    if not isinstance(tools, list):
        return True
    is_provider, _ = _walk_tools(tools, namespaces=namespaces)
    return is_provider


_BYPASS_PATHS = frozenset({"/healthz", "/readyz", "/readyz/serving"})
_HOSTED_PREFIXES = (
    "/v1",
    "/e/",
    "/s/",
    "/muse-code",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi",
)
_PROTECTED_HEADERS = frozenset(
    {
        "authorization",
        "x-pii-guard-token",
        "x-ms-client-principal",
        "origin",
        "x-pii-guard-connection",
        "cookie",
        "x-pii-guard-project",
        "x-pii-guard-endpoint",
    }
)
_ALLOWED_ROUTES = frozenset(
    {
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
)
_CONSOLE_ROUTES = frozenset({"/v1/status", "/v1/connect/snippets"})
_CREDENTIAL_ROUTES = frozenset(
    {
        "/v1/account/api-keys",
        "/v1/account/connections",
        "/v1/account/first-run",
    }
)
_PAID_ROUTES = frozenset({"/v1/chat/completions", "/v1/responses", "/v1/demo"})
_CHAT_ROUTES = frozenset({"/v1/chat/completions", "/v1/responses"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_READ_METHODS = frozenset({"GET", "HEAD"})
_DEMO_FORBIDDEN_HEADERS = (
    "x-pii-guard-connection",
    "x-pii-guard-session",
    "x-pii-guard-mode",
)
_STRIPPED_FORWARD_HEADERS = frozenset(
    {
        b"authorization",
        b"x-pii-guard-token",
        b"cookie",
        b"content-length",
        b"x-forwarded-for",
        b"forwarded",
        b"x-real-ip",
    }
)
_SESSION_PREFIX_RE = re.compile(r"^/s/[^/]+(?=/v1/|/muse-code/)")
_PARAMETERIZED_ROUTE_RE = re.compile(
    r"/v1/(?:sessions/[^/]+/known-values|vault/sessions/[^/]+|"
    r"account/(?:api-keys|connections)/[^/]+)"
)
_PROJECT_SUBPATH_RE = re.compile(
    r"/v1/projects/[A-Za-z0-9_-]+(?:/(?:policies|endpoints)"
    r"(?:/[A-Za-z0-9_-]+(?:/keys(?:/[A-Za-z0-9_-]+)?)?)?|/cli-codes)?"
)
_PROJECT_POLICY_VERSION_RE = re.compile(
    r"/v1/projects/[A-Za-z0-9_-]+/policies/versions/[A-Za-z0-9_-]+"
)
_CREDENTIAL_ITEM_RE = re.compile(r"/v1/account/(?:api-keys|connections)/[^/]+")


class HostedRequestError(PiiGuardError):
    status_code = 403
    code = "hosted_request_denied"


class HostedUnauthorizedError(PiiGuardError):
    status_code = 401
    code = "unauthorized"


@dataclass(slots=True)
class _ResponseTracker:
    """ASGI ``send`` wrapper that stamps hosted response headers and tracks response start."""

    send: Send
    state: dict[str, Any]
    cookie_header: str | None = None
    started: bool = False

    async def __call__(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self.started = True
            message = dict(message)
            headers = list(message.get("headers", []))
            headers.append((b"cache-control", b"no-store"))
            if self.state.get("project_policy"):
                headers.append(
                    (
                        b"x-pii-guard-policy-version",
                        self.state["project_policy"]["policy_version_id"].encode(),
                    )
                )
                headers.append((b"x-pii-guard-project", self.state["project_id"].encode()))
            if self.cookie_header is not None:
                headers.append((b"set-cookie", self.cookie_header.encode("ascii")))
            message["headers"] = headers
        await self.send(message)


@dataclass(slots=True)
class _RequestContext:
    """Mutable per-request state and resource leases released on exit."""

    scope: Scope
    receive: Receive
    state: dict[str, Any]
    tracker: _ResponseTracker
    runtime: Any = None
    reservation: Reservation | None = None
    #: The principal holding an ingress slot; set only once identity and admission pass.
    ingress: Principal | None = None
    streaming: str | None = None
    payload_limit: int | None = None
    settlement: _Settlement | None = None


@dataclass(frozen=True, slots=True)
class _RoutePlan:
    """Classified route permissions and resource requirements."""

    path: str
    canonical: str
    routed: tuple[str, str] | None
    image: bool
    needs_runtime: bool
    work: bool
    paid: bool
    read_or_first_run: bool
    account: bool


@dataclass(slots=True)
class _PayloadSpec:
    """Validated request body and token/image admission parameters."""

    raw: bytearray
    output_limit: int
    inline_images: int = 0
    image_bytes: int = 0
    strip_usage: bool = False


def _is_hosted_scope(scope: Scope) -> bool:
    if scope["type"] != "http":
        return False
    path = scope.get("path", "")
    return path not in _BYPASS_PATHS and path.startswith(_HOSTED_PREFIXES)


def _check_unique_security_headers(headers: Headers) -> None:
    for name in _PROTECTED_HEADERS:
        if len(headers.getlist(name)) > 1:
            raise HostedRequestError("Duplicate security header")


def _extract_auth_token(headers: Headers) -> str | None:
    auth = headers.get("authorization") or headers.get("x-pii-guard-token")
    if not auth:
        return None
    if headers.get("authorization"):
        scheme, _, auth = auth.partition(" ")
        if scheme.lower() != "bearer":
            raise HostedUnauthorizedError("Invalid guard API key")
    return auth


def _is_project_management(canonical: str) -> bool:
    return (
        canonical == "/v1/projects"
        or _PROJECT_SUBPATH_RE.fullmatch(canonical) is not None
        or _PROJECT_POLICY_VERSION_RE.fullmatch(canonical) is not None
    )


def _is_credential_route(canonical: str) -> bool:
    return canonical in _CREDENTIAL_ROUTES or _CREDENTIAL_ITEM_RE.fullmatch(canonical) is not None


def _check_owner_only_routes(
    canonical: str,
    principal: Principal,
    *,
    routed: tuple[str, str] | None,
    method: str | None,
    image: bool,
    project_management: bool,
    credentials: bool,
) -> None:
    if image:
        if principal.auth_method != "google":
            raise HostedUnauthorizedError("Image masking requires signed-in owner access")
        if routed is not None or method != "POST":
            raise HostedRequestError("Image masking accepts a direct POST only")
    if project_management and principal.auth_method != "google":
        raise HostedUnauthorizedError("Project management requires signed-in owner access")
    if canonical in _CONSOLE_ROUTES and principal.auth_method != "google":
        raise HostedUnauthorizedError("The console requires signed-in owner access")
    if credentials and principal.auth_method != "google":
        # A guard API key must never mint keys or connections that outlive it.
        raise HostedUnauthorizedError("Key and connection management requires a signed-in session")


def _check_access_and_origin(
    path: str,
    canonical: str,
    headers: Headers,
    principal: Principal,
    *,
    method: str | None,
    expected_origin: str,
) -> None:
    if canonical not in {"/v1/account", "/v1/demo"} and not principal.authenticated:
        raise HostedUnauthorizedError("Sign in with Google to use this endpoint")
    if canonical == "/v1/demo" and (
        path != canonical or any(headers.get(h) for h in _DEMO_FORBIDDEN_HEADERS)
    ):
        raise HostedRequestError("Demo accepts only a curated sample selection")
    if method not in _SAFE_METHODS:
        origin = headers.get("origin")
        if (principal.auth_method != "api_key" or origin is not None) and origin != expected_origin:
            raise HostedRequestError("A same-origin request is required")
        if headers.get("sec-fetch-site") == "cross-site":
            raise HostedRequestError("A same-origin request is required")


def _classify_route(
    path: str,
    routed: tuple[str, str] | None,
    headers: Headers,
    principal: Principal,
    *,
    method: str | None,
    hosted_images: bool,
    expected_origin: str,
    key_scope: str = "full",
) -> _RoutePlan:
    canonical = routed[1] if routed else _SESSION_PREFIX_RE.sub("", path)
    if routed is not None and canonical == "/v1/traffic" and method != "POST":
        raise HostedRequestError("Endpoint traffic route accepts POST only")
    if key_scope != "full" and not (
        key_scope == "telemetry"
        and routed is not None
        and canonical == "/v1/traffic"
        and method == "POST"
    ):
        # A CLI login key (LAB-1708) writes the project's Logs and nothing else: no
        # sponsored model call, catalog or other route, whatever the endpoint allows.
        raise HostedRequestError("A telemetry key can only post traffic events")
    # Hosted images (ADR 0014): signed-in Google owners only, never by key or as a
    # guest, never through an endpoint path, and only while the operator offers them.
    image = canonical == IMAGE_PATH and hosted_images
    project_management = _is_project_management(canonical)
    credentials = _is_credential_route(canonical)
    _check_owner_only_routes(
        canonical,
        principal,
        routed=routed,
        method=method,
        image=image,
        project_management=project_management,
        credentials=credentials,
    )
    parameterized = _PARAMETERIZED_ROUTE_RE.fullmatch(canonical)
    if (
        canonical not in _ALLOWED_ROUTES
        and not image
        and parameterized is None
        and not project_management
    ):
        raise HostedRequestError("This endpoint is unavailable in hosted mode")
    _check_access_and_origin(
        path,
        canonical,
        headers,
        principal,
        method=method,
        expected_origin=expected_origin,
    )
    read = method in _READ_METHODS
    preflight = method == "OPTIONS"
    # First run (LAB-1455) provisions the owner's default endpoint and its first key:
    # a signed-in owner's, like key management, and free like the account itself.
    first_run = canonical == "/v1/account/first-run"
    # Scrubbed traffic telemetry from a local gateway spends no inference quota;
    # the abuse read bucket and text body limit bound it (LAB-1704).
    traffic_ingest = canonical == "/v1/traffic" and method == "POST"
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
        work = not (account or preflight or read or first_run or traffic_ingest)
    return _RoutePlan(
        path=path,
        canonical=canonical,
        routed=routed,
        image=image,
        needs_runtime=needs_runtime,
        work=work,
        paid=canonical in _PAID_ROUTES,
        read_or_first_run=read or first_run or traffic_ingest,
        account=account,
    )


def _filter_forward_headers(
    raw_headers: list[tuple[bytes, bytes]], body_len: int
) -> list[tuple[bytes, bytes]]:
    filtered = [
        (k, v)
        for k, v in raw_headers
        if k.lower() not in _STRIPPED_FORWARD_HEADERS and not k.lower().startswith(b"x-ms-")
    ]
    filtered.append((b"content-length", str(body_len).encode()))
    return filtered
