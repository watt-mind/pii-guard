"""``POST /v1/mask``: detect and replace personal data with reversible placeholders.

Entity policies (:mod:`pii_guard.policy`): only ``mask`` spans are replaced; ``keep`` spans
stay in place and are reported in ``kept`` by type and count; any ``block`` span refuses the
request with ``422 blocked_entity``.

Known values pre-loaded into the session (``POST /v1/sessions/{id}/known-values``) are found
by the ``known`` detector on top of the configured ones and win their conflicts; they are
masked even when their type's policy is ``keep`` (the application asked for it), and a
``block`` type still refuses the request.

Fail closed (ADR 0006): the vault and session are resolved before detection, and any
detection, policy or masking error is returned as an error body -- never the input or a
partially masked text. A session this request created is dropped again on error, so a
refused text leaves nothing in the vault.
"""

from __future__ import annotations

from collections import Counter
from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel, Field

from pii_guard.api.deps import Analyzer, get_analyzer, get_language, get_policies, get_vault
from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import (
    check_text_size,
    ephemeral_session,
    log_extra,
    request_metrics,
    v1_router,
)
from pii_guard.api.routes.analyze import Language
from pii_guard.detect.known import KNOWN_DETECTOR, merge_known
from pii_guard.policy import PolicySet
from pii_guard.types import MaskingError
from pii_guard.vault import Vault
from pii_guard.vault.placeholders import PLACEHOLDER_RE

__all__ = ["KeptEntity", "MaskEntity", "MaskRequest", "MaskResponse", "router"]

router = v1_router()

SessionId = Annotated[str, Field(min_length=1, max_length=128)]


class MaskRequest(BaseModel):
    """Text to mask, and the vault session whose placeholders to use."""

    text: str = Field(description="The text to mask.", examples=["Teszt Elek írt Teszt Eleknek."])
    language: Language = None
    session_id: SessionId | None = Field(
        default=None,
        description="Vault session to mask in (1-128 characters). Omitted or `null`: a new "
        "session is created and returned. An existing id reuses its mapping, so the same "
        "value keeps the same placeholder across calls. Unknown, expired or bound to another "
        "client identity: 404 `not_found`.",
    )


class MaskEntity(BaseModel):
    """One distinct placeholder this call issued or reused. Never the original value."""

    placeholder: str = Field(
        description="The placeholder in `masked_text` (`[[TYPE_id]]`).",
        examples=["[[PERSON_7f3a]]"],
    )
    entity_type: str = Field(description="The entity type it stands for.", examples=["PERSON"])
    count: int = Field(description="How many occurrences this call replaced with it.")


class KeptEntity(BaseModel):
    """Detected but left in place by a ``keep`` policy. Type and count only, never values."""

    entity_type: str = Field(description="The kept entity type.", examples=["ORGANIZATION"])
    count: int = Field(description="How many spans of that type were left in place.")


class MaskResponse(BaseModel):
    """The masked text and the session that can restore it (``/v1/unmask``)."""

    masked_text: str = Field(
        description="The text with every `mask`-policy span replaced by its placeholder.",
        examples=["[[PERSON_7f3a]] írt [[PERSON_7f3a]]nek."],
    )
    session_id: str = Field(
        description="The vault session holding the mapping: the one sent, or a new one."
    )
    entities: list[MaskEntity] = Field(
        description="Each distinct placeholder once, with its replacement count."
    )
    kept: list[KeptEntity] = Field(
        default=[],
        description="Spans of `keep` types left in place, by type and count, sorted by type: "
        "no values, no offsets.",
    )


@router.post(
    "/v1/mask",
    response_model=MaskResponse,
    summary="Replace personal data with reversible placeholders",
    responses=error_responses(
        "not_found",
        "payload_too_large",
        "invalid_request",
        "blocked_entity",
        "placeholder_in_input",
        "vault_not_configured",
        "masking_failed",
        "detection_failed",
        "detection_profile_denied",
        "detection_unavailable",
        "detector_loading",
    ),
)
def mask(
    body: MaskRequest,
    request: Request,
    analyzer: Annotated[Analyzer, Depends(get_analyzer)],
    vault: Annotated[Vault, Depends(get_vault)],
    policies: Annotated[PolicySet, Depends(get_policies)],
) -> dict[str, object]:
    """Detect personal data and replace each ``mask``-policy span with a vault placeholder.

    ``keep`` spans stay in place and are counted in ``kept``; any ``block`` span refuses the
    request (422 ``blocked_entity``). The session's known values are masked on top of the
    configured detectors, even for a ``keep`` type. Fail closed: on any error the body carries
    no text, and a session this request created is dropped again."""
    check_text_size(request, body.text)
    language = get_language(request, body.language)
    with ephemeral_session(vault, body.session_id, request) as session:
        spans = analyzer.analyze(body.text, language)
        known = session.known_values
        if known:
            spans = merge_known(body.text, spans, known, language, keep_types=policies.keep_types)
        decision = policies.apply(spans)  # BlockedEntityError before anything is stored
        kept = [s for s in decision.kept if s.detector != KNOWN_DETECTOR]
        to_mask = decision.masked + [s for s in decision.kept if s.detector == KNOWN_DETECTOR]

        # Counted from this call's own replacements: entities() counts across the session, and
        # a concurrent request on the same session could land between two reads of it.
        result = session.mask_with_report(body.text, to_mask, language=language)
    counts = Counter(placeholder for _, _, placeholder in result.replacements)
    entities = [
        MaskEntity(placeholder=placeholder, entity_type=_entity_type(placeholder), count=count)
        for placeholder, count in counts.items()
    ]
    kept_entities = [
        KeptEntity(entity_type=entity_type.value, count=count)
        for entity_type, count in sorted(Counter(s.entity_type for s in kept).items())
    ]
    if (metrics := request_metrics(request)) is not None:
        detected_by_type = Counter(s.entity_type.value for s in spans)
        masked_by_type: Counter[str] = Counter()
        for entity in entities:
            masked_by_type[entity.entity_type] += entity.count
        metrics.observe_entities(detected=detected_by_type, masked=masked_by_type)
    log_extra(
        request,
        spans=len(spans),
        replaced=sum(e.count for e in entities),
        kept=sum(k.count for k in kept_entities),
        known=sum(s.detector == KNOWN_DETECTOR for s in spans),
        new_session=body.session_id is None,
    )
    return {
        "masked_text": result.text,
        "session_id": session.session_id,
        "entities": entities,
        "kept": kept_entities,
    }


def _entity_type(placeholder: str) -> str:
    match = PLACEHOLDER_RE.fullmatch(placeholder)
    if match is None:  # pragma: no cover - the vault only issues well-formed placeholders
        raise MaskingError("the vault returned a malformed placeholder")
    return match.group(1)
