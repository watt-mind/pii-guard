"""``pii-guard eval visual`` on a synthetic card with a mocked SAM API (no network, ADR 0005)."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageDraw

from pii_guard.eval import visual
from pii_guard.eval.cli import main as eval_main
from pii_guard.eval.visual import (
    CachingTransport,
    ExpectedRegion,
    load_specimens,
    score_regions,
)
from pii_guard.types import EntityType
from pii_guard.visual.regions import Box, Region

W, H = 400, 250
FACE = (40, 60, 140, 200)  # inclusive pixel box of the drawn "photo"
SIGNATURE = (200, 190, 360, 230)


def _card_png() -> bytes:
    image = Image.new("RGB", (W, H), (230, 235, 245))
    draw = ImageDraw.Draw(image)
    draw.rectangle(FACE, fill=(200, 170, 150))
    draw.line([(205, 210), (250, 195), (300, 225), (355, 200)], fill="black", width=3)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _frac(box: tuple[int, int, int, int]) -> list[float]:
    x1, y1, x2, y2 = box
    return [x1 / W, y1 / H, (x2 + 1) / W, (y2 + 1) / H]


def _sam_text(box: tuple[int, int, int, int]) -> str:
    x1, y1, x2, y2 = box
    return f"<0f>0<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={W};h={H}|>"


class FakeSam:
    """A Meta Responses API stand-in: finds the face for ``face``, nothing otherwise."""

    def __init__(self, found: dict[str, tuple[int, int, int, int]] | None = None) -> None:
        self.found = found if found is not None else {"face": FACE}
        self.prompts: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["store"] is False
        prompt = body["input"][0]["content"][0]["text"]
        self.prompts.append(prompt)
        box = self.found.get(prompt)
        text = _sam_text(box) if box else ""
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            },
        )


@pytest.fixture
def specimen_dir(tmp_path: Path) -> dict[str, Path]:
    data = _card_png()
    sha = hashlib.sha256(data).hexdigest()
    images = tmp_path / "specimens"
    images.mkdir()
    (images / "xx-card.png").write_bytes(data)
    manifest = {
        "specimens": [
            {
                "id": "xx-id-card-front-abc123",
                "country": "HU",
                "doc_type": "id_card",
                "side": "front",
                "sha256": sha,
                "file": "xx-card.png",
            },
            {  # in the manifest, but its image is not downloaded
                "id": "yy-id-card-front-def456",
                "country": "DE",
                "doc_type": "id_card",
                "side": "front",
                "sha256": "0" * 64,
                "file": "missing.png",
            },
        ]
    }
    labels = {
        "specimens": {
            sha: {
                "id": "xx-id-card-front-abc123",
                "regions": [
                    {"type": "portrait", "box": _frac(FACE)},
                    {"type": "signature", "box": _frac(SIGNATURE)},
                ],
            },
            "0" * 64: {"id": "yy", "regions": [{"type": "mrz", "box": [0.1, 0.7, 0.9, 0.9]}]},
        }
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    return {
        "root": tmp_path,
        "images": images,
        "manifest": tmp_path / "manifest.json",
        "labels": tmp_path / "labels.json",
        "cache": tmp_path / "cache",
    }


def _args(paths: dict[str, Path], *extra: str) -> list[str]:
    return [
        "--specimens",
        str(paths["images"]),
        "--manifest",
        str(paths["manifest"]),
        "--labels",
        str(paths["labels"]),
        "--cache",
        str(paths["cache"]),
        "--no-ocr",
        "--json",
        str(paths["root"] / "out.json"),
        "--markdown",
        str(paths["root"] / "out.md"),
        *extra,
    ]


@pytest.fixture(autouse=True)
def _fake_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_SAM_API_KEY", "test-key-not-real")


def test_score_regions_iou_coverage_and_over_masking() -> None:
    expected = [ExpectedRegion("portrait", (0.0, 0.0, 0.5, 0.5))]  # 50x50 in 100x100
    exact = [Region(EntityType.FACE, Box(0, 0, 49, 49), None, "sam")]
    [score], over = score_regions(expected, exact, (100, 100))
    assert score.best_iou == pytest.approx(1.0)
    assert score.coverage == pytest.approx(1.0)
    assert score.matched_by == "FACE"
    assert over == 0.0

    halves = [
        Region(EntityType.FACE, Box(0, 0, 24, 49), None, "sam"),
        Region(EntityType.ID_PHOTO, Box(25, 0, 49, 49), None, "sam"),
        Region(EntityType.SIGNATURE, Box(60, 60, 69, 69), None, "sam"),
    ]
    [score], over = score_regions(expected, halves, (100, 100))
    assert score.best_iou == pytest.approx(0.5)  # each half alone
    assert score.hit_iou
    assert score.coverage == pytest.approx(1.0)  # together they cover it all
    assert over == pytest.approx(100 / 10_000)

    [miss], _ = score_regions(expected, [], (100, 100))
    assert miss.best_iou == 0.0 and miss.coverage == 0.0 and miss.matched_by is None


def test_load_specimens_skips_missing_images_and_bad_hashes(specimen_dir) -> None:
    messages: list[str] = []
    found = load_specimens(
        specimen_dir["manifest"],
        specimen_dir["labels"],
        specimen_dir["images"],
        log=messages.append,
    )
    assert [s.id for s in found] == ["xx-id-card-front-abc123"]
    assert any("missing image" in m for m in messages)
    (specimen_dir["images"] / "xx-card.png").write_bytes(b"tampered")
    assert (
        load_specimens(
            specimen_dir["manifest"],
            specimen_dir["labels"],
            specimen_dir["images"],
            log=messages.append,
        )
        == []
    )
    assert any("SHA-256 mismatch" in m for m in messages)


def test_eval_visual_scores_counts_calls_and_caches(specimen_dir, capsys) -> None:
    sam = FakeSam()
    code = visual.main(_args(specimen_dir), inner_transport=httpx.MockTransport(sam))
    assert code == 0
    report = json.loads((specimen_dir["root"] / "out.json").read_text(encoding="utf-8"))
    by_type = report["by_region_type"]
    assert by_type["portrait"]["recall_iou50"] == 1.0  # FACE growth still overlaps ≥ 0.5
    assert by_type["portrait"]["mean_coverage"] == 1.0
    assert by_type["portrait"]["matched_by"] == {"FACE": 1}
    assert by_type["signature"]["recall_iou50"] == 0.0
    assert by_type["mrz"]["regions"] == 0
    assert report["by_country"]["HU"]["specimens"] == 1
    # One request per prompt: face, signature, squiggly line, photo of a person.
    assert sorted(sam.prompts) == ["face", "photo of a person", "signature", "squiggly line"]
    assert report["sam"]["calls"] == 4
    assert report["sam"]["live_calls_this_run"] == 4
    assert report["sam"]["estimated_cost_usd"] == pytest.approx(4 * visual.DEFAULT_SAM_COST)
    assert "| portrait | 1 | 100.0 |" in (specimen_dir["root"] / "out.md").read_text("utf-8")
    assert "Visual recall" in capsys.readouterr().out

    # A rerun is served from the cache: no network at all, same numbers.
    def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError("cached run must not call SAM")

    code = visual.main(
        _args(specimen_dir, "--offline"), inner_transport=httpx.MockTransport(no_network)
    )
    assert code == 0
    again = json.loads((specimen_dir["root"] / "out.json").read_text(encoding="utf-8"))
    assert again["sam"]["live_calls_this_run"] == 0
    assert again["sam"]["cached_calls_this_run"] == 4
    assert again["by_region_type"] == report["by_region_type"]


def test_budget_exhaustion_fails_closed_per_image(specimen_dir) -> None:
    code = visual.main(
        _args(specimen_dir, "--max-live-calls", "1"), inner_transport=httpx.MockTransport(FakeSam())
    )
    assert code == 0
    report = json.loads((specimen_dir["root"] / "out.json").read_text(encoding="utf-8"))
    assert report["errors"] == {"detection_failed": 1}
    assert report["overall"]["recall_iou50"] == 0.0  # nothing counted as covered
    assert report["sam"]["live_calls_this_run"] == 1


def test_prompt_study_scores_each_prompt_alone(specimen_dir) -> None:
    sam = FakeSam({"face": FACE, "scribble": SIGNATURE})
    study = json.dumps({"FACE": ["face"], "SIGNATURE": ["signature", "scribble"]})
    code = visual.main(
        _args(specimen_dir, "--prompt-study", study), inner_transport=httpx.MockTransport(sam)
    )
    assert code == 0
    rows = json.loads((specimen_dir["root"] / "out.json").read_text(encoding="utf-8"))["rows"]
    by_prompt = {row["prompt"]: row for row in rows}
    assert by_prompt["face"]["recall_iou50"] == 1.0
    assert by_prompt["face"]["targets"] == ["portrait"]
    assert by_prompt["signature"]["recall_iou50"] == 0.0
    assert by_prompt["scribble"]["recall_iou50"] == 1.0
    assert all(row["calls"] == 1 for row in rows)


def test_caching_transport_keys_on_body_not_key(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["authorization"])
        return httpx.Response(200, json={"status": "completed", "output": []})

    transport = CachingTransport(tmp_path, httpx.MockTransport(handler))
    for key in ("Bearer a", "Bearer b"):
        with httpx.Client(transport=transport, headers={"Authorization": key}) as client:
            assert client.post("https://api.test/v1/responses", json={"x": 1}).status_code == 200
    assert calls == ["Bearer a"]
    assert transport.live_calls == 1 and transport.cached_calls == 1
    stored = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
    assert "Bearer" not in stored


def test_no_labelled_images_is_a_usage_error(specimen_dir, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    args = _args(specimen_dir)
    args[1] = str(empty)
    assert visual.main(args) == 2


def test_eval_cli_dispatches_visual(specimen_dir) -> None:
    code = eval_main(["visual", *_args(specimen_dir, "--offline")])
    # Offline with an empty cache: every image fails closed, but the run completes.
    assert code == 0


def test_committed_labels_and_manifest_are_consistent() -> None:
    root = Path(__file__).resolve().parents[2] / "eval" / "visual"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    labels = json.loads((root / "labels.json").read_text(encoding="utf-8"))["specimens"]
    shas = {s["sha256"] for s in manifest["specimens"]}
    assert set(labels) <= shas
    for entry in labels.values():
        for region in entry["regions"]:
            assert region["type"] in visual.REGION_TYPES
            x1, y1, x2, y2 = region["box"]
            assert 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1
            assert set(region) == {"type", "box"}  # boxes only, never a value
    for entry in manifest["specimens"]:
        assert set(entry) <= {
            "id", "country", "doc_type", "side", "commons_title", "source_page", "url",
            "licence", "specimen_evidence", "retrieved", "sha256", "bytes", "file",
        }  # fmt: skip
