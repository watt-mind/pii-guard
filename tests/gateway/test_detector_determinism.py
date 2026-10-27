"""The suite's default gateway detectors do not depend on which extras are installed (LAB-1162)."""

from __future__ import annotations

import pytest
from gateway_helpers import FakeLlm

from pii_guard.config import Settings
from pii_guard.gateway import GatewayConfig, build_mode_detectors, detection
from pii_guard.gateway.config import Mode


def test_implicit_mode_detectors_are_rules_only() -> None:
    detectors = build_mode_detectors(Settings(), GatewayConfig(), llm_detector=FakeLlm())
    assert detectors[Mode.FAST].config_id.startswith("fast:rules;policies=")
    assert detectors[Mode.AUDIT].config_id.startswith("audit:rules;llm;model=fake-llm;")


@pytest.mark.ner_autodetect
def test_opting_in_restores_the_environment_dependent_selection() -> None:
    assert detection._ner_available.__name__ == "_ner_available"
