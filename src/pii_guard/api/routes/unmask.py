"""``POST /v1/unmask``: restore original values in text that carries placeholders."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel, Field

from pii_guard.api.deps import get_vault
from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import check_text_size, log_extra, request_metrics, v1_router
from pii_guard.api.routes.mask import SessionId
from pii_guard.gateway.sessions import check_owner, client_identity
from pii_guard.vault import Vault

__all__ = ["UnmaskRequest", "UnmaskResponse", "router"]

router = v1_router()


class UnmaskRequest(BaseModel):
    """Text carrying placeholders, and the session that issued them."""

    text: str = Field(
        description="Text with placeholders (`[[TYPE_id]]`), e.g. a model's answer.",
        examples=["Kedves [[PERSON_7f3a]]!"],
    )
    session_id: SessionId = Field(
        description="The vault session the placeholders belong to (1-128 characters). "
        "Unknown or expired: 404 `not_found`."
    )


class UnmaskResponse(BaseModel):
    """The text with every placeholder of the session restored."""

    text: str = Field(
        description="The re-identified text. Unresolved tokens are left in it as they are.",
        examples=["Kedves Teszt Elek!"],
    )
    unresolved: list[str] = Field(
        description="Placeholder-shaped tokens that aren't in the session mapping (invented "
        "or mangled by the model), once each, in order of first appearance."
    )


@router.post(
    "/v1/unmask",
    response_model=UnmaskResponse,
    summary="Restore the original values behind placeholders",
    responses=error_responses(
        "not_found",
        "payload_too_large",
        "unmask_output_too_large",
        "invalid_request",
        "vault_not_configured",
        "masking_failed",
    ),
)
def unmask(
    body: UnmaskRequest,
    request: Request,
    vault: Annotated[Vault, Depends(get_vault)],
) -> dict[str, object]:
    """Replace every placeholder the session issued with its original value.

    Tokens shaped like a placeholder but unknown to the session are reported in
    ``unresolved`` and left in place. Unknown or expired session: 404 ``not_found``.
    Restoring more than ``PII_GUARD_UNMASK_MAX_RESTORED_CHARS`` characters of original values:
    413 ``unmask_output_too_large``, nothing returned (LAB-1350).

    A session a gateway request bound to a client identity (LAB-1565) restores only for that
    identity (LAB-1580): a different ``Authorization`` value, or none for a credentialed
    owner, gets the same 404 as a missing session. Unbound sessions (``/v1/mask``) and
    anonymous-owned ones restore as before; unmasking never binds."""
    check_text_size(request, body.text)
    identity = client_identity(request.headers)
    # The owner check runs before the TTL is extended: a refused caller can't keep another
    # owner's session alive (LAB-1584).
    session = vault.session(body.session_id, authorize=lambda s: check_owner(s, identity))
    result = session.unmask_with_report(body.text)
    if result.unresolved and (metrics := request_metrics(request)) is not None:
        metrics.observe_unresolved(len(result.unresolved))
    log_extra(request, unresolved=len(result.unresolved))
    return {"text": result.text, "unresolved": list(result.unresolved)}
