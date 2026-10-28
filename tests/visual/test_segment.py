"""LocalSegmenter (on-device faces and ID photos, LAB-1229) and the segmenter comparison scorer.

Most tests inject a fake YuNet detector, so they need neither OpenCV nor the model file. The
real-model test runs only when OpenCV is installed (``uv sync --extra local-vision``) and the
pinned YuNet file is in the model directory; it uses a committed fictional card.
"""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image
from visual_helpers import id_card_png

from pii_guard.types import DetectionError, EntityType
from pii_guard.visual import segment
from pii_guard.visual.regions import Box, Region
from pii_guard.visual.sam import SamClient
from pii_guard.visual.segment import (
    LOCAL_ENTITY_TYPES,
    YUNET,
    LocalSegmenter,
    ModelFile,
    Segmenter,
    fetch_model,
    model_dir,
    nms,
    photo_box,
)
from pii_guard.visual.segment_eval import CANDIDATES, SCORED_TYPES, build_parser, score_image

ROOT = Path(__file__).resolve().parents[2]
FICTIONAL_CARD = ROOT / "eval" / "fixtures" / "visual" / "images" / "hu-id_card-front.png"


class FakeDetector:
    """Answers like cv2.FaceDetectorYN: rows of x, y, w, h, 10 landmark values, score."""

    def __init__(
        self, faces: list[tuple[float, float, float, float, float]], width: int = 640
    ) -> None:
        self.faces = faces  # in the pixel grid of the original image, ``width`` wide
        self.width = width
        self.sizes: list[tuple[int, int]] = []

    def setInputSize(self, size: tuple[int, int]) -> None:
        self.sizes.append(size)

    def detect(self, image: Any) -> tuple[int, Any]:
        np = pytest.importorskip("numpy")
        height, width = image.shape[:2]
        assert (width, height) == self.sizes[-1]
        if not self.faces:
            return 1, None
        scale = width / self.width
        rows = [
            [x * scale, y * scale, w * scale, h * scale, *([0.0] * 10), score]
            for x, y, w, h, score in self.faces
        ]
        return 1, np.array(rows, dtype=np.float32)


def _png(width: int = 640, height: int = 400) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (240, 240, 240)).save(buf, format="PNG")
    return buf.getvalue()


# --- the protocol and the parts that need no numpy -------------------------------------------


def test_both_segmenters_satisfy_the_protocol() -> None:
    assert isinstance(LocalSegmenter(detector=FakeDetector([])), Segmenter)
    assert isinstance(SamClient(api_key="test-key-not-a-secret"), Segmenter)


def test_signature_is_refused_not_silently_skipped() -> None:
    seg = LocalSegmenter(detector=FakeDetector([]))
    with pytest.raises(DetectionError, match="cannot find SIGNATURE"):
        seg.segment(_png(), [EntityType.FACE, EntityType.SIGNATURE])
    with pytest.raises(DetectionError, match="cannot find STAMP"):
        seg.segment(_png(), ["STAMP"])


def test_undecodable_image_fails_closed() -> None:
    with pytest.raises(DetectionError, match="could not be decoded"):
        LocalSegmenter(detector=FakeDetector([])).segment(b"not an image")


def test_missing_opencv_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "cv2", None)
    with pytest.raises(DetectionError, match="needs OpenCV"):
        LocalSegmenter()


def test_missing_or_wrong_model_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("cv2")
    monkeypatch.setenv(segment.MODEL_DIR_ENV_VAR, str(tmp_path))
    with pytest.raises(DetectionError, match="is missing"):
        LocalSegmenter()
    (tmp_path / YUNET.filename).write_bytes(b"not the model")
    with pytest.raises(DetectionError, match="SHA-256 mismatch"):
        LocalSegmenter()
    with pytest.raises(DetectionError, match="could not be loaded"):
        LocalSegmenter(verify=False)


def test_bad_threshold() -> None:
    with pytest.raises(ValueError, match="score_threshold"):
        LocalSegmenter(score_threshold=1.5, detector=FakeDetector([]))


