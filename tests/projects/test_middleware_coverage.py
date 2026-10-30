"""Coverage tests for ProjectMiddleware, prepare_project, and endpoint_body."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from pii_guard.config import Settings
from pii_guard.projects.middleware import (
    ProjectAccessError,
    ProjectMiddleware,
    endpoint_body,
    prepare_project,
)
from pii_guard.projects.runtime import ProjectService
from pii_guard.projects.store import EndpointSnapshot


def make_snapshot(
    *,
    id: str = "ep1",
    project_id: str = "prj1",
    enabled: bool = True,
    model: str | None = "pinned-model",
) -> EndpointSnapshot:
    return EndpointSnapshot(
        owner_id="owner",
        project_id=project_id,
        id=id,
        name="test-endpoint",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model=model,
        api_key=None,
        enabled=enabled,
        policy_id="pol1",
        policy_version_id="pv1",
        policy_version=1,
        policy={"mode": "fast", "language": "en", "entity_policies": {}},
    )


@pytest.fixture
def service(tmp_path) -> ProjectService:
    settings = Settings(
        _env_file=None,
        tenant_key="38" * 32,
        project_state_path=str(tmp_path / "projects.sqlite3"),
    )
    svc = ProjectService(settings)
    yield svc
    svc.close()


def test_prepare_project_header_validation(service: ProjectService) -> None:
    # Duplicate selection headers
    scope = {
        "type": "http",
        "path": "/v1/chat/completions",
        "headers": [
            (b"x-pii-guard-project", b"prj1"),
            (b"x-pii-guard-project", b"prj2"),
        ],
    }
    with pytest.raises(ProjectAccessError, match="Duplicate project selection header"):
        prepare_project(service, scope, "owner")

    # Endpoint inspection on disallowed route
    scope_disallowed = {
        "type": "http",
        "path": "/v1/models",
        "headers": [(b"x-pii-guard-endpoint", b"ep1")],
    }
    with pytest.raises(ProjectAccessError, match="Endpoint inspection selector is unavailable"):
        prepare_project(service, scope_disallowed, "owner")


def test_prepare_project_snapshot_conflict(service: ProjectService) -> None:
    prj = service.store.default_project("owner")
    snapshot = make_snapshot(project_id=prj["id"])

    # Different endpoint in header
    scope_ep = {
        "type": "http",
        "path": "/v1/traffic",
        "headers": [(b"x-pii-guard-endpoint", b"other-ep")],
    }
    with pytest.raises(ProjectAccessError, match="Endpoint key cannot select another endpoint"):
        prepare_project(service, scope_ep, "owner", snapshot=snapshot)

    # Different project in header
    scope_prj = {
        "type": "http",
        "path": "/v1/chat/completions",
        "headers": [(b"x-pii-guard-project", b"other-prj")],
    }
    with pytest.raises(ProjectAccessError, match="Endpoint key cannot select another project"):
        prepare_project(service, scope_prj, "owner", snapshot=snapshot)

    # Disabled snapshot
    disabled_snapshot = make_snapshot(project_id=prj["id"], enabled=False)
    with pytest.raises(ProjectAccessError, match="Endpoint is disabled or outside this request"):
        scope_chat = {"type": "http", "path": "/v1/chat/completions", "headers": []}
        prepare_project(service, scope_chat, "owner", snapshot=disabled_snapshot)


def test_endpoint_body_validation() -> None:
    endpoint = make_snapshot()
    state = {
        "project_endpoint": endpoint,
        "project_policy": {"mode": "fast", "language": "en"},
    }

    # Duplicate control header
    scope_dup = {
        "type": "http",
        "method": "POST",
        "path": "/e/ep1/v1/chat/completions",
        "headers": [
            (b"x-pii-guard-mode", b"fast"),
            (b"x-pii-guard-mode", b"audit"),
        ],
    }
    with pytest.raises(ProjectAccessError, match="Duplicate endpoint control header"):
        asyncio.run(endpoint_body(scope_dup, MagicMock(), state, 1000))

    # Connection override attempt
    scope_conn = {
        "type": "http",
        "method": "POST",
        "path": "/e/ep1/v1/chat/completions",
        "headers": [(b"x-pii-guard-connection", b"custom")],
    }
    with pytest.raises(ProjectAccessError, match="Endpoint upstream cannot be overridden"):
        asyncio.run(endpoint_body(scope_conn, MagicMock(), state, 1000))

    # Mode override attempt
    scope_mode = {
        "type": "http",
        "method": "POST",
        "path": "/e/ep1/v1/chat/completions",
        "headers": [(b"x-pii-guard-mode", b"audit")],
    }
    with pytest.raises(ProjectAccessError, match="Endpoint detection mode cannot be overridden"):
        asyncio.run(endpoint_body(scope_mode, MagicMock(), state, 1000))

    # Language override attempt
    scope_lang = {
        "type": "http",
        "method": "POST",
        "path": "/e/ep1/v1/chat/completions",
        "headers": [(b"x-pii-guard-language", b"hu")],
    }
    with pytest.raises(ProjectAccessError, match="Endpoint language cannot be overridden"):
        asyncio.run(endpoint_body(scope_lang, MagicMock(), state, 1000))

    # Disconnect
    async def disconnect_receive():
        return {"type": "http.disconnect"}

    scope_base = {
        "type": "http",
        "method": "POST",
        "path": "/e/ep1/v1/chat/completions",
        "headers": [],
    }
    with pytest.raises(ProjectAccessError, match="Request disconnected"):
        asyncio.run(endpoint_body(scope_base, disconnect_receive, state, 1000))

    # Body too large
    async def large_receive():
        return {"type": "http.request", "body": b"x" * 100, "more_body": False}

    with pytest.raises(ProjectAccessError, match="Endpoint request body is too large"):
        asyncio.run(endpoint_body(scope_base, large_receive, state, 50))

    # Invalid JSON
    async def bad_json_receive():
        return {"type": "http.request", "body": b"not valid json{", "more_body": False}

    with pytest.raises(ProjectAccessError, match="Invalid endpoint JSON request"):
        asyncio.run(endpoint_body(scope_base, bad_json_receive, state, 1000))

    # Request not an object
    async def list_json_receive():
        return {"type": "http.request", "body": b"[1, 2, 3]", "more_body": False}

    with pytest.raises(ProjectAccessError, match="Endpoint request must be an object"):
        asyncio.run(endpoint_body(scope_base, list_json_receive, state, 1000))

    # Model mismatch
    async def mismatch_model_receive():
        return {"type": "http.request", "body": b'{"model": "wrong-model"}', "more_body": False}

    with pytest.raises(ProjectAccessError, match="Endpoint allows only its configured model"):
        asyncio.run(endpoint_body(scope_base, mismatch_model_receive, state, 1000))


def test_project_middleware_non_http():
    app = MagicMock()

    async def mock_app(scope, receive, send):
        app()

    middleware = ProjectMiddleware(mock_app, MagicMock())
    scope = {"type": "lifespan"}
    asyncio.run(middleware(scope, MagicMock(), MagicMock()))
    app.assert_called_once()
