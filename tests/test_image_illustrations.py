"""Landing illustration provenance and reproducibility, without inference or API calls."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_illustrations_are_reproducible_and_separate_from_detector_evidence():
    subprocess.run(
        [sys.executable, "scripts/build_image_illustrations.py", "--check"],
        cwd=ROOT,
        check=True,
    )
    for language, suffix, sample in [("en", ".en", "id-card-en"), ("hu", "", "id-card")]:
        content = ROOT / "ui/src/content"
        original = json.loads((content / f"imageLabelsRecording{suffix}.json").read_text())
        illustrated = json.loads((content / f"imageLabelsIllustration.{language}.json").read_text())
        assert illustrated["provenance"]["kind"] == "annotated-illustration"
        assert (
            illustrated["provenance"]["image_sha256"]
            == hashlib.sha256((ROOT / f"ui/public/samples/{sample}.png").read_bytes()).hexdigest()
        )
        for field in ("message", "answer"):
            assert illustrated[field] == original[field]
        assert not {"analysis", "matches", "masked", "kept"} & illustrated["image"].keys()
        regions = illustrated["image"]["regions"]
        assert [r for r in regions if r["source"] == "ocr"] == [
            r for r in original["image"]["regions"] if r["source"] == "ocr"
        ]
        visual = [r for r in regions if r["source"] == "annotation"]
        assert {r["entity_type"] for r in visual} == {"ID_PHOTO", "SIGNATURE"}
        assert all("detector" not in r and "score" not in r for r in visual)
        photo = next(r for r in visual if r["entity_type"] == "ID_PHOTO")
        assert photo["box"] == [48, 120, 288, 432]
        assert photo["cover_box"] == [46, 118, 290, 434]
