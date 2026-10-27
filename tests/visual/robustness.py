"""OCR robustness on turned, skewed and large images (LAB-1210): aggregates only.

```
uv run --no-sync python tests/visual/robustness.py --set fictional --json OUT.json
    [--before] [--compare BEFORE.json --markdown OUT.md] [--transforms 0,90,5] [--jobs 6]
PII_GUARD_SPECIMENS_DIR=... uv run --no-sync python tests/visual/robustness.py --set specimens
```

Every labelled document (``fictional``: ``eval/fixtures/visual``; ``specimens``: the local,
never committed official specimens of ``eval/visual/manifest.json``) is turned by each
transform of ``eval/fixtures/visual/robustness.json`` (Pillow ``rotate`` with expand and a
white fill) and masked by the image pipeline with OCR and the rules detector, no SAM
(``ImageMasker`` with a segmenter that finds nothing: no network, no cost). The cover is
turned back onto the upright document and every labelled ``text`` and ``mrz`` region is
scored: covered when at least 90 % of its pixels are under the cover. ``lost`` counts regions
covered upright but not turned. The synthetic screenshots of ``robustness.json`` are scored
by whether both their fictional identifiers were masked.

``--before`` reads with orientation, deskew and the small-text pass off: the OCR as it was
before LAB-1210. Output holds counts, shares and timings only, never images or text.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, ClassVar

os.environ.setdefault("OMP_THREAD_LIMIT", "1")  # one Tesseract thread per worker process

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "eval" / "fixtures" / "visual" / "robustness.json"
SETS = {
    "fictional": (
        ROOT / "eval/fixtures/visual/manifest.json",
        ROOT / "eval/fixtures/visual/labels.json",
        ROOT / "eval/fixtures/visual/images",
    ),
    "specimens": (ROOT / "eval/visual/manifest.json", ROOT / "eval/visual/labels.json", None),
}
SCORED = ("text", "mrz")
COVERED = 0.9

_MASKER: Any = None


def _masker(before: bool) -> Any:
    global _MASKER
    if _MASKER is None:
        from pii_guard.api.routes.image_masking import ImageMasker
        from pii_guard.detect.rules import RuleDetector
        from pii_guard.policy import PolicySet
        from pii_guard.types import EntityType
        from pii_guard.visual.ocr import TesseractOcr

        class NoSam:
            model = "none"
            prompts: ClassVar = {EntityType.FACE: ("face",)}

            def segment(self, image: bytes, entity_types: object = None) -> list[object]:
                return []

        off = {"orient": False, "deskew": False, "small_text": False} if before else {}
        _MASKER = ImageMasker(
            sam=NoSam(),  # type: ignore[arg-type]
            policies=PolicySet(),
            ocr=TesseractOcr(**off),  # type: ignore[arg-type]
            text_detector=RuleDetector(),
        )
    return _MASKER


def _mask(image: Image.Image, language: str, before: bool) -> tuple[list[Any], float, str | None]:
    from pii_guard.policy import Policy
    from pii_guard.types import PiiGuardError
    from pii_guard.visual.image import encode_image

    start = time.perf_counter()
    try:
        outcome = _masker(before).mask(encode_image(image), language)
    except PiiGuardError as exc:
        return [], (time.perf_counter() - start) * 1000, exc.code
    regions = [r.region for r in outcome.regions if r.policy is Policy.MASK]
    return regions, (time.perf_counter() - start) * 1000, None


def _document(
    job: tuple[str, str, list[tuple[str, tuple[float, ...]]], float, bool],
) -> dict[str, Any]:
    from pii_guard.eval.visual import ExpectedRegion, prepare_image
    from pii_guard.visual.image import load_image

    path, language, labels, angle, before = job
    upright = load_image(prepare_image(Path(path).read_bytes()))
    width, height = upright.size
    turned = (
        upright
        if not angle
        else upright.rotate(angle, Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    )
    regions, ms, error = _mask(turned, language, before)
    cover = Image.new("L", turned.size, 0)
    draw = ImageDraw.Draw(cover)
    for region in regions:  # padded by 2 px, as the eval scores
        box = region.box
        draw.rectangle([box.x1 - 2, box.y1 - 2, box.x2 + 2, box.y2 + 2], fill=255)
    if angle:
        back = cover.rotate(-angle, Image.Resampling.NEAREST, expand=True)
        left, top = (back.width - width) // 2, (back.height - height) // 2
        cover = back.crop((left, top, left + width, top + height))
    covered = []
    for kind, box in labels:
        if kind not in SCORED:
            continue
        b = ExpectedRegion(kind, box).to_pixels(width, height)  # type: ignore[arg-type]
        area = b.width * b.height
        inside = cover.crop((b.x1, b.y1, b.x2 + 1, b.y2 + 1)).histogram()[255]
        covered.append(area > 0 and inside / area >= COVERED)
    return {"angle": angle, "covered": covered, "ms": ms, "error": error}


def _screenshot(job: tuple[dict[str, Any], bool]) -> dict[str, Any]:
    from pii_guard.types import EntityType

    shot, before = job
    image = Image.new("RGB", tuple(shot["size"]), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=shot["font_size"])
    for x, y, text in shot["lines"]:
        draw.text((x, y), text, fill="black", font=font)
    regions, ms, error = _mask(image, "hu", before)
    found = {r.entity_type for r in regions}
    wanted = {EntityType.NATIONAL_ID_HU_TAJ, EntityType.NATIONAL_ID_HU_TAX}
    return {
        "id": shot["id"],
        "masked": len(found & wanted),
        "values": len(wanted),
        "ms": ms,
        "error": error,
    }


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))])


def run(name: str, transforms: Sequence[float], before: bool, jobs: int) -> dict[str, Any]:
    from pii_guard.eval.data_dirs import specimens_dir
    from pii_guard.eval.visual import _LANGUAGE, load_specimens

    manifest, labels, images = SETS[name]
    specimens = load_specimens(manifest, labels, images or specimens_dir())
    if not specimens:
        raise SystemExit(f"no {name} images found")
    work = [
        (
            str(s.path),
            s.language or _LANGUAGE.get(s.country, "en"),
            [(r.type, r.box) for r in s.regions],
            float(angle),
            before,
        )
        for angle in transforms
        for s in specimens
    ]
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    with ProcessPoolExecutor(jobs) as pool:
        documents = list(pool.map(_document, work))
        shots = (
            list(pool.map(_screenshot, [(s, before) for s in spec["screenshots"]]))
            if name == "fictional"
            else []
        )
    count = len(specimens)
    upright = documents[:count] if transforms[0] == 0 else None
    rows: dict[str, Any] = {}
    for i, angle in enumerate(transforms):
        block = documents[i * count : (i + 1) * count]
        flags = [c for d in block for c in d["covered"]]
        lost = None
        if upright is not None:
            lost = sum(
                u and not t
                for up, d in zip(upright, block, strict=True)
                for u, t in zip(up["covered"], d["covered"], strict=True)
            )
        ms = [d["ms"] for d in block]
        rows[f"{angle:g}"] = {
            "regions": len(flags),
            "covered": sum(flags),
            "covered_pct": round(100 * sum(flags) / len(flags), 1) if flags else None,
            "lost_vs_upright": lost,
            "errors": sum(d["error"] is not None for d in block),
            "ms_p50": _percentile(ms, 0.5),
            "ms_p95": _percentile(ms, 0.95),
        }
    return {
        "suite": "visual-ocr-robustness",
        "set": name,
        "ocr": "before LAB-1210 (no orientation, deskew or small-text pass)"
        if before
        else "LAB-1210",
        "images": count,
        "scored_types": list(SCORED),
        "covered_at": COVERED,
        "transforms": rows,
        "screenshots": [
            {k: v for k, v in s.items() if k != "ms"} | {"ms": round(s["ms"])} for s in shots
        ],
    }


def render_markdown(after: dict[str, Any], before: dict[str, Any] | None = None) -> str:
    lines = [
        f"# OCR robustness: {after['set']} set, turned and skewed (LAB-1210)",
        "",
        f"{after['images']} documents, OCR (Tesseract) + rules detector, no SAM. A labelled "
        f"{' / '.join(after['scored_types'])} region counts as covered when ≥ "
        f"{after['covered_at']:.0%} of it is masked, scored after turning the cover back onto "
        "the upright document. Transforms are degrees counter-clockwise; latency is per image, "
        "OCR and detection, six images at a time on one machine.",
        "",
        "| Transform | Regions | Covered before % | Covered after % "
        "| Lost vs upright before → after | ms p50 before → after | ms p95 before → after |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key, row in after["transforms"].items():
        old = (before or {}).get("transforms", {}).get(key, {})
        lines.append(
            f"| {key}° | {row['regions']} | {old.get('covered_pct', '-')} | {row['covered_pct']} | "
            f"{old.get('lost_vs_upright', '-')} → {row['lost_vs_upright']} | "
            f"{old.get('ms_p50', '-')} → {row['ms_p50']} | "
            f"{old.get('ms_p95', '-')} → {row['ms_p95']} |"
        )
    if after["screenshots"]:
        lines += [
            "",
            "| Screenshot | Identifiers masked before | after | ms after |",
            "|---|---:|---:|---:|",
        ]
        old_shots = {s["id"]: s for s in (before or {}).get("screenshots", [])}
        for shot in after["screenshots"]:
            old = old_shots.get(shot["id"], {})
            lines.append(
                f"| {shot['id']} | {old.get('masked', '-')}/{shot['values']} | "
                f"{shot['masked']}/{shot['values']} | {shot['ms']} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--set", choices=sorted(SETS), required=True)
    parser.add_argument("--transforms", help="comma-separated degrees (default: robustness.json)")
    parser.add_argument("--before", action="store_true", help="the OCR before LAB-1210")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--json", type=Path, metavar="OUT")
    parser.add_argument(
        "--markdown", type=Path, metavar="OUT", help="with --compare: a before/after table"
    )
    parser.add_argument(
        "--compare", type=Path, metavar="BEFORE_JSON", help="the --before run to compare with"
    )
    args = parser.parse_args(argv)
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    transforms = (
        [float(a) for a in args.transforms.split(",")] if args.transforms else spec["transforms"]
    )
    report = run(args.set, transforms, args.before, args.jobs)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.markdown:
        before = json.loads(args.compare.read_text(encoding="utf-8")) if args.compare else None
        args.markdown.write_text(render_markdown(report, before), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