def test_model_dir_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(segment.MODEL_DIR_ENV_VAR, str(tmp_path))
    assert model_dir() == tmp_path
    monkeypatch.delenv(segment.MODEL_DIR_ENV_VAR)
    assert model_dir() == Path("~/.cache/pii-guard/models").expanduser()


def test_nms_keeps_the_best_of_overlapping_boxes() -> None:
    boxes = [(0, 0, 10, 10, 0.5), (1, 1, 11, 11, 0.9), (50, 50, 60, 60, 0.4)]
    assert nms(boxes) == [(1, 1, 11, 11, 0.9), (50, 50, 60, 60, 0.4)]
    assert nms([(0, 0, 0, 0, 0.5), (0, 0, 0, 0, 0.4)]) == [(0, 0, 0, 0, 0.5), (0, 0, 0, 0, 0.4)]


def test_photo_box_grows_the_face_and_clamps() -> None:
    face = Box(100, 100, 199, 199)  # 100 x 100
    photo = photo_box(face, 640, 400)
    assert photo.x1 < face.x1 and photo.y1 < face.y1
    assert photo.x2 > face.x2 and photo.y2 > face.y2
    left, _right, up, _down = segment.PHOTO_PADDING
    assert photo.x1 == int(100 - left * 100) and photo.y1 == int(100 - up * 100)
    clamped = photo_box(Box(0, 0, 99, 99), 120, 120)
    assert (clamped.x1, clamped.y1, clamped.x2, clamped.y2) == (0, 0, 119, 119)


class _Bytes(httpx.BaseTransport):
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(200, content=self.body, request=request)


def test_fetch_model_checks_the_hash(tmp_path: Path) -> None:
    body = b"fake onnx bytes"
    pinned = ModelFile("m.onnx", "https://example.invalid/m.onnx", "0" * 64, len(body), "MIT")
    with pytest.raises(DetectionError, match="SHA-256 does not match"):
        fetch_model(pinned, tmp_path, transport=_Bytes(body))
    assert list(tmp_path.iterdir()) == []

    good = ModelFile("m.onnx", pinned.url, hashlib.sha256(body).hexdigest(), len(body), "MIT")
    transport = _Bytes(body)
    path = fetch_model(good, tmp_path, transport=transport)
    assert path.read_bytes() == body and transport.calls == 1
    assert fetch_model(good, tmp_path, transport=transport) == path
    assert transport.calls == 1  # already there with the right hash
    assert "MIT" in repr(good)


def test_cli_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert segment.main(["nope"]) == 2
    assert "usage" in capsys.readouterr().err


# --- with numpy (the fake detector returns arrays) --------------------------------------------


def test_faces_and_photos_from_the_detector() -> None:
    pytest.importorskip("numpy")
    fake = FakeDetector([(100, 120, 80, 100, 0.93)])
    seg = LocalSegmenter(detector=fake)
    regions = seg.segment(_png(640, 400))
    assert [r.entity_type for r in regions] == [EntityType.FACE, EntityType.ID_PHOTO]
    face, photo = regions
    assert face.source == "yunet" and face.score == pytest.approx(0.93, abs=1e-3)
    assert abs(face.box.x1 - 100) <= 1 and abs(face.box.y2 - 220) <= 2
    assert photo.box.x1 < face.box.x1 and photo.box.y2 > face.box.y2
    # run at every pyramid size (no OpenCV: colour pass only)
    assert len(fake.sizes) == len({1.0 if s == 0 else s / 640 for s in segment.PYRAMID})
    only_faces = seg.segment(_png(640, 400), [EntityType.FACE])
    assert [r.entity_type for r in only_faces] == [EntityType.FACE]
    assert "LocalSegmenter" in repr(seg)


def test_no_faces_no_regions() -> None:
    pytest.importorskip("numpy")
    assert LocalSegmenter(detector=FakeDetector([])).segment(_png()) == []


