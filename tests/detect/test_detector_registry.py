"""Tests for the detector registry: registration, entry points, convention resolution."""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from pii_guard.registry import (
    ENTRY_POINT_GROUP,
    create_detector,
    detector_names,
    register_detector,
    resolve_detector,
)
from pii_guard.types import DetectionError


def test_register_detector_validation() -> None:
    with pytest.raises(ValueError, match="target must look like"):
        register_detector("bad", "invalid_target_without_colon")

    register_detector("custom_det", "pii_guard.detect.rules:RuleDetector")
    # Duplicate registration without replace raises ValueError
    with pytest.raises(ValueError, match="is already registered"):
        register_detector("custom_det", "other.module:OtherDetector")

    # With replace=True it succeeds
    register_detector("custom_det", "other.module:OtherDetector", replace=True)


def test_detector_names_and_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    names = detector_names()
    assert "rules" in names

    mock_ep = MagicMock()
    mock_ep.name = "mock_ep_detector"
    monkeypatch.setattr(
        "pii_guard.registry.entry_points",
        lambda group: [mock_ep] if group == ENTRY_POINT_GROUP else [],
    )
    assert "mock_ep_detector" in detector_names()


def test_resolve_detector_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_ep = MagicMock()
    mock_ep.name = "ep_success"
    mock_ep.load.return_value = str

    mock_ep_fail = MagicMock()
    mock_ep_fail.name = "ep_fail"
    mock_ep_fail.load.side_effect = ImportError("boom")

    monkeypatch.setattr(
        "pii_guard.registry.entry_points",
        lambda group: [mock_ep, mock_ep_fail] if group == ENTRY_POINT_GROUP else [],
    )

    assert resolve_detector("ep_success") is str
    with pytest.raises(DetectionError, match="entry point failed to load"):
        resolve_detector("ep_fail")


def test_resolve_detector_module_convention_and_errors() -> None:
    # Unknown module or non-identifier
    with pytest.raises(DetectionError, match="unknown detector"):
        resolve_detector("nonexistent_det_12345")

    with pytest.raises(DetectionError, match="unknown detector"):
        resolve_detector("bad-name-with-dash")

    # _import_target failure
    register_detector("bad_target_module", "nonexistent.module:Cls", replace=True)
    with pytest.raises(DetectionError, match="could not be loaded"):
        resolve_detector("bad_target_module")


def test_resolve_detector_convention_without_detector_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_mod = types.ModuleType("pii_guard.detect.dummy")
    monkeypatch.setattr(
        "importlib.import_module",
        lambda name: fake_mod if name == "pii_guard.detect.dummy" else __import__(name),
    )
    with pytest.raises(DetectionError, match="does not define DETECTOR_CLASS"):
        resolve_detector("dummy")


def test_resolve_detector_convention_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_mod = types.ModuleType("pii_guard.detect.dummy_det")
    fake_mod.DETECTOR_CLASS = str
    monkeypatch.setattr(
        "importlib.import_module",
        lambda name: fake_mod if name == "pii_guard.detect.dummy_det" else __import__(name),
    )
    assert resolve_detector("dummy_det") is str


def test_resolve_detector_convention_nested_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_import(name: str) -> types.ModuleType:
        if name == "pii_guard.detect.nested_err":
            err = ModuleNotFoundError("No module named 'dep'", name="dep")
            raise err
        return __import__(name)

    monkeypatch.setattr("importlib.import_module", fake_import)
    with pytest.raises(DetectionError, match="failed to import"):
        resolve_detector("nested_err")


def test_create_detector() -> None:
    det = create_detector("rules")
    assert hasattr(det, "detect")
