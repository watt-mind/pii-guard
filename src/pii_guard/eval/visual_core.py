"""Specimen loading, HTTP caching transport, and region scoring primitives for visual eval."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from pii_guard.types import DetectionError, EntityType
from pii_guard.visual.image import encode_image, load_image
from pii_guard.visual.regions import Box, Region, iou

DEFAULT_MANIFEST = Path("eval/visual/manifest.json")
DEFAULT_LABELS = Path("eval/visual/labels.json")
DEFAULT_SPECIMENS = Path("data/specimens")
DEFAULT_CACHE = Path("data/visual-cache")
DEFAULT_MAX_SIDE = 1600
#: Planning estimate per SAM image call (USD); override with ``--sam-cost``.
DEFAULT_SAM_COST = 0.0025
REGION_TYPES: tuple[str, ...] = ("portrait", "signature", "mrz", "text")
#: Label types a set may hold: the scored ones plus ``stamp``, which only the prompt study scores
#: (``STAMP`` is ``keep`` by default, so the recall report leaves it out).
LABEL_TYPES: tuple[str, ...] = (*REGION_TYPES, "stamp")
IOU_THRESHOLD = 0.5
COVERAGE_THRESHOLD = 0.9
#: The visual types the eval segments (``STAMP`` is ``keep`` by default and not labelled).
EVAL_SAM_TYPES: tuple[EntityType, ...] = (
    EntityType.FACE,
    EntityType.SIGNATURE,
    EntityType.ID_PHOTO,
)
#: Which expected region types a SAM entity type is meant to find (for the prompt study).
PROMPT_TARGETS: dict[EntityType, tuple[str, ...]] = {
    EntityType.FACE: ("portrait",),
    EntityType.ID_PHOTO: ("portrait",),
    EntityType.SIGNATURE: ("signature",),
    EntityType.STAMP: ("stamp",),
}
_LANGUAGE = {"HU": "hu"}
#: Baselines get each document's own language where a tool has a model for it.
_BASELINE_LANGUAGE = {"HU": "hu", "DE": "de", "AT": "de", "GB": "en"}


# --- SAM response cache --------------------------------------------------------------------


class BudgetExceeded(DetectionError):
    """A live SAM call was needed but the run's budget (or ``--offline``) forbids it."""


