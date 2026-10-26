"""``POST /v1/analyze``: detect personal data without masking it."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel, Field

from pii_guard.api.deps import Analyzer, get_analyzer, get_language
from pii_guard.api.routes._common import check_text_size, log_extra, v1_router

__all__ = ["AnalyzeRequest", "AnalyzeResponse", "PublicSpan", "router"]

router = v1_router()

Language = Annotated[str | None, Field(default=None, min_length=2, max_length=16)]


class AnalyzeRequest(BaseModel):
    text: str
    language: Language = None


class PublicSpan(BaseModel):
    """A span without its raw value (``Span.to_public_dict()``)."""

    start: int
    end: int
    entity_type: str
    score: float
    detector: str


class AnalyzeResponse(BaseModel):
    spans: list[PublicSpan]


@router.post("/v1/analyze", response_model=AnalyzeResponse)
def analyze(
    body: AnalyzeRequest,
    request: Request,
    analyzer: Annotated[Analyzer, Depends(get_analyzer)],
) -> dict[str, object]:
    check_text_size(request, body.text)
    spans = analyzer.analyze(body.text, get_language(request, body.language))
    log_extra(request, spans=len(spans), types=_type_counts(e.entity_type.value for e in spans))
    return {"spans": [span.to_public_dict() for span in spans]}


def _type_counts(types: Iterable[str]) -> str:
    counts = Counter(types)
    return ",".join(f"{name}:{count}" for name, count in sorted(counts.items())) or "-"
