"""Image masking with entity policies: the one image pipeline behind ``POST /v1/mask/image``,
the gateway's image parts and the visual evaluation.

A domain component with no HTTP in it, so every embedder (the API route, the gateway, eval, a
CLI) imports it from here (LAB-1271). Exposes :class:`ImageMasker` and its outcome
(:class:`ImageMaskOutcome`, :class:`PolicedRegion`), :func:`mask_images_bounded` (the
deadline-bounded worker pool), the input checks (:func:`sniff_media_type`,
:func:`decode_base64_image`, :func:`require_ocr`) and their errors.

:class:`ImageMasker` runs the visual pipeline (:func:`pii_guard.visual.analyze_image`):

1. the **segmenter** (``PII_GUARD_SEGMENTER``, :mod:`pii_guard.visual.segmenters`) finds the
   visual types: by default YuNet on the CPU for ``FACE`` and ``ID_PHOTO`` and SAM 3.1 for
   ``SIGNATURE`` (``hybrid``); with ``sam-api`` SAM 3.1 segments every type it has a prompt
   for (``FACE``, ``SIGNATURE``, ``ID_PHOTO``, ``STAMP``), one request per concept prompt;
2. **OCR** (Tesseract, when installed) + the configured **text detectors** find text personal
   data in the image (a TAJ number, a name), mapped back to word boxes;
3. **policies** decide per region: ``mask`` regions are covered, ``keep`` regions (``STAMP``
   by default) are reported but left visible, any ``block`` region refuses the image
   (:class:`~pii_guard.policy.BlockedEntityError`).

**Rendering** (``render``): ``"labels"`` (with a vault session, see
:mod:`pii_guard.visual.labels`) covers each region with a neutral box printed with the
session placeholder of its value (``[[PERSON_a1b2c3]]``, ``PHOTO · [[PERSON_a1b2c3]]``) and
returns a masked **transcript** and a document **summary** that use the same placeholders as
the text of the session; ``"opaque"`` covers each region with a solid fill and returns
neither. Both cover exactly the same pixels.

``FACE`` boxes are grown before masking (:data:`FACE_PADDING`: up, sides, down, as fractions of
the box, clamped to the image): SAM's face box runs from the brows to the chin, which leaves
hair and ears visible. The reported box is the grown one, the area actually covered.

Overlapping regions of the same type and source (SAM's ``signature`` and ``squiggly line``
prompts can find the same scribble) are merged into their union, which is never smaller.

Fail closed (ADR 0006): no OCR engine refuses the image (:func:`require_ocr`, 503
``ocr_unavailable``) unless ``PII_GUARD_IMAGE_REQUIRE_OCR=false``; a SAM, OCR or detector
failure raises :class:`~pii_guard.types.DetectionError`; a masking failure raises
:class:`~pii_guard.types.MaskingError`. The original image is never returned, and the masked
one is re-encoded from pixels (no metadata). Errors and logs carry types and counts only.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import datetime as dt
import io
import logging
import threading
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from PIL import Image

from pii_guard.policy import BlockedEntityError, Policy, PolicySet
from pii_guard.types import (
    Analyzer,
    DetectionError,
    Detector,
    EntityType,
    PayloadTooLargeError,
    PiiGuardError,
    Span,
)
from pii_guard.vault import VaultSession
from pii_guard.visual.image import load_image, mask_image
from pii_guard.visual.labels import RegionLabel, VaultMatcher, label_image
from pii_guard.visual.ocr import (
    OcrEngine,
    OcrText,
    TesseractOcr,
    check_deadline,
    deadline,
    tesseract_available,
)
from pii_guard.visual.pipeline import ImageAnalysis, analyze_image_text
from pii_guard.visual.regions import Box, Region, intersection, iou
from pii_guard.visual.render import LabelBox, render_labels
from pii_guard.visual.segment import Segmenter
from pii_guard.visual.segmenters import default_entity_types
from pii_guard.visual.summary import ExpiryPolicy
from pii_guard.workers import BoundedWorkers

__all__ = [
    "DEFAULT_IMAGE_MAX_PIXELS",
    "DEFAULT_MAX_IMAGE_BYTES",
    "SUPPORTED_MEDIA_TYPES",
    "AnalyzerDetector",
    "ImageMaskOutcome",
    "ImageMasker",
    "InvalidImageError",
    "OcrUnavailableError",
    "PolicedRegion",
    "Render",
    "UnsupportedImageError",
    "decode_base64_image",
    "default_ocr_engine",
    "grow_face",
    "image_workers_for",
    "mask_images_bounded",
    "require_ocr",
    "sniff_media_type",
]

logger = logging.getLogger(__name__)

#: Largest accepted image, in bytes (decoded). Override per app with ``app.state.max_image_bytes``.
DEFAULT_MAX_IMAGE_BYTES = 10 * 1024 * 1024
#: Largest accepted image, in pixels (``PII_GUARD_IMAGE_MAX_PIXELS``): OCR time and memory grow
#: with pixels, and a small PNG can decode to tens of megapixels (LAB-1207).
DEFAULT_IMAGE_MAX_PIXELS = 16_000_000

#: Accepted input formats and their signatures. The output is always PNG.
SUPPORTED_MEDIA_TYPES: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}

#: Where a region came from: SAM 3.1, the on-device segmenter (YuNet) or OCR + a text detector.
Origin = Literal["sam", "local", "ocr"]
_SEGMENTER_ORIGINS: dict[str, Origin] = {"sam": "sam", "yunet": "local"}
#: ``labels``: placeholder-labelled boxes + transcript + summary; ``opaque``: solid boxes.
Render = Literal["labels", "opaque"]
RENDER_MODES: tuple[Render, ...] = ("labels", "opaque")

#: How far a ``FACE`` box is grown before masking: (up, sides, down), fractions of its size.
FACE_PADDING: tuple[float, float, float] = (0.40, 0.10, 0.05)


class UnsupportedImageError(PiiGuardError):
    """Not a PNG or JPEG image."""

    code = "unsupported_media_type"
    status_code = 415


class InvalidImageError(PiiGuardError):
    """A PNG/JPEG signature, but the image can't be decoded (or base64 is malformed)."""

    code = "invalid_image"
    status_code = 422


