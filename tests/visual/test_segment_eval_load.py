"""The YOLOS signature spike loads safetensors weights only, at its pinned revision (LAB-1304)."""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from pii_guard.types import EntityType
from pii_guard.visual import segment_eval
from pii_guard.visual.regions import Box, Region


def test_yolos_signatures_refuse_pickled_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, tuple[str, dict[str, Any]]] = {}

    class Loader:
        def __init__(self, kind: str) -> None:
            self.kind = kind

        def from_pretrained(self, repo: str, **kwargs: Any) -> Any:
            calls[self.kind] = (repo, kwargs)
            return types.SimpleNamespace(eval=lambda: None)

    transformers = types.ModuleType("transformers")
    transformers.AutoImageProcessor = Loader("processor")  # type: ignore[attr-defined]
    transformers.AutoModelForObjectDetection = Loader("model")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.setitem(sys.modules, "torch", types.ModuleType("torch"))

    segment_eval.YolosSignatures()
    assert calls["model"] == (
        segment_eval.YOLOS_SIGNATURE,
        {"revision": segment_eval.YOLOS_REVISION, "use_safetensors": True},
    )
    assert calls["processor"][1] == {"revision": segment_eval.YOLOS_REVISION}


def test_segment_eval_combined_and_timed():
    p1 = MagicMock()
    p1.segment.return_value = [Region(EntityType.FACE, Box(0, 0, 10, 10), 1.0, "p1")]
    p2 = MagicMock()
    p2.segment.return_value = [Region(EntityType.SIGNATURE, Box(10, 10, 20, 20), 1.0, "p2")]
    combined = segment_eval._Combined(p1, p2)
    regions = combined.segment(b"fake-image")
    assert len(regions) == 2

    timed = segment_eval._Timed(p1)
    res = timed.segment(b"fake-image")
    assert len(res) == 1
    assert timed.last_ms >= 0.0


def test_segment_eval_sam_client():
    mock_transport = MagicMock()
    sam = segment_eval._sam(mock_transport)
    assert sam.max_retries == 2
