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

Detection: the segmenter (``PII_GUARD_SEGMENTER``, default ``hybrid``: YuNet on the CPU for
faces and ID photos, SAM 3.1 via ``PII_GUARD_SAM_URL`` / ``META_API_KEY`` for signatures; see
:mod:`pii_guard.visual.segmenters`) for visual types, and, when
Tesseract is installed (``uv sync --extra ocr`` + the ``tesseract`` binary), OCR text through
the API's own text detectors (``PII_GUARD_DETECTORS``). Without Tesseract only SAM runs and
``analysis.ocr.ran`` is ``false`` with a ``reason``.

Fail closed (ADR 0006): any SAM, OCR or detector error is ``503 detection_failed``, a
``block`` policy region is ``422 blocked_entity``; the original image is never returned.

Tests and embedders can set ``app.state.sam_client`` (any segmenter, e.g. a
:class:`~pii_guard.visual.SamClient`),
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
from pydantic import BaseModel, Field

from pii_guard.api.deps import (
    PayloadTooLargeError,
    get_analyzer,
    get_language,
    get_policies,
    get_vault,
)
from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import (
    LoggedRoute,
    ephemeral_session,
    log_extra,
    text_body_limit,
    v1_router,
)
from pii_guard.detection_profile import require_local_ocr, require_segmenter_instance
from pii_guard.policy import Policy, PolicySet
from pii_guard.types import PiiGuardError
from pii_guard.vault import Vault
from pii_guard.visual.masking import (
    DEFAULT_MAX_IMAGE_BYTES,
    RENDER_MODES,
    AnalyzerDetector,
    ImageMasker,
    ImageMaskOutcome,
    InvalidImageError,
    Render,
    UnsupportedImageError,
    decode_base64_image,
    default_ocr_engine,
    image_workers_for,
    mask_images_bounded,
    require_ocr,
)
from pii_guard.visual.ocr import OcrEngine
from pii_guard.visual.segment import Segmenter
from pii_guard.visual.segmenters import build_segmenter
from pii_guard.visual.summary import ExpiryPolicy

__all__ = ["ImageMaskResponse", "get_image_masker", "max_image_bytes", "router"]

_RAW_TYPES = frozenset({"image/png", "image/jpeg", "image/jpg"})
_JSON_OVERHEAD_BYTES = 16_384
_lock = threading.Lock()
_EXPIRY_MODES: tuple[ExpiryPolicy, ...] = ("reduce", "keep")


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


_BOX = "`[x1, y1, x2, y2]`, inclusive pixel corners in the image after EXIF orientation"


class ImageRegionOut(BaseModel):
    """A region found in the image: where, what and by whom. Never its text or pixels."""

    entity_type: str = Field(
        description="The entity type (`FACE`, `SIGNATURE`, `ID_PHOTO`, `STAMP`, or a text type "
        "found by OCR).",
        examples=["FACE"],
    )
    box: list[int] = Field(
        description=f"The detected area, {_BOX}. `FACE` boxes are grown before masking; the "
        "reported box is the area covered.",
        examples=[[72, 116, 188, 262]],
    )
    source: str = Field(
        description="`sam` (SAM 3.1), `local` (the on-device face detector) or `ocr` (OCR word "
        "boxes of a span a text detector found).",
        examples=["local"],
    )
    detector: str = Field(
        description="`sam`, `yunet`, the text detector's registry name, `captions` (a value "
        "next to a known field caption) or `vault` (a session value printed where no detector "
        "found it).",
        examples=["yunet"],
    )
    score: float | None = Field(description="Confidence in `[0, 1]`; `null` for SAM regions.")
    policy: str = Field(
        description="The type's policy: `mask` regions are covered, `keep` regions are left "
        "visible.",
        examples=["mask"],
    )
    #: ``render="labels"`` only: the session placeholder, the printed label and the match.
    placeholder: str | None = Field(
        default=None,
        description='`render: "labels"` only: the session placeholder of the covered value.',
        examples=["[[PERSON_a1b2c3]]"],
    )
    label: str | None = Field(
        default=None,
        description='`render: "labels"` only: what is printed in the box (`PHOTO · '
        "[[PERSON_x]]`, `SIGNATURE`, `STAMP`).",
    )
    match: str | None = Field(
        default=None,
        description='`render: "labels"` only: how the value was tied to the session: '
        "`exact`, `fuzzy`, `new` or `uncertain` (a new placeholder, never a guess).",
        examples=["fuzzy"],
    )
    match_confidence: float | None = Field(
        default=None,
        description='`render: "labels"` only: the match confidence in `[0, 1]`.',
    )
    cover_box: list[int] | None = Field(
        default=None,
        description='`render: "labels"` only: the area actually painted, '
        f"{_BOX}: the box grown by 2 px, extended to the right when the label needs room.",
    )


