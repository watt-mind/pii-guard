"""Entity policies: what happens to each detected entity type (``docs/entities.md``).

- ``mask``: replace the value with a reversible placeholder;
- ``keep``: leave it in place (reported by type and count only);
- ``block``: refuse the whole request -- nothing is masked, stored or forwarded.

Defaults: ``ORGANIZATION``, ``COMPANY_ID_HU`` and ``STAMP`` are ``keep``, everything else is
``mask``. A deployment overrides them with ``PII_GUARD_POLICY_OVERRIDES``
(``"ORGANIZATION=mask,EMAIL=block"``), parsed by :func:`parse_overrides` and validated when the
settings load, so a typo stops startup instead of silently masking less.

:meth:`PolicySet.apply` splits resolved spans into masked and kept ones and raises
:class:`BlockedEntityError` (types and counts only, never values) on any ``block`` span.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from pii_guard.types import EntityType, PiiGuardError, Span

__all__ = [
    "DEFAULT_POLICIES",
    "LINKAGE_OVERRIDES",
    "BlockedEntityError",
    "Policy",
    "PolicyDecision",
    "PolicySet",
    "parse_overrides",
]

logger = logging.getLogger(__name__)


class Policy(StrEnum):
    """What happens to an entity type: ``mask`` it, ``keep`` it in place, or ``block`` the
    request."""

    MASK = "mask"
    KEEP = "keep"
    BLOCK = "block"


_DEFAULT_KEEP = frozenset({EntityType.ORGANIZATION, EntityType.COMPANY_ID_HU, EntityType.STAMP})

#: The defaults from ``docs/entities.md``, for every entity type (text and visual).
DEFAULT_POLICIES: Mapping[EntityType, Policy] = MappingProxyType(
    {t: (Policy.KEEP if t in _DEFAULT_KEEP else Policy.MASK) for t in EntityType}
)


#: Opt-in linkage protection (``docs/privacy-model.md``, LAB-1152): also mask the text types
#: kept by default. A kept organization (an employer, the owner of an e-mail domain) narrows a
#: candidate list even when every name is masked. Pair it with
#: :func:`pii_guard.vault.generalize.generalize_context`; as configuration it is
#: ``PII_GUARD_POLICY_OVERRIDES="ORGANIZATION=mask,COMPANY_ID_HU=mask"``.
LINKAGE_OVERRIDES: Mapping[EntityType, Policy] = MappingProxyType(
    {EntityType.ORGANIZATION: Policy.MASK, EntityType.COMPANY_ID_HU: Policy.MASK}
)


class BlockedEntityError(PiiGuardError):
    """The text contains an entity type whose policy is ``block``. Nothing was masked."""

    code = "blocked_entity"
    status_code = 422

    def __init__(self, counts: Mapping[EntityType, int]) -> None:
        self.counts = dict(counts)
        listed = ", ".join(f"{t.value} ({n})" for t, n in sorted(self.counts.items()))
        super().__init__(f"the text contains entity types blocked by policy: {listed}")


def parse_overrides(value: str | Mapping[str, str] | None) -> dict[EntityType, Policy]:
    """Parse ``"TYPE=policy,TYPE=policy"`` (or a mapping) into policy overrides.

    Type names are case-insensitive. Raises ``ValueError`` naming the bad entry (these are
    configuration, never personal data).
    """
    if value is None:
        return {}
    if isinstance(value, Mapping):
        items = [(str(k), str(v)) for k, v in value.items()]
    else:
        items = []
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            name, sep, policy = part.partition("=")
            if not sep:
                raise ValueError(f"policy override {part!r} must look like TYPE=mask|keep|block")
            items.append((name, policy))
    out: dict[EntityType, Policy] = {}
    for name, policy in items:
        key = name.strip().upper()
        try:
            entity_type = EntityType(key)
        except ValueError:
            raise ValueError(f"unknown entity type {key!r} in policy overrides") from None
        try:
            out[entity_type] = Policy(policy.strip().lower())
        except ValueError:
            raise ValueError(
                f"unknown policy {policy.strip()!r} for {key} (expected mask, keep or block)"
            ) from None
    return out


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Spans split by policy. ``kept`` counts types only; its spans never leave the guard."""

    masked: list[Span]
    kept: list[Span]

    def kept_counts(self) -> dict[EntityType, int]:
        return dict(Counter(s.entity_type for s in self.kept))


