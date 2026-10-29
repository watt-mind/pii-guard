"""Keyed reversible pseudonyms, the placeholder mapping and re-identification (ADR 0007).

```python
vault = Vault(tenant_key)
session = vault.session()
masked = session.mask(text, spans)          # "[[PERSON_7f3a9c]] írt ..."
session.unmask(llm_answer)                  # originals restored
unmasker = StreamUnmasker(session)          # for streamed answers: feed() ... flush()
```

See ``docs/contracts.md`` (Vault).
"""

from pii_guard.vault.inflection import (
    ExactMatcher,
    HungarianSuffixMatcher,
    InflectionMatcher,
    inflection_for,
    register_inflection,
)
from pii_guard.vault.placeholders import PLACEHOLDER_RE, normalize_value
from pii_guard.vault.stream import StreamUnmasker
from pii_guard.vault.vault import (
    CASE_SENSITIVE_TYPES,
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_RESTORED_CHARS,
    DEFAULT_TTL_SECONDS,
    RestoreBudget,
    SessionEntryLimitError,
    SessionNotFoundError,
    Unmasked,
    UnmaskOutputTooLargeError,
    UnmaskResult,
    Vault,
    VaultSession,
)

__all__ = [
    "CASE_SENSITIVE_TYPES",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MAX_RESTORED_CHARS",
    "DEFAULT_TTL_SECONDS",
    "PLACEHOLDER_RE",
    "ExactMatcher",
    "HungarianSuffixMatcher",
    "InflectionMatcher",
    "RestoreBudget",
    "SessionEntryLimitError",
    "SessionNotFoundError",
    "StreamUnmasker",
    "UnmaskOutputTooLargeError",
    "UnmaskResult",
    "Unmasked",
    "Vault",
    "VaultSession",
    "inflection_for",
    "normalize_value",
    "register_inflection",
]
