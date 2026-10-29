"""``reasoning_strength``: Muse Glimmer's reasoning control, sent as chat_template_kwargs."""

from __future__ import annotations

import json

import httpx
import pytest

from pii_guard.config import Settings
from pii_guard.detect.llm import LlmDetector


def _detector(settings: Settings, **kwargs: object) -> tuple[LlmDetector, list[dict]]:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"entities": []}'}, "finish_reason": "stop"}]
            },
        )

    det = LlmDetector(
        base_url="https://llm.test/v1",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        settings=settings,
        **kwargs,
    )
    return det, bodies


def test_reasoning_strength_keyword_is_sent_as_chat_template_kwargs() -> None:
    det, bodies = _detector(Settings(), reasoning_strength="low")
    det.detect("Teszt Elek írt.", language="hu")
    assert bodies[0]["chat_template_kwargs"] == {"reasoning_strength": "low"}
    assert "reasoning_effort" not in bodies[0]


def test_reasoning_strength_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_LLM_DETECTOR_REASONING_STRENGTH", "medium")
    det, bodies = _detector(Settings())
    assert det.reasoning_strength == "medium"
    det.detect("Teszt Elek írt.", language="hu")
    assert bodies[0]["chat_template_kwargs"] == {"reasoning_strength": "medium"}


def test_keyword_beats_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_LLM_DETECTOR_REASONING_STRENGTH", "high")
    det, _ = _detector(Settings(), reasoning_strength="low")
    assert det.reasoning_strength == "low"


def test_unset_sends_no_chat_template_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PII_GUARD_LLM_DETECTOR_REASONING_STRENGTH", raising=False)
    det, bodies = _detector(Settings(_env_file=None))
    det.detect("Teszt Elek írt.", language="hu")
    assert "chat_template_kwargs" not in bodies[0]
