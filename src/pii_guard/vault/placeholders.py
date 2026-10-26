"""Placeholder format, value normalization and keyed id derivation (ADR 0007).

A placeholder is ``[[<TYPE>_<id>]]``: ``<TYPE>`` is the :class:`EntityType` value, ``<id>``
lowercase hex from a truncated HMAC-SHA256 of the normalized value under the tenant key,
mixed with the entity type and the session id. Without the tenant key an id can't be
reversed, enumerated or linked to another tenant's or session's placeholders.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata

from pii_guard.types import EntityType

__all__ = [
    "DEFAULT_ID_LENGTH",
    "MAX_ID_LENGTH",
    "MAX_PLACEHOLDER_LENGTH",
    "MIN_ID_LENGTH",
    "PLACEHOLDER_RE",
    "derive_id",
    "format_placeholder",
    "is_placeholder_prefix",
    "normalize_value",
]

#: The contract regex (docs/contracts.md). Group 1 is the type, group 2 the id.
PLACEHOLDER_RE = re.compile(r"\[\[([A-Z][A-Z0-9_]*)_([0-9a-f]{4,})\]\]")

MIN_ID_LENGTH = 4
DEFAULT_ID_LENGTH = 6
MAX_ID_LENGTH = 64  # a full SHA-256 hex digest

#: Longest placeholder this package can issue: ``[[`` + type + ``_`` + id + ``]]``.
MAX_PLACEHOLDER_LENGTH = 2 + max(len(t.value) for t in EntityType) + 1 + MAX_ID_LENGTH + 2

# Domain separation, so the tenant key's HMAC output is never reused for anything else.
_HMAC_DOMAIN = b"pii-guard/vault/v1"
_SEP = b"\x1f"

# A string that may still grow into a placeholder: "[", "[[", "[[PERS", "[[PERSON_7f3a]".
# Deliberately loose about the type/id split (hex digits are also valid type characters);
# it only decides how much of a stream to hold back, never what gets restored.
_PREFIX_RE = re.compile(r"\[(?:\[(?:[A-Z][A-Z0-9_a-f]*\]?)?)?")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_value(value: str) -> str:
    """The form a value is keyed by: NFKC, case-folded, whitespace collapsed and stripped."""
    folded = unicodedata.normalize("NFKC", value).casefold()
    return _WHITESPACE_RE.sub(" ", folded).strip()


def derive_id(
    tenant_key: bytes,
    session_id: str,
    entity_type: EntityType,
    normalized: str,
    length: int = DEFAULT_ID_LENGTH,
) -> str:
    """Lowercase hex id: the first ``length`` characters of the keyed HMAC-SHA256."""
    if not MIN_ID_LENGTH <= length <= MAX_ID_LENGTH:
        raise ValueError(f"id length must be in [{MIN_ID_LENGTH}, {MAX_ID_LENGTH}]")
    message = _SEP.join(
        (
            _HMAC_DOMAIN,
            entity_type.value.encode(),
            session_id.encode(),
            normalized.encode(),
        )
    )
    return hmac.new(tenant_key, message, hashlib.sha256).hexdigest()[:length]


def format_placeholder(entity_type: EntityType, placeholder_id: str) -> str:
    return f"[[{entity_type.value}_{placeholder_id}]]"


def is_placeholder_prefix(text: str) -> bool:
    """True if ``text`` is an incomplete placeholder that more input could complete."""
    return len(text) < MAX_PLACEHOLDER_LENGTH and _PREFIX_RE.fullmatch(text) is not None