class OcrUnavailableError(PiiGuardError):
    """No OCR engine, so the text in an image can't be checked (``image_require_ocr``)."""

    code = "ocr_unavailable"
    status_code = 503


def sniff_media_type(data: bytes) -> str:
    """The media type of ``data`` from its signature; never trusts a declared type."""
    for media_type, signatures in SUPPORTED_MEDIA_TYPES.items():
        if any(data.startswith(sig) for sig in signatures):
            return media_type
    raise UnsupportedImageError("only PNG and JPEG images are supported")


def decode_base64_image(value: str) -> bytes:
    """Decode base64 or a ``data:image/...;base64,`` URL; :class:`InvalidImageError` if bad."""
    raw = value.strip()
    if raw.startswith("data:"):
        header, sep, raw = raw.partition(",")
        if not sep or not header.endswith(";base64"):
            raise InvalidImageError("image data URL must be base64-encoded")
    try:
        return base64.b64decode("".join(raw.split()), validate=True)
    except (binascii.Error, ValueError):
        raise InvalidImageError("image is not valid base64") from None


@dataclass(frozen=True, slots=True)
class PolicedRegion:
    """A detected region, where it came from and what the policy did with it."""

    region: Region
    origin: Origin
    policy: Policy
    #: The placeholder label printed on it (``render="labels"`` only).
    label: RegionLabel | None = None
    #: The area the labelled cover takes (``render="labels"`` only): the box grown by the
    #: padding and, for a legible label, extended to the right into free space.
    cover_box: Box | None = None

    @property
    def entity_type(self) -> EntityType:
        return self.region.entity_type

    def to_public_dict(self) -> dict[str, object]:
        """``{entity_type, box, source, detector, score, policy}``, plus ``{placeholder,
        label, match, match_confidence, cover_box}`` when labelled. Never a value."""
        out: dict[str, object] = {
            "entity_type": self.region.entity_type.value,
            "box": self.region.box.to_list(),
            "source": self.origin,
            "detector": self.region.source,
            "score": self.region.score,
            "policy": self.policy.value,
        }
        if self.label is not None:
            out.update(
                placeholder=self.label.placeholder,
                label=self.label.label,
                match=self.label.match,
                match_confidence=self.label.confidence,
                cover_box=self.cover_box.to_list() if self.cover_box is not None else None,
            )
        return out


