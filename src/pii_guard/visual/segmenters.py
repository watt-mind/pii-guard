"""Which segmenter finds faces, ID photos and signatures (``PII_GUARD_SEGMENTER``, LAB-1245).

Modes (:data:`SEGMENTER_MODES`):

- ``hybrid`` (default): :class:`HybridSegmenter`. ``FACE`` and ``ID_PHOTO`` on the CPU with
  YuNet (:class:`~pii_guard.visual.segment.LocalSegmenter`), everything else (``SIGNATURE``,
  and ``STAMP`` when its policy is not ``keep``) with SAM 3.1 on the Meta API (or the on-device
  YOLOS-tiny :class:`SignatureDetector` for ``SIGNATURE`` when ``META_API_KEY`` is not set).
  Two SAM calls per image with the default policies (``signature``, ``squiggly line``) instead
  of five. The image still leaves the machine for the signature prompts when SAM is configured:
  a latency and cost win, not a privacy one.
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

Per-policy detection (LAB-1444): a project policy's ``visual_detection`` picks the segmenter
for its images (:func:`policy_segmenter`, :data:`VISUAL_DETECTIONS`):

- ``local`` (the default): :class:`LocalSignatureSegmenter`, YuNet for faces and ID photos and
  the pinned YOLOS-tiny signature detector (:class:`SignatureDetector`) for signatures, both on
  the CPU; nothing leaves the machine. Stamps cannot be found locally, so a policy that masks
  ``STAMP`` is refused.
- ``sam``: the server's segmenter (``hybrid`` by default: local faces, SAM 3.1 for signatures
  and stamps). A server that is stricter (``local`` or ``off``) wins: the policy never turns
  egress on.

Get the signature detector once (pinned Hugging Face revision, SHA-256 checked)::

    uv run python -m pii_guard.visual.segmenters fetch
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal, get_args

from pii_guard.config import Settings, get_settings
from pii_guard.detection_profile import require_segmenter_mode
from pii_guard.policy import Policy
from pii_guard.types import DetectionError, EntityType
from pii_guard.visual.image import load_image
from pii_guard.visual.regions import Box, Region
from pii_guard.visual.sam import SamClient
from pii_guard.visual.segment import (
    LOCAL_ENTITY_TYPES,
    MODEL_DIR_ENV_VAR,
    LocalSegmenter,
    ModelFile,
    Segmenter,
    _sha256,
    fetch_model,
    model_dir,
    nms,
)

__all__ = [
    "LOCAL_SIGNATURE_TYPES",
    "SEGMENTER_MODES",
    "SIGNATURE_DETECTOR",
    "SIGNATURE_DETECTOR_DIR",
    "VISUAL_DETECTIONS",
    "VISUAL_ENTITY_TYPES",
    "HybridSegmenter",
    "LocalSignatureSegmenter",
    "OffSegmenter",
    "SegmenterMode",
    "SignatureDetector",
    "VisualDetection",
    "build_segmenter",
    "default_entity_types",
    "fetch_signature_detector",
    "policy_segmenter",
    "sam_calls",
]

logger = logging.getLogger(__name__)

SegmenterMode = Literal["hybrid", "sam-api", "local", "off"]
SEGMENTER_MODES: tuple[str, ...] = get_args(SegmenterMode)

#: A project policy's ``visual_detection`` (LAB-1444); ``local`` is the default.
VisualDetection = Literal["local", "sam"]
VISUAL_DETECTIONS: tuple[str, ...] = get_args(VisualDetection)

#: Every visual type, in the order they are segmented.
VISUAL_ENTITY_TYPES: tuple[EntityType, ...] = (
    EntityType.FACE,
    EntityType.SIGNATURE,
    EntityType.ID_PHOTO,
    EntityType.STAMP,
)


class HybridSegmenter:
    """``FACE`` / ``ID_PHOTO`` with ``local``, every other requested type with ``sam``.

    ``local=None`` sends everything to SAM (the fallback when YuNet is unavailable). When
    ``sam`` has no API key configured and ``local`` is available, ``SIGNATURE`` falls back to
    the on-device :class:`SignatureDetector` so ``pii-guard up`` and ``pii-guard run`` work out
    of the box without ``META_API_KEY``. The two run concurrently; either failing raises (no
    partial result).
    """

    name = "hybrid"

    def __init__(
        self,
        *,
        sam: SamClient,
        local: Segmenter | None,
        signatures: Callable[[], Segmenter] | None = None,
    ) -> None:
        self.sam = sam
        self.local = local
        self.local_types: tuple[EntityType, ...] = LOCAL_ENTITY_TYPES if local is not None else ()
        self._build_signatures: Callable[[], Segmenter] = signatures or SignatureDetector
        self._signatures: Segmenter | None = None
        self._sig_lock = threading.Lock()
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

    def signatures(self) -> Segmenter:
        """The on-device signature detector, built lazily when ``sam`` has no API key."""
        if self._signatures is None:
            with self._sig_lock:
                if self._signatures is None:
                    self._signatures = self._build_signatures()
        return self._signatures

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
            if not sam_types:
                remote: list[Region] = []
            elif (
                not self.sam.configured
                and self.local is not None
                and set(sam_types) <= {EntityType.SIGNATURE}
            ):
                remote = self.signatures().segment(image, sam_types)
            else:
                remote = self.sam.segment(image, sam_types)
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


# --- On-device signatures (LAB-1444) -------------------------------------------------------

_HF = "https://huggingface.co/mdefrance/yolos-tiny-signature-detection/resolve"
_REVISION = "b788cf7376464453c3dea1e5ee8589adcaa0c634"
#: The pinned YOLOS-tiny signature detector (``mdefrance/yolos-tiny-signature-detection``,
#: Apache-2.0, 26 MB): its three files at one Hugging Face revision, each SHA-256 checked.
#: Weights are safetensors only; a pickled checkpoint is never loaded (LAB-1304).
SIGNATURE_DETECTOR: tuple[ModelFile, ...] = (
    ModelFile(
        "config.json",
        f"{_HF}/{_REVISION}/config.json",
        "081cca4b52b6c79d2ead6b5d9acc1c0cc04bd127758a95264ed5c305d8d53b58",
        825,
        "Apache-2.0",
    ),
    ModelFile(
        "preprocessor_config.json",
        f"{_HF}/{_REVISION}/preprocessor_config.json",
        "2723351e75bfcfb9a47656a8b46e259e3649ae7b2545c9deb2ce8a0f3a840d18",
        441,
        "Apache-2.0",
    ),
    ModelFile(
        "model.safetensors",
        f"{_HF}/{_REVISION}/model.safetensors",
        "fe95c5b4651a826f2ce3e4fb21e62445f943eac34950ba87abe5e9e3602b3897",
        25_909_400,
        "Apache-2.0",
    ),
)
#: Where the detector's files live under :func:`~pii_guard.visual.segment.model_dir`.
SIGNATURE_DETECTOR_DIR = "yolos-tiny-signature"
#: The types :class:`LocalSignatureSegmenter` finds.
LOCAL_SIGNATURE_TYPES: tuple[EntityType, ...] = (*LOCAL_ENTITY_TYPES, EntityType.SIGNATURE)


def fetch_signature_detector(directory: Path | None = None, **kwargs: Any) -> Path:
    """Download the pinned signature detector into ``directory`` (default
    ``model_dir() / SIGNATURE_DETECTOR_DIR``), SHA-256 checked; returns the directory."""
    directory = directory or model_dir() / SIGNATURE_DETECTOR_DIR
    for model in SIGNATURE_DETECTOR:
        fetch_model(model, directory, **kwargs)
    return directory


def _yolos(  # pragma: no cover - needs torch, transformers and the pinned files
    path: Path, threshold: Callable[[], float]
) -> Callable[[Any], list[tuple[float, float, float, float, float]]]:
    """The YOLOS model as a box function, loaded offline from ``path`` (already verified)."""
    try:
        import torch
        from transformers import AutoImageProcessor, AutoModelForObjectDetection
        from transformers.utils import logging as hf_logging
    except ImportError as exc:
        from pii_guard.detect.stack import no_torch_build

        where = (
            "PyTorch has no Intel macOS build; run the Docker demo for images"
            if no_torch_build()
            else "part of the default install; the rules-only base Docker image skips them"
        )
        raise DetectionError(
            f"the signature detector needs torch and transformers ({where})"
        ) from exc
    with contextlib.suppress(Exception):
        hf_logging.disable_progress_bar()
    try:
        processor = AutoImageProcessor.from_pretrained(str(path), local_files_only=True)
        network = AutoModelForObjectDetection.from_pretrained(
            str(path), local_files_only=True, use_safetensors=True
        ).eval()
    except Exception as exc:
        raise DetectionError("the signature detector could not be loaded") from exc

    def run(image: Any) -> list[tuple[float, float, float, float, float]]:
        inputs = processor(images=image, return_tensors="pt")
        with torch.no_grad():
            out = network(**inputs)
        found = processor.post_process_object_detection(
            out, threshold=threshold(), target_sizes=[(image.height, image.width)]
        )[0]
        out_boxes: list[tuple[float, float, float, float, float]] = []
        for box, score in zip(found["boxes"], found["scores"], strict=True):
            x1, y1, x2, y2 = (float(v) for v in box.tolist())
            out_boxes.append((x1, y1, x2, y2, float(score)))
        return out_boxes

    return run


class SignatureDetector:
    """Signature boxes from the pinned YOLOS-tiny detector, on the CPU.

    Runs on the whole image and on 2x2 overlapping tiles (signatures are small on a full ID
    card), merged by non-maximum suppression; the setting measured as ``small-detectors`` in
    the segment eval (LAB-1229). Loaded offline from ``model_path`` (default
    ``model_dir() / SIGNATURE_DETECTOR_DIR``) after every file's SHA-256 matches
    :data:`SIGNATURE_DETECTOR`. ``boxes`` replaces the model with a callable
    ``(PIL image) -> [(x1, y1, x2, y2, score)]``, for tests (no torch, no files).

    Fail closed: missing torch/transformers, a missing or mismatched file, an undecodable
    image and any inference error raise :class:`DetectionError`.
    """

    name = "signature"
    model = "yolos-tiny-signature"

    def __init__(
        self,
        *,
        model_path: str | Path | None = None,
        score_threshold: float = 0.5,
        grid: int = 2,
        boxes: Callable[[Any], list[tuple[float, float, float, float, float]]] | None = None,
    ) -> None:
        if not 0.0 < score_threshold < 1.0:
            raise ValueError("score_threshold must be in (0, 1)")
        self.score_threshold = score_threshold
        self.grid = grid
        self._lock = threading.Lock()
        if boxes is not None:
            self._boxes = boxes
            return
        path = Path(model_path) if model_path else model_dir() / SIGNATURE_DETECTOR_DIR
        if (
            model_path is None
            and not os.environ.get(MODEL_DIR_ENV_VAR)
            and not all((path / m.filename).is_file() for m in SIGNATURE_DETECTOR)
        ):
            with contextlib.suppress(Exception):
                fetch_signature_detector(path)
        for model in SIGNATURE_DETECTOR:
            file = path / model.filename
            if not file.is_file():
                raise DetectionError(
                    f"signature detector file {model.filename} is missing "
                    "(uv run python -m pii_guard.visual.segmenters fetch)"
                )
            if _sha256(file) != model.sha256:
                raise DetectionError(f"signature detector file {model.filename}: SHA-256 mismatch")
        self._boxes = _yolos(path, lambda: self.score_threshold)

    def __repr__(self) -> str:
        return f"SignatureDetector(model={self.model!r}, score_threshold={self.score_threshold})"

    def segment(
        self, image: bytes, entity_types: Sequence[EntityType | str] | None = None
    ) -> list[Region]:
        types = [EntityType(t) for t in (entity_types or (EntityType.SIGNATURE,))]
        unsupported = [t.value for t in types if t is not EntityType.SIGNATURE]
        if unsupported:
            raise DetectionError(f"signature detector cannot find {', '.join(unsupported)}")
        try:
            decoded = load_image(bytes(image)).convert("RGB")
        except (ValueError, TypeError) as exc:
            raise DetectionError("image could not be decoded for segmentation") from exc
        width, height = decoded.size
        try:
            with self._lock:
                found = list(self._boxes(decoded))
                tw, th = width / self.grid, height / self.grid
                for i in range(self.grid):
                    for j in range(self.grid):
                        x0, y0 = max(0, int((i - 0.25) * tw)), max(0, int((j - 0.25) * th))
                        x1 = min(width, int((i + 1.25) * tw))
                        y1 = min(height, int((j + 1.25) * th))
                        for a, b, c, d, s in self._boxes(decoded.crop((x0, y0, x1, y1))):
                            found.append((a + x0, b + y0, c + x0, d + y0, s))
        except DetectionError:
            raise
        except Exception as exc:
            raise DetectionError(f"signature detection failed ({type(exc).__name__})") from exc
        regions: list[Region] = []
        for a, b, c, d, s in nms(found, 0.5):
            left, top = max(0, int(a)), max(0, int(b))
            right, bottom = min(width - 1, round(c)), min(height - 1, round(d))
            if right > left and bottom > top:
                box = Box(left, top, right, bottom)
                regions.append(Region(EntityType.SIGNATURE, box, round(min(1.0, s), 4), "yolos"))
        logger.debug("signature detector: %d signature(s)", len(regions))
        return regions


class LocalSignatureSegmenter:
    """``visual_detection: local``: faces and ID photos with YuNet, signatures with YOLOS-tiny.

    Everything runs on the CPU; nothing leaves the machine. The signature detector is built
    on the first image that asks for ``SIGNATURE`` (``signatures`` builds it, default
    :class:`SignatureDetector`), so a deployment that keeps signatures needs no torch; once
    built it is reused. ``STAMP`` cannot be found and raises (fail closed).
    """

    name = "local"

    def __init__(
        self,
        local: Segmenter,
        *,
        signatures: Callable[[], Segmenter] = SignatureDetector,
    ) -> None:
        self.local = local
        self._build = signatures
        self._signatures: Segmenter | None = None
        self._lock = threading.Lock()

    @property
    def model(self) -> str:
        local = getattr(self.local, "model", "local")
        if self._signatures is None:
            return str(local)
        return f"{local}+{getattr(self._signatures, 'model', 'signature')}"

    def __repr__(self) -> str:
        return f"LocalSignatureSegmenter(local={self.local!r})"

    def signatures(self) -> Segmenter:
        """The signature detector, built once (raises :class:`DetectionError` if it can't)."""
        if self._signatures is None:
            with self._lock:
                if self._signatures is None:
                    self._signatures = self._build()
        return self._signatures

    def segment(
        self, image: bytes, entity_types: Sequence[EntityType | str] | None = None
    ) -> list[Region]:
        types = [EntityType(t) for t in (entity_types or LOCAL_SIGNATURE_TYPES)]
        unsupported = [t.value for t in types if t not in LOCAL_SIGNATURE_TYPES]
        if unsupported:
            raise DetectionError(f"on-device detection cannot find {', '.join(unsupported)}")
        faces = [t for t in types if t in LOCAL_ENTITY_TYPES]
        regions = self.local.segment(image, faces) if faces else []
        if EntityType.SIGNATURE in types:
            regions += self.signatures().segment(image, [EntityType.SIGNATURE])
        return regions


def policy_segmenter(
    detection: str, server: Segmenter, local: Callable[[], Segmenter]
) -> Segmenter:
    """The segmenter a project policy's ``visual_detection`` selects (see module docstring).

    ``server`` is the deployment's segmenter (``PII_GUARD_SEGMENTER``); ``local`` returns the
    shared :class:`LocalSignatureSegmenter`. The stricter of the two wins: a ``local`` / ``off``
    server is used even when the policy says ``sam``, and ``local`` never calls SAM.
    """
    if detection not in VISUAL_DETECTIONS:
        raise ValueError(f"visual_detection must be one of: {', '.join(VISUAL_DETECTIONS)}")
    if isinstance(server, OffSegmenter):
        return server
    if detection == "local" or not isinstance(server, (HybridSegmenter, SamClient)):
        return local()
    return server


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
        if (
            not segmenter.sam.configured
            and segmenter.local is not None
            and set(sam_types) <= {EntityType.SIGNATURE}
        ):
            return 0
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
    require_segmenter_mode(settings, mode)
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


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m pii_guard.visual.segmenters fetch``: download the pinned signature detector."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["fetch"]:
        print("usage: python -m pii_guard.visual.segmenters fetch", file=sys.stderr)
        return 2
    path = fetch_signature_detector()
    print(f"{path} (Apache-2.0, SHA-256 verified)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