class PolicySet:
    """The effective policy of every entity type: defaults plus overrides."""

    __slots__ = ("_policies",)

    def __init__(self, overrides: Mapping[EntityType, Policy] | None = None) -> None:
        policies = dict(DEFAULT_POLICIES)
        policies.update({EntityType(t): Policy(p) for t, p in (overrides or {}).items()})
        self._policies: Mapping[EntityType, Policy] = MappingProxyType(policies)

    @classmethod
    def from_settings(
        cls, settings: object, *, keep_types: Iterable[EntityType] | None = None
    ) -> PolicySet:
        """The one policy builder for the REST API and the gateway.

        ``Settings.policy_overrides`` on top of the deprecated keep list (``keep_types``, else
        ``Settings.gateway_keep_types`` from ``PII_GUARD_GATEWAY_KEEP_TYPES``): listed types
        are kept, the other default ``keep`` types are masked. Neither set -> the defaults.
        """
        if keep_types is None:
            keep_types = getattr(settings, "gateway_keep_types", None)
        overrides: dict[EntityType, Policy] = {}
        if keep_types is not None:
            logger.warning(
                "PII_GUARD_GATEWAY_KEEP_TYPES is deprecated; use PII_GUARD_POLICY_OVERRIDES"
            )
            kept = frozenset(keep_types)
            for entity_type, default in DEFAULT_POLICIES.items():
                if entity_type in kept:
                    overrides[entity_type] = Policy.KEEP
                elif default is Policy.KEEP:
                    overrides[entity_type] = Policy.MASK
        overrides.update(getattr(settings, "policy_overrides", None) or {})
        return cls(overrides)

    def __repr__(self) -> str:
        changed = {t.value: p.value for t, p in self.overrides().items()}
        return f"PolicySet(overrides={changed})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PolicySet) and dict(self._policies) == dict(other._policies)

    def __hash__(self) -> int:
        return hash(frozenset(self._policies.items()))

    def of(self, entity_type: EntityType) -> Policy:
        return self._policies[entity_type]

    def as_mapping(self) -> Mapping[EntityType, Policy]:
        return self._policies

    def overrides(self) -> dict[EntityType, Policy]:
        """Types whose policy differs from the default."""
        return {t: p for t, p in self._policies.items() if DEFAULT_POLICIES[t] is not p}

    def types(self, policy: Policy) -> frozenset[EntityType]:
        return frozenset(t for t, p in self._policies.items() if p is policy)

    @property
    def keep_types(self) -> frozenset[EntityType]:
        """For :class:`~pii_guard.detect.pipeline.DetectionPipeline`: kept types lose overlaps."""
        return self.types(Policy.KEEP)

    def fingerprint(self) -> str:
        """A stable id of the effective policies (cache keys, logs). Types only."""
        return ",".join(f"{t.value}={p.value}" for t, p in sorted(self.overrides().items()))

    def apply(self, spans: Iterable[Span]) -> PolicyDecision:
        """Split resolved spans; raise :class:`BlockedEntityError` if any is ``block``."""
        masked: list[Span] = []
        kept: list[Span] = []
        blocked: Counter[EntityType] = Counter()
        for span in spans:
            policy = self._policies[span.entity_type]
            if policy is Policy.BLOCK:
                blocked[span.entity_type] += 1
            elif policy is Policy.KEEP:
                kept.append(span)
            else:
                masked.append(span)
        if blocked:
            raise BlockedEntityError(blocked)
        return PolicyDecision(masked=masked, kept=kept)
