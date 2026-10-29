"""Segmenter selection (``PII_GUARD_SEGMENTER``, LAB-1245): hybrid, sam-api, local, off.

SAM answers come from an in-memory transport that records each prompt; YuNet is a fake
segmenter, so no OpenCV, model file or network is needed.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Sequence

import httpx
import pytest
from PIL import Image

from pii_guard.config import Settings
from pii_guard.policy import Policy, PolicySet
from pii_guard.types import DetectionError, EntityType
from pii_guard.visual.masking import ImageMasker
from pii_guard.visual.regions import Box, Region
from pii_guard.visual.sam import SamClient
from pii_guard.visual.segment import LocalSegmenter
from pii_guard.visual.segmenters import (
    SEGMENTER_MODES,
    HybridSegmenter,
    OffSegmenter,
    build_segmenter,
    default_entity_types,
    sam_calls,
)

SIGNATURE_TEXT = "<0f>0<|box;x1=300;y1=300;x2=400;y2=340;w=640;h=400|>"


def _png(width: int = 640, height: int = 400) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (240, 240, 240)).save(buf, format="PNG")
    return buf.getvalue()


class Sam:
    """Records prompts; answers a signature for ``signature``, nothing for the rest."""

    def __init__(self, fail: bool = False) -> None:
        self.prompts: list[str] = []
        self.fail = fail

    def __call__(self, request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["input"][0]["content"][0]["text"]
        self.prompts.append(prompt)
        if self.fail:
            return httpx.Response(400, json={"error": "bad"})
        text = SIGNATURE_TEXT if prompt == "signature" else ""
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            },
        )

    def client(self, **kwargs: object) -> SamClient:
        return SamClient(
            api_key="test-key-not-a-secret",
            max_retries=0,
            transport=httpx.MockTransport(self),
            **kwargs,  # type: ignore[arg-type]
        )


class FakeLocal:
    name = "local"
    model = "yunet-2023mar"

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[list[EntityType]] = []
        self.fail = fail

    def segment(
        self, image: bytes, entity_types: Sequence[EntityType | str] | None = None
    ) -> list[Region]:
        types = [EntityType(t) for t in entity_types or ()]
        self.calls.append(types)
        if self.fail:
            raise DetectionError("local segmentation failed (RuntimeError)")
        if any(t is EntityType.SIGNATURE for t in types):
            raise DetectionError("local segmenter cannot find SIGNATURE")
        return [Region(t, Box(70, 110, 170, 240), 0.9, "yunet") for t in types]


def _unavailable() -> LocalSegmenter:
    raise DetectionError("local segmenter needs OpenCV (uv sync --extra local-vision)")


# --- the setting -----------------------------------------------------------------------------


def test_hybrid_is_the_default_setting() -> None:
    assert Settings().segmenter == "hybrid"
    assert SEGMENTER_MODES == ("hybrid", "sam-api", "local", "off")


def test_setting_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_SEGMENTER", "sam-api")
    assert Settings().segmenter == "sam-api"
    monkeypatch.setenv("PII_GUARD_SEGMENTER", "yolo")
    with pytest.raises(ValueError, match="segmenter"):
        Settings()


def test_build_rejects_an_unknown_mode() -> None:
    with pytest.raises(ValueError, match="hybrid"):
        build_segmenter(Settings(), mode="yolo")


# --- building and the fallbacks (ADR 0006) ---------------------------------------------------


def test_build_hybrid() -> None:
    local = FakeLocal()
    seg = build_segmenter(Settings(), local=lambda: local)  # type: ignore[arg-type,return-value]
    assert isinstance(seg, HybridSegmenter)
    assert seg.local is local
    assert seg.model == "yunet-2023mar+sam-3.1"
    assert set(seg.prompts) == {EntityType.SIGNATURE, EntityType.STAMP}


def test_build_sam_api_and_off() -> None:
    assert isinstance(build_segmenter(Settings(), mode="sam-api"), SamClient)
    assert isinstance(build_segmenter(Settings(), mode="off"), OffSegmenter)


def test_build_local_never_falls_back_to_the_api() -> None:
    local = FakeLocal()
    assert build_segmenter(Settings(), mode="local", local=lambda: local) is local  # type: ignore[arg-type,return-value]
    with pytest.raises(DetectionError, match="OpenCV"):
        build_segmenter(Settings(meta_api_key="k"), mode="local", local=_unavailable)


def test_hybrid_without_yunet_falls_back_to_sam_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="pii_guard.visual.segmenters"):
        seg = build_segmenter(Settings(meta_api_key="k"), local=_unavailable)
    assert isinstance(seg, HybridSegmenter)
    assert seg.local is None and seg.local_types == ()
    assert seg.model == "sam-3.1"
    assert set(seg.prompts) == set(seg.sam.prompts)  # faces go to SAM too
    assert "faces and ID photos go to SAM" in caplog.text
    assert "k" not in caplog.text.split("(")[0]


def test_hybrid_without_yunet_and_without_a_key_raises() -> None:
    with pytest.raises(DetectionError, match="no API key"):
        build_segmenter(Settings(), local=_unavailable)


# --- segmenting ------------------------------------------------------------------------------


def test_hybrid_sends_only_signatures_to_sam() -> None:
    sam, local = Sam(), FakeLocal()
    seg = HybridSegmenter(sam=sam.client(), local=local)
    regions = seg.segment(_png())
    assert sam.prompts == ["signature", "squiggly line"]
    assert local.calls == [[EntityType.FACE, EntityType.ID_PHOTO]]
    assert sorted(r.entity_type.value for r in regions) == ["FACE", "ID_PHOTO", "SIGNATURE"]
    assert {r.source for r in regions} == {"yunet", "sam"}


def test_hybrid_fallback_sends_everything_to_sam() -> None:
    sam = Sam()
    seg = HybridSegmenter(sam=sam.client(), local=None)
    seg.segment(_png())
    assert sam.prompts == ["face", "signature", "squiggly line", "photo of a person"]


@pytest.mark.parametrize("failing", ["sam", "local"])
def test_hybrid_fails_closed_when_either_part_fails(failing: str) -> None:
    sam, local = Sam(fail=failing == "sam"), FakeLocal(fail=failing == "local")
    seg = HybridSegmenter(sam=sam.client(), local=local)
    with pytest.raises(DetectionError):
        seg.segment(_png())


def test_hybrid_with_only_local_types_makes_no_sam_call() -> None:
    sam = Sam()
    seg = HybridSegmenter(sam=sam.client(), local=FakeLocal())
    seg.segment(_png(), [EntityType.FACE])
    assert sam.prompts == []


def test_off_refuses() -> None:
    with pytest.raises(DetectionError, match="off"):
        OffSegmenter().segment(_png())


# --- which types an image masker asks for, and what that costs -------------------------------


def test_default_types_skip_kept_types_except_for_sam_api() -> None:
    policies = PolicySet()
    sam = Sam().client()
    hybrid = HybridSegmenter(sam=sam, local=FakeLocal())
    assert default_entity_types(sam, policies.of) == list(sam.prompts)  # unchanged, with STAMP
    assert default_entity_types(hybrid, policies.of) == [
        EntityType.FACE,
        EntityType.SIGNATURE,
        EntityType.ID_PHOTO,
    ]
    stamps = PolicySet({EntityType.STAMP: Policy.MASK})
    assert EntityType.STAMP in default_entity_types(hybrid, stamps.of)


def test_sam_calls_per_image() -> None:
    policies = PolicySet()
    sam = Sam().client()
    hybrid = HybridSegmenter(sam=sam, local=FakeLocal())
    fallback = HybridSegmenter(sam=sam, local=None)
    assert sam_calls(sam, default_entity_types(sam, policies.of)) == 5
    assert sam_calls(hybrid, default_entity_types(hybrid, policies.of)) == 2
    assert sam_calls(fallback, default_entity_types(fallback, policies.of)) == 4
    assert sam_calls(FakeLocal(), [EntityType.FACE]) == 0


def test_image_masker_with_hybrid_masks_faces_from_yunet_as_local() -> None:
    sam = Sam()
    masker = ImageMasker(
        sam=HybridSegmenter(sam=sam.client(), local=FakeLocal()), policies=PolicySet()
    )
    outcome = masker.mask(_png())
    assert sam.prompts == ["signature", "squiggly line"]
    assert outcome.sam_model == "yunet-2023mar+sam-3.1"
    assert outcome.sam_types == [EntityType.FACE, EntityType.SIGNATURE, EntityType.ID_PHOTO]
    sources = {r.entity_type.value: r.to_public_dict()["source"] for r in outcome.regions}
    assert sources == {"FACE": "local", "ID_PHOTO": "local", "SIGNATURE": "sam"}
    detectors = {r.to_public_dict()["detector"] for r in outcome.regions}
    assert detectors == {"yunet", "sam"}


def test_image_masker_local_refuses_while_signatures_are_masked() -> None:
    local = FakeLocal()
    with pytest.raises(DetectionError, match="SIGNATURE"):
        ImageMasker(sam=local, policies=PolicySet()).mask(_png())
    kept = PolicySet({EntityType.SIGNATURE: Policy.KEEP})
    outcome = ImageMasker(sam=local, policies=kept).mask(_png())
    assert outcome.sam_types == [EntityType.FACE, EntityType.ID_PHOTO]
    assert outcome.sam_model == "yunet-2023mar"


def test_image_masker_off_refuses() -> None:
    with pytest.raises(DetectionError, match="off"):
        ImageMasker(sam=OffSegmenter(), policies=PolicySet()).mask(_png())


# --- the end-to-end bench's summary (segment_eval --e2e-bench) -------------------------------


def test_e2e_summary_takes_medians_of_the_rounds_and_feeds_the_record() -> None:
    from pii_guard.visual.segment_eval import add_e2e, build_parser, e2e_summary

    summary = e2e_summary(
        {"hybrid": [[1.0, 2.0, 3.0], [2.0, 3.0, 4.0], [9.0, 9.0, 9.0]], "sam-api": [[5.0, 6.0]]},
        {"hybrid": [2, 2, 2], "sam-api": [5, 5]},
        {"sam-api": 1},
    )
    hybrid = summary["hybrid"]
    assert hybrid["p50_per_round"] == [2.0, 3.0, 9.0]
    assert hybrid["p50_median"] == 3.0
    assert hybrid["sam_calls_per_image"] == 2.0
    assert summary["sam-api"]["errors"] == 1
    card: dict[str, dict[str, object]] = {"latency_ms": {}, "sam": {}}
    add_e2e(card, {"modes": summary}, "hybrid")
    assert card["latency_ms"]["mask_image_per_image_p50"] == 3.0
    assert card["sam"]["mask_image_calls_per_image"] == 2.0
    add_e2e(card, {"modes": summary}, "local")  # not benched: unchanged
    args = build_parser().parse_args(["--e2e-bench", "--set", "fictional", "--rounds", "2"])
    assert (args.e2e_bench, args.rounds, args.candidate) == (True, 2, None)
