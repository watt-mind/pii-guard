"""The session sweep does not spread an NER-only value where the text's structure rules it out.

LAB-1470: one NER hit (``JSON`` or ``Claude`` read as a PERSON) used to be masked in every later
text of the conversation, ``contacts.json`` and the user's own prompt included. All values are
fictional (ADR 0005).
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from vault_helpers import span_of

from pii_guard.detect import ner_context
from pii_guard.gateway.restore import RESTORED_DETECTOR
from pii_guard.vault import Vault
from pii_guard.vault.vault import NEUTRAL_DETECTORS

FIRST = "Ask Claude to review the patch."
LATER = (
    "Claude Code wrote /private/tmp/claude-501/run/out.log. Claude reviewed it; tell Claude thanks."
)


def _ner(text: str, value: str, entity_type: str = "PERSON"):
    return replace(span_of(text, value, entity_type), detector="ner")


def test_ner_value_is_not_swept_into_product_names_and_paths(vault: Vault) -> None:
    session = vault.session()
    session.mask(FIRST, [_ner(FIRST, "Claude")])
    masked = session.mask(LATER, [])
    assert masked.startswith("Claude Code wrote /private/tmp/claude-501/run/out.log.")
    # In prose it is still the value the session masked.
    assert "Claude reviewed" not in masked
    assert "tell Claude" not in masked
    assert session.unmask(masked) == LATER


def test_value_confirmed_by_another_detector_is_swept_everywhere(vault: Vault) -> None:
    session = vault.session()
    session.mask(FIRST, [_ner(FIRST, "Claude")])
    other = "Claude Martin signs as Claude."
    session.mask(other, [span_of(other, "Claude", "PERSON", nth=1)])  # e.g. the LLM detector
    masked = session.mask(LATER, [])
    assert "Claude" not in masked
    assert "claude-501" not in masked


def test_restored_spans_keep_the_provenance(vault: Vault) -> None:
    assert RESTORED_DETECTOR in NEUTRAL_DETECTORS
    session = vault.session()
    session.mask(FIRST, [_ner(FIRST, "Claude")])
    session.mask(FIRST, [replace(span_of(FIRST, "Claude", "PERSON"), detector=RESTORED_DETECTOR)])
    assert session.mask(LATER, []).startswith("Claude Code wrote")


def test_remask_since_picks_up_a_cleared_entry(vault: Vault) -> None:
    session = vault.session()
    first = session.mask_with_report(FIRST, [_ner(FIRST, "Claude")])
    later = session.mask_with_report(LATER, [])
    assert later.text.startswith("Claude Code")
    other = "Claude Martin signs as Claude."
    session.mask(other, [span_of(other, "Claude", "PERSON", nth=1)])
    again = session.mask(later.text, [], remask=True, since=later.generation)
    assert "Claude Code" not in again
    assert first.text != FIRST


def test_email_without_at_is_not_swept(vault: Vault) -> None:
    session = vault.session()
    text = "Write the fixture file contacts.json now."
    session.mask(text, [_ner(text, "contacts.json", "EMAIL")])
    later = "Then run cat contacts.json and show it."
    # A value the model alone proposed, with no @: the sweep leaves it.
    assert session.mask(later, []) == later


def test_off_switch_sweeps_as_before(vault: Vault, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ner_context.ENV_VAR, "off")
    session = vault.session()
    session.mask(FIRST, [_ner(FIRST, "Claude")])
    assert "Claude Code" not in session.mask(LATER, [])
