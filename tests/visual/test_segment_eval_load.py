"""The YOLOS signature spike loads safetensors weights only, at its pinned revision (LAB-1304)."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from pii_guard.visual import segment_eval


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
