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


# untraced: building the index from every committed run record is about 7x slower under the
# branch tracer; report_charts and report_cli are covered by tests/eval/test_report*.py (LAB-1447).
@pytest.mark.untraced
def test_report_keeps_segmenter_runs_apart() -> None:
    from pii_guard.eval import report_charts as charts
    from pii_guard.eval import report_cli

    index = report_cli.current_index(ROOT)  # built, not committed (LAB-1269)
    segment_runs = [r for r in index["visual"] if charts.is_segment_run(r)]
    assert {r["fixture_set"] for r in segment_runs} == {
        "fictional-specimens",
        "prompt-set",
        "specimens",
    }
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


# --- coverage without optional cv2/numpy extras & segment_eval orchestration -------------------


class _FakeArray:
    """Minimal 3D RGB/BGR array stand-in when numpy is not installed."""

    def __init__(self, width: int, height: int, channels: int = 3) -> None:
        self.shape = (height, width, channels)

    def __getitem__(self, item: Any) -> _FakeArray:
        return self

    def copy(self) -> _FakeArray:
        return _FakeArray(self.shape[1], self.shape[0], self.shape[2])


def test_local_segmenter_with_stubbed_cv2_and_numpy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import types

    body = b"fake-yunet-weights"
    digest = hashlib.sha256(body).hexdigest()
    monkeypatch.setattr(
        segment,
        "YUNET",
        ModelFile("yunet.onnx", "https://example.invalid/y.onnx", digest, len(body), "MIT"),
    )
    monkeypatch.setenv(segment.MODEL_DIR_ENV_VAR, str(tmp_path))

    created: list[Any] = []

    class _StubDetector:
        def __init__(self) -> None:
            self.sizes: list[tuple[int, int]] = []
            self.calls = 0

        def setInputSize(self, size: tuple[int, int]) -> None:
            self.sizes.append(size)

        def detect(self, image: Any) -> tuple[int, Any]:
            self.calls += 1
            if self.calls == 1:
                return 1, None
            scale = image.shape[1] / 640.0
            # Include one valid face box and one degenerate zero-width box (_clip -> None)
            return 1, [
                [100.0 * scale, 120.0 * scale, 80.0 * scale, 100.0 * scale, *([0.0] * 10), 0.92],
                [50.0 * scale, 50.0 * scale, 0.0, 0.0, *([0.0] * 10), 0.80],
            ]

    class _StubClahe:
        def apply(self, grey: Any) -> Any:
            return grey

    fake_cv2 = types.ModuleType("cv2")
    fake_cv2.COLOR_BGR2GRAY = 1  # type: ignore[attr-defined]
    fake_cv2.COLOR_GRAY2BGR = 2  # type: ignore[attr-defined]
    fake_cv2.INTER_AREA = 3  # type: ignore[attr-defined]
    fake_cv2.INTER_LINEAR = 4  # type: ignore[attr-defined]
    fake_cv2.cvtColor = lambda img, _code: img  # type: ignore[attr-defined]
    fake_cv2.createCLAHE = lambda **_kw: _StubClahe()  # type: ignore[attr-defined]
    fake_cv2.resize = lambda img, size, interpolation=None: _FakeArray(size[0], size[1])  # type: ignore[attr-defined]
    fake_cv2.utils = types.SimpleNamespace(  # type: ignore[attr-defined]
        logging=types.SimpleNamespace(LOG_LEVEL_ERROR=0, setLogLevel=lambda _lvl: None)
    )

    def _create_detector(path: str, *_args: Any) -> _StubDetector:
        if Path(path).read_bytes() == b"corrupt":
            raise RuntimeError("bad model")
        det = _StubDetector()
        created.append(det)
        return det

    fake_cv2.FaceDetectorYN = types.SimpleNamespace(create=_create_detector)  # type: ignore[attr-defined]

    fake_np = types.ModuleType("numpy")
    fake_np.asarray = lambda pil_img: _FakeArray(pil_img.size[0], pil_img.size[1])  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    monkeypatch.setitem(sys.modules, "numpy", fake_np)

    # Missing model file
    with pytest.raises(DetectionError, match="is missing"):
        LocalSegmenter()

    model_file = tmp_path / "yunet.onnx"
    model_file.write_bytes(b"corrupt")
    with pytest.raises(DetectionError, match="SHA-256 mismatch"):
        LocalSegmenter()
    with pytest.raises(DetectionError, match="could not be loaded"):
        LocalSegmenter(verify=False)

    model_file.write_bytes(body)
    seg = LocalSegmenter()
    regions = seg.segment(_png(640, 400))
    assert [r.entity_type for r in regions] == [EntityType.FACE, EntityType.ID_PHOTO]

    # Also exercise injected detector (self._cv2 is None) resize path with PIL stub
    injected = LocalSegmenter(detector=_StubDetector())
    monkeypatch.setattr(
        Image, "fromarray", lambda arr: Image.new("RGB", (arr.shape[1], arr.shape[0]))
    )
    regions_injected = injected.segment(_png(640, 400), [EntityType.FACE])
    assert [r.entity_type for r in regions_injected] == [EntityType.FACE]

    # Also exercise segment.main(["fetch"])
    monkeypatch.setattr(segment, "fetch_model", lambda: model_file)
    assert segment.main(["fetch"]) == 0


