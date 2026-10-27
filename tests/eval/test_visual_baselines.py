"""Image redaction baselines in the visual eval (LAB-1164): worker protocol, box merging,
scoring with the visual scorer and run records. No tool is installed here: the workers are
replaced by a stand-in that speaks the same protocol."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from pii_guard.eval.baselines.base import BaselineUnavailable
from pii_guard.eval.baselines.image import (
    IMAGE_BASELINES,
    ImageWorkerBaseline,
    WordBox,
    create_image_baseline,
    merge_word_boxes,
    region_kinds,
)
from pii_guard.eval.baselines.worker import WORKERS_DIR
from pii_guard.eval.record import build_records, load_schema, validate
from pii_guard.eval.visual import (
    REGION_TYPES,
    build_baseline_report,
    build_parser,
    evaluate,
    load_specimens,
    render_markdown,
)
from pii_guard.eval.visual import (
    _run_baseline as run_baseline,
)
from pii_guard.types import DetectionError, EntityType
from pii_guard.visual.image import load_image
from pii_guard.visual.regions import Box, Region

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "eval" / "fixtures" / "visual"


def _specimens() -> list[Any]:
    return load_specimens(
        FIXTURES / "manifest.json", FIXTURES / "labels.json", FIXTURES / "images"
    )[:3]


def _word(x1: int, y1: int, x2: int, y2: int, group: str | None = "g") -> WordBox:
    return WordBox(Box(x1, y1, x2, y2), "PERSON", "text" if group else "visual", group, 0.8)


# --- merging and kinds ------------------------------------------------------------------------


def test_words_of_one_entity_on_one_line_become_one_box() -> None:
    merged = merge_word_boxes([_word(10, 10, 40, 30), _word(48, 12, 90, 31)])
    assert [w.box for w in merged] == [Box(10, 10, 90, 31)]


def test_lines_groups_and_wide_gaps_stay_apart() -> None:
    words = [
        _word(10, 10, 40, 30),
        _word(10, 50, 40, 70),  # next line
        _word(200, 10, 240, 30),  # same line, gap of 160 px > 1.5 x 21 px
        _word(45, 10, 60, 30, group="other"),
        _word(0, 0, 99, 99, group=None),  # visual: untouched
    ]
    boxes = sorted(w.box.to_list() for w in merge_word_boxes(words))
    assert boxes == [
        [0, 0, 99, 99],
        [10, 10, 40, 30],
        [10, 50, 40, 70],
        [45, 10, 60, 30],
        [200, 10, 240, 30],
    ]


def test_region_kinds_map_to_eval_region_types() -> None:
    assert region_kinds(["text"]) == {"text", "mrz"}
    assert region_kinds(["text", "face", "signature"]) == set(REGION_TYPES)


def test_unknown_image_baseline_is_unavailable() -> None:
    with pytest.raises(BaselineUnavailable):
        create_image_baseline("nope")
    assert {"presidio-image", "presidio-image-tuned", "eka", "eka-tuned"} <= set(IMAGE_BASELINES)


# --- worker protocol ----------------------------------------------------------------------------

_FAKE_WORKER = """
import sys
sys.path.insert(0, WORKERS)
from _image_protocol import clamp_box, protocol_stdout, serve

def handle(image, language):
    if language == "boom":
        raise RuntimeError("secret text in the message")
    w, h = image.size
    return [
        {"box": clamp_box((5, 5, 30, 20), w, h), "label": "PERSON", "kind": "text",
         "group": "0:4:PERSON", "score": 0.9},
        {"box": clamp_box((34, 6, 60, 20), w, h), "label": "PERSON", "kind": "text",
         "group": "0:4:PERSON", "score": 0.7},
        {"box": clamp_box((0, 0, 9999, 9999), w, h), "label": "face_photo", "kind": "visual",
         "group": None, "score": None},
    ]

