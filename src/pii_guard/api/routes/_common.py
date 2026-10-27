"""Shared pieces of the ``/v1/*`` routers (not a router itself: the ``_`` prefix skips it).

- :class:`LoggedRoute` logs one access line per request -- method, path, status, duration
  and, for masking, entity counts. It never logs bodies, text, session ids or values.
  It also rejects a body far beyond the text limit before it is parsed: a declared
  ``Content-Length`` at once, and any body (chunked included) as soon as the bytes read so
  far pass the limit, so an oversized body is never buffered whole (LAB-1207).
- :func:`v1_router` builds a router with that route class.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from pii_guard.api.deps import PayloadTooLargeError, get_max_text_chars
from pii_guard.types import PiiGuardError

__all__ = ["LoggedRoute", "check_text_size", "log_extra", "text_body_limit", "v1_router"]

access_logger = logging.getLogger("pii_guard.api.access")

# One code point is at most 12 bytes of JSON (an astral character escaped as a surrogate
# pair); allow that plus room for the other fields, so a legal text is never rejected here.
_BODY_BYTES_PER_CHAR = 12
_BODY_OVERHEAD_BYTES = 16_384


def log_extra(request: Request, **fields: object) -> None:
    """Attach safe fields (counts, entity types) to this request's access log line."""
    extra = getattr(request.state, "log_fields", None)
    if extra is None:
        extra = {}
        request.state.log_fields = extra
    extra.update(fields)


class LoggedRoute(APIRoute):
    """An ``APIRoute`` that writes a body-free access log line for every request.

    Subclasses with larger bodies (images) override :meth:`max_body_bytes`.
    """

    def max_body_bytes(self, request: Request) -> int:
        """The largest declared body accepted before parsing; derived from the text limit."""
        return text_body_limit(request)

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def logged(request: Request) -> Response:
            started = time.perf_counter()
            status = 500
            error_code: str | None = None
            try:
                limit = self.max_body_bytes(request)
                _check_body_size(request, limit)
                await _read_body_capped(request, limit)
                response = await handler(request)
                status = response.status_code
                return response
            except PiiGuardError as exc:
                status, error_code = exc.status_code, exc.code
                raise
            except StarletteHTTPException as exc:
                status = exc.status_code
                raise
            except RequestValidationError:
                status, error_code = 422, "invalid_request"
                raise
            except Exception as exc:
                # Never the exception text: it may contain raw values.
                error_code = type(exc).__name__
                raise
            finally:
                fields = getattr(request.state, "log_fields", None) or {}
                access_logger.info(
                    "%s %s %d %.1fms%s%s",
                    request.method,
                    self.path,  # the template: never a session id from the URL
                    status,
                    (time.perf_counter() - started) * 1000,
                    f" error={error_code}" if error_code else "",
                    "".join(f" {key}={value}" for key, value in sorted(fields.items())),
                )

        return logged


def text_body_limit(request: Request) -> int:
    """The body size (bytes) a request at the text limit can legally have, as JSON."""
    return get_max_text_chars(request) * _BODY_BYTES_PER_CHAR + _BODY_OVERHEAD_BYTES


def _check_body_size(request: Request, limit: int) -> None:
    """Reject bodies whose declared size is beyond ``limit``, before parsing."""
    declared = request.headers.get("content-length")
    if declared is None or not declared.isdigit():
        return
    if int(declared) > limit:
        raise PayloadTooLargeError("request body is too large")


async def _read_body_capped(request: Request, limit: int) -> None:
    """Read the body with a running byte count; 413 once it passes ``limit``.

    The body is cached on the request (Starlette's ``request.body()`` / ``stream()`` then
    return it), so the handler reads what was counted here."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise PayloadTooLargeError("request body is too large")
        chunks.append(chunk)
    request._body = b"".join(chunks)


def check_text_size(request: Request, text: str) -> None:
    """Fail with 413 if ``text`` is longer than the configured limit (in code points)."""
    limit = get_max_text_chars(request)
    if len(text) > limit:
        raise PayloadTooLargeError(f"text is longer than {limit} characters")


def v1_router(route_class: type[LoggedRoute] = LoggedRoute) -> APIRouter:
    return APIRouter(route_class=route_class, tags=["v1"])
