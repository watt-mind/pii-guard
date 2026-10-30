"""Hosted image masking (LAB-1390, ADR 0014): local-only, in memory, bounded, owner-scoped.

What differs from the self-hosted ``POST /v1/mask/image`` is decided here and nowhere else:

- the segmenter is always the on-device
  :class:`~pii_guard.visual.segmenters.LocalSignatureSegmenter` (YuNet for faces and ID photos,
  the pinned YOLOS-tiny detector for signatures, both on the CPU), and OCR is always the
  built-in Tesseract; no SAM, no remote detector, whatever ``PII_GUARD_SEGMENTER`` or an
  embedder put on ``app.state`` says;
- the owner's project policy decides text and visual actions (``FACE``, ``ID_PHOTO``,
  ``SIGNATURE``, ``STAMP``, LAB-1444); the operator's ``PII_GUARD_POLICY_OVERRIDES`` win when
  stricter, and versions saved before visual actions existed take the server's. A policy with
  ``visual_detection: sam``, or one that masks ``STAMP`` (which nothing local can find), is
  refused before any work (fail closed, ADR 0006);
- one image job per replica at a time: a busy slot is ``429 hosted_capacity``, never a queue;
- the decoded pixel cap is the lower of ``image_max_pixels`` and ``hosted_image_max_pixels``,
  and the deadline the lower of ``image_timeout`` and ``hosted_image_timeout``.

Admission (signed-in Google owner, same origin, the per-owner daily image count reserved
before the body is read) lives in :mod:`pii_guard.hosted.middleware`.

Inline images in hosted chat (``/v1/chat/completions`` and ``/v1/responses``, LAB-1439) are
opt-in (``PII_GUARD_HOSTED_CHAT_IMAGES``) and use the same local-only pipeline and the same
one-job pool. They go only to the owner's own connection, never the sponsored route, and
each one reserves a fixed provider input charge (``hosted_image_input_tokens``) plus room
for its masked transcript; the text token bound never covers image bytes.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Mapping
from typing import Any

from pii_guard.config import Settings
from pii_guard.detection_profile import DetectionProfileError
from pii_guard.hosted.runtime import HostedCapacityError
from pii_guard.policy import Policy, PolicySet
from pii_guard.projects.visual import effective_policies, visual_detection
from pii_guard.types import DetectionError, EntityType, PiiGuardError
from pii_guard.visual.masking import OcrUnavailableError, default_ocr_engine
from pii_guard.visual.ocr import OcrEngine, TesseractOcr
from pii_guard.visual.segment import LocalSegmenter
from pii_guard.visual.segmenters import (
    LOCAL_SIGNATURE_TYPES,
    VISUAL_ENTITY_TYPES,
    LocalSignatureSegmenter,
    build_segmenter,
)

__all__ = [
    "IMAGE_ANNOTATION_BYTES",
    "IMAGE_COMPUTE_TOKENS",
    "IMAGE_PATH",
    "ChatImageCharge",
    "chat_body_limit",
    "chat_image_charge",
    "chat_images_enabled",
    "count_chat_images",
    "hosted_image_limits",
    "hosted_visual_policies",
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
#: The masked transcript and summary text part the gateway adds after each chat image. It is
#: text sent upstream, so it is part of the payload bound and of the input token charge; a
#: longer one makes the gateway refuse the request (413) rather than send it.
IMAGE_ANNOTATION_BYTES = 32_768
#: The JSON around one inline image part (``{"type": ..., "image_url": {"url": "data:..."}}``).
_IMAGE_PART_OVERHEAD_BYTES = 256
_CHAT_PATHS = frozenset({"/v1/chat/completions", "/v1/responses"})
_lock = threading.Lock()


def image_body_limit(settings: Settings) -> int:
    """The most bytes the hosted ingress reads for an image request: base64 in JSON."""
    return math.ceil(settings.hosted_max_image_bytes / 3) * 4 + _JSON_OVERHEAD_BYTES


def chat_images_enabled(settings: Settings) -> bool:
    """Whether the operator offers inline images in hosted chat (both switches on)."""
    return bool(settings.hosted_images and settings.hosted_chat_images)


def chat_body_limit(settings: Settings) -> int:
    """The most bytes hosted chat reads with images on: the text limit plus base64 images.

    A body without an image part is still held to ``hosted_max_body_bytes`` once parsed."""
    per_image = math.ceil(settings.hosted_max_image_bytes / 3) * 4 + _IMAGE_PART_OVERHEAD_BYTES
    return settings.hosted_max_body_bytes + settings.hosted_chat_max_images * per_image


def count_chat_images(canonical: str, body: dict[str, Any]) -> tuple[int, int]:
    """``(images, base64 bytes)`` of the inline images in a chat or Responses body.

    The byte count is the base64 length of the decoded images, never more than their data
    URLs take in the body, so ``len(body) - bytes`` over-counts the text: conservative."""
    from pii_guard.gateway.request import collect_texts
    from pii_guard.gateway.responses_request import collect_response_texts

    if canonical not in _CHAT_PATHS:
        return 0, 0
    collect = collect_response_texts if canonical == "/v1/responses" else collect_texts
    images = collect(body).images
    return len(images), sum(math.ceil(len(image.data) / 3) * 4 for image in images)


class ChatImageCharge:
    """What one hosted chat request with ``images`` inline images is admitted for.

    ``payload_bytes`` bounds the masked upstream payload without the masked images' own data
    URLs (the gateway leaves those out of its check); ``input_tokens`` is that bound plus a
    fixed provider charge per image, so image input is never paid from the text bound."""

    __slots__ = ("images", "input_tokens", "payload_bytes")

    def __init__(self, images: int, payload_bytes: int, input_tokens: int) -> None:
        self.images, self.payload_bytes, self.input_tokens = images, payload_bytes, input_tokens


def chat_image_charge(settings: Settings, images: int, text_payload_bound: int) -> ChatImageCharge:
    """The charge for ``images`` inline images on top of the text's payload bound."""
    payload = text_payload_bound + images * IMAGE_ANNOTATION_BYTES
    return ChatImageCharge(images, payload, payload + images * settings.hosted_image_input_tokens)


