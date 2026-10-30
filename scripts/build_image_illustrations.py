"""Build explicitly annotated landing illustrations, never detector evidence.

Uses hash-bound synthetic composition annotations for portrait/signature geometry and
retains the original recording's OCR, message and text-only answer. No inference or
network calls. Original detector regions and metrics remain separate and unchanged.
Run with --check in CI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from record_image_labels import SAMPLES, _label_fit, assert_value_free

from pii_guard.visual.regions import Box
from pii_guard.visual.render import LabelBox, render_labels

ROOT = Path(__file__).resolve().parent.parent


def build(key: str) -> dict:
    sample = SAMPLES[key]
    original = json.loads(sample.out.read_text())
    image = original["image"]
    png = sample.image.read_bytes()
    sha = hashlib.sha256(png).hexdigest()
    labels = json.loads((ROOT / "eval/fixtures/visual/labels.json").read_text())
    specimen = labels["specimens"][sha]
    if specimen["id"] != sample.fixture_id:
        raise ValueError("fixture identity mismatch")
    holder = image["summary"]["holder"]
    regions = [r for r in image["regions"] if r["source"] == "ocr"]
    for annotation in specimen["regions"]:
        kind = annotation["type"]
        if kind not in ("portrait", "signature"):
            continue
        # Annotations are rounded to four decimals; nearest integer recovers original
        # composition pixels (these fixtures are 1012 x 638). No heuristic face padding.
        box = [
            round(n * image["width" if i % 2 == 0 else "height"])
            for i, n in enumerate(annotation["box"])
        ]
        label = f"PHOTO · {holder}" if kind == "portrait" else "SIGNATURE"
        # Use the repository renderer for coverage, without label-driven expansion.
        # Fit the explanatory label inside that geometry afterwards.
        rendered = render_labels(png, [LabelBox(Box(*box), None)])
        cover = rendered.boxes[0]
        if cover is None:
            raise ValueError("annotation outside image")
        region = dict(
            entity_type="ID_PHOTO" if kind == "portrait" else "SIGNATURE",
            box=box,
            source="annotation",
            policy="mask",
            label=label,
            cover_box=[cover.x1, cover.y1, cover.x2, cover.y2],
        )
        regions.append({**region, **_label_fit(region)})
    return {
        "recorded": original["recorded"],
        "provenance": {
            "kind": "annotated-illustration",
            "image_sha256": sha,
            "geometry": (
                "eval/fixtures/visual/labels.json: composition portrait and signature "
                "annotations; repository renderer padding, no label expansion"
            ),
            "text_recording": sample.out.name,
            "note": (
                "OCR, message, summary, transcript and text-only Muse answer retained from "
                "the original recording. Visual boxes are annotations, not detector output. "
                "No detection metrics claimed."
            ),
        },
        "message": original["message"],
        "image": {k: image[k] for k in ("media_type", "width", "height", "transcript", "summary")}
        | {"regions": regions},
        "answer": original["answer"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for key, sample in SAMPLES.items():
        illustration = build(key)
        assert_value_free(illustration, sample)
        target = sample.out.with_name(f"imageLabelsIllustration.{key}.json")
        content = json.dumps(illustration, ensure_ascii=False, indent=2) + "\n"
        if args.check:
            if target.read_text() != content:
                raise SystemExit(f"{target.name}: stale illustration")
        else:
            target.write_text(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