def test_detector_errors_fail_closed() -> None:
    pytest.importorskip("numpy")

    class Broken(FakeDetector):
        def detect(self, image: Any) -> tuple[int, Any]:
            raise RuntimeError("boom")

    with pytest.raises(DetectionError, match="local segmentation failed"):
        LocalSegmenter(detector=Broken([])).segment(_png())


def test_real_yunet_on_a_fictional_card() -> None:
    pytest.importorskip("cv2")
    if not (model_dir() / YUNET.filename).is_file():
        pytest.skip("YuNet model not fetched (python -m pii_guard.visual.segment fetch)")
    seg = LocalSegmenter()
    regions = seg.segment(FICTIONAL_CARD.read_bytes())
    faces = [r for r in regions if r.entity_type is EntityType.FACE]
    assert len(faces) == 1
    # the synthetic Pillow card has an ellipse, not a face: nothing found, nothing raised
    assert all(r.entity_type in LOCAL_ENTITY_TYPES for r in seg.segment(id_card_png()))


# --- the comparison scorer ---------------------------------------------------------------------


def test_score_image_counts_leaks_and_precision() -> None:
    portrait = Box(10, 10, 109, 109)
    signature = Box(200, 200, 299, 239)
    expected = [("portrait", portrait), ("signature", signature), ("text", Box(0, 0, 5, 5))]
    covered = [
        Region(EntityType.ID_PHOTO, Box(8, 8, 111, 111), None, "yunet"),  # matches
        Region(EntityType.FACE, Box(40, 30, 80, 90), None, "yunet"),  # inside: not a false alarm
        Region(EntityType.FACE, Box(400, 300, 450, 350), None, "yunet"),  # false alarm
        Region(EntityType.SIGNATURE, Box(250, 150, 330, 215), None, "x"),  # mostly outside
        Region(EntityType.STAMP, Box(0, 0, 3, 3), None, "x"),  # not scored
    ]
    out = score_image(expected, covered, [1.0, 0.61, 0.0])
    assert set(out) == set(SCORED_TYPES)
    p, s = out["portrait"], out["signature"]
    assert (p.regions, p.leaks, p.leaks_strict, p.predicted, p.predicted_ok) == (1, 0, 0, 3, 2)
    assert (s.regions, s.leaks, s.leaks_strict, s.predicted, s.predicted_ok) == (1, 1, 1, 1, 0)


def test_candidates_and_parser() -> None:
    assert set(CANDIDATES) == {"hybrid", "sam-api", "local", "small-detectors", "efficientsam"}
    assert CANDIDATES["hybrid"].size_bytes == YUNET.size
    assert CANDIDATES["local"].size_bytes == YUNET.size
    assert CANDIDATES["sam-api"].size_bytes is None
    args = build_parser().parse_args(["--candidate", "local", "--set", "fictional"])
    assert (args.candidate, args.set_name, args.offline) == ("local", "fictional", False)


# no_cover: building the index from every committed run record is about 7x slower under the
# branch tracer; report_charts and report_cli are covered by tests/eval/test_report*.py (LAB-1447).
@pytest.mark.no_cover
def test_report_keeps_segmenter_runs_apart() -> None:
    from pii_guard.eval import report_charts as charts
    from pii_guard.eval import report_cli

    index = report_cli.current_index(ROOT)  # built, not committed (LAB-1269)
    segment_runs = [r for r in index["visual"] if charts.is_segment_run(r)]
    assert {r["fixture_set"] for r in segment_runs} == {"fictional-specimens", "specimens"}
    main_chart = charts.visual_recall(index)
    seg_chart = charts.visual_recall(index, segmenters=True)
    assert "yunet" not in main_chart and "yunet-2023mar" in seg_chart
    assert "Segmenters: SAM 3.1 API vs on-device" in seg_chart
    table = report_cli._segmenter_table(index)
    assert table.count("\n") == len(segment_runs) + 2
    assert "segment-" not in report_cli._visual_table(index)
    assert report_cli._drawn(index, "segmenter-recall.svg")
    assert report_cli._drawn(index, "visual-recall.svg")
    assert not report_cli._drawn({"visual": []}, "segmenter-recall.svg")
