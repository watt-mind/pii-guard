"""``POST /v1/unmask``: restore original values in text that carries placeholders."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel

from pii_guard.api.deps import get_vault
from pii_guard.api.routes._common import check_text_size, log_extra, v1_router
from pii_guard.api.routes.mask import SessionId
from pii_guard.vault import Vault

__all__ = ["UnmaskRequest", "UnmaskResponse", "router"]

router = v1_router()


class UnmaskRequest(BaseModel):
    text: str
    session_id: SessionId


class UnmaskResponse(BaseModel):
    text: str
    unresolved: list[str]


@router.post("/v1/unmask", response_model=UnmaskResponse)
def unmask(
    body: UnmaskRequest,
    request: Request,
    vault: Annotated[Vault, Depends(get_vault)],
) -> dict[str, object]:
    check_text_size(request, body.text)
    result = vault.session(body.session_id).unmask_with_report(body.text)
    log_extra(request, unresolved=len(result.unresolved))
    return {"text": result.text, "unresolved": list(result.unresolved)}