@dataclass
class CachingTransport(httpx.BaseTransport):
    """An httpx transport that caches successful responses on disk by request-body hash.

    The key covers the model, the prompt and the image (the JSON body), never the API key.
    ``max_live_calls`` bounds network calls (``0`` = offline); a miss beyond it raises
    :class:`BudgetExceeded` (a :class:`DetectionError`, so the pipeline fails closed).
    """

    cache_dir: Path
    inner: httpx.BaseTransport | None = None
    max_live_calls: int | None = None
    live_calls: int = 0
    cached_calls: int = 0
    #: Latency (ms) of each request in this run as originally recorded (live or from cache).
    recorded_ms: list[float] = field(default_factory=list)
    live_ms: float = 0.0

    def __post_init__(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self.inner is None:
            self.inner = httpx.HTTPTransport()

    def key(self, request: httpx.Request) -> str:
        body = request.read()
        return hashlib.sha256(request.url.path.encode() + b"\0" + body).hexdigest()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        key = self.key(request)
        path = self.cache_dir / f"{key}.json"
        if path.is_file():
            record = json.loads(path.read_text(encoding="utf-8"))
            self.cached_calls += 1
            self.recorded_ms.append(float(record.get("elapsed_ms", 0.0)))
            return httpx.Response(200, json=record["body"], request=request)
        if self.max_live_calls is not None and self.live_calls >= self.max_live_calls:
            raise BudgetExceeded("SAM call budget for this run is used up")
        if self.inner is None:  # pragma: no cover - set in __post_init__
            raise DetectionError("SAM transport is not configured")
        start = time.perf_counter()
        response = self.inner.handle_request(request)
        response.read()
        elapsed = (time.perf_counter() - start) * 1000
        self.live_calls += 1
        self.live_ms += elapsed
        self.recorded_ms.append(elapsed)
        if response.status_code == 200:
            try:
                body = response.json()
            except ValueError:
                body = None
            if isinstance(body, dict) and body.get("status") == "completed":
                record = {"elapsed_ms": round(elapsed, 1), "body": body}
                path.write_text(json.dumps(record), encoding="utf-8")
        return response

    def close(self) -> None:
        if self.inner is not None:
            self.inner.close()


# --- data ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExpectedRegion:
    type: str
    box: tuple[float, float, float, float]  # fractions of width/height

    def to_pixels(self, width: int, height: int) -> Box:
        x1, y1, x2, y2 = self.box
        return Box(
            max(0, min(width - 1, round(x1 * width))),
            max(0, min(height - 1, round(y1 * height))),
            max(0, min(width - 1, round(x2 * width) - 1)),
            max(0, min(height - 1, round(y2 * height) - 1)),
        )


@dataclass(frozen=True, slots=True)
class Specimen:
    id: str
    country: str
    doc_type: str
    side: str
    sha256: str
    path: Path
    regions: tuple[ExpectedRegion, ...]
    #: The document's language for the text detectors; ``None``: derived from the country.
    language: str | None = None


def load_specimens(
    manifest_path: Path,
    labels_path: Path,
    specimens_dir: Path,
    *,
    countries: Sequence[str] | None = None,
    log: Callable[[str], None] = lambda _msg: None,
) -> list[Specimen]:
    """Join the manifest and the labels; keep images that exist and match their SHA-256."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8")).get("specimens", {})
    wanted = {c.upper() for c in countries} if countries else None
    out: list[Specimen] = []
    for entry in manifest.get("specimens", []):
        sha = entry.get("sha256")
        label = labels.get(sha)
        if label is None or (wanted and entry["country"].upper() not in wanted):
            continue
        path = specimens_dir / entry["file"]
        if not path.is_file():
            log(f"missing image for {entry['id']} (run eval/visual/fetch_specimens.py)")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            log(f"SHA-256 mismatch for {entry['id']}; skipped")
            continue
        regions = []
        for region in label["regions"]:
            if region["type"] not in LABEL_TYPES:
                raise ValueError(f"unknown region type {region['type']!r}")
            x1, y1, x2, y2 = (float(v) for v in region["box"])
            if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
                raise ValueError(f"bad box in labels for {entry['id']}")
            regions.append(ExpectedRegion(region["type"], (x1, y1, x2, y2)))
        out.append(
            Specimen(
                entry["id"],
                entry["country"].upper(),
                entry["doc_type"],
                entry["side"],
                sha,
                path,
                tuple(regions),
                entry.get("language"),
            )
        )
    return out


def prepare_image(raw: bytes, max_side: int = DEFAULT_MAX_SIDE) -> bytes:
    """Decode, downscale so the longer side is at most ``max_side``, re-encode as PNG."""
    image = load_image(raw)
    longest = max(image.size)
    if longest > max_side:
        scale = max_side / longest
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(size, Image.Resampling.LANCZOS)
    return encode_image(image)


# --- scoring ---------------------------------------------------------------------------------


def _mask(size: tuple[int, int], boxes: Sequence[Box]) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for box in boxes:
        draw.rectangle([box.x1, box.y1, box.x2, box.y2], fill=255)
    return mask


def _count(mask: Image.Image, box: Box | None = None) -> int:
    """Covered (255) pixels in ``mask``, or in ``box`` of it."""
    region = mask if box is None else mask.crop((box.x1, box.y1, box.x2 + 1, box.y2 + 1))
    return region.histogram()[255]


@dataclass(frozen=True, slots=True)
class RegionScore:
    type: str
    best_iou: float
    coverage: float
    matched_by: str | None  # entity type of the best-IoU covered box

    @property
    def hit_iou(self) -> bool:
        return self.best_iou >= IOU_THRESHOLD

    @property
    def hit_coverage(self) -> bool:
        return self.coverage >= COVERAGE_THRESHOLD


def score_regions(
    expected: Sequence[ExpectedRegion],
    covered: Sequence[Region],
    size: tuple[int, int],
) -> tuple[list[RegionScore], float]:
    """Score each expected region against the covered boxes; return scores and over-masking."""
    width, height = size
    boxes = [r.box for r in covered]
    union = _mask(size, boxes)
    expected_boxes = [e.to_pixels(width, height) for e in expected]
    scores: list[RegionScore] = []
    for region, box in zip(expected, expected_boxes, strict=True):
        best, by = 0.0, None
        for pred in covered:
            value = iou(box, pred.box)
            if value > best:
                best, by = value, pred.entity_type.value
        area = box.width * box.height
        coverage = _count(union, box) / area if area else 0.0
        scores.append(RegionScore(region.type, best, coverage, by))
    outside = Image.new("L", size, 0)
    outside.paste(union)
    if expected_boxes:
        draw = ImageDraw.Draw(outside)
        for box in expected_boxes:
            draw.rectangle([box.x1, box.y1, box.x2, box.y2], fill=0)
    over = _count(outside) / (width * height)
    return scores, over


def _pad(box: Box, padding: int, size: tuple[int, int]) -> Box:
    width, height = size
    return Box(
        max(0, box.x1 - padding),
        max(0, box.y1 - padding),
        min(width - 1, box.x2 + padding),
        min(height - 1, box.y2 + padding),
    )


# --- the run ---------------------------------------------------------------------------------


@dataclass
class SpecimenResult:
    specimen: Specimen
    scores: list[RegionScore] = field(default_factory=list)
    over_masking: float = 0.0
    sam_calls: int = 0
    sam_ms: float = 0.0
    local_ms: float = 0.0
    regions_masked: int = 0
    error: str | None = None
