"""``POST /v1/mask/image``: cover faces, signatures, ID photos and text personal data in an image.

Two request forms, both answered with JSON:

- **raw upload**: the image bytes as the body, ``Content-Type: image/png`` or ``image/jpeg``
  (``curl --data-binary @card.png -H 'Content-Type: image/png'``); ``?language=hu`` optional;
- **JSON**: ``{"image": "<base64 or data:image/png;base64,...>", "language": "hu"}``.

The format is sniffed from the bytes (PNG or JPEG only; anything else is ``415``). The
response carries the masked image as base64 PNG (``image``), re-encoded from pixels with no
metadata, plus the regions found, without values. See ``docs/contracts.md``.

Detection: SAM 3.1 (``PII_GUARD_SAM_URL`` / ``META_API_KEY``) for visual types, and, when
Tesseract is installed (``uv sync --extra ocr`` + the ``tesseract`` binary), OCR text through
the API's own text detectors (``PII_GUARD_DETECTORS``). Without Tesseract only SAM runs and
``analysis.ocr.ran`` is ``false`` with a ``reason``.

Fail closed (ADR 0006): any SAM, OCR or detector error is ``503 detection_failed``, a
``block`` policy region is ``422 blocked_entity``; the original image is never returned.

Tests and embedders can set ``app.state.sam_client`` (a :class:`~pii_guard.visual.SamClient`),
``app.state.ocr_engine`` (an :class:`~pii_guard.visual.OcrEngine`, or ``None`` to disable OCR)
and ``app.state.max_image_bytes``.
"""

from __future__ import annotations

import base64
import json
import math
import threading
from typing import Annotated, Any

from fastapi import Query, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from pii_guard.api.deps import (
    PayloadTooLargeError,
    get_analyzer,
    get_language,
    get_policies,
)
from pii_guard.api.routes._common import LoggedRoute, log_extra, text_body_limit, v1_router
from pii_guard.api.routes.image_masking import (
    DEFAULT_MAX_IMAGE_BYTES,
    AnalyzerDetector,
    ImageMasker,
    ImageMaskOutcome,
    InvalidImageError,
    UnsupportedImageError,
    decode_base64_image,
    default_ocr_engine,
)
from pii_guard.policy import BlockedEntityError, Policy
from pii_guard.visual.ocr import OcrEngine
from pii_guard.visual.sam import SamClient

__all__ = ["ImageMaskResponse", "get_image_masker", "max_image_bytes", "router"]

_RAW_TYPES = frozenset({"image/png", "image/jpeg", "image/jpg"})
_JSON_OVERHEAD_BYTES = 16_384
_lock = threading.Lock()
_UNSET = object()


def max_image_bytes(request: Request) -> int:
    return int(getattr(request.app.state, "max_image_bytes", DEFAULT_MAX_IMAGE_BYTES))


def _body_limit(request: Request) -> int:
    # Base64 in JSON is 4/3 of the image, plus the other fields.
    encoded = math.ceil(max_image_bytes(request) / 3) * 4
    return max(text_body_limit(request), encoded + _JSON_OVERHEAD_BYTES)


class ImageRoute(LoggedRoute):
    """Accepts bodies up to the image limit (base64-encoded), not the text limit."""

    def max_body_bytes(self, request: Request) -> int:
        return _body_limit(request)


router = v1_router(ImageRoute)


class ImageRegionOut(BaseModel):
    entity_type: str
    box: list[int]
    source: str
    detector: str
    score: float | None
    policy: str


class TypeCount(BaseModel):
    entity_type: str
    count: int


class SamInfo(BaseModel):
    model: str
    entity_types: list[str]


class OcrInfo(BaseModel):
    ran: bool
    engine: str | None
    detectors: list[str]
    models: dict[str, str]
    reason: str | None


class Analysis(BaseModel):
    sam: SamInfo
    ocr: OcrInfo


class ImageMaskResponse(BaseModel):
    image: str
    media_type: str
    width: int
    height: int
    regions: list[ImageRegionOut]
    masked: list[TypeCount]
    kept: list[TypeCount]
    analysis: Analysis


def _sam_client(request: Request) -> SamClient:
    state = request.app.state
    sam = getattr(state, "sam_client", None)
    if sam is None:
        with _lock:
            sam = getattr(state, "sam_client", None)
            if sam is None:
                sam = SamClient(settings=state.settings)
                state.sam_client = sam
    return sam