def test_segment_eval_orchestration_and_reporting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pii_guard.visual import segment_eval as se

    # _Timed and _Combined
    class _Part:
        model = "part-model"

        def __init__(self, region: Region) -> None:
            self.region = region

        def segment(self, image: bytes, entity_types: Any = None) -> list[Region]:
            return [self.region]

    r_face = Region(EntityType.FACE, Box(10, 10, 50, 50), 0.95, "yunet")
    r_sig = Region(EntityType.SIGNATURE, Box(100, 100, 180, 130), 0.90, "yolos")
    timed = se._Timed(_Part(r_face))
    assert timed.model == "part-model"
    assert timed.segment(b"img") == [r_face]
    assert timed.last_ms >= 0.0

    combined = se._Combined(_Part(r_face), _Part(r_sig))
    assert combined.segment(b"img") == [r_face, r_sig]

    # visual_cache_dir and set_paths
    monkeypatch.setenv("PII_GUARD_VISUAL_CACHE", str(tmp_path / "cache"))
    assert se.visual_cache_dir() == tmp_path / "cache"
    monkeypatch.delenv("PII_GUARD_VISUAL_CACHE", raising=False)
    assert len(se.set_paths("fictional")) == 3

    # run(), build_card(), _notes(), to_record() on the committed fictional set
    from pii_guard.eval.visual import ExpectedRegion, Specimen

    one_specimen = [
        Specimen(
            id="hu-id_card-front",
            country="HU",
            doc_type="id_card",
            side="front",
            sha256="0" * 64,
            path=FICTIONAL_CARD,
            regions=(
                ExpectedRegion("portrait", (0.05, 0.1, 0.3, 0.7)),
                ExpectedRegion("signature", (0.4, 0.7, 0.8, 0.9)),
            ),
            language="hu",
        )
    ]
    monkeypatch.setattr("pii_guard.eval.visual.load_specimens", lambda *_a, **_kw: one_specimen)

    cand_local = se.Candidate(
        "local",
        (se._yunet_detector(),),
        "MIT",
        100_000,
        lambda _t: _Part(r_face),
    )
    done = se.run(cand_local, "fictional")
    assert len(done.results) == 1
    card = se.build_card(cand_local, "fictional", done, transport=None)
    assert card["segmenter"]["candidate"] == "local"
    notes = se._notes(card)
    assert any("LAB-1229" in n for n in notes)
    rec = se.to_record(card, cand_local, "fictional", "unit-slug")
    assert rec["cost"]["usd"] == 0.0

    # Also test hybrid/transport branch and error branch in run()
    class _FakeTransport:
        recorded_ms = (12.5, 8.0)
        calls = 2
        live_calls = 0
        cached_calls = 2
        total_ms = 20.5

    class _HybridStub:
        def __init__(self) -> None:
            self.local = timed

        def segment(self, image: bytes, entity_types: Any = None) -> list[Region]:
            timed.segment(image, entity_types)
            raise DetectionError("simulated sam error")

    cand_hybrid = se.Candidate(
        "hybrid",
        (se._yunet_detector(),),
        "MIT",
        100_000,
        lambda _t: _HybridStub(),
    )
    done_h = se.run(cand_hybrid, "fictional", transport=_FakeTransport())
    assert done_h.results[0].error is not None

    # e2e_summary and add_e2e
    summary = se.e2e_summary(
        {"hybrid": [[10.0, 20.0], [12.0, 22.0]]},
        {"hybrid": [1, 2]},
        {"hybrid": 0},
    )
    assert summary["hybrid"]["rounds"] == 2
    assert summary["hybrid"]["sam_calls_per_image"] == 1.5
    se.add_e2e(card, {"modes": summary}, "hybrid")
    assert card["latency_ms"]["mask_image_per_image_p50"] == summary["hybrid"]["p50_median"]
    se.add_e2e(card, {"modes": summary}, "missing-mode")
