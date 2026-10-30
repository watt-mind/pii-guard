"""On-device segmentation of faces and ID photos (LAB-1229), the local counterpart of SAM 3.1.

:class:`LocalSegmenter` has the same ``segment(image, entity_types)`` interface as
:class:`~pii_guard.visual.sam.SamClient` (the :class:`Segmenter` protocol), so the visual
pipeline takes either. It runs **YuNet** (OpenCV model zoo, MIT licence, 0.23 MB ONNX) on the
CPU through OpenCV (``uv sync --extra local-vision``); nothing leaves the machine.

What it finds:

- ``FACE``: every face YuNet detects, searched at several image sizes (YuNet finds faces of
  about 10-300 px) and on a contrast-equalised grey copy (security print and overprints hide
  faces from the colour pass);
- ``ID_PHOTO``: for each face, the photo around it, estimated by growing the face box
  (:data:`PHOTO_PADDING`); a box, not a detected photo edge.

It does **not** find ``SIGNATURE``: no permissively licensed small detector came close to SAM
3.1 on ID documents (see ``docs/models.md``, *Local segmentation*). Asking for it raises
:class:`~pii_guard.types.DetectionError` rather than returning a result that silently skips
signatures (fail closed, ADR 0006). The default ``hybrid`` segmenter
(:mod:`pii_guard.visual.segmenters`, LAB-1245) therefore pairs it with SAM 3.1 for signatures.

Fail closed: a missing OpenCV, a missing model file or one whose SHA-256 does not match, an
undecodable image and any inference error raise :class:`DetectionError`. Messages carry
counts and file names only, never image content.

Get the model once (official OpenCV model zoo URL, SHA-256 checked)::

    uv run python -m pii_guard.visual.segment fetch
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx

from pii_guard.types import DetectionError, EntityType
from pii_guard.visual.image import load_image
from pii_guard.visual.regions import Box, Region, iou_xyxy

__all__ = [
    "DEFAULT_MODEL_DIR",
    "LOCAL_ENTITY_TYPES",
    "MODEL_DIR_ENV_VAR",
    "PHOTO_PADDING",
    "YUNET",
    "LocalSegmenter",
    "ModelFile",
    "Segmenter",
    "fetch_model",
    "model_dir",
]

logger = logging.getLogger(__name__)


@runtime_checkable
class Segmenter(Protocol):
    """Finds visual personal data (``FACE``, ``SIGNATURE``, ``ID_PHOTO``) in an image.

    Implemented by :class:`~pii_guard.visual.sam.SamClient` (SAM 3.1 on the Meta API) and
    :class:`LocalSegmenter`. Raises :class:`~pii_guard.types.DetectionError` on any failure,
    including a requested type it cannot find.
    """

    def segment(
        self, image: bytes, entity_types: Sequence[EntityType | str] | None = None
    ) -> list[Region]: ...


class ModelFile:
    """A pinned model file: where it comes from, its SHA-256, size and licence."""

    __slots__ = ("filename", "licence", "sha256", "size", "url")

    def __init__(self, filename: str, url: str, sha256: str, size: int, licence: str) -> None:
        self.filename = filename
        self.url = url
        self.sha256 = sha256
        self.size = size
        self.licence = licence

    def __repr__(self) -> str:
        return f"ModelFile({self.filename!r}, {self.size} bytes, {self.licence})"


#: YuNet face detector, fixed-input-shape export (works on OpenCV 4.x and 5.x).
YUNET = ModelFile(
    "face_detection_yunet_2023mar.onnx",
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    232_589,
    "MIT",
)

MODEL_DIR_ENV_VAR = "PII_GUARD_MODEL_DIR"
DEFAULT_MODEL_DIR = Path("~/.cache/pii-guard/models")

#: The types :class:`LocalSegmenter` can find (its default when none are requested).
LOCAL_ENTITY_TYPES: tuple[EntityType, ...] = (EntityType.FACE, EntityType.ID_PHOTO)

#: How far a face box is grown to estimate the ID photo around it: (left, right, up, down) as
#: fractions of the face box. The portrait's edges sit a median 0.3-0.4 face widths/heights
#: beyond YuNet's box (90th percentile 0.5-0.7); these values were picked from four settings
#: on the fictional set and the specimens (LAB-1229) as the smallest with no fictional portrait
#: under 95 % covered. Over-masking is the safe side: a larger box costs precision, not privacy.
#: Kept generous on purpose (LAB-1488 review): the masking pipeline (:func:`masking._clip_photos`)
#: clips the estimate back at swallowed caption starts instead, so captions stay readable while
#: the portrait stays covered.
PHOTO_PADDING: tuple[float, float, float, float] = (0.65, 0.65, 0.6, 0.8)

#: The image sizes (longer side, px; 0 = as given) YuNet runs at.
PYRAMID: tuple[int, ...] = (0, 960, 640, 400)


def model_dir() -> Path:
    """``PII_GUARD_MODEL_DIR``, default ``~/.cache/pii-guard/models``."""
    return Path(os.environ.get(MODEL_DIR_ENV_VAR) or DEFAULT_MODEL_DIR).expanduser()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_model(
    model: ModelFile = YUNET,
    directory: Path | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> Path:
    """Download ``model`` into ``directory`` (default :func:`model_dir`) unless it is already
    there, check its SHA-256 and return its path. A mismatch raises and leaves no file."""
    directory = directory or model_dir()
    path = directory / model.filename
    if path.is_file() and _sha256(path) == model.sha256:
        return path
    directory.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    with (
        httpx.Client(follow_redirects=True, timeout=60.0, transport=transport) as client,
        client.stream("GET", model.url) as response,
    ):
        response.raise_for_status()
        with partial.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)
    if _sha256(partial) != model.sha256:
        partial.unlink()
        raise DetectionError(f"{model.filename}: SHA-256 does not match the pinned value")
    partial.replace(path)
    return path


def nms(
    boxes: Sequence[tuple[float, float, float, float, float]], threshold: float = 0.3
) -> list[tuple[float, float, float, float, float]]:
    """Greedy non-maximum suppression of ``(x1, y1, x2, y2, score)`` boxes, best first."""
    kept: list[tuple[float, float, float, float, float]] = []
    for box in sorted(boxes, key=lambda b: -b[4]):
        if all(iou_xyxy(box, k) < threshold for k in kept):
            kept.append(box)
    return kept


def _clip(x1: float, y1: float, x2: float, y2: float, width: int, height: int) -> Box | None:
    left, top = max(0, int(x1)), max(0, int(y1))
    right, bottom = min(width - 1, round(x2)), min(height - 1, round(y2))
    if right <= left or bottom <= top:
        return None
    return Box(left, top, right, bottom)


def photo_box(face: Box, width: int, height: int) -> Box:
    """The ID photo estimated around ``face`` (:data:`PHOTO_PADDING`, clamped to the image)."""
    left, right, up, down = PHOTO_PADDING
    fw, fh = face.width, face.height
    box = _clip(
        face.x1 - left * fw, face.y1 - up * fh, face.x2 + right * fw, face.y2 + down * fh,
        width, height,
    )  # fmt: skip
    return box or face


class LocalSegmenter:
    """Faces and ID photos with YuNet on the CPU; see the module docstring.

    Keyword-only, all optional:

    - ``model_path``: the YuNet ONNX file (default :func:`model_dir` / ``YUNET.filename``);
      its SHA-256 must match :data:`YUNET` unless ``verify=False``;
    - ``score_threshold``: YuNet's face confidence cut-off (0.6, the model zoo default);
    - ``detector``: a ready ``cv2.FaceDetectorYN``-like object (``setInputSize``, ``detect``),
      for tests; OpenCV and the model file are then not needed.
    """

    name = "local"
    model = "yunet-2023mar"

    def __init__(
        self,
        *,
        model_path: str | Path | None = None,
        score_threshold: float = 0.6,
        verify: bool = True,
        detector: Any = None,
    ) -> None:
        if not 0.0 < score_threshold < 1.0:
            raise ValueError("score_threshold must be in (0, 1)")
        self.score_threshold = score_threshold
        self._lock = threading.Lock()
        self._cv2: Any = None
        if detector is not None:
            self._detector = detector
            self.model_path: Path | None = None
            return
        try:
            import cv2
        except ImportError as exc:
            raise DetectionError(
                "local segmenter needs OpenCV (uv sync --extra local-vision)"
            ) from exc
        self._cv2 = cv2
        with contextlib.suppress(AttributeError):  # OpenCV 5's DNN backend notice is not an error
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        path = Path(model_path) if model_path else model_dir() / YUNET.filename
        if not path.is_file():
            raise DetectionError(
                f"local segmenter model {path.name} is missing (pii-guard models fetch yunet)"
            )
        if verify and _sha256(path) != YUNET.sha256:
            raise DetectionError(f"local segmenter model {path.name}: SHA-256 mismatch")
        try:
            self._detector = cv2.FaceDetectorYN.create(
                str(path), "", (320, 320), score_threshold, 0.3, 5000
            )
        except Exception as exc:  # cv2.error
            raise DetectionError(
                f"local segmenter model could not be loaded ({path.name})"
            ) from exc
        self.model_path = path

    def __repr__(self) -> str:
        return f"LocalSegmenter(model={self.model!r}, score_threshold={self.score_threshold})"

    def segment(
        self, image: bytes, entity_types: Sequence[EntityType | str] | None = None
    ) -> list[Region]:
        """Return ``FACE`` and ``ID_PHOTO`` regions (default both) found in ``image``.

        Raises :class:`DetectionError` for a type it cannot find (``SIGNATURE``, ``STAMP``)
        and on any failure.
        """
        types = [EntityType(t) for t in (entity_types or LOCAL_ENTITY_TYPES)]
        unsupported = [t.value for t in types if t not in LOCAL_ENTITY_TYPES]
        if unsupported:
            raise DetectionError(f"local segmenter cannot find {', '.join(unsupported)}")
        try:
            decoded = load_image(bytes(image))
        except (ValueError, TypeError) as exc:
            raise DetectionError("image could not be decoded for segmentation") from exc
        import numpy as np

        rgb = np.asarray(decoded.convert("RGB"))
        width, height = decoded.size
        try:
            faces = self._faces(rgb)
        except DetectionError:
            raise
        except Exception as exc:
            raise DetectionError(f"local segmentation failed ({type(exc).__name__})") from exc
        regions: list[Region] = []
        for x1, y1, x2, y2, score in faces:
            face = _clip(x1, y1, x2, y2, width, height)
            if face is None:
                continue
            score = round(min(1.0, max(0.0, score)), 4)
            if EntityType.FACE in types:
                regions.append(Region(EntityType.FACE, face, score, "yunet"))
            if EntityType.ID_PHOTO in types:
                regions.append(
                    Region(EntityType.ID_PHOTO, photo_box(face, width, height), score, "yunet")
                )
        logger.debug("local segmenter: %d face(s)", len(faces))
        return regions

    def _variants(self, bgr: Any) -> list[Any]:
        cv2 = self._cv2
        if cv2 is None:  # an injected detector: no OpenCV preprocessing
            return [bgr]
        grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        equalised = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(grey)
        return [bgr, cv2.cvtColor(equalised, cv2.COLOR_GRAY2BGR)]

    def _resize(self, image: Any, scale: float) -> Any:
        if scale == 1.0:
            return image
        height, width = image.shape[:2]
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        if self._cv2 is None:
            import numpy as np
            from PIL import Image

            return np.asarray(Image.fromarray(image).resize(size))
        interpolation = self._cv2.INTER_AREA if scale < 1 else self._cv2.INTER_LINEAR
        return self._cv2.resize(image, size, interpolation=interpolation)

    def _faces(self, rgb: Any) -> list[tuple[float, float, float, float, float]]:
        height, width = rgb.shape[:2]
        bgr = rgb[:, :, ::-1].copy()
        longest = max(height, width)
        scales = sorted({1.0 if side == 0 else side / longest for side in PYRAMID})
        found: list[tuple[float, float, float, float, float]] = []
        with self._lock:  # setInputSize mutates the detector
            for variant in self._variants(bgr):
                for scale in scales:
                    scaled = self._resize(variant, scale)
                    self._detector.setInputSize((scaled.shape[1], scaled.shape[0]))
                    _, faces = self._detector.detect(scaled)
                    if faces is None:
                        continue
                    for row in faces:
                        x, y, w, h = (float(v) / scale for v in row[:4])
                        found.append((x, y, x + w, y + h, float(row[-1])))
        return nms(found)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m pii_guard.visual.segment fetch``: download the pinned YuNet model."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["fetch"]:
        print("usage: python -m pii_guard.visual.segment fetch", file=sys.stderr)
        return 2
    path = fetch_model()
    print(f"{path} ({YUNET.licence}, SHA-256 verified)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
