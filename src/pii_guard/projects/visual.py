"""A project policy's image settings: visual actions and ``visual_detection`` (LAB-1444).

- :func:`visual_detection`: the policy's ``visual_detection``; ``local`` for versions saved
  before it existed.
- :func:`effective_policies`: the policy's actions with the server's visual ones folded in. A
  visual type the version does not hold (saved before LAB-1444) takes the server's action, as
  it did then; a type the operator sets in ``PII_GUARD_POLICY_OVERRIDES`` takes the stricter of
  the two (``keep`` < ``mask`` < ``block``), so an owner can never mask less than the operator
  requires.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pii_guard.policy import Policy, PolicySet
from pii_guard.projects.store import VISUAL_DETECTIONS
from pii_guard.types import VISUAL_ENTITY_TYPES, EntityType

__all__ = ["effective_policies", "stricter", "visual_detection"]

_RANK = {Policy.KEEP: 0, Policy.MASK: 1, Policy.BLOCK: 2}


def stricter(a: Policy, b: Policy) -> Policy:
    """The stricter of two actions (``keep`` < ``mask`` < ``block``)."""
    return a if _RANK[a] >= _RANK[b] else b


def visual_detection(policy: Mapping[str, Any] | None) -> str:
    """``local`` or ``sam``; ``local`` when the version predates the field."""
    value = (policy or {}).get("visual_detection", VISUAL_DETECTIONS[0])
    return value if value in VISUAL_DETECTIONS else VISUAL_DETECTIONS[0]


def effective_policies(
    policy: Mapping[str, Any] | None,
    project: PolicySet,
    server: PolicySet,
    overrides: Mapping[EntityType, Policy] | None = None,
) -> PolicySet:
    """``project`` with its visual actions resolved against the server (module docstring).

    ``policy`` is the stored version (its ``entity_policies`` say which visual types it holds),
    ``server`` the deployment's effective policies and ``overrides`` its explicit
    ``PII_GUARD_POLICY_OVERRIDES``."""
    stored = (policy or {}).get("entity_policies") or {}
    explicit = overrides or {}
    merged = dict(project.as_mapping())
    for entity in VISUAL_ENTITY_TYPES:
        action = Policy(stored[entity.value]) if entity.value in stored else server.of(entity)
        if entity in explicit:
            action = stricter(action, Policy(explicit[entity]))
        merged[entity] = action
    return PolicySet(merged)
