"""``pii-guard eval visual``: visual recall of image masking on official specimen ID documents.

```
pii-guard eval visual --specimens data/specimens [--manifest eval/visual/manifest.json]
                      [--labels eval/visual/labels.json] [--cache data/visual-cache]
                      [--offline] [--max-live-calls 800] [--no-ocr] [--country HU,DE]
                      [--detectors rules[,ner,llm]] [--no-captions] [--ocr-upscale 2000]
                      [--prompts JSON] [--prompt-study JSON] [--baseline NAME]
                      [--json OUT] [--markdown OUT]
```

The specimens are fetched by ``eval/visual/fetch_specimens.py`` into a gitignored directory and
never committed (ADR 0005); ``labels.json`` holds the expected regions per image SHA-256
(boxes only). Each image runs through the same pipeline as ``POST /v1/mask/image``
(:class:`~pii_guard.visual.masking.ImageMasker`: SAM 3.1 + OCR + text detectors,
``FACE`` growth, policies), and every expected region is scored against the boxes that were
actually covered:

- **recall@IoU≥0.5**: some single covered box overlaps the region with IoU ≥ 0.5;
- **coverage**: the share of the region's pixels under the union of covered boxes;
  **recall@cov≥0.9** counts regions that are (almost) fully covered;
- **over-masking**: covered pixels outside every expected region, as a share of the image.

SAM requests go through :class:`CachingTransport`, which stores each response under the cache
directory (keyed by a hash of the request body: model, prompt and image), so reruns cost
nothing. ``--max-live-calls`` caps network calls per run; ``--offline`` forbids them. The
report counts SAM calls (live and cached), estimates their cost and reports latency (the SAM
latency recorded when each response was first fetched, plus local OCR/detection time).

``--baseline NAME`` scores an open-source image redaction tool instead of pii-guard, with the
same images and the same scorer (:mod:`pii_guard.eval.baselines.image`): each tool runs in its
own pinned environment and returns the boxes it would black out.

Results contain numbers, region types, countries and specimen ids only, never images or text.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import httpx

from pii_guard.eval.data_dirs import specimens_dir, visual_cache_dir
from pii_guard.eval.stats import fmt_pct, percentile
from pii_guard.eval.visual_core import (
    _BASELINE_LANGUAGE as _BASELINE_LANGUAGE,
)
from pii_guard.eval.visual_core import (
    _LANGUAGE as _LANGUAGE,
)
from pii_guard.eval.visual_core import (
    COVERAGE_THRESHOLD as COVERAGE_THRESHOLD,
)
from pii_guard.eval.visual_core import (
    DEFAULT_CACHE as DEFAULT_CACHE,
)
from pii_guard.eval.visual_core import (
    DEFAULT_LABELS as DEFAULT_LABELS,
)
from pii_guard.eval.visual_core import (
    DEFAULT_MANIFEST as DEFAULT_MANIFEST,
)
from pii_guard.eval.visual_core import (
    DEFAULT_MAX_SIDE as DEFAULT_MAX_SIDE,
)
from pii_guard.eval.visual_core import (
    DEFAULT_SAM_COST as DEFAULT_SAM_COST,
)
from pii_guard.eval.visual_core import (
    DEFAULT_SPECIMENS as DEFAULT_SPECIMENS,
)
from pii_guard.eval.visual_core import (
    EVAL_SAM_TYPES as EVAL_SAM_TYPES,
)
from pii_guard.eval.visual_core import (
    IOU_THRESHOLD as IOU_THRESHOLD,
)
from pii_guard.eval.visual_core import (
    LABEL_TYPES as LABEL_TYPES,
)
from pii_guard.eval.visual_core import (
    PROMPT_TARGETS as PROMPT_TARGETS,
)
from pii_guard.eval.visual_core import (
    REGION_TYPES as REGION_TYPES,
)
from pii_guard.eval.visual_core import (
    BudgetExceeded as BudgetExceeded,
)
from pii_guard.eval.visual_core import (
    CachingTransport as CachingTransport,
)
from pii_guard.eval.visual_core import (
    ExpectedRegion as ExpectedRegion,
)
from pii_guard.eval.visual_core import (
    RegionScore as RegionScore,
)
from pii_guard.eval.visual_core import (
    Specimen as Specimen,
)
from pii_guard.eval.visual_core import (
    SpecimenResult as SpecimenResult,
)
from pii_guard.eval.visual_core import (
    _count as _count,
)
from pii_guard.eval.visual_core import (
    _mask as _mask,
)
from pii_guard.eval.visual_core import (
    _pad as _pad,
)
from pii_guard.eval.visual_core import (
    load_specimens as load_specimens,
)
from pii_guard.eval.visual_core import (
    prepare_image as prepare_image,
)
from pii_guard.eval.visual_core import (
    score_regions as score_regions,
)
from pii_guard.policy import Policy, PolicySet
from pii_guard.types import DetectionError, Detector, EntityType, PiiGuardError
from pii_guard.visual.image import load_image
from pii_guard.visual.ocr import DEFAULT_UPSCALE_TO, OcrEngine
from pii_guard.visual.regions import Region, iou
from pii_guard.visual.sam import DEFAULT_PROMPTS, SamClient

__all__ = [
    "DEFAULT_LABELS",
    "DEFAULT_MANIFEST",
    "REGION_TYPES",
    "CachingTransport",
    "Specimen",
    "build_parser",
    "evaluate",
    "load_specimens",
    "main",
    "prompt_study",
    "render_markdown",
    "score_regions",
]


def evaluate(
    specimens: Sequence[Specimen],
    *,
    sam: SamClient | None,
    transport: CachingTransport | None,
    ocr: OcrEngine | None,
    detector: Detector | None,
    entity_types: Sequence[EntityType] = EVAL_SAM_TYPES,
    captions: bool = True,
    max_side: int = DEFAULT_MAX_SIDE,
    log: Callable[[str], None] = lambda _msg: None,
    baseline: ImageBaseline | None = None,
) -> list[SpecimenResult]:
    """Run the masking pipeline on every specimen and score it. Never raises on one image:
    a failure (fail closed: nothing would have been sent) is recorded as that image's error
    and its regions count as missed. With ``baseline``, that tool masks the images instead
    (``sam``, ``transport``, ``ocr`` and ``detector`` are not used).
    """
    if baseline is not None:
        return _evaluate_baseline(specimens, baseline, max_side=max_side, log=log)
    if sam is None or transport is None:
        raise ValueError("evaluate() needs a SAM client and its transport")
    from pii_guard.visual.masking import ImageMasker

    masker = ImageMasker(
        sam=sam,
        policies=PolicySet(),
        ocr=ocr,
        text_detector=detector,
        entity_types=list(entity_types),
        captions=captions,
    )
    results: list[SpecimenResult] = []
    for specimen in specimens:
        result = SpecimenResult(specimen)
        data = prepare_image(specimen.path.read_bytes(), max_side)
        size = load_image(data).size
        calls_before = len(transport.recorded_ms)
        live_before = transport.live_ms
        start = time.perf_counter()
        try:
            outcome = masker.mask(data, specimen.language or _LANGUAGE.get(specimen.country, "en"))
        except PiiGuardError as exc:
            result.error = exc.code
            covered: list[Region] = []
        else:
            covered = [
                Region(r.region.entity_type, _pad(r.region.box, 2, size), None, r.region.source)
                for r in outcome.regions
                if r.policy is Policy.MASK
            ]
        wall = (time.perf_counter() - start) * 1000
        recorded = transport.recorded_ms[calls_before:]
        result.sam_calls = len(recorded)
        result.sam_ms = sum(recorded)
        result.local_ms = max(0.0, wall - (transport.live_ms - live_before))
        result.regions_masked = len(covered)
        result.scores, result.over_masking = score_regions(specimen.regions, covered, size)
        results.append(result)
        log(f"{specimen.id}: {sum(s.hit_iou for s in result.scores)}/{len(result.scores)}")
    return results


class ImageBaseline(Protocol):
    """An image redaction tool (:class:`~pii_guard.eval.baselines.image.ImageWorkerBaseline`)."""

    name: str
    info: dict[str, Any]
    supports: set[str]

    def mask(self, image: bytes, language: str) -> tuple[list[Region], float]: ...


def _evaluate_baseline(
    specimens: Sequence[Specimen],
    baseline: ImageBaseline,
    *,
    max_side: int,
    log: Callable[[str], None],
) -> list[SpecimenResult]:
    results: list[SpecimenResult] = []
    for specimen in specimens:
        result = SpecimenResult(specimen)
        data = prepare_image(specimen.path.read_bytes(), max_side)
        size = load_image(data).size
        language = specimen.language or _BASELINE_LANGUAGE.get(specimen.country, "en")
        try:
            regions, tool_ms = baseline.mask(data, language)
        except PiiGuardError as exc:
            result.error = exc.code
            regions, tool_ms = [], 0.0
        # The same 2 px padding pii-guard's covered boxes get.
        covered = [Region(r.entity_type, _pad(r.box, 2, size), None, r.source) for r in regions]
        result.local_ms = tool_ms
        result.regions_masked = len(covered)
        result.scores, result.over_masking = score_regions(specimen.regions, covered, size)
        results.append(result)
        log(f"{specimen.id}: {sum(s.hit_iou for s in result.scores)}/{len(result.scores)}")
    return results


def build_baseline_report(
    results: Sequence[SpecimenResult], baseline: ImageBaseline, *, max_side: int
) -> dict[str, Any]:
    """The report for a baseline run: region types the tool can't mask are left out of the
    per-type breakdowns (``unsupported_region_types``) and stay in ``overall``."""
    report = build_report(
        results,
        transport=None,
        sam=None,
        entity_types=(),
        ocr_engine=None,
        detector_name=None,
        sam_cost=0.0,
        max_side=max_side,
    )
    unsupported = [t for t in REGION_TYPES if t not in baseline.supports]
    for t in unsupported:
        report["by_region_type"].pop(t, None)
        for group in report["by_country"].values():
            group["by_type"].pop(t, None)
    report["pipeline"] = {
        "baseline": baseline.name,
        "info": baseline.info,
        "unsupported_region_types": unsupported,
        "max_side": max_side,
        "iou_threshold": IOU_THRESHOLD,
        "coverage_threshold": COVERAGE_THRESHOLD,
    }
    report.pop("sam")
    for key in [k for k in report["latency_ms"] if k.startswith("sam_")]:
        report["latency_ms"].pop(key)
    return report


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _group(scores: Sequence[RegionScore]) -> dict[str, Any]:
    n = len(scores)
    return {
        "regions": n,
        "recall_iou50": _ratio(sum(s.hit_iou for s in scores), n),
        "recall_cov90": _ratio(sum(s.hit_coverage for s in scores), n),
        "mean_coverage": round(statistics.fmean(s.coverage for s in scores), 4) if n else None,
    }


def build_report(
    results: Sequence[SpecimenResult],
    *,
    transport: CachingTransport | None,
    sam: SamClient | None,
    entity_types: Sequence[EntityType],
    ocr_engine: str | None,
    detector_name: str | None,
    sam_cost: float,
    max_side: int,
    captions: bool = True,
    ocr_upscale_to: int | None = None,
) -> dict[str, Any]:
    all_scores = [s for r in results for s in r.scores]
    by_type = {t: _group([s for s in all_scores if s.type == t]) for t in REGION_TYPES}
    for t in REGION_TYPES:
        matched = Counter(s.matched_by for s in all_scores if s.type == t and s.hit_iou)
        by_type[t]["matched_by"] = dict(sorted((k or "none", v) for k, v in matched.items()))
    countries = sorted({r.specimen.country for r in results})
    by_country: dict[str, Any] = {}
    for country in countries:
        rows = [r for r in results if r.specimen.country == country]
        scores = [s for r in rows for s in r.scores]
        group = _group(scores)
        group["specimens"] = len(rows)
        group["by_type"] = {
            t: _group([s for s in scores if s.type == t])
            for t in REGION_TYPES
            if any(s.type == t for s in scores)
        }
        by_country[country] = group
    by_doc_type: dict[str, Any] = {}
    for doc_type in sorted({r.specimen.doc_type for r in results}):
        rows = [r for r in results if r.specimen.doc_type == doc_type]
        group = _group([s for r in rows for s in r.scores])
        group["specimens"] = len(rows)
        by_doc_type[doc_type] = group
    total_calls = sum(r.sam_calls for r in results)
    sam_ms = [r.sam_ms for r in results]
    local_ms = [r.local_ms for r in results]
    total_ms = [r.sam_ms + r.local_ms for r in results]
    per_call = transport.recorded_ms if transport is not None else []
    live_calls = transport.live_calls if transport is not None else 0
    return {
        "suite": "visual-specimens",
        "pipeline": {
            "sam_model": sam.model if sam is not None else None,
            "sam_types": [t.value for t in entity_types],
            "sam_prompts": {t.value: list(sam.prompts[t]) for t in entity_types}
            if sam is not None
            else {},
            "ocr_engine": ocr_engine,
            "text_detector": detector_name,
            "captions": captions if ocr_engine else False,
            "ocr_upscale_to": ocr_upscale_to if ocr_engine else None,
            "max_side": max_side,
            "iou_threshold": IOU_THRESHOLD,
            "coverage_threshold": COVERAGE_THRESHOLD,
        },
        "specimens": len(results),
        "errors": dict(Counter(r.error for r in results if r.error)),
        "overall": _group(all_scores),
        "by_region_type": by_type,
        "by_country": by_country,
        "by_doc_type": by_doc_type,
        "over_masking_mean": round(statistics.fmean(r.over_masking for r in results), 4)
        if results
        else None,
        "sam": {
            "calls": total_calls,
            "calls_per_image": round(total_calls / len(results), 2) if results else None,
            "live_calls_this_run": live_calls,
            "cached_calls_this_run": transport.cached_calls if transport is not None else 0,
            "cost_per_call_usd": sam_cost,
            "estimated_cost_usd": round(total_calls * sam_cost, 4),
            "spent_this_run_usd": round(live_calls * sam_cost, 4),
        },
        "latency_ms": {
            "sam_call_p50": percentile(per_call, 0.5, 1),
            "sam_call_p95": percentile(per_call, 0.95, 1),
            "sam_per_image_p50": percentile(sam_ms, 0.5, 1),
            "sam_per_image_p95": percentile(sam_ms, 0.95, 1),
            "local_per_image_p50": percentile(local_ms, 0.5, 1),
            "local_per_image_p95": percentile(local_ms, 0.95, 1),
            "total_per_image_p50": percentile(total_ms, 0.5, 1),
            "total_per_image_p95": percentile(total_ms, 0.95, 1),
        },
        "per_specimen": [
            {
                "id": r.specimen.id,
                "country": r.specimen.country,
                "doc_type": r.specimen.doc_type,
                "side": r.specimen.side,
                "regions": len(r.scores),
                "hits_iou50": sum(s.hit_iou for s in r.scores),
                "hits_cov90": sum(s.hit_coverage for s in r.scores),
                "regions_masked": r.regions_masked,
                "over_masking": round(r.over_masking, 4),
                "sam_calls": r.sam_calls,
                "error": r.error,
            }
            for r in results
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    pipe = report["pipeline"]
    if "baseline" in pipe:
        unsupported = pipe.get("unsupported_region_types") or []
        system = (
            f"{report['specimens']} specimen images, baseline `{pipe['baseline']}` "
            f"({pipe['info'].get('tool')}"
            + (f"; can't mask {', '.join(unsupported)}" if unsupported else "")
            + ")"
        )
    else:
        system = (
            f"{report['specimens']} specimen images, SAM `{pipe['sam_model']}` "
            f"({', '.join(pipe['sam_types'])}), OCR `{pipe['ocr_engine'] or 'off'}`, "
            f"text detector `{pipe['text_detector'] or 'off'}`"
            + (
                f" (OCR on images enlarged to {pipe['ocr_upscale_to']} px)"
                if pipe.get("ocr_upscale_to")
                else ""
            )
        )
    lines = [
        f"# {report.get('title') or 'Visual recall on official specimen ID documents'}",
        "",
        system + f". A region is a hit at IoU ≥ "
        f"{pipe['iou_threshold']} with one covered box; coverage is the share of its pixels "
        f"under any mask (cov ≥ {pipe['coverage_threshold']} = fully covered).",
        "",
        "| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, group in [*report["by_region_type"].items(), ("**all**", report["overall"])]:
        lines.append(
            f"| {name} | {group['regions']} | {fmt_pct(group['recall_iou50'])} | "
            f"{fmt_pct(group['recall_cov90'])} | {fmt_pct(group['mean_coverage'])} |"
        )
    lines += [
        "",
        "| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | "
        "Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for country, group in report["by_country"].items():
        per = group["by_type"]
        cells = [fmt_pct(per[t]["recall_iou50"]) if t in per else "-" for t in REGION_TYPES]
        lines.append(
            f"| {country} | {group['specimens']} | {group['regions']} | "
            f"{fmt_pct(group['recall_iou50'])} | {fmt_pct(group['recall_cov90'])} | "
            + " | ".join(cells)
            + " |"
        )
    lines += ["", "| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |"]
    lines.append("|---|---:|---:|---:|---:|")
    for doc_type, group in report["by_doc_type"].items():
        lines.append(
            f"| {doc_type} | {group['specimens']} | {group['regions']} | "
            f"{fmt_pct(group['recall_iou50'])} | {fmt_pct(group['recall_cov90'])} |"
        )
    sam, lat = report.get("sam"), report["latency_ms"]
    lines += [
        "",
        f"Over-masking (covered area outside every labelled region, mean share of the image): "
        f"{fmt_pct(report['over_masking_mean'])} %. Errors: {report['errors'] or 'none'}.",
        "",
    ]
    if sam is None:
        lines += [
            f"Latency (the tool's own time per image, without the worker pipe): p50 "
            f"{lat['local_per_image_p50']} ms / p95 {lat['local_per_image_p95']} ms.",
            "",
        ]
        return "\n".join(lines)
    lines += [
        f"SAM: {sam['calls']} calls ({sam['calls_per_image']} per image), estimated "
        f"${sam['estimated_cost_usd']:.2f} at ${sam['cost_per_call_usd']}/call; this run "
        f"{sam['live_calls_this_run']} live, {sam['cached_calls_this_run']} cached.",
        f"Latency: SAM per call p50 {lat['sam_call_p50']} ms / p95 {lat['sam_call_p95']} ms; "
        f"SAM per image p50 {lat['sam_per_image_p50']} ms / p95 {lat['sam_per_image_p95']} ms "
        f"(sequential calls); OCR + detection per image p50 {lat['local_per_image_p50']} ms / "
        f"p95 {lat['local_per_image_p95']} ms"
        + (
            f"; total per image p50 {lat['total_per_image_p50']} ms / p95 "
            f"{lat['total_per_image_p95']} ms."
            if "total_per_image_p50" in lat
            else "."
        ),
        "",
    ]
    return "\n".join(lines)


# --- prompt study ----------------------------------------------------------------------------


def prompt_study(
    specimens: Sequence[Specimen],
    candidates: Mapping[EntityType, Sequence[str]],
    *,
    transport: CachingTransport,
    sam_factory: Callable[[dict[EntityType, tuple[str, ...]]], SamClient],
    max_side: int = DEFAULT_MAX_SIDE,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Score each candidate prompt on its own (SAM only, raw boxes) against its target types.

    Each entity type's prompts run on the specimens that contain one of its target region
    types (at most ``limit`` of them, evenly spread), so every prompt sees the same images.
    Each row also breaks recall down by document type (``by_variant``; in the prompt-study set
    the document type is the variant: scribble, script, scanned, ...).
    """
    from pii_guard.visual.masking import grow_face

    rows: list[dict[str, Any]] = []
    cache: dict[str, bytes] = {}

    def prepared_for(targets: tuple[str, ...]) -> list[tuple[Specimen, bytes]]:
        chosen = [s for s in specimens if any(e.type in targets for e in s.regions)]
        if limit is not None and len(chosen) > limit:
            step = len(chosen) / limit
            chosen = [chosen[int(i * step)] for i in range(limit)]
        out = []
        for specimen in chosen:
            if specimen.sha256 not in cache:
                cache[specimen.sha256] = prepare_image(specimen.path.read_bytes(), max_side)
            out.append((specimen, cache[specimen.sha256]))
        return out

    for entity_type, prompts in candidates.items():
        targets = PROMPT_TARGETS.get(entity_type, ())
        prepared = prepared_for(targets)
        for prompt in prompts:
            client = sam_factory({entity_type: (prompt,)})
            scores: list[RegionScore] = []
            by_variant: dict[str, list[RegionScore]] = {}
            found = errors = stray = 0
            calls_before = transport.live_calls + transport.cached_calls
            for specimen, data in prepared:
                size = load_image(data).size
                expected = [e for e in specimen.regions if e.type in targets]
                try:
                    regions = client.segment(data, [entity_type])
                except PiiGuardError:
                    errors += 1
                    regions = []
                regions = [grow_face(r, *size) for r in regions]
                found += len(regions)
                image_scores, _ = score_regions(expected, regions, size)
                scores.extend(image_scores)
                by_variant.setdefault(specimen.doc_type, []).extend(image_scores)
                boxes = [e.to_pixels(*size) for e in expected]
                stray += sum(1 for r in regions if all(iou(r.box, b) < 0.1 for b in boxes))
            group = _group(scores)
            rows.append(
                {
                    "entity_type": entity_type.value,
                    "prompt": prompt,
                    "targets": list(targets),
                    "images": len(prepared),
                    **group,
                    "regions_found": found,
                    "stray_regions": stray,
                    "errors": errors,
                    "calls": transport.live_calls + transport.cached_calls - calls_before,
                    "by_variant": {k: _group(v) for k, v in sorted(by_variant.items())},
                }
            )
    return rows