class TypeCount(BaseModel):
    """How many regions of one entity type got a policy."""

    entity_type: str = Field(description="The entity type.", examples=["FACE"])
    count: int = Field(description="How many regions of that type.")


class SamInfo(BaseModel):
    """What the segmenter ran."""

    model: str = Field(
        description="The segmenter's model id (`yunet-2023mar+sam-3.1` for `hybrid`).",
        examples=["yunet-2023mar+sam-3.1"],
    )
    entity_types: list[str] = Field(
        description="The visual entity types the segmenter was asked for."
    )


class OcrInfo(BaseModel):
    """Whether the text in the image was checked, and with what."""

    ran: bool = Field(
        description="`false` only with `PII_GUARD_IMAGE_REQUIRE_OCR=false` and no Tesseract: "
        "text in the image was **not** checked."
    )
    engine: str | None = Field(description="The OCR engine (`tesseract`), or `null`.")
    detectors: list[str] = Field(description="The text detectors OCR text went through.")
    models: dict[str, str] = Field(
        description="Each model-backed text detector's model id, by detector name."
    )
    reason: str | None = Field(
        description="Why OCR did not run (`tesseract_unavailable`), or `null`."
    )


class Analysis(BaseModel):
    """What ran on the image, so clients can label regions by what actually ran."""

    sam: SamInfo = Field(description="The visual segmenter.")
    ocr: OcrInfo = Field(description="OCR and the text detectors.")


class ImageMaskResponse(BaseModel):
    """The masked image and a value-free account of what was covered.

    ``render``, ``session_id``, ``transcript``, ``summary`` and ``matches`` are only present
    with ``render: "labels"``.
    """

    image: str = Field(
        description="The masked image, base64 PNG, re-encoded from pixels with no metadata."
    )
    media_type: str = Field(description="Always `image/png`.", examples=["image/png"])
    width: int = Field(description="Width of the image in pixels.")
    height: int = Field(description="Height of the image in pixels.")
    regions: list[ImageRegionOut] = Field(description="Every region found, covered or kept.")
    masked: list[TypeCount] = Field(description="Covered regions by entity type.")
    kept: list[TypeCount] = Field(description="Regions left visible by a `keep` policy.")
    analysis: Analysis = Field(description="The segmenter, OCR and detectors that ran.")
    render: str = Field(
        default="opaque",
        description="`labels` (placeholders printed in the boxes) or `opaque` (solid boxes).",
    )
    #: The vault session the placeholders belong to (``render="labels"``).
    session_id: str | None = Field(
        default=None,
        description="The vault session the placeholders belong to: the one sent, or a new one.",
    )
    transcript: str | None = Field(
        default=None,
        description="The OCR text with every covered value replaced by its placeholder (or "
        "`[PHOTO]`, `[SIGNATURE]`).",
    )
    summary: dict[str, Any] | None = Field(
        default=None,
        description="The document summary (`document_type`, `holder`, `document_number`, ...), "
        "with placeholders instead of values.",
    )
    matches: dict[str, int] = Field(
        default={},
        description="How many values matched the session: `exact`, `fuzzy`, `new`, `uncertain`.",
    )


class ImageOptions(BaseModel):
    """Per-request options (JSON body fields or query parameters)."""

    language: str | None = None
    session_id: str | None = None
    render: Render | None = None
    expiry: ExpiryPolicy = "reduce"


def _hosted(request: Request) -> bool:
    return bool(getattr(request.app.state.settings, "hosted", False))


def _sam_client(request: Request) -> Segmenter:
    state = request.app.state
    if _hosted(request):
        from pii_guard.hosted.images import local_segmenter

        return local_segmenter(state)
    sam = getattr(state, "sam_client", None)
    if sam is None:
        with _lock:
            sam = getattr(state, "sam_client", None)
            if sam is None:
                sam = build_segmenter(state.settings)
                state.sam_client = sam
    require_segmenter_instance(state.settings, sam)
    policy = getattr(request.state, "project_policy", None)
    if policy is None:
        return sam
    # A selected project policy picks local or SAM detection; a stricter server wins (LAB-1444).
    from pii_guard.projects.visual import visual_detection
    from pii_guard.visual.segmenters import policy_segmenter

    return policy_segmenter(visual_detection(policy), sam, lambda: _policy_local(state, sam))


