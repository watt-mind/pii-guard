"""Image masking with entity policies, shared by ``POST /v1/mask/image`` and the gateway.

Not a router (it defines no ``router``), so :func:`pii_guard.api.routes.include_routers`
imports it but mounts nothing.

:class:`ImageMasker` runs the visual pipeline (:func:`pii_guard.visual.analyze_image`):

1. **SAM 3.1** segments every visual type it has a prompt for (``FACE``, ``SIGNATURE``,
   ``ID_PHOTO``, ``STAMP``), one request per concept prompt;
2. **OCR** (Tesseract, when installed) + the configured **text detectors** find text personal
   data in the image (a TAJ number, a name), mapped back to word boxes;
3. **policies** decide per region: ``mask`` regions are covered with a solid fill, ``keep``
   regions (``STAMP`` by default) are reported but left visible, any ``block`` region refuses
   the image (:class:`~pii_guard.policy.BlockedEntityError`).

``FACE`` boxes are grown before masking (:data:`FACE_PADDING`: up, sides, down, as fractions of
the box, clamped to the image): SAM's face box runs from the brows to the chin, which leaves
hair and ears visible. The reported box is the grown one, the area actually covered.

Overlapping regions of the same type and source (SAM's ``signature`` and ``squiggly line``
prompts can find the same scribble) are merged into their union, which is never smaller.

Fail closed (ADR 0006): a SAM, OCR or detector failure raises
:class:`~pii_guard.types.DetectionError`; a masking failure raises
:class:`~pii_guard.types.MaskingError`. The original image is never returned, and the masked
one is re-encoded from pixels (no metadata). Errors and logs carry types and counts only.
"""

from __future__ import annotations

import base64
import binascii
import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from pii_guard.policy import BlockedEntityError, Policy, PolicySet
from pii_guard.types import Detector, EntityType, PiiGuardError, Span
from pii_guard.visual.image import load_image, mask_image
from pii_guard.visual.ocr import OcrEngine, TesseractOcr, tesseract_available
from pii_guard.visual.pipeline import analyze_image
from pii_guard.visual.regions import Box, Region
from pii_guard.visual.sam import SamClient

__all__ = [
    "DEFAULT_MAX_IMAGE_BYTES",
    "SUPPORTED_MEDIA_TYPES",
    "AnalyzerDetector",
    "ImageMaskOutcome",
    "ImageMasker",
    "InvalidImageError",
    "PolicedRegion",
    "UnsupportedImageError",
    "decode_base64_image",
    "default_ocr_engine",
    "sniff_media_type",
]

logger = logging.getLogger(__name__)

#: Largest accepted image, in bytes (decoded). Override per app with ``app.state.max_image_bytes``.
DEFAULT_MAX_IMAGE_BYTES = 10 * 1024 * 1024

#: Accepted input formats and their signatures. The output is always PNG.
SUPPORTED_MEDIA_TYPES: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}

Origin = Literal["sam", "ocr"]

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

    @property
    def entity_type(self) -> EntityType:
        return self.region.entity_type

    def to_public_dict(self) -> dict[str, object]:
        """``{entity_type, box, source, detector, score, policy}``. Never a value."""
        return {
            "entity_type": self.region.entity_type.value,
            "box": self.region.box.to_list(),
            "source": self.origin,
            "detector": self.region.source,
            "score": self.region.score,
            "policy": self.policy.value,
        }


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

    def __repr__(self) -> str:
        return (
            f"ImageMaskOutcome(image=<{len(self.image)} bytes>, size={self.width}x{self.height}, "
            f"regions={len(self.regions)}, ocr={self.ocr_engine!r})"
        )

    def counts(self, policy: Policy) -> dict[EntityType, int]:
        found = Counter(r.entity_type for r in self.regions if r.policy is policy)
        return dict(sorted(found.items()))


class AnalyzerDetector:
    """Adapts anything with ``analyze(text, language)`` (the API's analyzer) to a Detector.

    Spans keep their own ``detector`` names (``rules``, ``llm``), so OCR regions report them.
    """

    name = "analyzer"

    def __init__(self, analyzer: object) -> None:
        self.analyzer = analyzer

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        return self.analyzer.analyze(text, language)  # type: ignore[attr-defined]


