"""The SAM prompt-study set (LAB-1118): committed images load, and the study scores stamps and
breaks recall down by variant."""

from __future__ import annotations

import hashlib
import io
import json
from collections import Counter
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from pii_guard.eval import visual
from pii_guard.eval.visual import load_specimens, render_prompt_study

ROOT = Path(__file__).resolve().parents[2]
SET = ROOT / "eval" / "visual" / "prompt-set"
W, H = 400, 250
STAMP = (220, 40, 330, 150)
SIGNATURE = (40, 180, 200, 230)


def test_committed_prompt_set_loads_with_every_variant() -> None:
    specimens = load_specimens(SET / "manifest.json", SET / "labels.json", SET / "images")
    assert len(specimens) == 24  # every image present and matching its SHA-256
    variants = Counter(s.doc_type for s in specimens)
    assert variants == {"scribble": 4, "script": 4, "scanned": 4, "id_photo": 6, "stamp": 6}
    expected = {
        "scribble": "signature",
        "script": "signature",
        "scanned": "signature",
        "id_photo": "portrait",
        "stamp": "stamp",
    }
    for specimen in specimens:
        assert [r.type for r in specimen.regions] == [expected[specimen.doc_type]]


def _png() -> bytes:
    image = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse(STAMP, outline=(180, 30, 40), width=4)
    draw.line([(45, 210), (120, 185), (195, 220)], fill="black", width=3)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _frac(box: tuple[int, int, int, int]) -> list[float]:
    return [box[0] / W, box[1] / H, (box[2] + 1) / W, (box[3] + 1) / H]


def _sam(found: dict[str, tuple[int, int, int, int]]):
    def handler(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["input"][0]["content"][0]["text"]
        box = found.get(prompt)
        text = (
            f"<0f>0<|box;x1={box[0]};y1={box[1]};x2={box[2]};y2={box[3]};w={W};h={H}|>"
            if box
            else ""
        )
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            },
        )

    return httpx.MockTransport(handler)


def test_prompt_study_scores_stamps_and_variants(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PII_GUARD_SAM_API_KEY", "test-key")
    data = _png()
    images = tmp_path / "images"
    images.mkdir()
    entries, labels = [], {}
    # same pixels, two variants: the study must report each variant separately
    for ident, kind, region, box in (
        ("a", "stamp", "stamp", STAMP),
        ("b", "scribble", "signature", SIGNATURE),
        ("c", "script", "signature", SIGNATURE),
    ):
        raw = data + ident.encode()  # trailing bytes keep the PNG valid and the SHA distinct
        (images / f"{ident}.png").write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        entries.append(
            {
                "id": ident,
                "country": "GB",
                "doc_type": kind,
                "side": "page",
                "file": f"{ident}.png",
                "sha256": sha,
            }
        )
        labels[sha] = {"id": ident, "regions": [{"type": region, "box": _frac(box)}]}
    (tmp_path / "m.json").write_text(json.dumps({"specimens": entries}), "utf-8")
    (tmp_path / "l.json").write_text(json.dumps({"specimens": labels}), "utf-8")
    study = json.dumps({"STAMP": ["stamp", "seal"], "SIGNATURE": ["scribble"]})
    out = tmp_path / "out.json"
    code = visual.main(
        [
            "--specimens",
            str(images),
            "--manifest",
            str(tmp_path / "m.json"),
            "--labels",
            str(tmp_path / "l.json"),
            "--cache",
            str(tmp_path / "cache"),
            "--prompt-study",
            study,
            "--json",
            str(out),
        ],
        inner_transport=_sam({"stamp": STAMP, "scribble": SIGNATURE}),
    )
    assert code == 0
    rows = {r["prompt"]: r for r in json.loads(out.read_text("utf-8"))["rows"]}
    assert rows["stamp"]["targets"] == ["stamp"]
    assert rows["stamp"]["recall_iou50"] == 1.0 and rows["stamp"]["images"] == 1
    assert rows["seal"]["recall_iou50"] == 0.0
    assert set(rows["scribble"]["by_variant"]) == {"scribble", "script"}
    assert rows["scribble"]["by_variant"]["script"]["recall_iou50"] == 1.0
    assert "| SIGNATURE | `scribble` | script |" in render_prompt_study(list(rows.values()))


def test_segment_eval_knows_the_prompt_set() -> None:
    from pii_guard.visual.segment_eval import SETS, set_paths

    manifest, labels, images = set_paths("prompts")
    assert SETS["prompts"] == (manifest, labels, images)
    assert (ROOT / manifest).is_file() and (ROOT / images).is_dir()
