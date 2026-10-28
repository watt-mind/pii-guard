"""The API error body: ``{"error": {"code": "...", "message": "..."}}``.

Every error response uses this shape. Messages never echo request content: request
validation errors report field locations only, because the body may contain personal data.

:class:`ErrorResponse` is that body as a model, for OpenAPI. :data:`ERROR_CODES` lists every
code a ``/v1`` route can return, with its status and when (the wording of
``docs/contracts.md``); a route declares the ones it can return with
``responses=error_responses("not_found", ...)``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from pii_guard.types import PiiGuardError

__all__ = [
    "COMMON_ERRORS",
    "ERROR_CODES",
    "ErrorDetail",
    "ErrorResponse",
    "error_response",
    "error_responses",
    "install_error_handlers",
]


class ErrorDetail(BaseModel):
    """What went wrong: a stable code and a message that never contains request content."""

    code: str = Field(
        description="Stable, machine-readable error code (see the response's examples).",
        examples=["invalid_request"],
    )
    message: str = Field(
        description="Human-readable explanation. Never echoes request text, values, keys or "
        "session ids: it names field locations, entity types or counts instead.",
        examples=["invalid request body: body.text"],
    )


class ErrorResponse(BaseModel):
    """The body of every non-2xx response, including validation errors and unknown routes.

    Fail closed: an error body never carries masked, partially masked or input text.
    """

    error: ErrorDetail = Field(description="The error code and message.")


#: Every documented error code: ``code -> (status, when)``. The status is the
#: ``status_code`` of the :class:`~pii_guard.types.PiiGuardError` subclass that carries
#: the code (``tests/api/test_openapi_docs.py`` checks both against ``docs/contracts.md``).
ERROR_CODES: Mapping[str, tuple[int, str]] = {
    "unauthorized": (401, "`PII_GUARD_API_TOKEN` is set and the request has no valid token."),
    "traffic_log_not_local": (
        403,
        "`PII_GUARD_TRAFFIC_LOG=full` and the connection is not loopback on both ends.",
    ),
    "vault_inspect_not_local": (
        403,
        "`PII_GUARD_VAULT_INSPECT=full` and the connection is not loopback on both ends.",
    ),
    "vault_reveal_disabled": (
        403,
        "`reveal=true` on the vault inspector while `PII_GUARD_VAULT_INSPECT` is not `full`.",
    ),
    "not_found": (404, "Unknown route, or an unknown or expired `session_id`."),
    "vault_inspect_disabled": (
        404,
        "The vault inspector is off (`PII_GUARD_VAULT_INSPECT=off`).",
    ),
    "traffic_log_disabled": (404, "The traffic log is off (`PII_GUARD_TRAFFIC_LOG=off`)."),
    "payload_too_large": (413, "The body, text or image is larger than the configured limit."),
    "unsupported_media_type": (415, "The image is not a PNG or JPEG (sniffed from its bytes)."),
    "invalid_request": (
        422,
        "The request fails validation. The message lists field locations only, never values.",
    ),
    "invalid_image": (
        422,
        "The image can't be decoded, or its base64 or JSON body is malformed.",
    ),
    "invalid_known_value": (
        422,
        "A pre-loaded known value is too short, too long, or has an unknown or visual type.",
    ),
    "too_many_known_values": (
        422,
        "The session would hold more than `PII_GUARD_KNOWN_VALUES_MAX` known values.",
    ),
    "blocked_entity": (
        422,
        "An entity type whose policy is `block` was found; nothing is masked or stored.",
    ),
    "placeholder_in_input": (
        422,
        "The text to mask contains a placeholder this session already issued.",
    ),
    "vault_not_configured": (
        500,
        "`PII_GUARD_TENANT_KEY` is unset, not hex or shorter than 16 bytes.",
    ),
    "masking_failed": (500, "Masking or re-identification could not complete."),
    "internal_error": (500, "Anything unexpected. No exception text is returned."),
    "detection_failed": (503, "A detector (or SAM, or OCR) failed or timed out."),
    "detection_unavailable": (
        503,
        "A configured detector can't run safely (the LLM detector without a key).",
    ),
    "detector_loading": (
        503,
        "The NER model is still loading after `PII_GUARD_NER_WARMUP_TIMEOUT`; retry after "
        "`Retry-After` seconds.",
    ),
    "ocr_unavailable": (
        503,
        "No OCR engine, so the text in an image can't be checked (`image_require_ocr`).",
    ),
}

#: Codes every authenticated route can return, whatever it does.
COMMON_ERRORS = ("unauthorized", "traffic_log_not_local", "internal_error")


def error_responses(*codes: str, common: bool = True) -> dict[int | str, dict[str, Any]]:
    """The OpenAPI ``responses`` of a route that can fail with ``codes``.

    One entry per status, the :class:`ErrorResponse` schema, and one example per code.
    ``common`` adds :data:`COMMON_ERRORS`. Unknown codes raise ``KeyError``: document them
    in :data:`ERROR_CODES` (and ``docs/contracts.md``) first.
    """
    by_status: dict[int, list[str]] = {}
    for code in (*codes, *(COMMON_ERRORS if common else ())):
        status, _ = ERROR_CODES[code]
        if code not in by_status.setdefault(status, []):
            by_status[status].append(code)
    responses: dict[int | str, dict[str, Any]] = {}
    for status in sorted(by_status):
        listed = by_status[status]
        responses[status] = {
            "model": ErrorResponse,
            "description": " ".join(f"`{c}`: {ERROR_CODES[c][1]}" for c in listed),
            "content": {
                "application/json": {
                    "examples": {
                        code: {
                            "summary": ERROR_CODES[code][1],
                            "value": {"error": {"code": code, "message": code}},
                        }
                        for code in listed
                    }
                }
            },
        }
    return responses


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
