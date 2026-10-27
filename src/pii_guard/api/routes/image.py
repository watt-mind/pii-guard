"""``POST /v1/mask/image``: cover faces, signatures, ID photos and text personal data in an image.

Two request forms, both answered with JSON:

- **raw upload**: the image bytes as the body, ``Content-Type: image/png`` or ``image/jpeg``
  (``curl --data-binary @card.png -H 'Content-Type: image/png'``); ``?language=hu`` optional;
- **JSON**: ``{"image": "<base64 or data:image/png;base64,...>", "language": "hu",
  "session_id": "s_...", "render": "labels", "expiry": "reduce"}`` (all but ``image``
  optional; the raw form takes the same as query parameters).

**Rendering** (``render``, default ``PII_GUARD_IMAGE_RENDER``, ``labels``): ``labels`` prints
each covered region's vault placeholder on it and also returns ``transcript`` (the OCR text
with placeholders) and ``summary`` (the document summary), with values registered in the vault
session ``session_id`` (a new one when omitted; its id is returned), so an ID card and a
contract masked in one session share placeholders. ``opaque`` covers regions with solid
boxes and returns neither. Without a configured vault (``PII_GUARD_TENANT_KEY``) the default
falls back to ``opaque``; an explicit ``labels`` is then ``500 vault_not_configured``.

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
    get_vault,
)
from pii_guard.api.routes._common import LoggedRoute, log_extra, text_body_limit, v1_router
from pii_guard.api.routes.image_masking import (
    DEFAULT_MAX_IMAGE_BYTES,
    RENDER_MODES,
    AnalyzerDetector,
    ImageMasker,
    ImageMaskOutcome,
    InvalidImageError,
    UnsupportedImageError,
    decode_base64_image,
    default_ocr_engine,
    require_ocr,
)
from pii_guard.policy import BlockedEntityError, Policy
from pii_guard.types import PiiGuardError
from pii_guard.vault import Vault, VaultSession
from pii_guard.visual.labels import VaultMatcher
from pii_guard.visual.ocr import OcrEngine
from pii_guard.visual.sam import SamClient

__all__ = ["ImageMaskResponse", "get_image_masker", "max_image_bytes", "router"]

_RAW_TYPES = frozenset({"image/png", "image/jpeg", "image/jpg"})
_JSON_OVERHEAD_BYTES = 16_384
_lock = threading.Lock()
_UNSET = object()
_EXPIRY_MODES = ("reduce", "keep")


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
    #: ``render="labels"`` only: the session placeholder, the printed label and the match.
    placeholder: str | None = None
    label: str | None = None
    match: str | None = None
    match_confidence: float | None = None
    cover_box: list[int] | None = None


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
    render: str = "opaque"
    #: The vault session the placeholders belong to (``render="labels"``).
    session_id: str | None = None
    transcript: str | None = None
    summary: dict[str, Any] | None = None
    matches: dict[str, int] = {}


class ImageOptions(BaseModel):
    """Per-request options (JSON body fields or query parameters)."""

    language: str | None = None
    session_id: str | None = None
    render: str | None = None
    expiry: str = "reduce"


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


def _option(value: object, name: str, allowed: tuple[str, ...] | None = None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise InvalidImageError(f"{name} must be a short string")
    if allowed is not None and value not in allowed:
        raise InvalidImageError(f"{name} must be one of: {', '.join(allowed)}")
    return value


async def _image_from_request(request: Request) -> tuple[bytes, ImageOptions]:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    image_limit = max_image_bytes(request)
    query = request.query_params
    options = ImageOptions(
        session_id=_option(query.get("session_id"), "session_id"),
        render=_option(query.get("render"), "render", RENDER_MODES),
        expiry=_option(query.get("expiry"), "expiry", _EXPIRY_MODES) or "reduce",
    )
    if content_type in _RAW_TYPES:
        return await _read_body(request, image_limit), options
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
        options.language = language
        options.session_id = _option(body.get("session_id"), "session_id") or options.session_id
        options.render = _option(body.get("render"), "render", RENDER_MODES) or options.render
        options.expiry = _option(body.get("expiry"), "expiry", _EXPIRY_MODES) or options.expiry
        return decode_base64_image(body["image"]), options
    raise UnsupportedImageError(
        "send the image as the body (Content-Type: image/png or image/jpeg) "
        'or as JSON {"image": "<base64>"}'
    )


def _counts(counts: dict[Any, int]) -> list[TypeCount]:
    return [TypeCount(entity_type=t.value, count=n) for t, n in counts.items()]


def _response(outcome: ImageMaskOutcome, session_id: str | None = None) -> ImageMaskResponse:
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
        render=outcome.render,
        session_id=session_id,
        transcript=outcome.transcript,
        summary=outcome.summary,
        matches=outcome.matches,
    )


def _render_and_vault(request: Request, requested: str | None) -> tuple[str, Vault | None]:
    """The render mode and, for ``labels``, the vault. The default falls back to ``opaque``
    when no vault is configured; an explicit ``labels`` fails closed instead."""
    state = request.app.state
    default = getattr(state, "image_render", None) or getattr(
        state.settings, "image_render", "labels"
    )
    render = requested or default
    if render != "labels":
        return "opaque", None
    try:
        return "labels", get_vault(request)
    except PiiGuardError:
        if requested == "labels":
            raise
        return "opaque", None


@router.post("/v1/mask/image", response_model=ImageMaskResponse, response_model_exclude_unset=True)
async def mask_image_endpoint(
    request: Request,
    language: Annotated[str | None, Query(min_length=2, max_length=16)] = None,
) -> ImageMaskResponse:
    data, options = await _image_from_request(request)
    if not data:
        raise InvalidImageError("image is empty")
    if len(data) > max_image_bytes(request):
        raise PayloadTooLargeError(f"image is larger than {max_image_bytes(request)} bytes")
    masker = get_image_masker(request)
    require_ocr(masker.ocr, required=request.app.state.settings.image_require_ocr)
    lang = get_language(request, options.language or language)
    render, vault = _render_and_vault(request, options.render)
    session: VaultSession | None = None
    if vault is not None:
        # Unknown or expired id -> 404 session_not_found, before any detection.
        session = vault.session(options.session_id)
    try:
        matcher = VaultMatcher(session, lang) if session is not None else None
        outcome = await run_in_threadpool(
            masker.mask,
            data,
            lang,
            render=render,  # type: ignore[arg-type]
            matcher=matcher,
            expiry=options.expiry,  # type: ignore[arg-type]
        )
    except BaseException as exc:
        if session is not None and vault is not None and options.session_id is None:
            vault.drop(session.session_id)  # a refused image leaves nothing in the vault
        if isinstance(exc, BlockedEntityError):
            log_extra(request, blocked=",".join(f"{t.value}:{n}" for t, n in exc.counts.items()))
        raise
    log_extra(
        request,
        regions=len(outcome.regions),
        masked=sum(outcome.counts(Policy.MASK).values()),
        kept=sum(outcome.counts(Policy.KEEP).values()),
        ocr=outcome.ocr_engine or "off",
        render=outcome.render,
    )
    return _response(outcome, session.session_id if session is not None else None)