@dataclass(frozen=True, slots=True)
class ImageMaskOutcome:
    """The masked PNG and a value-free account of what ran and what was covered."""

    image: bytes
    width: int
    height: int
    regions: list[PolicedRegion]
    sam_model: str
    sam_types: list[EntityType]
    ocr_engine: str | None
    text_detectors: list[str] = field(default_factory=list)
    #: Model id per model-backed text detector (``{"llm": "muse-spark-1.3"}``), for labels.
    detector_models: dict[str, str] = field(default_factory=dict)
    render: Render = "opaque"
    #: The OCR text with placeholders (``render="labels"`` with OCR only).
    transcript: str | None = None
    #: The document summary (``render="labels"`` only; see :mod:`pii_guard.visual.summary`).
    summary: dict[str, Any] | None = None
    #: Vault matches of the image's values: ``{"exact": 2, "fuzzy": 1, "new": 3, ...}``.
    matches: dict[str, int] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"ImageMaskOutcome(image=<{len(self.image)} bytes>, size={self.width}x{self.height}, "
            f"regions={len(self.regions)}, ocr={self.ocr_engine!r})"
        )

    def counts(self, policy: Policy) -> dict[EntityType, int]:
        found = Counter(r.entity_type for r in self.regions if r.policy is policy)
        return dict(sorted(found.items()))


class AnalyzerDetector:
    """Adapts an :class:`~pii_guard.types.Analyzer` (the API's analyzer) to a Detector.

    Spans keep their own ``detector`` names (``rules``, ``llm``), so OCR regions report them.
    """

    name = "analyzer"

    def __init__(self, analyzer: Analyzer) -> None:
        self.analyzer = analyzer

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        return self.analyzer.analyze(text, language)


def default_ocr_engine() -> OcrEngine | None:
    """Tesseract (``hun+eng``) if ``pytesseract`` and the binary are installed, else ``None``."""
    return TesseractOcr() if tesseract_available() else None


def require_ocr(ocr: OcrEngine | None, *, required: bool) -> None:
    """Fail closed (ADR 0006) when OCR is required but there is no engine: without one the
    text in an image (a TAJ, a name) would reach the upstream unchecked.

    Raises :class:`OcrUnavailableError` (503 ``ocr_unavailable``). ``required=False``
    (``PII_GUARD_IMAGE_REQUIRE_OCR=false``) accepts SAM-only masking."""
    if required and ocr is None:
        raise OcrUnavailableError(
            "OCR is unavailable (Tesseract is not installed), so text in the image can't be "
            "checked; install it (docs/operations.md) or set PII_GUARD_IMAGE_REQUIRE_OCR=false "
            "to mask images with SAM only"
        )


