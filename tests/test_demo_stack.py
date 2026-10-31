"""``make demo`` / ``make smoke``: fast mode by default, rules only on request (LAB-1192)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import demo_stack

from pii_guard.detect import ner_resolve
from pii_guard.detect.ner_resolve import PinnedModel

PIN = PinnedModel(
    repo_id="fictional/pii-ner",
    revision="0123456789abcdef0123456789abcdef01234567",
    licence="Apache-2.0",
    size_mb=1,
)


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_stack, "dotenv", lambda *_: {})
    monkeypatch.setattr(ner_resolve, "PUBLIC_FALLBACK", PIN)
    monkeypatch.setenv("PII_GUARD_NER_FALLBACK", "download")
    # The published step (pinned since LAB-1306) is skipped, so these tests see the fallback.
    monkeypatch.setenv("PII_GUARD_NER_PUBLISHED_MODEL", "fictional/unpublished-ner")


def test_fast_mode_is_the_default_and_names_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_stack, "extra_installed", lambda: True)
    p = demo_stack.plan(force_mock=True, ui=False)
    assert p.mode == "fast"
    assert p.ner == (
        "fictional/pii-ner@0123456789ab (public fallback, Apache-2.0, downloads on first run)"
    )
    assert "PII_GUARD_NER_FALLBACK" not in p.env
    text = demo_stack.banner(p)
    assert "fast mode      rules + NER: fictional/pii-ner@0123456789ab" in text
    assert "expected miss" not in text


def test_prepare_ner_downloads_before_the_stack_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_stack, "extra_installed", lambda: True)
    fetched: list[str] = []
    monkeypatch.setattr(demo_stack, "ensure", lambda choice: fetched.append(choice.source) or "")
    p = demo_stack.plan(force_mock=True, ui=False)
    demo_stack.prepare_ner(p)
    assert fetched == ["fallback"]
    assert p.ner is not None and "downloads on first run" not in p.ner


def test_prepare_ner_turns_a_failed_download_into_a_startup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(demo_stack, "extra_installed", lambda: True)

    def fail(_: object) -> str:
        raise demo_stack.DetectionError("ner model download failed (OSError)")

    monkeypatch.setattr(demo_stack, "ensure", fail)
    p = demo_stack.plan(force_mock=True, ui=False)
    with pytest.raises(RuntimeError, match="download failed"):
        demo_stack.prepare_ner(p)


def test_rules_mode_is_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_stack, "extra_installed", lambda: True)
    monkeypatch.setenv("PII_GUARD_NER_MODEL", "./models/fictional-ner")
    p = demo_stack.plan(force_mock=True, ui=False, mode="rules")
    assert p.ner is None
    assert p.env["PII_GUARD_NER_FALLBACK"] == "off"
    assert p.env["PII_GUARD_NER_MODEL"] == ""
    text = demo_stack.banner(p)
    assert "rules only (MODE=rules" in text
    assert "expected miss" in text
    demo_stack.prepare_ner(p)  # nothing to fetch


def test_fast_mode_without_the_extra_says_how_to_get_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_stack, "extra_installed", lambda: False)
    p = demo_stack.plan(force_mock=True, ui=False)
    assert p.ner is None
    assert p.env["PII_GUARD_NER_FALLBACK"] == "off"
    assert "`uv sync` installs them" in demo_stack.banner(p)


def test_configured_model_and_fallback_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_stack, "extra_installed", lambda: True)
    monkeypatch.setenv("PII_GUARD_NER_MODEL", "./models/fictional-ner")
    assert demo_stack.plan(force_mock=True, ui=False).ner == (
        "./models/fictional-ner (PII_GUARD_NER_MODEL)"
    )
    monkeypatch.delenv("PII_GUARD_NER_MODEL")
    monkeypatch.setenv("PII_GUARD_NER_FALLBACK", "off")
    p = demo_stack.plan(force_mock=True, ui=False)
    assert p.ner is None and "PII_GUARD_NER_FALLBACK=off" in demo_stack.banner(p)


def test_unknown_mode() -> None:
    with pytest.raises(ValueError, match="mode"):
        demo_stack.plan(mode="strict")


def test_mock_plan_marks_the_upstream_as_the_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """LAB-1311: `make demo` runs the API as plain `serve`, so the plan marks its separate
    mock upstream process through the environment for /v1/status and Connect."""
    p = demo_stack.plan(force_mock=True, ui=False)
    assert p.upstream == "mock"
    assert p.env["PII_GUARD_UPSTREAM_MOCK"] == "true"
