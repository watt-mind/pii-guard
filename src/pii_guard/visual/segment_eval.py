"""Segmenter comparison for LAB-1229: SAM 3.1 on the Meta API against on-device candidates.

```
python -m pii_guard.visual.segment_eval --candidate local --set specimens
       [--record SLUG] [--json OUT] [--offline] [--max-live-calls 400] [--note TEXT]
```

Scores only what a segmenter is for, the ``portrait`` and ``signature`` regions of the
fictional set (``eval/fixtures/visual``, committed) and of the official specimen set
(``eval/visual``, images fetched locally and never committed), with the same image
preparation (longer side ≤ 1600 px), ``FACE`` growth and 2 px padding as
``pii-guard eval visual``. Per region type:

- **recall@IoU≥0.5** and **recall@cov≥0.9** (as in ``pii-guard eval visual``);
- **leak**: a labelled region less than 95 % covered by the union of every box the segmenter
  returned (``leak_strict``: less than 100 %; specimen labels are hand-drawn to about ±1-2 %
  of the image side, so the strict figure counts label slack as leaks for every candidate);
- **precision**: predicted boxes that overlap a labelled region of their kind with IoU ≥ 0.5
  or lie at least 80 % inside one (a face box inside a portrait is not a false alarm).

Latency is per image: wall time of ``segment()`` for local candidates; for SAM the sum of
its sequential API calls as recorded when each response was first fetched (cached replays
cost nothing and keep the original latency). Also reported: model load time, the first
image's time, peak RSS of the process and the model files' size.

Candidates (the extra packages are needed only for the candidate that uses them):

- ``sam-api``: :class:`~pii_guard.visual.sam.SamClient`, through the eval's response cache;
- ``local``: :class:`~pii_guard.visual.segment.LocalSegmenter` (YuNet; ``local-vision``);
- ``small-detectors``: ``local`` plus a YOLOS-tiny signature detector run on the whole image
  and 2x2 overlapping tiles (``mdefrance/yolos-tiny-signature-detection``, Apache-2.0;
  needs ``torch`` + ``transformers``, the ``ner`` extra);
- ``efficientsam``: ``local`` with each ID-photo box replaced by the bounding box of an
  EfficientSAM-ViT-T mask prompted with it (``yformer/EfficientSAM`` ONNX export,
  Apache-2.0; needs ``onnxruntime``).

Output holds numbers, region types and specimen ids only, never images or text.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from pii_guard.types import DetectionError, EntityType, PiiGuardError
from pii_guard.visual.image import load_image
from pii_guard.visual.regions import Box, Region
from pii_guard.visual.segment import (
    YUNET,
    LocalSegmenter,
    ModelFile,
    Segmenter,
    model_dir,
    nms,
)

__all__ = ["CANDIDATES", "SETS", "SegmentScore", "build_parser", "main", "score_image"]

#: (manifest, labels, images) per evaluation set.
SETS: dict[str, tuple[Path, Path, Path]] = {
    "fictional": (
        Path("eval/fixtures/visual/manifest.json"),
        Path("eval/fixtures/visual/labels.json"),
        Path("eval/fixtures/visual/images"),
    ),
    "specimens": (
        Path("eval/visual/manifest.json"),
        Path("eval/visual/labels.json"),
        Path("data/specimens"),
    ),
}
#: How each fixture set is described in a run record.
_SET_INFO = {
    "fictional": ("fictional-specimens", "generated", "muse-image"),
    "specimens": ("specimens", "specimens", None),
}
SCORED_TYPES: tuple[str, ...] = ("portrait", "signature")
_GROUP = {
    EntityType.FACE: "portrait",
    EntityType.ID_PHOTO: "portrait",
    EntityType.SIGNATURE: "signature",
}
LEAK_COVERAGE = 0.95

EFFICIENTSAM_ENCODER = ModelFile(
    "efficient_sam_vitt_encoder.onnx",
    "https://raw.githubusercontent.com/yformer/EfficientSAM/main/weights/efficient_sam_vitt_encoder.onnx",
    "84ed466ffcc5c1f8d08409bc34a23bb364ab2c15e402cb12d4335a42be0e0951",
    24_799_761,
    "Apache-2.0",
)
EFFICIENTSAM_DECODER = ModelFile(
    "efficient_sam_vitt_decoder.onnx",
    "https://raw.githubusercontent.com/yformer/EfficientSAM/main/weights/efficient_sam_vitt_decoder.onnx",
    "a62f8fa5ea080447c0689418d69e58f1e83e0b7adf9c142e2bd9bcc8045c0b11",
    16_565_728,
    "Apache-2.0",
)
YOLOS_SIGNATURE = "mdefrance/yolos-tiny-signature-detection"
YOLOS_REVISION = "b788cf7376464453c3dea1e5ee8589adcaa0c634"
YOLOS_SIZE = 25_909_400


# --- Spike candidates (measured, not shipped) ---------------------------------------------


class YolosSignatures:  # pragma: no cover - needs torch + transformers and the hub model
    """YOLOS-tiny signature boxes on the whole image and on 2x2 overlapping tiles."""

    def __init__(self, score: float = 0.5, grid: int = 2) -> None:
        import torch
        from transformers import AutoImageProcessor, AutoModelForObjectDetection

        self._torch = torch
        self._proc = AutoImageProcessor.from_pretrained(YOLOS_SIGNATURE, revision=YOLOS_REVISION)
        self._model = AutoModelForObjectDetection.from_pretrained(
            YOLOS_SIGNATURE, revision=YOLOS_REVISION
        ).eval()
        self.score = score
        self.grid = grid

    def _boxes(self, image: Any) -> list[tuple[float, float, float, float, float]]:
        inputs = self._proc(images=image, return_tensors="pt")
        with self._torch.no_grad():
            out = self._model(**inputs)
        res = self._proc.post_process_object_detection(
            out, threshold=self.score, target_sizes=[(image.height, image.width)]
        )[0]
        return [
            (*(float(v) for v in b.tolist()), float(s))
            for b, s in zip(res["boxes"], res["scores"], strict=True)
        ]

    def segment(
        self, image: bytes, entity_types: Sequence[EntityType | str] | None = None
    ) -> list[Region]:
        decoded = load_image(image).convert("RGB")
        width, height = decoded.size
        found = self._boxes(decoded)
        tw, th = width / self.grid, height / self.grid
        for i in range(self.grid):
            for j in range(self.grid):
                x0, y0 = max(0, int((i - 0.25) * tw)), max(0, int((j - 0.25) * th))
                x1, y1 = min(width, int((i + 1.25) * tw)), min(height, int((j + 1.25) * th))
                for a, b, c, d, s in self._boxes(decoded.crop((x0, y0, x1, y1))):
                    found.append((a + x0, b + y0, c + x0, d + y0, s))
        regions = []
        for a, b, c, d, s in nms(found, 0.5):
            left, top = max(0, int(a)), max(0, int(b))
            right, bottom = min(width - 1, round(c)), min(height - 1, round(d))
            if right > left and bottom > top:
                box = Box(left, top, right, bottom)
                regions.append(Region(EntityType.SIGNATURE, box, round(min(1.0, s), 4), "yolos"))
        return regions


class EfficientSamPhotos:  # pragma: no cover - needs onnxruntime and the EfficientSAM files
    """``local``, with each ID-photo box refined by an EfficientSAM-ViT-T box prompt."""

    def __init__(self, local: LocalSegmenter) -> None:
        import onnxruntime as ort

        self.local = local
        providers = ["CPUExecutionProvider"]
        self._enc = ort.InferenceSession(
            str(model_dir() / EFFICIENTSAM_ENCODER.filename), providers=providers
        )
        self._dec = ort.InferenceSession(
            str(model_dir() / EFFICIENTSAM_DECODER.filename), providers=providers
        )

    def segment(
        self, image: bytes, entity_types: Sequence[EntityType | str] | None = None
    ) -> list[Region]:
        import numpy as np

        regions = self.local.segment(image)
        faces = [r for r in regions if r.entity_type is EntityType.FACE]
        photos = [r for r in regions if r.entity_type is EntityType.ID_PHOTO]
        if not faces:
            return regions
        rgb = np.asarray(load_image(image).convert("RGB"))
        height, width = rgb.shape[:2]
        pixels = (rgb.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
        embeddings = self._enc.run(None, {"batched_images": pixels})[0]
        out = list(faces)
        for face, photo in zip(faces, photos, strict=True):
            b = photo.box
            masks, ious = self._dec.run(
                ["output_masks", "iou_predictions"],
                {
                    "image_embeddings": embeddings,
                    "batched_point_coords": np.array([[[[b.x1, b.y1], [b.x2, b.y2]]]], np.float32),
                    "batched_point_labels": np.array([[[2, 3]]], np.float32),
                    "orig_im_size": np.array([height, width], np.int64),
                },
            )
            best = None
            f = face.box
            for k in np.argsort(-ious[0, 0]):
                ys, xs = np.nonzero(masks[0, 0, k] > 0)
                if len(xs) == 0:
                    continue
                cand = Box(int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
                contains = (
                    cand.x1 <= f.x1 + 2
                    and cand.y1 <= f.y1 + 2
                    and cand.x2 >= f.x2 - 2
                    and cand.y2 >= f.y2 - 2
                )
                if contains and cand.width * cand.height <= 6 * f.width * f.height:
                    best = cand.union(f)
                    break
            out.append(Region(EntityType.ID_PHOTO, best or b, photo.score, "efficientsam"))
        return out


class _Combined:
    def __init__(self, *parts: Any) -> None:
        self.parts = parts

    def segment(
        self, image: bytes, entity_types: Sequence[EntityType | str] | None = None
    ) -> list[Region]:
        return [r for part in self.parts for r in part.segment(image)]


@dataclass(frozen=True)
class Candidate:
    name: str
    #: Detector entries for the run record (name, model, model_ref, revision).
    detectors: tuple[dict[str, Any], ...]
    licence: str
    #: Model bytes on disk (``None``: not local).
    size_bytes: int | None
    #: Builds the segmenter; ``transport`` is the SAM cache (``sam-api`` only).
    build: Callable[[Any], Any]


def _sam(transport: Any) -> Any:
    from pii_guard.visual.sam import SamClient

    return SamClient(transport=transport, max_retries=2)


def _yunet_detector() -> dict[str, Any]:
    return {
        "name": "local-segmenter",
        "model": "yunet-2023mar",
        "model_ref": "opencv_zoo/models/face_detection_yunet/" + YUNET.filename,
        "revision": YUNET.sha256[:16],
    }


CANDIDATES: dict[str, Candidate] = {
    "sam-api": Candidate(
        "sam-api",
        ({"name": "sam", "model": "sam-3.1", "model_ref": "meta-api:sam-3.1"},),
        "hosted (Meta Model API)",
        None,
        _sam,
    ),
    "local": Candidate(
        "local",
        (_yunet_detector(),),
        "MIT (YuNet weights), Apache-2.0 (OpenCV)",
        YUNET.size,
        lambda _t: LocalSegmenter(),
    ),
    "small-detectors": Candidate(
        "small-detectors",
        (
            _yunet_detector(),
            {
                "name": "signature-detector",
                "model": "yolos-tiny-signature",
                "model_ref": YOLOS_SIGNATURE,
                "revision": YOLOS_REVISION,
            },
        ),
        "MIT (YuNet), Apache-2.0 (YOLOS-tiny signature weights, transformers)",
        YUNET.size + YOLOS_SIZE,
        lambda _t: _Combined(LocalSegmenter(), YolosSignatures()),
    ),
    "efficientsam": Candidate(
        "efficientsam",
        (
            _yunet_detector(),
            {
                "name": "photo-refiner",
                "model": "efficientsam-vitt",
                "model_ref": "yformer/EfficientSAM efficient_sam_vitt_{encoder,decoder}.onnx",
                "revision": EFFICIENTSAM_ENCODER.sha256[:16],
            },
        ),
        "MIT (YuNet), Apache-2.0 (EfficientSAM code and weights)",
        YUNET.size + EFFICIENTSAM_ENCODER.size + EFFICIENTSAM_DECODER.size,
        lambda _t: EfficientSamPhotos(LocalSegmenter()),
    ),
}


# --- Scoring --------------------------------------------------------------------------------


@dataclass
class SegmentScore:
    """Counts for one region type, summed over images."""

    regions: int = 0
    leaks: int = 0
    leaks_strict: int = 0
    predicted: int = 0
    predicted_ok: int = 0

    def add(self, other: SegmentScore) -> None:
        self.regions += other.regions
        self.leaks += other.leaks
        self.leaks_strict += other.leaks_strict
        self.predicted += other.predicted
        self.predicted_ok += other.predicted_ok


def _inside_share(inner: Box, outer: Box) -> float:
    ix = min(inner.x2, outer.x2) - max(inner.x1, outer.x1) + 1
    iy = min(inner.y2, outer.y2) - max(inner.y1, outer.y1) + 1
    if ix <= 0 or iy <= 0:
        return 0.0
    return ix * iy / (inner.width * inner.height)


def score_image(
    expected: Sequence[tuple[str, Box]], covered: Sequence[Region], coverage: Sequence[float]
) -> dict[str, SegmentScore]:
    """Leak and precision counts per scored region type for one image.

    ``expected`` holds (type, pixel box) of the labelled regions, ``coverage`` the share of
    each one under the union of ``covered`` (same order).
    """
    from pii_guard.eval.visual import iou

    out = {t: SegmentScore() for t in SCORED_TYPES}
    for (kind, _box), cov in zip(expected, coverage, strict=True):
        if kind in out:
            out[kind].regions += 1
            out[kind].leaks += cov < LEAK_COVERAGE
            out[kind].leaks_strict += cov < 0.999
    for region in covered:
        kind = _GROUP.get(region.entity_type)
        if kind is None:
            continue
        out[kind].predicted += 1
        targets = [box for k, box in expected if k == kind]
        if any(
            iou(box, region.box) >= 0.5 or _inside_share(region.box, box) >= 0.8 for box in targets
        ):
            out[kind].predicted_ok += 1
    return out


def _peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # bytes on macOS, KiB on Linux
    return round(peak / 1e6 if sys.platform == "darwin" else peak / 1e3, 1)


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


@dataclass
class _Run:
    results: list[Any] = field(default_factory=list)
    scores: dict[str, SegmentScore] = field(
        default_factory=lambda: {t: SegmentScore() for t in SCORED_TYPES}
    )
    per_image_ms: list[float] = field(default_factory=list)
    load_ms: float = 0.0


def run(
    candidate: Candidate,
    set_name: str,
    *,
    transport: Any = None,
    log: Callable[[str], None] = lambda _m: None,
) -> _Run:
    """Segment and score every labelled image of ``set_name``."""
    from pii_guard.api.routes.image_masking import _grow_face
    from pii_guard.eval.visual import (
        DEFAULT_MAX_SIDE,
        SpecimenResult,
        _pad,
        load_specimens,
        prepare_image,
        score_regions,
    )

    specimens = load_specimens(*SETS[set_name], log=log)
    if not specimens:
        raise DetectionError(f"no labelled images found for {set_name}")
    out = _Run()
    start = time.perf_counter()
    segmenter: Segmenter = candidate.build(transport)
    out.load_ms = (time.perf_counter() - start) * 1000
    types = [EntityType.FACE, EntityType.SIGNATURE, EntityType.ID_PHOTO]
    if candidate.name in ("local", "efficientsam"):
        types = [EntityType.FACE, EntityType.ID_PHOTO]
    for specimen in specimens:
        data = prepare_image(specimen.path.read_bytes(), DEFAULT_MAX_SIDE)
        size = load_image(data).size
        result = SpecimenResult(specimen)
        recorded_before = len(transport.recorded_ms) if transport is not None else 0
        start = time.perf_counter()
        try:
            found = segmenter.segment(data, types)
        except PiiGuardError as exc:
            result.error = exc.code
            found = []
        wall = (time.perf_counter() - start) * 1000
        if transport is not None:
            recorded = transport.recorded_ms[recorded_before:]
            result.sam_calls = len(recorded)
            result.sam_ms = sum(recorded)
            elapsed = result.sam_ms
        else:
            result.local_ms = wall
            elapsed = wall
        out.per_image_ms.append(elapsed)
        covered = [
            Region(r.entity_type, _pad(_grow_face(r, *size).box, 2, size), None, r.source)
            for r in found
        ]
        expected = [e for e in specimen.regions if e.type in SCORED_TYPES]
        result.regions_masked = len(covered)
        result.scores, result.over_masking = score_regions(expected, covered, size)
        pixel = [(e.type, e.to_pixels(*size)) for e in expected]
        per = score_image(pixel, covered, [s.coverage for s in result.scores])
        for kind, counts in per.items():
            out.scores[kind].add(counts)
        out.results.append(result)
        log(f"{specimen.id}: {sum(s.hit_iou for s in result.scores)}/{len(result.scores)}")
    return out


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))], 1)


def build_card(candidate: Candidate, set_name: str, done: _Run, transport: Any) -> dict[str, Any]:
    """The run as a ``visual-specimens`` result (portrait and signature only) plus a
    ``segmenter`` block with leak, precision, latency, memory, size and licence."""
    from pii_guard.eval.visual import EVAL_SAM_TYPES, build_report

    card = build_report(
        done.results,
        transport=transport,
        sam=None,
        entity_types=EVAL_SAM_TYPES,
        ocr_engine=None,
        detector_name=None,
        sam_cost=0.0025 if transport is not None else 0.0,
        max_side=1600,
    )
    for kind in [k for k in card["by_region_type"] if k not in SCORED_TYPES]:
        card["by_region_type"].pop(kind)
    for group in card["by_country"].values():
        for kind in [k for k in group["by_type"] if k not in SCORED_TYPES]:
            group["by_type"].pop(kind)
    ms = done.per_image_ms
    card["latency_ms"].update(
        {
            "segment_per_image_p50": _percentile(ms, 0.5),
            "segment_per_image_p95": _percentile(ms, 0.95),
            "segment_first_image": round(ms[0], 1) if ms else None,
            "segment_model_load": round(done.load_ms, 1),
        }
    )
    card["segmenter"] = {
        "candidate": candidate.name,
        "set": set_name,
        "licence": candidate.licence,
        "model_size_mb": round(candidate.size_bytes / 1e6, 2) if candidate.size_bytes else None,
        "peak_rss_mb": _peak_rss_mb(),
        "platform": f"{platform.system()} {platform.machine()}",
        "leak_coverage_threshold": LEAK_COVERAGE,
        "by_region_type": {
            kind: {
                "regions": s.regions,
                "recall_iou50": card["by_region_type"][kind]["recall_iou50"],
                "leak_rate": _rate(s.leaks, s.regions),
                "leak_rate_strict": _rate(s.leaks_strict, s.regions),
                "predicted": s.predicted,
                "precision": _rate(s.predicted_ok, s.predicted),
            }
            for kind, s in done.scores.items()
        },
    }
    return card


def _notes(card: dict[str, Any]) -> list[str]:
    seg = card["segmenter"]
    lat = card["latency_ms"]
    parts = []
    for kind, s in seg["by_region_type"].items():

        def pct(v: float | None) -> str:
            return "n/a" if v is None else f"{v * 100:.1f} %"

        parts.append(
            f"{kind}: recall@IoU0.5 {pct(s['recall_iou50'])}, leak (<95 % covered) "
            f"{pct(s['leak_rate'])}, strict leak {pct(s['leak_rate_strict'])}, precision "
            f"{pct(s['precision'])} ({s['predicted']} boxes)"
        )
    size = "hosted" if seg["model_size_mb"] is None else f"{seg['model_size_mb']} MB"
    return [
        "LAB-1229 segmenter comparison: portrait and signature regions only, no OCR; "
        f"candidate {seg['candidate']}.",
        "; ".join(parts) + ".",
        f"Per image p50 {lat['segment_per_image_p50']} ms, p95 {lat['segment_per_image_p95']} "
        f"ms on {seg['platform']} CPU; model load {lat['segment_model_load']} ms; peak RSS "
        f"{seg['peak_rss_mb']} MB; weights {size}; licence {seg['licence']}.",
    ]


def to_record(
    card: dict[str, Any], candidate: Candidate, set_name: str, slug: str
) -> dict[str, Any]:
    from pii_guard.eval.record import build_records, host_info
    from pii_guard.eval.report import git_commit

    set_label, origin, generator = _SET_INFO[set_name]
    manifest = SETS[set_name][0]
    commit, dirty = git_commit()
    detectors = [
        {"model_ref": None, "revision": None, "settings": {}, "serving": None, **d}
        for d in candidate.detectors
    ]
    names = "+".join(str(d["model"]) for d in detectors)
    hardware = host_info()
    load = os.getloadavg()[0] if hasattr(os, "getloadavg") else None
    hardware["description"] = f"{platform.machine()} CPU, one process" + (
        f"; host load average {load:.0f} (shared with other jobs)" if load is not None else ""
    )
    (record,) = build_records(
        card,
        slug=slug,
        day=date.today().isoformat(),
        hardware=hardware,
        notes=_notes(card),
        extra={
            "system": {
                "detectors": detectors,
                "key": f"visual-segment:{names}",
                "label": f"segmenter {names} (no OCR)",
            }
        },
    )
    record["code"] = {
        "commit": commit,
        "dirty": dirty,
        "pii_guard_version": record["code"].get("pii_guard_version"),
        "note": None,
    }
    record["title"] = f"Segmenter {candidate.name} on {set_label} (LAB-1229)"
    record["fixture_set"] = set_label
    record["fixtures"] = [
        {
            "path": str(manifest),
            "sha256": None,
            "set": set_label,
            "language": None,
            "origin": origin,
            "generator": generator,
            "documents": card["specimens"],
        }
    ]
    if candidate.name != "sam-api":
        record["cost"] = {
            "usd": 0.0,
            "estimated": False,
            "gpu_minutes": None,
            "model_calls": None,
            "tokens": None,
            "shared_with": [],
            "note": "on-device, CPU",
        }
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pii_guard.visual.segment_eval",
        description="Compare segmenters (SAM 3.1 API vs on-device) on portraits and signatures.",
    )
    parser.add_argument("--candidate", choices=sorted(CANDIDATES), required=True)
    parser.add_argument("--set", choices=sorted(SETS), required=True, dest="set_name")
    parser.add_argument("--cache", type=Path, default=Path("data/visual-cache"))
    parser.add_argument("--offline", action="store_true", help="cached SAM responses only")
    parser.add_argument("--max-live-calls", type=int, default=400)
    parser.add_argument("--json", type=Path, metavar="OUT")
    parser.add_argument("--record", metavar="SLUG", help="write eval/results/runs/<date>-SLUG")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - needs the data sets
    args = build_parser().parse_args(argv)
    candidate = CANDIDATES[args.candidate]

    def log(message: str) -> None:
        print(f"segment_eval: {message}", file=sys.stderr)

    transport = None
    if candidate.name == "sam-api":
        from pii_guard.eval.visual import CachingTransport

        transport = CachingTransport(
            args.cache, max_live_calls=0 if args.offline else args.max_live_calls
        )
    try:
        done = run(candidate, args.set_name, transport=transport, log=log)
    except PiiGuardError as exc:
        log(f"run failed: {exc.code}: {exc.message}")
        return 1
    finally:
        if transport is not None:
            transport.close()
    card = build_card(candidate, args.set_name, done, transport)
    summary = {
        "segmenter": card["segmenter"],
        "latency_ms": {k: v for k, v in card["latency_ms"].items() if k.startswith("segment")},
        "errors": card["errors"],
    }
    print(json.dumps(summary, indent=2))
    if args.json:
        args.json.write_text(json.dumps(card, indent=2) + "\n", encoding="utf-8")
    if args.record:
        from pii_guard.eval.record import write_records

        record = to_record(card, candidate, args.set_name, args.record)
        for path in write_records([record], overwrite=args.overwrite):
            log(f"wrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