class ImageMasker:
    """A segmenter + optional OCR text detection + policies → a masked PNG.

    - ``sam``: the segmenter (:func:`pii_guard.visual.segmenters.build_segmenter`; a
      :class:`~pii_guard.visual.sam.SamClient` without an API key fails every call closed).
    - ``ocr`` / ``text_detector``: both or neither. Without them only SAM runs, and the
      outcome says so (``ocr_engine is None``).
    - ``captions``: also mask the values next to known field captions on the OCR'd text
      (:mod:`pii_guard.visual.captions`; on by default).
    - ``entity_types``: the visual types to segment; default
      :func:`~pii_guard.visual.segmenters.default_entity_types`: for a ``SamClient`` every
      type it has a prompt for (``keep`` types such as ``STAMP`` are found and reported), for
      the other segmenters every visual type whose policy is not ``keep``.
    - ``max_pixels``: larger images are refused (413 ``payload_too_large``) before decoding.
    """

    def __init__(
        self,
        *,
        sam: Segmenter,
        policies: PolicySet,
        ocr: OcrEngine | None = None,
        text_detector: Detector | None = None,
        text_detector_names: Sequence[str] = (),
        text_detector_models: dict[str, str] | None = None,
        entity_types: Sequence[EntityType] | None = None,
        captions: bool = True,
        max_pixels: int = DEFAULT_IMAGE_MAX_PIXELS,
    ) -> None:
        if (ocr is None) != (text_detector is None):
            raise ValueError("ocr and text_detector go together")
        self.sam = sam
        self.policies = policies
        self.ocr = ocr
        self.text_detector = text_detector
        self.text_detector_names = list(text_detector_names)
        self.text_detector_models = dict(text_detector_models or {})
        self.captions = captions
        self.max_pixels = max_pixels
        self.entity_types = (
            list(entity_types)
            if entity_types is not None
            else default_entity_types(sam, policies.of)
        )
        if not self.entity_types:
            raise ValueError("at least one visual entity type is needed")

    def __repr__(self) -> str:
        ocr = getattr(self.ocr, "name", None)
        return f"ImageMasker(sam={self.sam!r}, ocr={ocr!r}, types={len(self.entity_types)})"

    def mask(
        self,
        data: bytes,
        language: str = "hu",
        *,
        render: Render = "opaque",
        matcher: VaultMatcher | None = None,
        expiry: ExpiryPolicy = "reduce",
        today: dt.date | None = None,
        until: float | None = None,
    ) -> ImageMaskOutcome:
        """Detect, police and cover. ``render="labels"`` needs ``matcher`` (the request's
        :class:`~pii_guard.visual.labels.VaultMatcher`); values are registered in its
        session only once the image passed the policies (a refused image stores nothing).

        ``until`` (a ``time.monotonic()`` deadline) bounds the work: Tesseract is killed when
        it runs out and the stages check it, raising
        :class:`~pii_guard.visual.ocr.OcrTimeoutError` (503 ``detection_failed``)."""
        if render not in RENDER_MODES:
            raise ValueError(f"render must be one of {RENDER_MODES}")
        if render == "labels" and matcher is None:
            raise ValueError("render='labels' needs a vault matcher")
        sniff_media_type(data)
        _check_pixels(data, self.max_pixels)
        with deadline(until):
            return self._mask(data, language, render, matcher, expiry, today)

    def _mask(
        self,
        data: bytes,
        language: str,
        render: Render,
        matcher: VaultMatcher | None,
        expiry: ExpiryPolicy,
        today: dt.date | None,
    ) -> ImageMaskOutcome:
        check_deadline()
        try:
            decoded = load_image(data)
        except ValueError:
            raise InvalidImageError("image could not be decoded") from None
        width, height = decoded.size

        analysis = analyze_image_text(
            data,
            sam=self.sam,
            entity_types=self.entity_types,
            ocr=self.ocr,
            detectors=[self.text_detector] if self.text_detector is not None else (),
            language=language,
            captions=self.captions,
        )
        check_deadline()
        masked_types = frozenset(t for t in EntityType if self.policies.of(t) is Policy.MASK)
        if render == "labels" and matcher is not None and analysis.ocr is not None:
            # Values the conversation already named, printed where no detector found them.
            found = matcher.find(analysis.ocr, masked_types)
            if found:
                ocr_text = analysis.ocr
                analysis = ImageAnalysis(
                    analysis.regions + [f.region for f in found],
                    OcrText(
                        ocr_text.words, ocr_text.findings + found, ocr_text.zones, ocr_text.fields
                    ),
                )
        regions = [grow_face(r, width, height) for r in analysis.regions]
        policed = _merge([self._police(r) for r in regions])
        blocked = Counter(r.entity_type for r in policed if r.policy is Policy.BLOCK)
        if blocked:
            raise BlockedEntityError(dict(blocked))
        transcript: str | None = None
        summary: dict[str, Any] | None = None
        matches: dict[str, int] = {}
        check_deadline()  # last check before values are registered
        if render == "labels" and matcher is not None:
            labels = label_image(
                analysis.ocr,
                [(r.region, r.policy) for r in policed],
                matcher,
                expiry=expiry,
                today=today,
                masked_types=masked_types,
            )
            policed = [
                PolicedRegion(
                    r.region, r.origin, r.policy, label if r.policy is Policy.MASK else None
                )
                for r, label in zip(policed, labels.labels, strict=True)
            ]
            masked_regions = [r for r in policed if r.policy is Policy.MASK]
            rendered = render_labels(
                data,
                [
                    LabelBox(r.region.box, r.label.label if r.label else None)
                    for r in masked_regions
                ],
                obstacles=_visible_words(analysis, masked_regions),
            )
            masked = rendered.image
            grown = dict(zip(map(id, masked_regions), rendered.boxes, strict=True))
            policed = [_with_box(r, grown.get(id(r))) for r in policed]
            transcript = labels.transcript if analysis.ocr is not None else None
            summary, matches = labels.summary, labels.matches
        else:
            masked = mask_image(data, [r.region for r in policed if r.policy is Policy.MASK])
        logger.debug(
            "image: %dx%d, %d region(s), ocr=%s",
            width,
            height,
            len(policed),
            getattr(self.ocr, "name", "off"),
        )
        return ImageMaskOutcome(
            image=masked,
            width=width,
            height=height,
            regions=policed,
            sam_model=str(getattr(self.sam, "model", type(self.sam).__name__)),
            sam_types=list(self.entity_types),
            ocr_engine=getattr(self.ocr, "name", None) if self.ocr is not None else None,
            text_detectors=self.text_detector_names if self.ocr is not None else [],
            detector_models=self.text_detector_models if self.ocr is not None else {},
            render=render,
            transcript=transcript,
            summary=summary,
            matches=matches,
        )

    def _police(self, region: Region) -> PolicedRegion:
        origin: Origin = _SEGMENTER_ORIGINS.get(region.source, "ocr")
        return PolicedRegion(region, origin, self.policies.of(region.entity_type))


