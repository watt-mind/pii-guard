"""Entity policies (``pii_guard.policy``) and their settings. All values are fictional."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from pii_guard.config import Settings
from pii_guard.policy import (
    DEFAULT_POLICIES,
    BlockedEntityError,
    Policy,
    PolicySet,
    parse_overrides,
)
from pii_guard.types import EntityType, Span

ENTITIES_MD = Path(__file__).resolve().parents[1] / "docs" / "entities.md"


def _span(entity_type: EntityType, start: int = 0, end: int = 4) -> Span:
    return Span(start, end, entity_type, "x" * (end - start), 1.0, "test")


def test_defaults_match_entities_md() -> None:
    rows = re.findall(
        r"^\| `([A-Z_]+)` \|.*\| (mask|keep|block) \|$", ENTITIES_MD.read_text(), re.M
    )
    documented = {EntityType(name): Policy(policy) for name, policy in rows}
    assert documented == dict(DEFAULT_POLICIES)
    assert PolicySet().types(Policy.KEEP) == {
        EntityType.ORGANIZATION,
        EntityType.COMPANY_ID_HU,
        EntityType.STAMP,
    }
    assert PolicySet().types(Policy.BLOCK) == frozenset()


def test_parse_overrides() -> None:
    assert parse_overrides(" organization=MASK , EMAIL=block,") == {
        EntityType.ORGANIZATION: Policy.MASK,
        EntityType.EMAIL: Policy.BLOCK,
    }
    assert parse_overrides("") == {}
    assert parse_overrides(None) == {}
    assert parse_overrides({"person": "keep"}) == {EntityType.PERSON: Policy.KEEP}


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("NOPE=mask", "unknown entity type 'NOPE'"),
        ("EMAIL=hide", "unknown policy 'hide' for EMAIL"),
        ("EMAIL", "must look like TYPE=mask|keep|block"),
    ],
)
def test_parse_overrides_rejects_bad_entries(value: str, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        parse_overrides(value)


def test_settings_validate_overrides_and_detectors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_POLICY_OVERRIDES", "ORGANIZATION=mask,EMAIL=block")
    monkeypatch.setenv("PII_GUARD_DETECTORS", "rules, llm")
    settings = Settings()
    assert settings.detectors == ("rules", "llm")
    policies = PolicySet.from_settings(settings)
    assert policies.of(EntityType.ORGANIZATION) is Policy.MASK
    assert policies.of(EntityType.EMAIL) is Policy.BLOCK
    assert policies.of(EntityType.COMPANY_ID_HU) is Policy.KEEP
    assert policies.fingerprint() == "EMAIL=block,ORGANIZATION=mask"

    monkeypatch.setenv("PII_GUARD_POLICY_OVERRIDES", "EMAIL=sometimes")
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.setenv("PII_GUARD_POLICY_OVERRIDES", "")
    monkeypatch.setenv("PII_GUARD_DETECTORS", " , ")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    # Unset: the shared stack decides (rules, + ner when available; LAB-1270).
    assert settings.detectors is None
    assert settings.policy_overrides == {}
    assert PolicySet.from_settings(settings) == PolicySet()


def test_apply_splits_and_blocks() -> None:
    policies = PolicySet({EntityType.PHONE: Policy.BLOCK})
    person, org = _span(EntityType.PERSON), _span(EntityType.ORGANIZATION, 5, 9)
    decision = policies.apply([person, org, _span(EntityType.ORGANIZATION, 10, 14)])
    assert decision.masked == [person]
    assert decision.kept_counts() == {EntityType.ORGANIZATION: 2}

    with pytest.raises(BlockedEntityError) as caught:
        policies.apply([person, _span(EntityType.PHONE, 5, 9), _span(EntityType.PHONE, 10, 14)])
    assert caught.value.code == "blocked_entity"
    assert caught.value.status_code == 422
    assert caught.value.counts == {EntityType.PHONE: 2}
    assert "PHONE (2)" in caught.value.message
    assert "xxxx" not in caught.value.message


def test_policy_set_value_semantics() -> None:
    a = PolicySet({EntityType.EMAIL: Policy.BLOCK})
    assert a == PolicySet({EntityType.EMAIL: "block"})  # type: ignore[dict-item]
    assert a != PolicySet()
    assert hash(a) == hash(PolicySet({EntityType.EMAIL: Policy.BLOCK}))
    assert "EMAIL" in repr(a)
    assert a.keep_types == PolicySet().keep_types
    assert a.overrides() == {EntityType.EMAIL: Policy.BLOCK}
    assert a.as_mapping()[EntityType.PERSON] is Policy.MASK
