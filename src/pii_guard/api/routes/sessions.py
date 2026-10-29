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
from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import ephemeral_session, log_extra, v1_router
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
    """A value the application already knows is sensitive, with its entity type."""

    value: Annotated[
        str,
        Field(
            max_length=_MAX_CHARS,
            repr=False,
            description="The value, at least 3 non-space characters and at most "
            "`PII_GUARD_KNOWN_VALUES_MAX_LENGTH` (256). Matched case- and "
            "whitespace-insensitively, whole words, inflected forms included. Never logged "
            "or echoed.",
            examples=["Gyakorló Tihamér"],
        ),
    ]
    entity_type: Annotated[
        str,
        Field(
            max_length=64,
            description="A text entity type (`PERSON`, `ID_DOCUMENT`, ...); visual types are "
            "refused.",
            examples=["PERSON"],
        ),
    ]

    def __repr__(self) -> str:
        return "KnownValueIn(value=<redacted>)"

    __str__ = __repr__


KnownValueList = Annotated[
    list[KnownValueIn],
    Field(
        max_length=_MAX_ITEMS,
        description="Values to pre-load. At most `PII_GUARD_KNOWN_VALUES_MAX` (1000) per "
        "session; duplicates are ignored.",
    ),
]


class CreateSessionRequest(BaseModel):
    """Optional body of ``POST /v1/sessions``: known values to pre-load."""

    known_values: KnownValueList = []


class KnownValuesRequest(BaseModel):
    """Known values to add to an existing session."""

    known_values: KnownValueList


class KnownValuesResponse(BaseModel):
    """Counts only: ``added`` new values (duplicates are ignored), ``total`` in the session."""

    session_id: str = Field(description="The vault session the values are stored on.")
    added: int = Field(description="New values this request added (duplicates excluded).")
    total: int = Field(description="Known values the session now holds.")


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


@router.post(
    "/v1/sessions",
    response_model=KnownValuesResponse,
    status_code=201,
    summary="Create a vault session, optionally with known values",
    responses=error_responses(
        "payload_too_large",
        "invalid_request",
        "invalid_known_value",
        "too_many_known_values",
        "vault_not_configured",
    ),
)
def create_session(
    request: Request,
    vault: Annotated[Vault, Depends(get_vault)],
    body: CreateSessionRequest | None = None,
) -> dict[str, object]:
    """A new vault session, optionally pre-loaded with known values.

    Pass its ``session_id`` to ``/v1/mask``, ``/v1/unmask`` or the gateway's session header.
    """
    values = _validated(request, body.known_values if body else [])  # before creating
    with ephemeral_session(vault, None, request) as session:  # a refused body creates none
        return _add(request, session, values)


@router.post(
    "/v1/sessions/{session_id}/known-values",
    response_model=KnownValuesResponse,
    summary="Add known values to a session",
    responses=error_responses(
        "not_found",
        "payload_too_large",
        "invalid_request",
        "invalid_known_value",
        "too_many_known_values",
        "vault_not_configured",
    ),
)
def add_known_values(
    session_id: Annotated[
        str,
        Path(min_length=1, max_length=128, description="The vault session to add values to."),
    ],
    body: KnownValuesRequest,
    request: Request,
    vault: Annotated[Vault, Depends(get_vault)],
) -> dict[str, object]:
    """Add known values to an existing session (404 if it is unknown or expired).

    A refused request (an invalid value, or more than the session may hold) adds nothing."""
    values = _validated(request, body.known_values)
    return _add(request, vault.session(session_id), values)
