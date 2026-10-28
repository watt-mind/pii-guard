"""Hosted image masking (LAB-1390, ADR 0014): local-only, in memory, bounded, owner-scoped.

What differs from the self-hosted ``POST /v1/mask/image`` is decided here and nowhere else:

- the segmenter is always the on-device :class:`~pii_guard.visual.segment.LocalSegmenter`
  (YuNet on the CPU), and OCR is always the built-in Tesseract; no SAM, no remote detector,
  whatever ``PII_GUARD_SEGMENTER`` or an embedder put on ``app.state`` says;
- visual policies (``FACE``, ``SIGNATURE``, ``ID_PHOTO``, ``STAMP``) are the operator's
  (``PII_GUARD_POLICY_OVERRIDES``), text policies the owner's project's: projects hold text
  types only. The local segmenter cannot find signatures or stamps, so while the server masks
  them every image is refused before any work (fail closed, ADR 0006) and ``images`` is not
  offered; the deployment opts in to visible signatures with ``SIGNATURE=keep``;
- one image job per replica at a time: a busy slot is ``429 hosted_capacity``, never a queue;
- the decoded pixel cap is the lower of ``image_max_pixels`` and ``hosted_image_max_pixels``,
  and the deadline the lower of ``image_timeout`` and ``hosted_image_timeout``.

Admission (signed-in Google owner, same origin, the per-owner daily image count reserved
before the body is read) lives in :mod:`pii_guard.hosted.middleware`.
"""

from __future__ import annotations

import math
import threading
from typing import Any

from pii_guard.config import Settings
from pii_guard.detection_profile import DetectionProfileError
from pii_guard.hosted.runtime import HostedCapacityError
from pii_guard.policy import Policy, PolicySet
from pii_guard.types import DetectionError, PiiGuardError
from pii_guard.visual.masking import OcrUnavailableError, default_ocr_engine
from pii_guard.visual.ocr import OcrEngine, TesseractOcr
from pii_guard.visual.segment import LOCAL_ENTITY_TYPES, LocalSegmenter
from pii_guard.visual.segmenters import VISUAL_ENTITY_TYPES, build_segmenter

__all__ = [
    "IMAGE_COMPUTE_TOKENS",
    "IMAGE_PATH",
    "hosted_image_limits",
    "hosted_image_policies",
    "image_body_limit",
    "local_ocr",
    "local_segmenter",
    "require_image_capacity",
    "require_image_pipeline",
    "require_local_visual_policies",
    "unservable_visual_types",
]

#: The one hosted image route. ``/e/<endpoint>/...`` (endpoint keys) is not admitted.
IMAGE_PATH = "/v1/mask/image"
#: What one image costs against the owner's daily compute-token allowance, on top of the
#: separate image count. A fixed charge: the body size would charge megabytes as tokens.
IMAGE_COMPUTE_TOKENS = 16_384
#: Room for the JSON fields around a base64 image (language, session_id, render, expiry).
_JSON_OVERHEAD_BYTES = 16_384
_lock = threading.Lock()


def image_body_limit(settings: Settings) -> int:
    """The most bytes the hosted ingress reads for an image request: base64 in JSON."""
    return math.ceil(settings.hosted_max_image_bytes / 3) * 4 + _JSON_OVERHEAD_BYTES


def hosted_image_limits(settings: Settings) -> tuple[int, float]:
    """``(max_pixels, timeout)`` for one hosted image: the lower of each pair of settings."""
    return (
        min(settings.image_max_pixels, settings.hosted_image_max_pixels),
        min(settings.image_timeout, settings.hosted_image_timeout),
    )


def local_segmenter(state: Any) -> LocalSegmenter:
    """The app's segmenter, which on hosted must be the built-in on-device one.

    Built once with ``mode="local"`` (never from ``PII_GUARD_SEGMENTER``). Anything else on
    ``app.state.sam_client`` (a SAM client, a hybrid, an embedder's object) is refused rather
    than used, so a remote call cannot be configured in by accident."""
    segmenter = getattr(state, "sam_client", None)
    if segmenter is None:
        with _lock:
            segmenter = getattr(state, "sam_client", None)
            if segmenter is None:
                segmenter = build_segmenter(state.settings, mode="local")
                state.sam_client = segmenter
    if type(segmenter) is not LocalSegmenter:
        raise DetectionProfileError("hosted images require the built-in on-device segmenter")
    return segmenter


def local_ocr(state: Any) -> OcrEngine:
    """The app's OCR engine, which on hosted must be the built-in Tesseract, and present."""
    if not hasattr(state, "ocr_engine"):
        state.ocr_engine = default_ocr_engine()
    ocr = state.ocr_engine
    if ocr is None:
        raise OcrUnavailableError(
            "no OCR engine on this server, so the text in an image can't be checked"
        )
    if type(ocr) is not TesseractOcr:
        raise DetectionProfileError("hosted images require the built-in local Tesseract OCR")
    return ocr


def require_image_pipeline(state: Any) -> None:
    """Readiness: OCR and the on-device segmenter both work, or this replica is not ready."""
    local_ocr(state)
    try:
        local_segmenter(state)
    except PiiGuardError:
        raise
    except Exception:  # an unexpected build failure is still "not ready", never a 500
        raise DetectionError("the on-device segmenter could not be built") from None


def hosted_image_policies(project: PolicySet, server: PolicySet) -> PolicySet:
    """The project's text policies with the server's visual ones (projects hold text only)."""
    visual = set(VISUAL_ENTITY_TYPES)
    return PolicySet({t: (server if t in visual else project).of(t) for t in project.as_mapping()})


def unservable_visual_types(policies: PolicySet) -> list[str]:
    """Visual types ``policies`` masks or blocks that the on-device segmenter cannot find."""
    return [
        t.value
        for t in VISUAL_ENTITY_TYPES
        if t not in LOCAL_ENTITY_TYPES and policies.of(t) is not Policy.KEEP
    ]


def require_local_visual_policies(policies: PolicySet) -> None:
    """Refuse, before any work, an image whose policy needs a type only SAM could find.

    The on-device segmenter finds faces and ID photos. A ``mask`` or ``block`` signature or
    stamp would otherwise fail inside the worker after the upload was decoded; here it fails
    first and says why."""
    remote = unservable_visual_types(policies)
    if remote:
        raise DetectionProfileError(
            "hosted images are processed on this server only, and its on-device segmenter "
            f"cannot find {', '.join(remote)}, which this server masks; images are refused"
        )


def require_image_capacity(workers: Any) -> None:
    """One image job per replica: a busy (or still-finishing, timed-out) slot is a 429."""
    if workers.running >= workers.size:
        raise HostedCapacityError("Image capacity reached; try again shortly")
