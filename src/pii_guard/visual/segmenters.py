"""Which segmenter finds faces, ID photos and signatures (``PII_GUARD_SEGMENTER``, LAB-1245).

Modes (:data:`SEGMENTER_MODES`):

- ``hybrid`` (default): :class:`HybridSegmenter`. ``FACE`` and ``ID_PHOTO`` on the CPU with
  YuNet (:class:`~pii_guard.visual.segment.LocalSegmenter`), everything else (``SIGNATURE``,
  and ``STAMP`` when its policy is not ``keep``) with SAM 3.1 on the Meta API. Two SAM calls per
  image with the default policies (``signature``, ``squiggly line``) instead of five. The image
  still leaves the machine for the signature prompts: a latency and cost win, not a privacy one.
- ``sam-api``: :class:`~pii_guard.visual.sam.SamClient` for every type (the previous default):
  one call per prompt, ``face``, ``signature``, ``squiggly line``, ``photo of a person``,
  ``stamp``.
- ``local``: :class:`~pii_guard.visual.segment.LocalSegmenter` only; nothing leaves the
  machine. It cannot find signatures, so with the default policies (``SIGNATURE`` is ``mask``)
  every image is refused (``detection_failed``); set ``SIGNATURE`` to ``keep`` to accept
  images with visible signatures.
- ``off``: :class:`OffSegmenter`, no segmentation; every image is refused, so nothing is
  returned with an unchecked face.

Fail closed (ADR 0006), decided once when the segmenter is built (:func:`build_segmenter`):

- ``hybrid`` without OpenCV or the YuNet model falls back to SAM for faces too, with a
  warning (still masked, so not a leak). With no SAM API key either, it raises.
- ``local`` without OpenCV or the model raises; it never falls back to the API.
- A failure while segmenting (SAM or YuNet) raises; no partial result is returned.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal, get_args

from pii_guard.config import Settings, get_settings
from pii_guard.policy import Policy
from pii_guard.types import DetectionError, EntityType
from pii_guard.visual.regions import Region
from pii_guard.visual.sam import SamClient
from pii_guard.visual.segment import LOCAL_ENTITY_TYPES, LocalSegmenter, Segmenter

__all__ = [
    "SEGMENTER_MODES",
    "VISUAL_ENTITY_TYPES",
    "HybridSegmenter",
    "OffSegmenter",
    "SegmenterMode",
    "build_segmenter",
    "default_entity_types",
    "sam_calls",
]

logger = logging.getLogger(__name__)

SegmenterMode = Literal["hybrid", "sam-api", "local", "off"]
SEGMENTER_MODES: tuple[str, ...] = get_args(SegmenterMode)

#: Every visual type, in the order they are segmented.
VISUAL_ENTITY_TYPES: tuple[EntityType, ...] = (
    EntityType.FACE,
    EntityType.SIGNATURE,
    EntityType.ID_PHOTO,
    EntityType.STAMP,
)


class HybridSegmenter:
    """``FACE`` / ``ID_PHOTO`` with ``local``, every other requested type with ``sam``.

    ``local=None`` sends everything to SAM (the fallback when YuNet is unavailable). The two
    run concurrently; either failing raises (no partial result).
    """

    name = "hybrid"

    def __init__(self, *, sam: SamClient, local: Segmenter | None) -> None:
        self.sam = sam
        self.local = local
        self.local_types: tuple[EntityType, ...] = LOCAL_ENTITY_TYPES if local is not None else ()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pii-guard-yunet")

    @property
    def model(self) -> str:
        local = getattr(self.local, "model", None) if self.local is not None else None
        return f"{local}+{self.sam.model}" if local else self.sam.model

    @property
    def prompts(self) -> dict[EntityType, tuple[str, ...]]:
        """SAM's prompts for the types it is sent (``FACE`` / ``ID_PHOTO`` go to YuNet)."""
        return {t: p for t, p in self.sam.prompts.items() if t not in self.local_types}

    def __repr__(self) -> str:
        return f"HybridSegmenter(local={self.local!r}, sam={self.sam!r})"

    def split(
        self, entity_types: Sequence[EntityType | str] | None
    ) -> tuple[list[EntityType], list[EntityType]]:
        """(types for YuNet, types for SAM)."""
        types = [EntityType(t) for t in (entity_types or VISUAL_ENTITY_TYPES[:3])]
        local = [t for t in types if t in self.local_types]
        return local, [t for t in types if t not in self.local_types]

    def segment(
        self, image: bytes, entity_types: Sequence[EntityType | str] | None = None
    ) -> list[Region]:
        local_types, sam_types = self.split(entity_types)
        future = (
            self._pool.submit(self.local.segment, image, local_types)
            if local_types and self.local is not None
            else None
        )
        try:
            remote = self.sam.segment(image, sam_types) if sam_types else []
        finally:
            local = future.result() if future is not None else []  # raises its error
        return local + remote


