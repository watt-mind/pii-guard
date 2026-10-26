"""``POST /v1/mask``: detect and replace personal data with reversible placeholders.

Entity policies (:mod:`pii_guard.policy`): only ``mask`` spans are replaced; ``keep`` spans
stay in place and are reported in ``kept`` by type and count; any ``block`` span refuses the
request with ``422 blocked_entity``.

Fail closed (ADR 0006): the vault and session are resolved before detection, and any
detection, policy or masking error is returned as an error body -- never the input or a
partially masked text. A session this request created is dropped again on error, so a
refused text leaves nothing in the vault.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel, Field

from pii_guard.api.deps import Analyzer, get_analyzer, get_language, get_policies, get_vault
from pii_guard.api.routes._common import check_text_size, log_extra, v1_router
from pii_guard.api.routes.analyze import Language
from pii_guard.policy import BlockedEntityError, PolicySet
from pii_guard.vault import Vault

__all__ = ["KeptEntity", "MaskEntity", "MaskRequest", "MaskResponse", "router"]

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


class KeptEntity(BaseModel):
    """Detected but left in place by a ``keep`` policy. Type and count only, never values."""

    entity_type: str
    count: int


class MaskResponse(BaseModel):
    masked_text: str
    session_id: str
    entities: list[MaskEntity]
    kept: list[KeptEntity] = []


@router.post("/v1/mask", response_model=MaskResponse)
def mask(
    body: MaskRequest,
    request: Request,
    analyzer: Annotated[Analyzer, Depends(get_analyzer)],
    vault: Annotated[Vault, Depends(get_vault)],
    policies: Annotated[PolicySet, Depends(get_policies)],
) -> dict[str, object]:
    check_text_size(request, body.text)
    language = get_language(request, body.language)
    session = vault.session(body.session_id)
    try:
        spans = analyzer.analyze(body.text, language)
        decision = policies.apply(spans)  # BlockedEntityError before anything is stored

        # entities() counts across the whole session; report only what this call replaced.
        before = {placeholder: count for placeholder, _, count in session.entities()}
        masked_text = session.mask(body.text, decision.masked, language=language)
    except BaseException as exc:
        if isinstance(exc, BlockedEntityError):
            log_extra(request, blocked=",".join(f"{t.value}:{n}" for t, n in exc.counts.items()))
        if body.session_id is None:
            vault.drop(session.session_id)
        raise
    entities = [
        MaskEntity(placeholder=placeholder, entity_type=entity_type.value, count=delta)
        for placeholder, entity_type, count in session.entities()
        if (delta := count - before.get(placeholder, 0)) > 0
    ]
    kept = [
        KeptEntity(entity_type=entity_type.value, count=count)
        for entity_type, count in sorted(decision.kept_counts().items())
    ]
    log_extra(
        request,
        spans=len(spans),
        replaced=sum(e.count for e in entities),
        kept=sum(k.count for k in kept),
        new_session=body.session_id is None,
    )
    return {
        "masked_text": masked_text,
        "session_id": session.session_id,
        "entities": entities,
        "kept": kept,
    }
