"""Explicit limits on components that see original input (not the downstream model).

This is configuration enforcement for the supported built-ins, not a sandbox for arbitrary
Python extensions. Model provisioning is a separate operator action; inference does not fetch
missing weights in the local-only profile.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

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


#: Host suffixes of names that resolve only inside the operator's own network.
_PRIVATE_SUFFIXES = (".local", ".internal", ".lan", ".home.arpa", ".svc", ".cluster.local")


def is_self_hosted_url(url: str | None) -> bool:
    """Whether ``url`` names an endpoint on the operator's own network (LAB-1796).

    True for ``localhost``, loopback, private and link-local IP literals, single-label names
    (a compose or Kubernetes service such as ``http://muse:8000``) and names under
    :data:`_PRIVATE_SUFFIXES`. Anything else, including every public provider, is remote.
    """
    if not url:
        return False
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return False
    if not host:
        return False
    host = host.rstrip(".").lower()
    if host == "localhost" or ("." not in host and ":" not in host):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host.endswith(_PRIVATE_SUFFIXES)
    return address.is_loopback or address.is_private or address.is_link_local


def refuse_remote_ocr(settings: Settings, url: str | None) -> None:
    """Refuse Muse Spark Open OCR in the local-only profile unless ``url`` is self-hosted
    (:func:`is_self_hosted_url`): the OCR endpoint sees the unmasked image."""
    if is_local_only(settings) and not is_self_hosted_url(url):
        raise DetectionProfileError(
            "local-only detection profile does not permit remote OCR (Muse Spark Open); set "
            "PII_GUARD_OCR_URL to a self-hosted endpoint or PII_GUARD_OCR_ENGINE=tesseract"
        )


def require_local_ocr(settings: Settings, ocr: object) -> None:
    if not is_local_only(settings):
        return
    from pii_guard.visual.ocr import TesseractOcr
    from pii_guard.visual.ocr_muse import MuseOcr

    if not settings.image_require_ocr:
        raise DetectionProfileError("local-only images require OCR")
    if type(ocr) is TesseractOcr:
        return
    if type(ocr) is MuseOcr and is_self_hosted_url(ocr.url):
        return
    raise DetectionProfileError(
        "local-only images require the built-in Tesseract OCR or Muse Spark Open OCR on a "
        "self-hosted PII_GUARD_OCR_URL"
    )


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