def _check_pixels(data: bytes, limit: int) -> None:
    """Refuse an image of more than ``limit`` pixels from its header, before decoding it."""
    try:
        with Image.open(io.BytesIO(data)) as raw:
            pixels = raw.width * raw.height
    except (OSError, ValueError, Image.DecompressionBombError):
        raise InvalidImageError("image could not be decoded") from None
    if pixels > limit:
        raise PayloadTooLargeError(f"image has more than {limit} pixels")


_workers_lock = threading.Lock()


def image_workers_for(state: Any, size: int) -> BoundedWorkers:
    """The app's one image worker pool (``state.image_workers``), created on first use.

    ``POST /v1/mask/image`` and the gateway share it, so ``PII_GUARD_IMAGE_CONCURRENCY``
    bounds the app's concurrent image work."""
    workers = getattr(state, "image_workers", None)
    if workers is None:
        with _workers_lock:
            workers = getattr(state, "image_workers", None)
            if workers is None:
                workers = BoundedWorkers(size, "pii-guard-image")
                state.image_workers = workers
    return workers


async def mask_images_bounded(
    masker: ImageMasker,
    images: Sequence[bytes],
    language: str,
    *,
    workers: BoundedWorkers,
    timeout: float,
    render: Render = "opaque",
    session: VaultSession | None = None,
    expiry: ExpiryPolicy = "reduce",
) -> list[ImageMaskOutcome]:
    """Mask ``images`` on ``workers`` within ``timeout`` seconds (waiting for a slot included).

    The work holds its worker slot until its thread has finished, and stops at ``timeout``
    (Tesseract killed, the stages check the deadline). With ``render="labels"`` the values
    are registered in a fork of ``session``, committed only when every image succeeded: a
    refused or timed-out request leaves nothing in the session, even if its thread is still
    finishing (LAB-1207). Raises :class:`~pii_guard.types.DetectionError` on timeout; other
    errors propagate as the masker raised them.
    """
    until = time.monotonic() + timeout
    scratch = session.fork() if render == "labels" and session is not None else None

    def run_all() -> list[ImageMaskOutcome]:
        matcher = VaultMatcher(scratch, language) if scratch is not None else None
        return [
            masker.mask(data, language, render=render, matcher=matcher, expiry=expiry, until=until)
            for data in images
        ]

    try:
        outcomes = await asyncio.wait_for(workers.run(run_all), timeout=timeout)
    except TimeoutError:
        raise DetectionError(f"image masking timed out after {timeout:g}s") from None
    if scratch is not None and session is not None:
        session.commit(scratch)
    return outcomes


