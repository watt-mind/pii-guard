"""``POST /v1/messages``: the Anthropic Messages API is not served yet (LAB-1313).

Claude Code (and any Anthropic SDK client) speaks ``POST /v1/messages``. The gateway masks
only the OpenAI-compatible APIs (``/v1/chat/completions``, ``/v1/responses``), so this route
answers ``400 unsupported_api`` with a message that names them and the console's Connect page,
instead of a bare 405 that Claude Code reports as a problem with the selected model.

Nothing is detected, stored or forwarded. The attempt is still recorded as one ``refused``
traffic event, so it shows in Logs. The event carries the request's ``model`` and ``stream``
only: the body is never masked here, so its text is never kept, at any traffic level.
It is a 400, not a 501: Claude Code shows a 5xx as "a server-side issue, usually temporary"
(checked with Claude Code 2.1.312), which this is not. ``x-should-retry: false`` also tells
Anthropic SDKs not to retry.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from starlette.responses import Response

from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import v1_router
from pii_guard.api.routes.traffic import _observability
from pii_guard.gateway.service import REQUEST_ID_HEADER
from pii_guard.gateway.trace import CallTrace
from pii_guard.observability import RequestTimer
from pii_guard.types import PiiGuardError

__all__ = ["UnsupportedApiError", "router"]

router = v1_router()

MESSAGE = (
    "the Anthropic Messages API (/v1/messages) is not supported yet, so Claude Code cannot "
    "use this gateway; use an OpenAI-compatible client with /v1/chat/completions or "
    "/v1/responses (see the Connect page in the PII Guard console). Nothing was sent upstream."
)


class UnsupportedApiError(PiiGuardError):
    """The client spoke an API the gateway does not serve; nothing was processed."""

    code = "unsupported_api"
    status_code = 400

    def __init__(self, message: str, headers: dict[str, str]) -> None:
        super().__init__(message)
        self.headers = headers


def _summary(raw: bytes) -> dict[str, Any]:
    """Only ``model`` and ``stream`` of the body, for the event; never its text."""
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return {}
    if not isinstance(body, dict):
        return {}
    model = body.get("model")
    return {
        "model": model if isinstance(model, str) and len(model) <= 256 else None,
        "stream": body.get("stream") is True,
    }


async def _unsupported(request: Request) -> Response:
    trace = CallTrace(_observability(request), RequestTimer(), _summary(await request.body()))
    error = UnsupportedApiError(
        MESSAGE, {"x-should-retry": "false", REQUEST_ID_HEADER: trace.request_id}
    )
    trace.fail(error)
    raise error


_RESPONSES = error_responses("unsupported_api")


@router.post("/v1/messages", tags=["gateway"], responses=_RESPONSES)
async def messages(request: Request) -> Response:
    return await _unsupported(request)


@router.post("/v1/messages/count_tokens", tags=["gateway"], responses=_RESPONSES)
async def count_tokens(request: Request) -> Response:
    return await _unsupported(request)
