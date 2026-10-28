"""Shared pieces of the Codex and OpenCode e2e tests (not a test module: ``_`` prefix)."""

from __future__ import annotations

import os

from pii_guard.integrations.e2e import RunResult, load_gold

#: The live variant runs when META_API_KEY is in the environment (Meta Model API credits).
LIVE_KEY = os.environ.get("META_API_KEY")
LIVE_UPSTREAM = "https://api.meta.ai/v1"
LIVE_MODEL = os.environ.get("PII_GUARD_E2E_LIVE_MODEL") or "muse-spark-1.3"


def assert_scripted(result: RunResult) -> None:
    """The scripted task: read three files, write reply.md, finish; nothing leaked."""
    assert result.client_exit == 0, result.client_output
    assert result.requests >= 3
    assert result.refused == 0, result.gateway_statuses  # the allow-list covers its fields
    assert result.gold_upstream == []
    assert result.placeholders_upstream > 0
    assert result.files_written == ["reply.md"], result.client_output[-3000:]
    # Tool-call arguments came back restored: the file holds the real (fictional) values.
    assert sorted(result.restored_in_files) == sorted(result.gold_checked)
    assert result.placeholders_in_files == 0
    assert set(load_gold()["rules"]) <= set(result.gold_checked)
    # The quickstart's session URL: one vault session, each value one placeholder.
    assert result.session_sources == {"path": result.requests}
    assert result.sessions == 1
    assert result.gold_unstable == 0
    assert result.ok


def assert_live(result: RunResult) -> None:
    """A real model: what it writes varies, but no gold value may reach it."""
    assert result.client_exit == 0, result.client_output
    assert result.refused == 0, result.gateway_statuses
    assert result.requests >= 1
    assert result.gold_upstream == []
    assert result.placeholders_upstream > 0
    assert result.placeholders_in_files == 0
