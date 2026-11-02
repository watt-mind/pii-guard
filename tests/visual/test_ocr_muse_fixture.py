"""The recorded Muse Spark Open OCR words (``eval/fixtures/visual/ocr/muse.json``, LAB-1796).

All 24 images are fictional specimens; the visual eval replays the words offline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image

from pii_guard.eval.visual import main
from pii_guard.eval.visual_labels_core import CachedOcr, RecordingOcr, pixel_key
from pii_guard.visual.image import load_image
from pii_guard.visual.ocr import OcrWord
from pii_guard.visual.ocr_muse import PAD_SHARE
from pii_guard.visual.regions import Box

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "eval" / "fixtures" / "visual"
MUSE = FIXTURES / "ocr" / "muse.json"


def test_the_recording_covers_every_fictional_specimen() -> None:
    data = json.loads(MUSE.read_text(encoding="utf-8"))
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    assert data["region_pad_share"] == PAD_SHARE
    assert data["engine"].startswith("muse meta-models/muse-spark-open")
    assert {e["id"] for e in data["images"].values()} == {s["id"] for s in manifest["specimens"]}
    ocr = CachedOcr.load(MUSE, name="muse")
    assert ocr.name == "muse-cached" and ocr.region_pad_share == PAD_SHARE
    first = manifest["specimens"][0]
    image = load_image((FIXTURES / "images" / first["file"]).read_bytes())
    assert ocr.words(image)  # keyed by pixels


def test_recording_round_trips_words_and_padding(tmp_path: Path) -> None:
    class Inner:
        name = "muse"
        model = "synthetic-model"
        region_pad_share = PAD_SHARE

        def words(self, image: Any) -> list[OcrWord]:
            return [OcrWord("Name", Box(1, 2, 30, 12), (0,))]

    class Spec:
        id = "synthetic"
        path = tmp_path / "x.png"

    Image.new("RGB", (40, 20), "white").save(Spec.path)
    image = load_image(Spec.path.read_bytes())
    recorder = RecordingOcr(Inner())
    assert recorder.words(image)[0].text == "Name"
    out = tmp_path / "rec.json"
    recorder.write(out, [Spec], engine="muse")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["images"][pixel_key(image)]["id"] == "synthetic"
    replay = CachedOcr.load(out, name="muse")
    assert replay.words(image) == [OcrWord("Name", Box(1, 2, 30, 12), (0,))]
    assert replay.region_pad_share == PAD_SHARE


def test_the_visual_eval_replays_muse_ocr_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PII_GUARD_SAM_API_KEY", "synthetic-not-a-key")  # the stub only

    def empty_sam(request: httpx.Request) -> httpx.Response:
        assert "meta.ai" in str(request.url), "only the stubbed SAM may be called"
        message = {"type": "message", "content": [{"type": "output_text", "text": ""}]}
        return httpx.Response(200, json={"status": "completed", "output": [message]})

    out = tmp_path / "muse.json"
    code = main(
        [
            "--specimens",
            str(FIXTURES / "images"),
            "--manifest",
            str(FIXTURES / "manifest.json"),
            "--labels",
            str(FIXTURES / "labels.json"),
            "--cache",
            str(tmp_path / "cache"),
            "--country",
            "GB",
            "--ocr-engine",
            "muse",
            "--ocr-replay",
            str(MUSE),
            "--json",
            str(out),
        ],
        inner_transport=httpx.MockTransport(empty_sam),
    )
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["pipeline"]["ocr_engine"] == "muse-cached"
    assert report["errors"] == {}
    text = report["by_region_type"]["text"]
    assert text["recall_cov90"] >= 0.6  # Muse lines + 2 % padding (all sets: 84.5 %)