def _ocr_engine(request: Request) -> OcrEngine | None:
    state = request.app.state
    ocr = getattr(state, "ocr_engine", _UNSET)
    if ocr is _UNSET:
        ocr = default_ocr_engine()
        state.ocr_engine = ocr
    return ocr  # type: ignore[return-value]


def get_image_masker(request: Request) -> ImageMasker:
    """SAM + (OCR + the app's analyzer, when an OCR engine is available) + the app's policies."""
    ocr = _ocr_engine(request)
    detector = AnalyzerDetector(get_analyzer(request)) if ocr is not None else None
    names = list(getattr(request.app.state, "detector_names", None) or [])
    models: dict[str, str] = {}
    if detector is not None:
        for inner in getattr(detector.analyzer, "detectors", None) or []:
            model = getattr(inner, "model", None)
            if isinstance(model, str) and model:
                models[getattr(inner, "name", type(inner).__name__)] = model
    return ImageMasker(
        sam=_sam_client(request),
        policies=get_policies(request),
        ocr=ocr,
        text_detector=detector,
        text_detector_names=names,
        text_detector_models=models,
    )


async def _read_body(request: Request, limit: int) -> bytes:
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > limit:
            raise PayloadTooLargeError("request body is too large")
    return bytes(data)


async def _image_from_request(request: Request) -> tuple[bytes, str | None]:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    image_limit = max_image_bytes(request)
    if content_type in _RAW_TYPES:
        return await _read_body(request, image_limit), None
    if content_type == "application/json":
        raw = await _read_body(request, _body_limit(request))
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise InvalidImageError("request body is not valid JSON") from None
        if not isinstance(body, dict) or not isinstance(body.get("image"), str):
            raise InvalidImageError("JSON body needs an 'image' field (base64 or data URL)")
        language = body.get("language")
        if language is not None and not (isinstance(language, str) and 1 <= len(language) <= 16):
            raise InvalidImageError("language must be a short language tag")
        return decode_base64_image(body["image"]), language
    raise UnsupportedImageError(
        "send the image as the body (Content-Type: image/png or image/jpeg) "
        'or as JSON {"image": "<base64>"}'
    )


def _counts(counts: dict[Any, int]) -> list[TypeCount]:
    return [TypeCount(entity_type=t.value, count=n) for t, n in counts.items()]


def _response(outcome: ImageMaskOutcome) -> ImageMaskResponse:
    ocr_ran = outcome.ocr_engine is not None
    return ImageMaskResponse(
        image=base64.b64encode(outcome.image).decode("ascii"),
        media_type="image/png",
        width=outcome.width,
        height=outcome.height,
        regions=[ImageRegionOut(**r.to_public_dict()) for r in outcome.regions],  # type: ignore[arg-type]
        masked=_counts(outcome.counts(Policy.MASK)),
        kept=_counts(outcome.counts(Policy.KEEP)),
        analysis=Analysis(
            sam=SamInfo(model=outcome.sam_model, entity_types=[t.value for t in outcome.sam_types]),
            ocr=OcrInfo(
                ran=ocr_ran,
                engine=outcome.ocr_engine,
                detectors=outcome.text_detectors,
                models=outcome.detector_models,
                reason=None if ocr_ran else "tesseract_unavailable",
            ),
        ),
    )


@router.post("/v1/mask/image", response_model=ImageMaskResponse)
async def mask_image_endpoint(
    request: Request,
    language: Annotated[str | None, Query(min_length=2, max_length=16)] = None,
) -> ImageMaskResponse:
    data, body_language = await _image_from_request(request)
    if not data:
        raise InvalidImageError("image is empty")
    if len(data) > max_image_bytes(request):
        raise PayloadTooLargeError(f"image is larger than {max_image_bytes(request)} bytes")
    masker = get_image_masker(request)
    lang = get_language(request, body_language or language)
    try:
        outcome = await run_in_threadpool(masker.mask, data, lang)
    except BlockedEntityError as exc:
        log_extra(request, blocked=",".join(f"{t.value}:{n}" for t, n in exc.counts.items()))
        raise
    log_extra(
        request,
        regions=len(outcome.regions),
        masked=sum(outcome.counts(Policy.MASK).values()),
        kept=sum(outcome.counts(Policy.KEEP).values()),
        ocr=outcome.ocr_engine or "off",
    )
    return _response(outcome)