def _visible_words(analysis: ImageAnalysis, covered: list[PolicedRegion]) -> list[Box]:
    """The boxes of OCR words no covered region hides: a label never extends over them."""
    if analysis.ocr is None:
        return []
    out: list[Box] = []
    for word in analysis.ocr.words:
        area = word.box.width * word.box.height
        hidden = any(intersection(word.box, r.region.box) >= 0.3 * area for r in covered)
        if not hidden:
            out.append(word.box)
    return out


def _with_box(item: PolicedRegion, box: Box | None) -> PolicedRegion:
    """``item`` carrying ``box``, the area its labelled cover actually takes (grown by the
    padding and any extension for the label). ``region.box`` stays the detected box, so
    visual recall is scored the same in both render modes."""
    if box is None:
        return item
    return PolicedRegion(item.region, item.origin, item.policy, item.label, box)


def grow_face(region: Region, width: int, height: int) -> Region:
    """A ``FACE`` region grown by :data:`FACE_PADDING` (clamped); other regions unchanged."""
    if region.entity_type is not EntityType.FACE:
        return region
    up, sides, down = FACE_PADDING
    box = region.box
    grown = Box(
        max(0, box.x1 - round(box.width * sides)),
        max(0, box.y1 - round(box.height * up)),
        min(width - 1, box.x2 + round(box.width * sides)),
        min(height - 1, box.y2 + round(box.height * down)),
    )
    return Region(region.entity_type, grown, region.score, region.source, mask=region.mask)


def _merge(regions: list[PolicedRegion], threshold: float = 0.5) -> list[PolicedRegion]:
    """Merge same-type, same-origin regions that mostly overlap into their union box."""
    out: list[PolicedRegion] = []
    for item in regions:
        for index, other in enumerate(out):
            same = other.entity_type is item.entity_type and other.origin == item.origin
            if same and iou(other.region.box, item.region.box) >= threshold:
                a, b = other.region, item.region
                scores = [s for s in (a.score, b.score) if s is not None]
                merged = Region(
                    a.entity_type,
                    a.box.union(b.box),
                    max(scores) if scores else None,
                    a.source,
                    mask=a.mask,
                )
                out[index] = PolicedRegion(
                    merged, other.origin, other.policy, other.label, other.cover_box
                )
                break
        else:
            out.append(item)
    return sorted(out, key=lambda r: (r.region.box.y1, r.region.box.x1, r.entity_type.value))
