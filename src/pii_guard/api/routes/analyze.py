"""``POST /v1/analyze``: detect personal data without masking it."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel, Field

from pii_guard.api.deps import Analyzer, get_analyzer, get_language, get_policies, get_vault
from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import (
    check_text_size,
    log_extra,
    owned_session,
    request_metrics,
    v1_router,
)
from pii_guard.detect.known import KNOWN_DETECTOR, merge_known
from pii_guard.policy import Policy, PolicySet
from pii_guard.types import Span
from pii_guard.vault import Vault

__all__ = ["AnalyzeRequest", "AnalyzeResponse", "PublicSpan", "router"]

router = v1_router()

Language = Annotated[
    str | None,
    Field(
        default=None,
        min_length=2,
        max_length=16,
        description="ISO 639-1 language of the text (`hu`, `en`, `de`, ...). Defaults to "
        "`PII_GUARD_DEFAULT_LANGUAGE` (`hu`).",
        examples=["hu"],
    ),
]
# Same constraint as ``MaskRequest.session_id`` (routes/mask.py imports this module, so it
# cannot be imported from there).
SessionId = Annotated[str, Field(min_length=1, max_length=128)]


class AnalyzeRequest(BaseModel):
    """Text to scan for personal data. Nothing is masked or stored."""

    text: str = Field(
        description="The text to analyse. Offsets in the response are code-point indices into it.",
        examples=["Teszt Elek, teszt.elek@example.com"],
    )
    language: Language = None
    session_id: SessionId | None = Field(
        default=None,
        description="Optional vault session (1-128 characters, as on `/v1/mask`) whose "
        'pre-loaded known values are merged in (`detector: "known"`). Unknown, expired or '
        "bound to another client identity: 404 `not_found`. Never creates a session.",
    )


class PublicSpan(BaseModel):
    """A span without its raw value (``Span.to_public_dict()``) plus its type's policy."""

    start: int = Field(description="Code-point offset of the span in `text`, inclusive.")
    end: int = Field(description="Code-point offset of the span in `text`, exclusive.")
    entity_type: str = Field(
        description="The entity type (`PERSON`, `EMAIL`, ...; see docs/entities.md).",
        examples=["PERSON"],
    )
    score: float = Field(description="Detector confidence in `[0, 1]`.", examples=[0.97])
    detector: str = Field(
        description="Registry name of the detector that found it (`rules`, `ner`, `llm`, `known`).",
        examples=["ner"],
    )
    subtype: str | None = Field(
        default=None,
        description="Which shape of the type the rule matched, e.g. `github_token`, "
        "`url_password` or `assignment` for `SECRET` (docs/contracts.md). Left out when the "
        "detector sets none. Names a rule, never a value.",
        examples=["github_token"],
    )
    policy: Policy = Field(
        description="The type's effective policy. Known values report `mask` even for a "
        "`keep` type, because `/v1/mask` masks them."
    )


class AnalyzeResponse(BaseModel):
    """Every detected span, `keep` and `block` ones included: analyze never refuses."""

    spans: list[PublicSpan] = Field(
        description="Spans sorted by `start`, after the resolver merged overlaps. The raw "
        "text of a span is not returned: slice `text` with `start`/`end`."
    )


@router.post(
    "/v1/analyze",
    response_model=AnalyzeResponse,
    # Optional span fields (``subtype``) are left out, not sent as null: Span.to_public_dict().
    response_model_exclude_none=True,
    summary="Detect personal data without masking it",
    responses=error_responses(
        "not_found",
        "payload_too_large",
        "invalid_request",
        "vault_not_configured",
        "detection_failed",
        "detection_profile_denied",
        "detection_unavailable",
        "detector_loading",
    ),
)
def analyze(
    body: AnalyzeRequest,
    request: Request,
    analyzer: Annotated[Analyzer, Depends(get_analyzer)],
    policies: Annotated[PolicySet, Depends(get_policies)],
) -> dict[str, object]:
    """Detect without masking. Every span carries its type's policy; ``block`` spans are
    reported here, not refused (nothing leaves the guard).

    With ``session_id`` the session's known values are merged in as ``/v1/mask`` does
    (``detector: "known"``). The vault is only resolved then, so analyze without a session
    needs no tenant key. Nothing is stored and no session is created; an unknown or expired
    session is a 404, as is one a gateway request bound to another client identity (LAB-1590).
    Known spans of a ``keep`` type report ``mask``: ``/v1/mask`` masks them."""
    check_text_size(request, body.text)
    language = get_language(request, body.language)
    known_session = None
    if body.session_id is not None:
        vault: Vault = get_vault(request)
        # Unknown, expired or bound to another client identity -> 404 (LAB-1590): the known
        # spans would tell a foreign caller which values the session holds.
        known_session = owned_session(vault, body.session_id, request)
    spans = analyzer.analyze(body.text, language)
    if known_session is not None and (known := known_session.known_values):
        spans = merge_known(body.text, spans, known, language, keep_types=policies.keep_types)
    known_count = sum(s.detector == KNOWN_DETECTOR for s in spans)
    detected_counts = Counter(e.entity_type.value for e in spans)
    if (metrics := request_metrics(request)) is not None and detected_counts:
        metrics.observe_entities(detected=detected_counts)
    log_extra(
        request,
        spans=len(spans),
        types=_type_counts(detected_counts),
        known=known_count,
        session=known_session is not None,
    )
    return {
        "spans": [
            {
                **span.to_public_dict(),
                "policy": _policy(policies, span).value,
            }
            for span in spans
        ]
    }


def _policy(policies: PolicySet, span: Span) -> Policy:
    policy = policies.of(span.entity_type)
    # /v1/mask masks known values even of a keep type, so the preview must not say keep.
    if span.detector == KNOWN_DETECTOR and policy is Policy.KEEP:
        return Policy.MASK
    return policy


def _type_counts(types: Iterable[str] | Counter[str]) -> str:
    counts = types if isinstance(types, Counter) else Counter(types)
    return ",".join(f"{name}:{count}" for name, count in sorted(counts.items())) or "-"
