"""The visual pipeline: SAM 3.1 regions + OCR text regions → masked image.

Fail closed (ADR 0006): if segmentation, OCR, detection or masking fails, the call raises
(:class:`~pii_guard.types.DetectionError` / :class:`~pii_guard.types.MaskingError`) and no
image is returned. There is no option that returns the input unmasked.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pii_guard.types import DetectionError, Detector, EntityType, PiiGuardError
from pii_guard.visual.image import DEFAULT_FILL, load_image, mask_image
from pii_guard.visual.ocr import OcrEngine, OcrText, ocr_text
from pii_guard.visual.regions import Region
from pii_guard.visual.sam import SamClient

__all__ = ["ImageAnalysis", "VisualResult", "analyze_image", "analyze_image_text", "mask_visual"]


@dataclass(frozen=True, slots=True)
class VisualResult:
    """A masked image (re-encoded, metadata-free) and the regions that were covered."""

    image: bytes
    regions: list[Region]

    def __repr__(self) -> str:
        return f"VisualResult(image=<{len(self.image)} bytes>, regions={len(self.regions)})"


@dataclass(frozen=True, slots=True)
class ImageAnalysis:
    """What :func:`analyze_image_text` found: every region (SAM's first, then OCR's, in the
    order :func:`analyze_image` returns them) and the OCR pass behind the text regions
    (``None`` when OCR did not run). Holds OCR text in memory; ``repr()`` shows counts."""

    regions: list[Region]
    ocr: OcrText | None

    def __repr__(self) -> str:
        return f"ImageAnalysis(regions={len(self.regions)}, ocr={self.ocr!r})"


def analyze_image(
    image: bytes,
    *,
    sam: SamClient | None = None,
    entity_types: Sequence[EntityType | str] | None = None,
    ocr: OcrEngine | None = None,
    detectors: Sequence[Detector] = (),
    language: str = "hu",
    captions: bool = True,
) -> list[Region]:
    """Find personal data regions in ``image`` without masking.

    ``sam`` segments the visual ``entity_types`` (default ``FACE``, ``SIGNATURE``,
    ``ID_PHOTO``); ``ocr`` + ``detectors`` find text personal data, and with ``captions``
    the values next to known field captions (:mod:`pii_guard.visual.captions`). At least one
    of SAM and OCR must be configured.
    """
    return analyze_image_text(
        image,
        sam=sam,
        entity_types=entity_types,
        ocr=ocr,
        detectors=detectors,
        language=language,
        captions=captions,
    ).regions


def analyze_image_text(
    image: bytes,
    *,
    sam: SamClient | None = None,
    entity_types: Sequence[EntityType | str] | None = None,
    ocr: OcrEngine | None = None,
    detectors: Sequence[Detector] = (),
    language: str = "hu",
    captions: bool = True,
) -> ImageAnalysis:
    """Like :func:`analyze_image`, also returning the OCR words and the text of every OCR
    finding, which placeholder labelling needs (:mod:`pii_guard.visual.labels`)."""
    if sam is None and ocr is None:
        raise DetectionError("no visual detector configured (need SAM and/or OCR)")
    if ocr is not None and not detectors:
        raise DetectionError("OCR configured without a text detector")
    try:
        decoded = load_image(bytes(image))
    except (ValueError, TypeError) as exc:
        raise DetectionError("image could not be decoded") from exc

    regions: list[Region] = []
    found: OcrText | None = None
    try:
        if sam is not None:
            regions.extend(sam.segment(image, entity_types))
        if ocr is not None:
            found = ocr_text(decoded, detectors, ocr=ocr, language=language, captions=captions)
            regions.extend(finding.region for finding in found.findings)
    except PiiGuardError:
        raise
    except Exception as exc:
        raise DetectionError(f"visual detection failed ({type(exc).__name__})") from exc
    return ImageAnalysis(regions, found)


def mask_visual(
    image: bytes,
    *,
    sam: SamClient | None = None,
    entity_types: Sequence[EntityType | str] | None = None,
    ocr: OcrEngine | None = None,
    detectors: Sequence[Detector] = (),
    language: str = "hu",
    captions: bool = True,
    fill: tuple[int, int, int] = DEFAULT_FILL,
    padding: int = 2,
    image_format: str = "PNG",
) -> VisualResult:
    """Detect (see :func:`analyze_image`) and cover every region with a solid fill."""
    regions = analyze_image(
        image,
        sam=sam,
        entity_types=entity_types,
        ocr=ocr,
        detectors=detectors,
        language=language,
        captions=captions,
    )
    masked = mask_image(image, regions, fill=fill, padding=padding, image_format=image_format)
    return VisualResult(masked, regions)
