"""The API error body: ``{"error": {"code": "...", "message": "..."}}``.

Every error response uses this shape. Messages never echo request content: request
validation errors report field locations only, because the body may contain personal data.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from pii_guard.types import PiiGuardError

__all__ = ["error_response", "install_error_handlers"]

_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "invalid_request",
    429: "rate_limited",
}


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


async def _pii_guard_error(_: Request, exc: PiiGuardError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, "internal_error" if exc.status_code >= 500 else "error")
    message = exc.detail if isinstance(exc.detail, str) else code
    return error_response(exc.status_code, code, message)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Only locations and error kinds: pydantic's own messages may quote the input value.
    fields = sorted({".".join(str(p) for p in err.get("loc", ())) for err in exc.errors()})
    message = "invalid request body"
    if fields:
        message += ": " + ", ".join(fields)
    return error_response(422, "invalid_request", message)


async def _unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    # Never include str(exc): it may contain raw values.
    return error_response(500, "internal_error", "internal error")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(PiiGuardError, _pii_guard_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
