"""Explicit limits on components that see original input (not the downstream model).

This is configuration enforcement for the supported built-ins, not a sandbox for arbitrary
Python extensions. Model provisioning is a separate operator action; inference does not fetch
missing weights in the local-only profile.
"""

from __future__ import annotations

from pathlib import Path

from pii_guard.config import Settings
from pii_guard.types import DetectionError


class DetectionProfileError(DetectionError):
    code = "detection_profile_denied"


def is_local_only(settings: Settings) -> bool:
    return settings.detection_profile == "local-only"


def refuse_remote(settings: Settings, component: str) -> None:
    if is_local_only(settings):
        raise DetectionProfileError(f"local-only detection profile does not permit {component}")


def require_detector(settings: Settings, name: str) -> None:
    if not is_local_only(settings):
        return
    if name not in {"rules", "ner"}:
        raise DetectionProfileError("local-only detection permits only built-in rules and NER")
    if name == "ner":
        require_local_model(settings.ner_model, settings.ner_backend)


def require_local_model(model: str | None, backend: str) -> None:
    if backend != "transformers" or not model or not Path(model).is_dir():
        raise DetectionProfileError(
            "local-only NER requires a provisioned local Transformers model directory; "
            "use DETECTORS=rules only when reduced coverage is deliberate"
        )
    if (Path(model) / "gliner_config.json").exists():
        raise DetectionProfileError("local-only NER currently supports Transformers checkpoints")


def require_segmenter_mode(settings: Settings, mode: str) -> None:
    if is_local_only(settings) and mode not in {"local", "off"}:
        raise DetectionProfileError(
            "local-only images require SEGMENTER=local or off; remote segmentation is refused"
        )


def require_segmenter_instance(settings: Settings, segmenter: object) -> None:
    if not is_local_only(settings):
        return
    from pii_guard.visual.segment import LocalSegmenter
    from pii_guard.visual.segmenters import OffSegmenter

    if type(segmenter) not in (LocalSegmenter, OffSegmenter):
        raise DetectionProfileError("local-only images require the built-in local segmenter")


def require_local_ocr(settings: Settings, ocr: object) -> None:
    if not is_local_only(settings):
        return
    from pii_guard.visual.ocr import TesseractOcr

    if not settings.image_require_ocr or type(ocr) is not TesseractOcr:
        raise DetectionProfileError("local-only images require the built-in local Tesseract OCR")


def require_detector_instance(settings: Settings, detector: object) -> None:
    """Validate supported cached detector trees before they receive original content."""
    if not is_local_only(settings):
        return
    from pii_guard.detect.ner import NerDetector
    from pii_guard.detect.pipeline import DetectionPipeline
    from pii_guard.detect.rules import RuleDetector
    from pii_guard.detect.stack import CheckedDetector
    from pii_guard.gateway.detection import _CheckedBatch, _Timed

    if type(detector) is RuleDetector:
        return
    if type(detector) is NerDetector:
        if not detector.local_files_only:
            raise DetectionProfileError("local-only cannot reuse NER with model downloads enabled")
        require_local_model(detector.model, detector.backend_kind)
        return
    if type(detector) is DetectionPipeline:
        for inner in detector.detectors:
            require_detector_instance(settings, inner)
        return
    if isinstance(detector, (CheckedDetector, _Timed)) and type(detector) in (
        CheckedDetector,
        _CheckedBatch,
        _Timed,
    ):
        require_detector_instance(settings, detector.inner)
        return
    raise DetectionProfileError("local-only requires built-in local detector instances")
