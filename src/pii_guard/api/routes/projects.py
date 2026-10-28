"""Owner-authorized management of projects, immutable policies and inference endpoints."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from urllib.parse import urlsplit, urlunsplit

from anyio import from_thread
from fastapi import Path, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from starlette.responses import Response

from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import v1_router
from pii_guard.hosted.egress import validate_destination
from pii_guard.projects.runtime import ProjectAccessError
from pii_guard.projects.store import InvalidProjectConfigError, ProjectStore
from pii_guard.types import TEXT_ENTITY_TYPES
from pii_guard.upstreams import PRESETS

router = v1_router()
router.tags = ["projects"]
router.responses = error_responses(
    "invalid_request",
    "payload_too_large",
    "project_access_denied",
    "project_not_found",
    "invalid_project_config",
    "project_storage_unavailable",
    "upstream_destination_not_allowed",
)
ResourceId = Annotated[
    str,
    Path(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Opaque identifier of an owner-authorized project resource.",
    ),
]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def known_fields_only(cls, value: object) -> object:
        # Unknown JSON field names can themselves contain secrets. Reject them before
        # Pydantic includes those names in a validation error's field location.
        if isinstance(value, dict) and any(key not in cls.model_fields for key in value):
            raise ValueError("unknown request field")
        return value


class NameRequest(_Body):
    """A display name visible only to the configuration owner."""

    name: str = Field(
        min_length=1, max_length=64, repr=False, description="Owner-visible display name."
    )

    @field_validator("name")
    @classmethod
    def name_is_valid(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("invalid resource name")
        return value


class PolicyRequest(NameRequest):
    """A new complete immutable policy version; omitted actions use deployment defaults."""

    entity_policies: dict[str, Literal["mask", "keep", "block"]] = Field(
        default_factory=dict, description="Text entity actions: mask, keep or block."
    )
    language: str = Field(
        default="hu", min_length=2, max_length=16, description="Detection language tag."
    )
    mode: Literal["fast", "audit"] = Field(
        default="fast", description="Detection mode; hosted policies require fast."
    )
    detection_profile: Literal["standard", "local-only"] | None = Field(
        default=None, description="Must match the deployment detection profile when supplied."
    )

    @field_validator("entity_policies", mode="before")
    @classmethod
    def text_policies_only(cls, value: object) -> object:
        if not isinstance(value, dict) or any(
            key not in {entity.value for entity in TEXT_ENTITY_TYPES} for key in value
        ):
            raise ValueError("unknown text entity type")
        return value


class EndpointRequest(NameRequest):
    """One provider, optional pinned model, credential and explicitly pinned policy version."""

    policy_version_id: str = Field(
        min_length=1, max_length=128, description="Immutable policy version in this project."
    )
    provider: Literal["meta", "openai", "fireworks", "openrouter", "custom", "sponsored"] = Field(
        description="Upstream provider or hosted sponsored Meta inference."
    )
    base_url: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
        repr=False,
        description="Upstream API base URL; required for custom providers.",
    )
    model: str | None = Field(
        default=None,
        max_length=256,
        repr=False,
        description="The upstream model this endpoint pins. Omit it, or send null or an empty "
        "string, for pass-through: the client's own `model` is forwarded unchanged. Optional "
        "for own-key providers; sponsored endpoints require an allow-listed model.",
    )
    api_key: SecretStr | None = Field(
        default=None,
        min_length=1,
        max_length=4096,
        repr=False,
        description="Write-only provider credential; omit on edits to preserve it.",
    )
    enabled: bool = Field(
        default=True, description="Whether the endpoint accepts new gateway requests."
    )


def _context(request: Request) -> tuple[ProjectStore, str]:
    owner = getattr(request.state, "project_owner_id", None)
    if not isinstance(owner, str) or not owner:
        raise ProjectAccessError("Owner authorization is required")
    if request.app.state.settings.hosted:
        principal = getattr(request.state, "hosted_principal", None)
        if (
            principal is None
            or not principal.authenticated
            or principal.auth_method != "google"
            or principal.id != owner
        ):
            raise ProjectAccessError("Google owner authorization is required")
    return request.app.state.projects.store, owner


def _policy_data(body: PolicyRequest, request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    if settings.hosted and body.mode != "fast":
        raise InvalidProjectConfigError()
    return body.model_dump(exclude_none=True)


def _local_base_url(value: str) -> str:
    """Retain local upstream support without persisting embedded URL credentials."""
    try:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or any(char in value for char in ("?", "#", "\\"))
            or any(ord(char) <= 32 or ord(char) == 127 for char in value)
            or parts.port == 0
        ):
            raise InvalidProjectConfigError()
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    except (ValueError, UnicodeError):
        raise InvalidProjectConfigError() from None


def _endpoint_data(body: EndpointRequest, request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    data = body.model_dump(exclude_none=True)
    if body.provider == "sponsored":
        if (
            not settings.hosted
            or body.api_key is not None
            or body.model not in settings.hosted_models
        ):
            raise InvalidProjectConfigError()
        destination = PRESETS["meta"].base_url
    elif body.provider in PRESETS:
        destination = PRESETS[body.provider].base_url
    else:
        if body.base_url is None:
            raise InvalidProjectConfigError()
        destination = body.base_url
    if (
        body.provider != "custom"
        and body.base_url is not None
        and _local_base_url(body.base_url) != destination
    ):
        raise InvalidProjectConfigError()
    # Sync FastAPI handlers run in AnyIO workers; DNS preflight returns to the event loop.
    # The hosted gateway validates again when connecting, preserving DNS-rebinding protection.
    data["base_url"] = (
        from_thread.run(validate_destination, destination)
        if settings.hosted
        else _local_base_url(destination)
    )
    return data


@router.get("/v1/projects")
def list_projects(request: Request) -> dict[str, Any]:
    """List owned projects and the automatically established default project."""
    store, owner = _context(request)
    default = store.default_project(owner)
    return {"projects": store.list_projects(owner), "default_project_id": default["id"]}


@router.post("/v1/projects", status_code=201)
def create_project(body: NameRequest, request: Request) -> dict[str, Any]:
    """Create a project with a deployment-default policy version."""
    store, owner = _context(request)
    return store.create_project(owner, body.name)


@router.get("/v1/projects/{project_id}")
def get_project(request: Request, project_id: ResourceId) -> dict[str, Any]:
    """Read one owned project and its default policy version identifier."""
    store, owner = _context(request)
    return store.get_project(owner, project_id)


@router.get("/v1/projects/{project_id}/policies")
def list_policies(request: Request, project_id: ResourceId) -> dict[str, Any]:
    """List immutable policy versions in an owned project."""
    store, owner = _context(request)
    return {"policies": store.list_policies(owner, project_id)}


@router.post("/v1/projects/{project_id}/policies", status_code=201)
def create_policy(body: PolicyRequest, request: Request, project_id: ResourceId) -> dict[str, Any]:
    """Create a reusable policy family with its first immutable version."""
    store, owner = _context(request)
    return store.create_policy(owner, project_id, _policy_data(body, request))


@router.put("/v1/projects/{project_id}/policies/{policy_id}", status_code=201)
def revise_policy(
    body: PolicyRequest, request: Request, project_id: ResourceId, policy_id: ResourceId
) -> dict[str, Any]:
    """Append an immutable version; existing endpoint assignments remain pinned."""
    store, owner = _context(request)
    return store.create_policy(owner, project_id, _policy_data(body, request), policy_id=policy_id)


@router.get("/v1/projects/{project_id}/policies/versions/{policy_version_id}")
def get_policy_version(
    request: Request, project_id: ResourceId, policy_version_id: ResourceId
) -> dict[str, Any]:
    """Read an exact immutable policy version from an owned project."""
    store, owner = _context(request)
    return store.get_policy(owner, project_id, policy_version_id)


@router.get("/v1/projects/{project_id}/endpoints")
def list_endpoints(request: Request, project_id: ResourceId) -> dict[str, Any]:
    """List endpoint metadata without returning provider credentials."""
    store, owner = _context(request)
    return {"endpoints": store.list_endpoints(owner, project_id)}


@router.post("/v1/projects/{project_id}/endpoints", status_code=201)
def create_endpoint(
    body: EndpointRequest, request: Request, project_id: ResourceId
) -> dict[str, Any]:
    """Create an endpoint bound to one provider, model and explicit policy version."""
    store, owner = _context(request)
    store.get_project(owner, project_id)
    return store.save_endpoint(owner, project_id, _endpoint_data(body, request))


@router.put("/v1/projects/{project_id}/endpoints/{endpoint_id}")
def update_endpoint(
    body: EndpointRequest, request: Request, project_id: ResourceId, endpoint_id: ResourceId
) -> dict[str, Any]:
    """Replace endpoint configuration; an omitted credential preserves the existing one."""
    store, owner = _context(request)
    store.get_project(owner, project_id)
    return store.save_endpoint(
        owner, project_id, _endpoint_data(body, request), endpoint_id=endpoint_id
    )


@router.delete("/v1/projects/{project_id}/endpoints/{endpoint_id}", status_code=204)
def delete_endpoint(request: Request, project_id: ResourceId, endpoint_id: ResourceId) -> Response:
    """Delete an owned endpoint and revoke all of its endpoint keys."""
    store, owner = _context(request)
    store.delete_endpoint(owner, project_id, endpoint_id)
    return Response(status_code=204)


@router.get("/v1/projects/{project_id}/endpoints/{endpoint_id}/keys")
def list_keys(request: Request, project_id: ResourceId, endpoint_id: ResourceId) -> dict[str, Any]:
    """List endpoint key metadata; raw bearer keys cannot be recovered."""
    store, owner = _context(request)
    return {"keys": store.list_keys(owner, project_id, endpoint_id)}


@router.post("/v1/projects/{project_id}/endpoints/{endpoint_id}/keys", status_code=201)
def issue_key(
    body: NameRequest, request: Request, project_id: ResourceId, endpoint_id: ResourceId
) -> dict[str, Any]:
    """Issue a revocable endpoint key, revealing its raw value only in this response."""
    store, owner = _context(request)
    return store.issue_key(owner, project_id, endpoint_id, body.name)


@router.delete("/v1/projects/{project_id}/endpoints/{endpoint_id}/keys/{key_id}", status_code=204)
def revoke_key(
    request: Request, project_id: ResourceId, endpoint_id: ResourceId, key_id: ResourceId
) -> Response:
    """Revoke an endpoint key for subsequent gateway admissions."""
    store, owner = _context(request)
    store.revoke_key(owner, project_id, endpoint_id, key_id)
    return Response(status_code=204)
