"""SAM 3.1 output decoded with Meta's ``meta_sam_parser`` (LAB-1665), synthetic fixtures only.

The recorded responses in ``tests/fixtures/visual/`` are live SAM 3.1 answers for the synthetic
ID card in ``visual_helpers.py``; here they go through the official parser and must give the
same regions as the pre-LAB-1665 decoder (kept as the tolerant fallback).
"""

from __future__ import annotations

import builtins
import json
from pathlib import Path
from typing import Any

import pytest
from visual_helpers import HEIGHT, WIDTH

from pii_guard.types import DetectionError, EntityType
from pii_guard.visual import sam
from pii_guard.visual.sam import parse_sam_output

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "visual"


def fixture_text(name: str) -> str:
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return str(data["output"][0]["content"][0]["text"])


@pytest.mark.parametrize("name", ["sam_face", "sam_eye"])
def test_recorded_output_decodes_with_meta_parser_like_the_old_decoder(name: str) -> None:
    text = fixture_text(name)
    meta = sam._parse_with_meta(text, EntityType.FACE, (WIDTH, HEIGHT))
    assert meta is not None, "recorded SAM 3.1 output must be in meta_sam_parser's grammar"
    assert meta == sam._parse_tolerant(text, EntityType.FACE, (WIDTH, HEIGHT))
    assert parse_sam_output(text, EntityType.FACE, (WIDTH, HEIGHT)) == meta
    assert all(r.mask is not None and r.mask.encoding == "meta-sam-b85" for r in meta)


def test_meta_parser_path_rescales_like_the_old_decoder() -> None:
    text = fixture_text("sam_face")
    size = (WIDTH * 2, HEIGHT // 2)
    meta = sam._parse_with_meta(text, EntityType.FACE, size)
    assert meta is not None
    assert meta == sam._parse_tolerant(text, EntityType.FACE, size)


@pytest.mark.parametrize(
    "text",
    [
        # Outside Meta's grammar: box without its mask, box past the image edge, mask not at 0,0.
        "<0f>0<|box;x1=10;y1=10;x2=19;y2=19;w=100;h=100|>",
        "<0f>0<|box;x1=-5;y1=0;x2=700;y2=399;w=640;h=400|>",
        "<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=10|><|mask;x=1;y=0;data=3,3,~!!!|>",
        # A one_bit mask (``!``): the old decoder never accepted it.
        "<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=10|><|mask;x=0;y=0;data=3,3,!!!!|>",
    ],
)
def test_output_outside_the_grammar_goes_to_the_tolerant_decoder(text: str) -> None:
    assert sam._parse_with_meta(text, EntityType.FACE, (WIDTH, HEIGHT)) is None


def test_corrupt_mask_payload_is_not_decoded_by_meta_parser() -> None:
    text = fixture_text("sam_eye").replace("data=13,16,~!!!!v", "data=13,16,~!!!!w", 1)
    assert sam._parse_with_meta(text, EntityType.FACE, (WIDTH, HEIGHT)) is None


def test_large_masks_are_not_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    text = fixture_text("sam_face")  # one 128 x 99 mask
    monkeypatch.setattr(sam, "MAX_DECODED_MASK_PIXELS", 128 * 99 - 1)
    assert sam._parse_with_meta(text, EntityType.FACE, (WIDTH, HEIGHT)) is None
    # The boxes are still read, exactly as before.
    (region,) = parse_sam_output(text, EntityType.FACE, (WIDTH, HEIGHT))
    assert region.box.to_list() == [71, 111, 169, 238]


def test_mask_size_with_absurd_digits_is_not_decoded() -> None:
    text = "<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=10|><|mask;x=0;y=0;data=9999999999,3,~!!!|>"
    assert sam._parse_with_meta(text, EntityType.FACE, (WIDTH, HEIGHT)) is None


@pytest.mark.parametrize(
    "text",
    [
        "<0f>" + "x" * (sam.MAX_OUTPUT_CHARS + 1),
        "<0f>"
        + ",".join(f"{i}<|box;x1=1;y1=1;x2=2;y2=2;w=10;h=10|>" for i in range(sam.MAX_OBJECTS + 1)),
    ],
)
def test_oversized_output_fails_closed(text: str) -> None:
    with pytest.raises(DetectionError, match="size limits"):
        parse_sam_output(text, EntityType.FACE, (WIDTH, HEIGHT))


def test_parser_crash_falls_back_and_never_passes_output_unchecked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Boom:
        def image_segmentation_format(self) -> Any:
            raise RuntimeError("parser bug")

    monkeypatch.setattr(sam, "_meta_parser", Boom)
    text = fixture_text("sam_eye")
    assert sam._parse_with_meta(text, EntityType.FACE, (WIDTH, HEIGHT)) is None
    assert len(parse_sam_output(text, EntityType.FACE, (WIDTH, HEIGHT))) == 2
    with pytest.raises(DetectionError):
        parse_sam_output("<0f>not a SAM object", EntityType.FACE, (WIDTH, HEIGHT))


def test_missing_parser_package_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def no_meta(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "meta_sam_parser":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(__import__("sys").modules, "meta_sam_parser", raising=False)
    monkeypatch.setattr(builtins, "__import__", no_meta)
    with pytest.raises(DetectionError, match="meta-sam-parser"):
        parse_sam_output(fixture_text("sam_face"), EntityType.FACE, (WIDTH, HEIGHT))
    # Empty output still means nothing found, parser or not.
    assert parse_sam_output("", EntityType.FACE, (WIDTH, HEIGHT)) == []
