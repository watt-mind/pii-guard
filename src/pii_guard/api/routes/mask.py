"""``POST /v1/mask``: detect and replace personal data with reversible placeholders.

Fail closed (ADR 0006): the vault and session are resolved before detection, and any
detection or masking error is returned as an error body -- never the input or a partially
masked text.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel, Field

from pii_guard.api.deps import Analyzer, get_analyzer, get_language, get_vault
from pii_guard.api.routes._common import check_text_size, log_extra, v1_router
from pii_guard.api.routes.analyze import Language
from pii_guard.vault import Vault

__all__ = ["MaskEntity", "MaskRequest", "MaskResponse", "router"]

router = v1_router()

SessionId = Annotated[str, Field(min_length=1, max_length=128)]


class MaskRequest(BaseModel):
    text: str
    language: Language = None
    session_id: SessionId | None = None


class MaskEntity(BaseModel):
    placeholder: str
    entity_type: str
    count: int


class MaskResponse(BaseModel):
    masked_text: str
    session_id: str
    entities: list[MaskEntity]


@router.post("/v1/mask", response_model=MaskResponse)
def mask(
    body: MaskRequest,
    request: Request,
    analyzer: Annotated[Analyzer, Depends(get_analyzer)],
    vault: Annotated[Vault, Depends(get_vault)],
) -> dict[str, object]:
    check_text_size(request, body.text)
    language = get_language(request, body.language)
    session = vault.session(body.session_id)
    spans = analyzer.analyze(body.text, language)

    # entities() counts across the whole session; report only what this call replaced.
    before = {placeholder: count for placeholder, _, count in session.entities()}
    masked_text = session.mask(body.text, spans, language=language)
    entities = [
        MaskEntity(placeholder=placeholder, entity_type=entity_type.value, count=delta)
        for placeholder, entity_type, count in session.entities()
        if (delta := count - before.get(placeholder, 0)) > 0
    ]
    log_extra(
        request,
        spans=len(spans),
        replaced=sum(e.count for e in entities),
        new_session=body.session_id is None,
    )
    return {"masked_text": masked_text, "session_id": session.session_id, "entities": entities}