class OffSegmenter:
    """``PII_GUARD_SEGMENTER=off``: refuses every image (fail closed, ADR 0006)."""

    name = "off"
    model = "off"
    prompts: dict[EntityType, tuple[str, ...]] = {}  # noqa: RUF012 - read-only

    def __repr__(self) -> str:
        return "OffSegmenter()"

    def segment(
        self, image: bytes, entity_types: Sequence[EntityType | str] | None = None
    ) -> list[Region]:
        raise DetectionError("image segmentation is off (PII_GUARD_SEGMENTER=off)")


def default_entity_types(
    segmenter: Any, policy_of: Callable[[EntityType], Policy]
) -> list[EntityType]:
    """The visual types an image masker asks ``segmenter`` for.

    :class:`~pii_guard.visual.sam.SamClient` (``sam-api``): every type it has a prompt for,
    so ``keep`` types (``STAMP``) are found and reported, as before LAB-1245. Every other
    segmenter: every visual type whose policy is not ``keep``. A ``keep`` region would be left
    visible anyway, so it is not worth a SAM call; a ``mask`` / ``block`` type the segmenter
    cannot find (``SIGNATURE`` with ``local``) is still asked for, so it raises.
    """
    if isinstance(segmenter, SamClient):
        return list(segmenter.prompts)
    return [t for t in VISUAL_ENTITY_TYPES if policy_of(t) is not Policy.KEEP]


def sam_calls(segmenter: Any, entity_types: Sequence[EntityType]) -> int:
    """How many SAM API requests one image costs with ``segmenter`` and ``entity_types``."""
    if isinstance(segmenter, HybridSegmenter):
        _, sam_types = segmenter.split(entity_types)
        return sum(len(segmenter.sam.prompts.get(t, ())) for t in sam_types)
    if isinstance(segmenter, SamClient):
        return sum(len(segmenter.prompts.get(t, ())) for t in entity_types)
    return 0


def build_segmenter(
    settings: Settings | None = None,
    *,
    mode: str | None = None,
    local: Callable[[], Segmenter] = LocalSegmenter,
) -> Segmenter:
    """The segmenter for ``mode`` (default ``settings.segmenter``); see the module docstring.

    ``local`` builds the on-device segmenter (default :class:`LocalSegmenter`), for tests.
    Raises :class:`DetectionError` when the mode cannot work at all.
    """
    settings = settings or get_settings()
    mode = mode or settings.segmenter
    if mode not in SEGMENTER_MODES:
        raise ValueError(f"segmenter must be one of: {', '.join(SEGMENTER_MODES)}")
    if mode == "off":
        logger.warning("image segmentation is off (PII_GUARD_SEGMENTER=off): images are refused")
        return OffSegmenter()
    if mode == "local":
        return local()
    sam = SamClient(settings=settings)
    if mode == "sam-api":
        return sam
    try:
        on_device: Segmenter | None = local()
    except DetectionError as exc:
        if not sam.configured:
            raise DetectionError(
                "hybrid segmenter: on-device face detection is unavailable "
                f"({exc.message}) and SAM has no API key"
            ) from exc
        logger.warning(
            "hybrid segmenter: on-device face detection unavailable (%s); faces and ID photos "
            "go to SAM 3.1 too",
            exc.message,
        )
        on_device = None
    return HybridSegmenter(sam=sam, local=on_device)