def render_prompt_study(rows: Sequence[dict[str, Any]]) -> str:
    lines = [
        "# SAM prompt study (SAM only, one prompt at a time)",
        "",
        "| Type | Prompt | Targets | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | "
        "Mean coverage % | Found | Stray | Errors |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['entity_type']} | `{row['prompt']}` | {', '.join(row['targets'])} | "
            f"{row['regions']} | {fmt_pct(row['recall_iou50'])} | {fmt_pct(row['recall_cov90'])} | "
            f"{fmt_pct(row['mean_coverage'])} | {row['regions_found']} | {row['stray_regions']} | "
            f"{row['errors']} |"
        )
    variants = [row for row in rows if len(row.get("by_variant", {})) > 1]
    if variants:
        lines += [
            "",
            "## By variant",
            "",
            "| Type | Prompt | Variant | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | "
            "Mean coverage % |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
        for row in variants:
            for variant, group in row["by_variant"].items():
                lines.append(
                    f"| {row['entity_type']} | `{row['prompt']}` | {variant} | "
                    f"{group['regions']} | "
                    f"{fmt_pct(group['recall_iou50'])} | {fmt_pct(group['recall_cov90'])} | "
                    f"{fmt_pct(group['mean_coverage'])} |"
                )
    return "\n".join(lines) + "\n"


# --- CLI -------------------------------------------------------------------------------------


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _parse_prompts(value: str) -> dict[EntityType, tuple[str, ...]]:
    raw = json.loads(Path(value).read_text("utf-8") if Path(value).is_file() else value)
    return {EntityType(k): tuple(v) for k, v in raw.items()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pii-guard eval visual",
        description="Visual recall of image masking on official specimen ID documents.",
    )
    parser.add_argument(
        "--specimens",
        type=Path,
        default=specimens_dir(),
        help="specimen images (default: PII_GUARD_SPECIMENS_DIR, else data/specimens)",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument(
        "--cache",
        type=Path,
        default=visual_cache_dir(),
        help="SAM response cache (default: PII_GUARD_VISUAL_CACHE, else data/visual-cache)",
    )
    parser.add_argument("--offline", action="store_true", help="cached SAM responses only")
    parser.add_argument(
        "--max-live-calls", type=int, default=800, help="cap on live SAM calls in this run"
    )
    parser.add_argument("--sam-cost", type=float, default=DEFAULT_SAM_COST, metavar="USD")
    parser.add_argument("--no-ocr", action="store_true", help="SAM only (no OCR text masking)")
    parser.add_argument(
        "--detectors",
        type=_csv,
        default=["rules"],
        help="text detectors for OCR text, comma-separated (rules,ner,llm)",
    )
    parser.add_argument(
        "--no-captions",
        action="store_true",
        help="don't mask the values next to known field captions (visual/captions.py)",
    )
    parser.add_argument(
        "--ocr-upscale",
        type=int,
        default=DEFAULT_UPSCALE_TO,
        metavar="PX",
        help="enlarge images for OCR to this longer side (0: read them as they are)",
    )
    parser.add_argument("--country", type=_csv, help="only these countries (comma-separated)")
    parser.add_argument("--max-side", type=int, default=DEFAULT_MAX_SIDE)
    parser.add_argument(
        "--prompts", type=_parse_prompts, help='prompt override, e.g. {"FACE": ["face"]}'
    )
    parser.add_argument(
        "--prompt-study",
        type=_parse_prompts,
        metavar="JSON",
        help="score these candidate prompts one by one instead of running the pipeline",
    )
    parser.add_argument(
        "--limit", type=int, help="prompt study: at most this many images per entity type"
    )
    parser.add_argument(
        "--baseline",
        metavar="NAME",
        help="score this open-source image redaction tool instead of pii-guard "
        "(presidio-image, presidio-image-tuned, eka, eka-tuned)",
    )
    parser.add_argument("--title", help="report heading (default: the official specimen set)")
    parser.add_argument("--json", type=Path, metavar="OUT")
    parser.add_argument("--markdown", type=Path, metavar="OUT")
    return parser


def _ocr_and_detector(
    args: argparse.Namespace,
) -> tuple[OcrEngine | None, Detector | None, str | None]:
    """The OCR engine, the text detector (one detector, or the pipeline the API runs for
    several) and its report name (``rules+llm``)."""
    if args.no_ocr:
        return None, None, None
    from pii_guard.visual.ocr import TesseractOcr, tesseract_available

    if not tesseract_available():
        raise DetectionError("OCR unavailable (install the 'ocr' extra and tesseract)")
    ocr = TesseractOcr(upscale_to=args.ocr_upscale or None)
    names = list(dict.fromkeys(args.detectors))
    if len(names) == 1:
        from pii_guard.registry import create_detector

        detector: Detector = create_detector(names[0])
        loaded = [getattr(detector, "name", names[0])]
    else:
        from pii_guard.eval.scorer import DetectorAnalyzer
        from pii_guard.visual.masking import AnalyzerDetector

        analyzer = DetectorAnalyzer(names)
        if analyzer.skipped:
            reasons = "; ".join(f"{name}: {reason}" for name, reason in analyzer.skipped)
            raise DetectionError(f"text detector unavailable ({reasons})")
        detector = AnalyzerDetector(analyzer)
        loaded = analyzer.loaded
    if not args.no_captions:
        loaded.append("captions")
    return ocr, detector, "+".join(loaded)


def _write(args: argparse.Namespace, output: dict[str, Any], markdown: str) -> None:
    sys.stdout.write(markdown)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")


def _run_baseline(
    args: argparse.Namespace,
    specimens: Sequence[Specimen],
    log: Callable[[str], None],
    *,
    factory: Callable[[str], ImageBaseline] | None = None,
) -> int:
    from pii_guard.eval.baselines.base import BaselineUnavailable

    if factory is None:
        from pii_guard.eval.baselines.image import create_image_baseline

        factory = create_image_baseline
    try:
        baseline = factory(args.baseline)
    except BaselineUnavailable as exc:
        log(f"baseline {args.baseline} unavailable: {exc.reason}")
        return 2
    try:
        results = evaluate(
            specimens,
            sam=None,
            transport=None,
            ocr=None,
            detector=None,
            max_side=args.max_side,
            log=log,
            baseline=baseline,
        )
    finally:
        close = getattr(baseline, "close", None)
        if close is not None:
            close()
    output = build_baseline_report(results, baseline, max_side=args.max_side)
    if args.title:
        output = {"title": args.title, **output}
    _write(args, output, render_markdown(output))
    return 0


def main(
    argv: Sequence[str] | None = None, *, inner_transport: httpx.BaseTransport | None = None
) -> int:
    args = build_parser().parse_args(argv)

    def log(message: str) -> None:
        print(f"pii-guard eval visual: {message}", file=sys.stderr)

    try:
        specimens = load_specimens(
            args.manifest, args.labels, args.specimens, countries=args.country, log=log
        )
    except (OSError, ValueError, KeyError) as exc:
        log(f"cannot load specimens: {type(exc).__name__}: {exc}")
        return 2
    if not specimens:
        log("no labelled specimen images found (run eval/visual/fetch_specimens.py first)")
        return 2

    if args.baseline:
        return _run_baseline(args, specimens, log)

    transport = CachingTransport(
        args.cache, inner_transport, max_live_calls=0 if args.offline else args.max_live_calls
    )
    prompts = dict(DEFAULT_PROMPTS)
    if args.prompts:
        prompts.update(args.prompts)

    def sam_factory(override: dict[EntityType, tuple[str, ...]] | None = None) -> SamClient:
        # Offline, nothing reaches the network, so a placeholder key lets cached runs work
        # without the real one.
        key = "offline-cache-only" if args.offline else None
        return SamClient(
            prompts=override or prompts, transport=transport, max_retries=2, api_key=key
        )

    try:
        if args.prompt_study:
            rows = prompt_study(
                specimens,
                args.prompt_study,
                transport=transport,
                sam_factory=sam_factory,
                max_side=args.max_side,
                limit=args.limit,
            )
            output: dict[str, Any] = {
                "suite": "visual-prompt-study",
                "specimens": len(specimens),
                "rows": rows,
                "sam_live_calls_this_run": transport.live_calls,
                "sam_cached_calls_this_run": transport.cached_calls,
            }
            markdown = render_prompt_study(rows)
        else:
            ocr, detector, detector_name = _ocr_and_detector(args)
            sam = sam_factory()
            results = evaluate(
                specimens,
                sam=sam,
                transport=transport,
                ocr=ocr,
                detector=detector,
                max_side=args.max_side,
                captions=not args.no_captions,
                log=log,
            )
            output = build_report(
                results,
                transport=transport,
                sam=sam,
                entity_types=EVAL_SAM_TYPES,
                ocr_engine=getattr(ocr, "name", None),
                detector_name=detector_name,
                sam_cost=args.sam_cost,
                max_side=args.max_side,
                captions=not args.no_captions,
                ocr_upscale_to=args.ocr_upscale or None,
            )
            if args.title:
                output = {"title": args.title, **output}
            markdown = render_markdown(output)
    except PiiGuardError as exc:
        log(f"run failed: {exc.code}: {exc.message}")
        return 1
    finally:
        transport.close()

    log(f"SAM calls this run: {transport.live_calls} live, {transport.cached_calls} cached")
    _write(args, output, markdown)
    return 0
