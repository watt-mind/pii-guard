"""Distillation corpus planning and the cost cap (no network: mocked transport)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from pii_guard.eval.generate import ChatClient, ResponseCache


def test_extra_kinds_are_added_and_planning_is_deterministic(corpus_mod) -> None:
    for language in ("hu", "en"):
        pack = corpus_mod.language_pack(language)
        ids = {k.id for k in pack.kinds}
        assert {"tool-output", "form", "log", "negative-prose", "negative-ops"} <= ids
        assert {"chat", "email"} <= ids  # the generator's own kinds stay
        first = corpus_mod.plan(language, 3, 7)
        again = corpus_mod.plan(language, 3, 7)
        assert first.messages == again.messages and first.kind == again.kind
        assert first.doc_id == f"{language}-distill-s3-00007"


def test_negative_kinds_have_no_values(corpus_mod) -> None:
    pack = corpus_mod.language_pack("en")
    for i in range(400):
        p = corpus_mod.plan("en", 1, i, pack)
        if p.kind.startswith("negative-"):
            assert p.values == ()
            assert corpus_mod.NO_VALUES in p.messages[1]["content"]
            return
    raise AssertionError("no negative document in 400 plans")


def _client(handler) -> ChatClient:
    return ChatClient(
        base_url="https://llm.test/v1",
        api_key="k",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )


def test_budget_stops_uncached_calls(corpus_mod, tmp_path: Path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Nothing here."}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
                "model": "m",
            },
        )

    budget = corpus_mod.Budget(0.25)  # one call costs $0.30
    result = corpus_mod.build_corpus(
        "en", 4, 1, _client(handler), ResponseCache(tmp_path / "cache"), budget
    )
    assert len(calls) == 1
    assert [o.reason for o in result.outcomes].count("budget") == 3
    assert round(budget.spent, 2) == 0.30
    stats = corpus_mod.write(result, tmp_path / "out", budget, "m")
    assert stats["cost_usd_uncached"] == 0.3
    saved = json.loads((tmp_path / "out" / "en-distill-stats.json").read_text())
    assert saved["discard_reasons"]["budget"] == 3


def test_cost(corpus_mod) -> None:
    assert corpus_mod.cost_usd({"prompt_tokens": 2_000_000, "completion_tokens": 500_000}) == 0.3


def test_plans_have_unique_prompts(corpus_mod) -> None:
    """Value-free kinds must not share a prompt (they would share a cache entry and a text)."""
    pack = corpus_mod.language_pack("en")
    plans = [corpus_mod.plan("en", 11, i, pack) for i in range(300)]
    negatives = [p for p in plans if not p.values]
    assert negatives, "expected some value-free documents in 300 plans"
    assert len({str(p.messages) for p in plans}) == len(plans)