def _policy_local(state: Any, server: Segmenter) -> Segmenter:
    """The shared on-device segmenter (faces, ID photos, signatures) for ``local`` policies."""
    from pii_guard.visual.segment import LocalSegmenter
    from pii_guard.visual.segmenters import HybridSegmenter, LocalSignatureSegmenter

    local = getattr(state, "policy_local_segmenter", None)
    if local is None:
        with _lock:
            local = getattr(state, "policy_local_segmenter", None)
            if local is None:
                faces = server.local if isinstance(server, HybridSegmenter) else server
                if not isinstance(faces, LocalSegmenter):
                    faces = build_segmenter(state.settings, mode="local")
                local = LocalSignatureSegmenter(faces)
                state.policy_local_segmenter = local
    return local


def _ocr_engine(request: Request) -> OcrEngine | None:
    state = request.app.state
    if _hosted(request):
        from pii_guard.hosted.images import local_ocr

        return local_ocr(state)
    if not hasattr(state, "ocr_engine"):
        state.ocr_engine = default_ocr_engine()
    ocr: OcrEngine | None = state.ocr_engine
    require_local_ocr(state.settings, ocr)
    return ocr


def get_image_masker(request: Request) -> ImageMasker:
    """SAM + (OCR + the app's analyzer, when an OCR engine is available) + the app's policies."""
    ocr = _ocr_engine(request)
    analyzer = get_analyzer(request) if ocr is not None else None
    if analyzer is not None:
        # OCR text would reach a detector that can't run (llm without a key): refuse before
        # the image is segmented or sent anywhere (503 detection_unavailable, LAB-1290).
        require = getattr(analyzer, "require_available", None)
        if callable(require):
            require()
    detector = AnalyzerDetector(analyzer) if analyzer is not None else None
    names = list(getattr(request.app.state, "detector_names", None) or [])
    models: dict[str, str] = {}
    if detector is not None:
        for inner in getattr(detector.analyzer, "detectors", None) or []:
            model = getattr(inner, "model", None)
            if isinstance(model, str) and model:
                models[getattr(inner, "name", type(inner).__name__)] = model
    max_pixels = request.app.state.settings.image_max_pixels
    if _hosted(request):
        from pii_guard.hosted.images import hosted_image_limits

        max_pixels, _ = hosted_image_limits(request.app.state.settings)
    return ImageMasker(
        max_pixels=max_pixels,
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


def _choice[C: str](value: object, name: str, allowed: tuple[C, ...]) -> C | None:
    """:func:`_option` for a closed set, typed as that set's ``Literal``."""
    checked = _option(value, name, allowed)
    return next((choice for choice in allowed if choice == checked), None)


async def _image_from_request(request: Request) -> tuple[bytes, ImageOptions]:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    image_limit = max_image_bytes(request)
    query = request.query_params
    options = ImageOptions(
        session_id=_option(query.get("session_id"), "session_id"),
        render=_choice(query.get("render"), "render", RENDER_MODES),
        expiry=_choice(query.get("expiry"), "expiry", _EXPIRY_MODES) or "reduce",
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
        options.render = _choice(body.get("render"), "render", RENDER_MODES) or options.render
        options.expiry = _choice(body.get("expiry"), "expiry", _EXPIRY_MODES) or options.expiry
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
        regions=[ImageRegionOut.model_validate(r.to_public_dict()) for r in outcome.regions],
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


def _render_and_vault(request: Request, requested: Render | None) -> tuple[Render, Vault | None]:
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


_OPTIONS_DOC = {
    "session_id": "The vault session to mask in (`labels` only). Omitted: a new one is created "
    "and returned. Unknown or expired: 404 `not_found`.",
    "render": "`labels` (default, `PII_GUARD_IMAGE_RENDER`) or `opaque`. Without a tenant key "
    "the default falls back to `opaque`; an explicit `labels` is then 500 "
    "`vault_not_configured`.",
    "expiry": "`reduce` (default; the summary says `expired: true|false` only) or `keep` (also "
    "the ISO expiry date).",
}
_ENUMS = {"render": list(RENDER_MODES), "expiry": list(_EXPIRY_MODES)}
_BINARY = {"schema": {"type": "string", "format": "binary"}}
_OPENAPI_EXTRA: dict[str, Any] = {
    "parameters": [
        {
            "name": name,
            "in": "query",
            "required": False,
            "description": f"{doc} A JSON body's field of the same name wins.",
            "schema": {"type": "string", **({"enum": _ENUMS[name]} if name in _ENUMS else {})},
        }
        for name, doc in _OPTIONS_DOC.items()
    ],
    "requestBody": {
        "required": True,
        "description": "The image bytes (`image/png` or `image/jpeg`; the format is sniffed "
        "from the bytes), or JSON with the image as base64 or a data URL.",
        "content": {
            "image/png": _BINARY,
            "image/jpeg": _BINARY,
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["image"],
                    "properties": {
                        "image": {
                            "type": "string",
                            "description": "Base64, or `data:image/png;base64,...`.",
                        },
                        "language": {
                            "type": "string",
                            "description": "ISO 639-1 language of the text in the image.",
                        },
                        **{
                            name: {
                                "type": "string",
                                "description": doc,
                                **({"enum": _ENUMS[name]} if name in _ENUMS else {}),
                            }
                            for name, doc in _OPTIONS_DOC.items()
                        },
                    },
                }
            },
        },
    },
}


