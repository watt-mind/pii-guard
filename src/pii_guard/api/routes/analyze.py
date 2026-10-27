"""``POST /v1/analyze``: detect personal data without masking it."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel, Field

from pii_guard.api.deps import Analyzer, get_analyzer, get_language, get_policies, get_vault
from pii_guard.api.routes._common import check_text_size, log_extra, v1_router
from pii_guard.detect.known import KNOWN_DETECTOR, merge_known
from pii_guard.policy import Policy, PolicySet
from pii_guard.types import Span
from pii_guard.vault import Vault

__all__ = ["AnalyzeRequest", "AnalyzeResponse", "PublicSpan", "router"]

router = v1_router()

Language = Annotated[str | None, Field(default=None, min_length=2, max_length=16)]
# Same constraint as ``MaskRequest.session_id`` (routes/mask.py imports this module, so it
# cannot be imported from there).
SessionId = Annotated[str, Field(min_length=1, max_length=128)]


class AnalyzeRequest(BaseModel):
    text: str
    language: Language = None
    session_id: SessionId | None = None


class PublicSpan(BaseModel):
    """A span without its raw value (``Span.to_public_dict()``) plus its type's policy."""

    start: int
    end: int
    entity_type: str
    score: float
    detector: str
    policy: Policy


class AnalyzeResponse(BaseModel):
    spans: list[PublicSpan]


@router.post("/v1/analyze", response_model=AnalyzeResponse)
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
    session is a 404. Known spans of a ``keep`` type report ``mask``: ``/v1/mask`` masks them."""
    check_text_size(request, body.text)
    language = get_language(request, body.language)
    known_session = None
    if body.session_id is not None:
        vault: Vault = get_vault(request)
        known_session = vault.session(body.session_id)  # SessionNotFoundError -> 404
    spans = analyzer.analyze(body.text, language)
    if known_session is not None and (known := known_session.known_values):
        spans = merge_known(body.text, spans, known, language, keep_types=policies.keep_types)
    known_count = sum(s.detector == KNOWN_DETECTOR for s in spans)
    log_extra(
        request,
        spans=len(spans),
        types=_type_counts(e.entity_type.value for e in spans),
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


def _type_counts(types: Iterable[str]) -> str:
    counts = Counter(types)
    return ",".join(f"{name}:{count}" for name, count in sorted(counts.items())) or "-"