def default_ocr_engine() -> OcrEngine | None:
    """Tesseract (``hun+eng``) if ``pytesseract`` and the binary are installed, else ``None``."""
    return TesseractOcr() if tesseract_available() else None


class ImageMasker:
    """SAM 3.1 + optional OCR text detection + policies → a masked PNG.

    - ``sam``: required. Without an API key every call fails closed (``detection_failed``).
    - ``ocr`` / ``text_detector``: both or neither. Without them only SAM runs, and the
      outcome says so (``ocr_engine is None``).
    - ``captions``: also mask the values next to known field captions on the OCR'd text
      (:mod:`pii_guard.visual.captions`; on by default).
    - ``entity_types``: the visual types to segment; default every type ``sam`` has a prompt
      for, so ``keep`` types (``STAMP``) are found and reported, not silently ignored.
    """

    def __init__(
        self,
        *,
        sam: SamClient,
        policies: PolicySet,
        ocr: OcrEngine | None = None,
        text_detector: Detector | None = None,
        text_detector_names: Sequence[str] = (),
        text_detector_models: dict[str, str] | None = None,
        entity_types: Sequence[EntityType] | None = None,
        captions: bool = True,
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
        self.entity_types = list(entity_types) if entity_types is not None else list(sam.prompts)
        if not self.entity_types:
            raise ValueError("at least one visual entity type is needed")

    def __repr__(self) -> str:
        ocr = getattr(self.ocr, "name", None)
        return f"ImageMasker(sam={self.sam!r}, ocr={ocr!r}, types={len(self.entity_types)})"

    def mask(self, data: bytes, language: str = "hu") -> ImageMaskOutcome:
        sniff_media_type(data)
        try:
            decoded = load_image(data)
        except ValueError:
            raise InvalidImageError("image could not be decoded") from None
        width, height = decoded.size

        regions = analyze_image(
            data,
            sam=self.sam,
            entity_types=self.entity_types,
            ocr=self.ocr,
            detectors=[self.text_detector] if self.text_detector is not None else (),
            language=language,
            captions=self.captions,
        )
        regions = [_grow_face(r, width, height) for r in regions]
        policed = _merge([self._police(r) for r in regions])
        blocked = Counter(r.entity_type for r in policed if r.policy is Policy.BLOCK)
        if blocked:
            raise BlockedEntityError(dict(blocked))
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
            sam_model=self.sam.model,
            sam_types=list(self.entity_types),
            ocr_engine=getattr(self.ocr, "name", None) if self.ocr is not None else None,
            text_detectors=self.text_detector_names if self.ocr is not None else [],
            detector_models=self.text_detector_models if self.ocr is not None else {},
        )

    def _police(self, region: Region) -> PolicedRegion:
        origin: Origin = "sam" if region.source == "sam" else "ocr"
        return PolicedRegion(region, origin, self.policies.of(region.entity_type))


def _grow_face(region: Region, width: int, height: int) -> Region:
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


def _iou(a: Box, b: Box) -> float:
    ix = min(a.x2, b.x2) - max(a.x1, b.x1) + 1
    iy = min(a.y2, b.y2) - max(a.y1, b.y1) + 1
    if ix <= 0 or iy <= 0:
        return 0.0
    inter = ix * iy
    return inter / (a.width * a.height + b.width * b.height - inter)


def _merge(regions: list[PolicedRegion], threshold: float = 0.5) -> list[PolicedRegion]:
    """Merge same-type, same-origin regions that mostly overlap into their union box."""
    out: list[PolicedRegion] = []
    for item in regions:
        for index, other in enumerate(out):
            same = other.entity_type is item.entity_type and other.origin == item.origin
            if same and _iou(other.region.box, item.region.box) >= threshold:
                a, b = other.region, item.region
                scores = [s for s in (a.score, b.score) if s is not None]
                merged = Region(
                    a.entity_type,
                    a.box.union(b.box),
                    max(scores) if scores else None,
                    a.source,
                    mask=a.mask,
                )
                out[index] = PolicedRegion(merged, other.origin, other.policy)
                break
        else:
            out.append(item)
    return sorted(out, key=lambda r: (r.region.box.y1, r.region.box.x1, r.entity_type.value))