@router.post(
    "/v1/mask/image",
    response_model=ImageMaskResponse,
    response_model_exclude_unset=True,
    summary="Cover faces, signatures, ID photos and text personal data in an image",
    openapi_extra=_OPENAPI_EXTRA,
    responses=error_responses(
        "not_found",
        "payload_too_large",
        "unsupported_media_type",
        "invalid_request",
        "invalid_image",
        "blocked_entity",
        "vault_not_configured",
        "masking_failed",
        "detection_failed",
        "detection_profile_denied",
        "detection_unavailable",
        "detector_loading",
        "ocr_unavailable",
    ),
)
async def mask_image_endpoint(
    request: Request,
    language: Annotated[
        str | None,
        Query(
            min_length=2,
            max_length=16,
            description="ISO 639-1 language of the text in the image. A JSON body's `language` "
            "wins. Defaults to `PII_GUARD_DEFAULT_LANGUAGE`.",
        ),
    ] = None,
) -> ImageMaskResponse:
    """Mask a PNG or JPEG image: visual types by the segmenter, text by OCR + the detectors.

    Send the image as the raw body or as JSON (base64 or a data URL). ``render: "labels"``
    (the default) prints each region's vault placeholder on it and returns a masked
    transcript and a document summary; ``opaque`` covers regions with solid boxes. Fail
    closed: any SAM, OCR or detector error is 503 ``detection_failed``, a ``block`` region
    422 ``blocked_entity``; the original image is never returned. See docs/contracts.md."""
    settings = request.app.state.settings
    timeout = settings.image_timeout
    workers = image_workers_for(request.app.state, settings.image_concurrency)
    if _hosted(request):
        from pii_guard.hosted.images import (
            hosted_image_limits,
            hosted_visual_policies,
            require_image_capacity,
            require_local_visual_policies,
        )

        # The owner's policy, text and visual; the operator's overrides win when stricter.
        policy = getattr(request.state, "project_policy", None)
        request.state.project_policies = hosted_visual_policies(
            policy, get_policies(request), settings, request.app.state.policies
        )
        # Before the image is decoded: a policy only SAM could serve, or a busy replica.
        require_local_visual_policies(request.state.project_policies, policy)
        require_image_capacity(workers)
        _, timeout = hosted_image_limits(settings)
    elif getattr(request.state, "project_policy", None) is not None:
        from pii_guard.projects.visual import effective_policies

        request.state.project_policies = effective_policies(
            request.state.project_policy,
            get_policies(request),
            getattr(request.app.state, "policies", None) or PolicySet.from_settings(settings),
            settings.policy_overrides,
        )
    data, options = await _image_from_request(request)
    if not data:
        raise InvalidImageError("image is empty")
    if len(data) > max_image_bytes(request):
        raise PayloadTooLargeError(f"image is larger than {max_image_bytes(request)} bytes")
    masker = get_image_masker(request)
    require_ocr(masker.ocr, required=settings.image_require_ocr)
    lang = get_language(request, options.language or language)
    render, vault = _render_and_vault(request, options.render)
    # Unknown or expired id -> 404 not_found, before any detection; a session this request
    # created is dropped again on any error, so a refused image leaves nothing in the vault.
    with ephemeral_session(vault, options.session_id, request) as session:
        # Bounded pool and deadline; values committed to the session only on success.
        (outcome,) = await mask_images_bounded(
            masker,
            [data],
            lang,
            workers=workers,
            timeout=timeout,
            render=render,
            session=session,
            expiry=options.expiry,
        )
    log_extra(
        request,
        regions=len(outcome.regions),
        masked=sum(outcome.counts(Policy.MASK).values()),
        kept=sum(outcome.counts(Policy.KEEP).values()),
        ocr=outcome.ocr_engine or "off",
        render=outcome.render,
    )
    return _response(outcome, session.session_id if session is not None else None)