out = protocol_stdout()
print("library chatter goes to stderr")
serve(out, {"tool": "fake", "supports": ["text", "face"]}, handle)
"""


def _fake_command(tmp_path: Path, body: str = _FAKE_WORKER) -> list[str]:
    script = tmp_path / "fake_image_worker.py"
    script.write_text(textwrap.dedent(body).replace("WORKERS", repr(str(WORKERS_DIR))))
    return [sys.executable, str(script)]


def _png(width: int = 120, height: int = 80) -> bytes:
    from PIL import Image

    from pii_guard.visual.image import encode_image

    return encode_image(Image.new("RGB", (width, height), "white"))


def test_image_worker_round_trip(tmp_path: Path) -> None:
    baseline = ImageWorkerBaseline("fake", _fake_command(tmp_path))
    try:
        assert baseline.info["tool"] == "fake"
        assert baseline.supports == {"text", "mrz", "portrait"}
        regions, ms = baseline.mask(_png(), "en")
        assert ms >= 0
        by_type = {r.entity_type: r for r in regions}
        assert by_type[EntityType.PERSON].box == Box(5, 5, 60, 20)  # two words, one line
        assert by_type[EntityType.PERSON].score == 0.9
        assert by_type[EntityType.FACE].box == Box(0, 0, 119, 79)  # clamped to the image
        with pytest.raises(DetectionError) as err:
            baseline.mask(_png(), "boom")
        assert "secret" not in str(err.value) and "RuntimeError" in str(err.value)
    finally:
        assert baseline.close() == 0


def test_image_worker_that_dies_at_startup_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(BaselineUnavailable):
        ImageWorkerBaseline("dead", _fake_command(tmp_path, "raise SystemExit(3)\n"))


# --- scoring and records -------------------------------------------------------------------------


class _Box:
    """A stand-in tool that masks nothing."""

    name = "stand-in"

    def __init__(self, specimens: list[Any]) -> None:
        self.info: dict[str, Any] = {"tool": "stand-in", "supports": ["text"]}
        self.supports = {"text", "mrz"}
        self.languages: list[str] = []
        self.closed = False

    def mask(self, image: bytes, language: str) -> tuple[list[Region], float]:
        self.languages.append(language)
        return [], 12.5

    def close(self) -> None:
        self.closed = True


class _Oracle(_Box):
    def __init__(self, specimens: list[Any]) -> None:
        super().__init__(specimens)
        self._queue = list(specimens)

    def mask(self, image: bytes, language: str) -> tuple[list[Region], float]:
        self.languages.append(language)
        specimen = self._queue.pop(0)
        size = load_image(image).size
        regions = [
            Region(EntityType.PERSON, e.to_pixels(*size), None, self.name)
            for e in specimen.regions
            if e.type == "text"
        ]
        return regions, 10.0


def test_baseline_is_scored_with_the_visual_scorer() -> None:
    specimens = _specimens()
    oracle = _Oracle(specimens)
    results = evaluate(
        specimens, sam=None, transport=None, ocr=None, detector=None, baseline=oracle
    )
    report = build_baseline_report(results, oracle, max_side=1600)
    assert report["by_region_type"]["text"]["recall_iou50"] == 1.0
    # The tool can't mask portraits or signatures: left out of the per-type breakdown ...
    assert set(report["by_region_type"]) == {"mrz", "text"}
    assert report["pipeline"]["unsupported_region_types"] == ["portrait", "signature"]
    # ... but still counted in the overall recall.
    assert report["overall"]["regions"] == sum(len(s.regions) for s in specimens)
    assert "sam" not in report
    assert report["latency_ms"]["local_per_image_p50"] == 10.0
    assert all(not k.startswith("sam_") for k in report["latency_ms"])
    # Fictional documents carry their language; the tool gets it.
    assert oracle.languages == [s.language for s in specimens]
    text = render_markdown(report)
    assert "baseline `stand-in`" in text and "can't mask portrait, signature" in text


def test_baseline_report_becomes_a_schema_valid_comparison_record() -> None:
    specimens = _specimens()
    tool = _Box(specimens)
    results = evaluate(specimens, sam=None, transport=None, ocr=None, detector=None, baseline=tool)
    card = build_baseline_report(results, tool, max_side=1600)
    extra = {
        "system": {
            "family": "comparison",
            "tool": "stand-in",
            "version": "1",
            "detectors": [{"name": "stand-in", "model": None}],
            "key": "visual:stand-in",
            "label": "Stand-in",
            "info": card["pipeline"]["info"],
        },
        "fixtures": [
            {
                "path": "eval/fixtures/visual/manifest.json",
                "sha256": None,
                "set": "fictional-specimens",
                "language": None,
                "origin": "generated",
                "generator": "muse-image",
                "documents": len(specimens),
            }
        ],
    }
    (record,) = build_records(card, slug="stand-in-test", day="2026-10-27", extra=extra)
    assert validate(record, load_schema(ROOT / "eval/results/schema/run.schema.json")) == []
    assert record["system"]["family"] == "comparison"
    assert record["cost"] is None
    assert "portrait" not in record["metrics"]["by_region_type"]
    dumped = json.dumps(record)
    assert "images" not in record["metrics"] and str(FIXTURES) not in dumped


def test_cli_baseline_run_writes_report_and_closes(tmp_path: Path) -> None:
    specimens = _specimens()
    tools: list[_Box] = []

    def factory(name: str) -> _Box:
        tools.append(_Box(specimens))
        return tools[-1]

    out = tmp_path / "card.json"
    args = build_parser().parse_args(["--baseline", "stand-in", "--json", str(out)])
    assert run_baseline(args, specimens, lambda _m: None, factory=factory) == 0
    assert tools[0].closed
    card = json.loads(out.read_text("utf-8"))
    assert card["suite"] == "visual-specimens" and card["pipeline"]["baseline"] == "stand-in"

    def unavailable(name: str) -> _Box:
        raise BaselineUnavailable("not installed")

    assert run_baseline(args, specimens, lambda _m: None, factory=unavailable) == 2


def test_baseline_failure_on_one_image_counts_as_missed() -> None:
    specimens = _specimens()

    class Failing(_Box):
        def mask(self, image: bytes, language: str) -> tuple[list[Region], float]:
            raise DetectionError("tool failed")

    tool = Failing(specimens)
    results = evaluate(specimens, sam=None, transport=None, ocr=None, detector=None, baseline=tool)
    assert all(r.error == "detection_failed" for r in results)
    assert all(not s.hit_iou for r in results for s in r.scores)
