"""``POST /v1/sessions`` and ``POST /v1/sessions/{session_id}/known-values``.

An application that already knows which values are sensitive in a conversation (a customer
record, a case file) pre-loads them into the vault session; ``/v1/mask`` and the gateway then
mask every occurrence of them, inflected forms included, with the ``known`` detector
(:mod:`pii_guard.detect.known`), on top of the configured detectors.

Known values are stored only on the vault session (same sliding TTL; they are forgotten when
it expires) and are never logged or echoed: responses carry counts only, and errors name the
index and entity type of an invalid item, never its value.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Path, Request
from pydantic import BaseModel, Field

from pii_guard.api.deps import get_vault
from pii_guard.api.routes._common import log_extra, v1_router
from pii_guard.vault import Vault, VaultSession
from pii_guard.vault.known import KnownValue, known_values_from

__all__ = [
    "CreateSessionRequest",
    "KnownValueIn",
    "KnownValuesRequest",
    "KnownValuesResponse",
    "router",
]

router = v1_router()

# A hard cap on the body before the settings' limits apply (which give the clearer error).
_MAX_ITEMS = 100_000
_MAX_CHARS = 10_000


class KnownValueIn(BaseModel):
    value: Annotated[str, Field(max_length=_MAX_CHARS, repr=False)]
    entity_type: Annotated[str, Field(max_length=64)]

    def __repr__(self) -> str:
        return "KnownValueIn(value=<redacted>)"

    __str__ = __repr__


KnownValueList = Annotated[list[KnownValueIn], Field(max_length=_MAX_ITEMS)]


class CreateSessionRequest(BaseModel):
    known_values: KnownValueList = []


class KnownValuesRequest(BaseModel):
    known_values: KnownValueList


class KnownValuesResponse(BaseModel):
    """Counts only: ``added`` new values (duplicates are ignored), ``total`` in the session."""

    session_id: str
    added: int
    total: int


def _validated(request: Request, items: list[KnownValueIn]) -> list[KnownValue]:
    settings = request.app.state.settings
    return known_values_from(
        ({"value": item.value, "entity_type": item.entity_type} for item in items),
        max_length=settings.known_values_max_length,
    )


def _add(request: Request, session: VaultSession, values: list[KnownValue]) -> dict[str, object]:
    store = session.known_values
    added = store.add(values, max_values=request.app.state.settings.known_values_max)
    log_extra(request, known_added=added, known_total=len(store))
    return {"session_id": session.session_id, "added": added, "total": len(store)}


@router.post("/v1/sessions", response_model=KnownValuesResponse, status_code=201)
def create_session(
    request: Request,
    vault: Annotated[Vault, Depends(get_vault)],
    body: CreateSessionRequest | None = None,
) -> dict[str, object]:
    """A new vault session, optionally pre-loaded with known values.

    Pass its ``session_id`` to ``/v1/mask``, ``/v1/unmask`` or the gateway's session header.
    """
    values = _validated(request, body.known_values if body else [])  # before creating
    session = vault.session()
    try:
        return _add(request, session, values)
    except BaseException:
        vault.drop(session.session_id)
        raise


@router.post("/v1/sessions/{session_id}/known-values", response_model=KnownValuesResponse)
def add_known_values(
    session_id: Annotated[str, Path(min_length=1, max_length=128)],
    body: KnownValuesRequest,
    request: Request,
    vault: Annotated[Vault, Depends(get_vault)],
) -> dict[str, object]:
    """Add known values to an existing session (404 if it is unknown or expired)."""
    values = _validated(request, body.known_values)
    return _add(request, vault.session(session_id), values)
