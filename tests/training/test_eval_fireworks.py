"""Fireworks eval driver for the Glimmer LoRA (training/llm/eval_fireworks.py). No network."""

from __future__ import annotations

import types

import pytest

from .conftest import load_script


@pytest.fixture(scope="module")
def ev() -> types.ModuleType:
    return load_script("training/llm/eval_fireworks.py", "llm_eval_fireworks")


def _completion(content: str, *, reasoning: str | None = None, reasoning_tokens: int = 0) -> dict:
    message = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return {
        "choices": [{"message": message, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 1128,
            "completion_tokens": 80,
            "completion_tokens_details": {"reasoning_tokens": reasoning_tokens},
        },
    }


def test_answer_only_completion_has_no_reasoning(ev: types.ModuleType) -> None:
    flags = ev.response_flags(_completion('{"entities": []}'))
    assert flags["completion_tokens"] == 80
    assert flags["reasoning_tokens"] == 0
    assert flags["reasoning_chars"] == 0
    assert not flags["self_turn"]
    assert flags["json_first"]


def test_reasoning_is_flagged_without_keeping_text(ev: types.ModuleType) -> None:
    flags = ev.response_flags(
        _completion("to=self thinking... {}", reasoning="Teszt Elek", reasoning_tokens=699)
    )
    assert flags["reasoning_tokens"] == 699
    assert flags["reasoning_chars"] == len("Teszt Elek")
    assert flags["self_turn"]
    assert not flags["json_first"]
    assert "Teszt Elek" not in repr(flags)  # counts only, never the text


def test_subset_takes_first_n_per_language(ev: types.ModuleType) -> None:
    docs = [
        types.SimpleNamespace(id=f"{lang}-{i}", language=lang) for lang in "ab" for i in range(3)
    ]
    assert [d.id for d in ev.subset(docs, 2)] == ["a-0", "a-1", "b-0", "b-1"]
    assert ev.subset(docs, None) == docs


def test_percentile(ev: types.ModuleType) -> None:
    assert ev._pct([], 50) is None
    assert ev._pct([5.0], 95) == 5.0
    assert ev._pct([1.0, 2.0, 3.0], 50) == 2.0
