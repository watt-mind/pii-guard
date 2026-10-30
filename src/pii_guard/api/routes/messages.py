"""``POST /v1/messages`` and ``/v1/messages/count_tokens``: the Anthropic Messages API.

Claude Code (and any Anthropic SDK client) speaks this API. Both routes are
:class:`~pii_guard.gateway.messages.MessagesGateway` (LAB-1605): mask the request, forward it
to the upstream's own ``/messages`` (or ``/messages/count_tokens``), restore the (streamed)
answer, on the same detectors, cache, vault and sessions as ``/v1/chat/completions``.

An upstream without a Messages API answers ``400 unsupported_api`` (the error LAB-1313
introduced, with ``x-should-retry: false``): Claude Code shows a 5xx as "a server-side issue,
usually temporary" (checked with Claude Code 2.1.312), which this is not. Every call, refused or
not, is one traffic event, so it shows in Logs.
"""

from __future__ import annotations

import json
import threading
import time

from fastapi import Request
from starlette.responses import Response

from pii_guard.api.deps import get_max_text_chars
from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import ensure_connected, log_extra, v1_router
from pii_guard.api.routes.chat import GatewayRoute, get_gateway
from pii_guard.gateway.messages import MessagesGateway, UnsupportedApiError
from pii_guard.gateway.request import InvalidChatRequestError
from pii_guard.gateway.sessions import path_session
from pii_guard.gateway.trace import new_request_id

__all__ = ["UnsupportedApiError", "get_messages_gateway", "router"]

# Same route class as chat: inline image bodies get the gateway allowance (LAB-1566).
router = v1_router(GatewayRoute)
_lock = threading.Lock()


def get_messages_gateway(request: Request) -> MessagesGateway:
    state = request.app.state
    gateway = get_gateway(request)
    if getattr(state, "hosted", None) is not None or getattr(
        request.state, "project_routed_endpoint", False
    ):
        return MessagesGateway(gateway)
    messages = getattr(state, "messages_gateway", None)
    if messages is None or messages.gateway is not gateway:
        with _lock:
            messages = getattr(state, "messages_gateway", None)
            if messages is None or messages.gateway is not gateway:
                messages = MessagesGateway(gateway)
                state.messages_gateway = messages
    return messages


async def _serve(request: Request, *, count_tokens: bool) -> Response:
    await ensure_connected(request)
    gateway = get_messages_gateway(request)
    raw = await request.body()
    received_at = time.perf_counter()
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        # Never the decoder's message: it quotes the body.
        raise InvalidChatRequestError("request body is not valid JSON") from None
    # The traffic event id, assigned before detection (LAB-1179): even a refused call
    # carries it, so the client can join the error to its traffic event.
    request.state.pii_guard_request_id = new_request_id()
    response, stats = await gateway.messages(
        body,
        request.headers,
        max_text_chars=get_max_text_chars(request),
        received_at=received_at,
        path_session=path_session(request.scope),
        request_id=request.state.pii_guard_request_id,
        count_tokens=count_tokens,
    )
    log_extra(request, **stats.log_fields())
    return response


_RESPONSES = error_responses("unsupported_api", "detection_profile_denied", "outbound_check_failed")


@router.post("/v1/messages", tags=["gateway"], responses=_RESPONSES)
async def messages(request: Request) -> Response:
    return await _serve(request, count_tokens=False)


@router.post("/v1/messages/count_tokens", tags=["gateway"], responses=_RESPONSES)
async def count_tokens(request: Request) -> Response:
    return await _serve(request, count_tokens=True)