def hosted_image_limits(settings: Settings) -> tuple[int, float]:
    """``(max_pixels, timeout)`` for one hosted image: the lower of each pair of settings."""
    return (
        min(settings.image_max_pixels, settings.hosted_image_max_pixels),
        min(settings.image_timeout, settings.hosted_image_timeout),
    )


def local_segmenter(state: Any) -> LocalSignatureSegmenter:
    """The app's segmenter, which on hosted must be the built-in on-device one.

    Built once with ``mode="local"`` (never from ``PII_GUARD_SEGMENTER``) and paired with the
    on-device signature detector; a bare :class:`LocalSegmenter` on ``app.state.sam_client`` is
    paired the same way. Anything else (a SAM client, a hybrid, an embedder's object) is
    refused rather than used, so a remote call cannot be configured in by accident."""
    segmenter = getattr(state, "sam_client", None)
    if segmenter is None or type(segmenter) is LocalSegmenter:
        with _lock:
            segmenter = getattr(state, "sam_client", None)
            if segmenter is None:
                segmenter = build_segmenter(state.settings, mode="local")
            if type(segmenter) is LocalSegmenter:
                segmenter = LocalSignatureSegmenter(segmenter)
                state.sam_client = segmenter
    if type(segmenter) is not LocalSignatureSegmenter or type(segmenter.local) is not (
        LocalSegmenter
    ):
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
    """Readiness: OCR and the on-device segmenter both work, or this replica is not ready.

    The signature detector is loaded too while the server's own policies mask signatures
    (the default), so a replica without it is not admitted."""
    local_ocr(state)
    try:
        segmenter = local_segmenter(state)
        policies = getattr(state, "policies", None)
        if policies is None or policies.of(EntityType.SIGNATURE) is not Policy.KEEP:
            segmenter.signatures()
    except PiiGuardError:
        raise
    except Exception:  # an unexpected build failure is still "not ready", never a 500
        raise DetectionError("the on-device segmenter could not be built") from None


def hosted_visual_policies(
    policy: Mapping[str, Any] | None, project: PolicySet, settings: Settings, server: PolicySet
) -> PolicySet:
    """The owner's policy with the operator's stricter visual overrides folded in."""
    return effective_policies(policy, project, server, settings.policy_overrides)


def unservable_visual_types(policies: PolicySet) -> list[str]:
    """Visual types ``policies`` masks or blocks that on-device detection cannot find."""
    return [
        t.value
        for t in VISUAL_ENTITY_TYPES
        if t not in LOCAL_SIGNATURE_TYPES and policies.of(t) is not Policy.KEEP
    ]


def require_local_visual_policies(
    policies: PolicySet, policy: Mapping[str, Any] | None = None
) -> None:
    """Refuse, before any work, an image whose policy needs a remote segmenter.

    On-device detection finds faces, ID photos and signatures. ``visual_detection: sam`` is
    not offered on hosted yet (it needs its own spend reservation, LAB-1444 follow-up), and a
    ``mask`` or ``block`` stamp would otherwise fail inside the worker after the upload was
    decoded; here both fail first and say why."""
    if visual_detection(policy) != "local":
        raise DetectionProfileError(
            "hosted images use on-device detection only; SAM 3.1 detection is not available "
            "on the hosted service, so choose on-device detection in this policy"
        )
    remote = unservable_visual_types(policies)
    if remote:
        raise DetectionProfileError(
            "hosted images are processed on this server only, and on-device detection "
            f"cannot find {', '.join(remote)}, which this policy masks; images are refused"
        )


def require_image_capacity(workers: Any) -> None:
    """One image job per replica: a busy (or still-finishing, timed-out) slot is a 429."""
    if workers.running >= workers.size:
        raise HostedCapacityError("Image capacity reached; try again shortly")
