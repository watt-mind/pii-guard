"""The OpenAPI schema documents every model, field, operation and error (LAB-1272).

Plus the shared fail-closed helper the masking routes use (``ephemeral_session``).
All values are fictional (ADR 0005).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from api_helpers import TEST_TENANT_KEY
from fastapi import Request

from pii_guard.api.app import create_app
from pii_guard.api.errors import COMMON_ERRORS, ERROR_CODES, error_responses
from pii_guard.api.routes._common import ephemeral_session
from pii_guard.api.routes.traffic import TrafficLogDisabledError
from pii_guard.config import Settings
from pii_guard.detect.stack import DetectionUnavailableError
from pii_guard.detection_profile import DetectionProfileError
from pii_guard.policy import BlockedEntityError
from pii_guard.types import (
    DetectionError,
    EntityType,
    MaskingError,
    PayloadTooLargeError,
    PiiGuardError,
)
from pii_guard.vault import Vault
from pii_guard.vault.known import KnownValueError
from pii_guard.vault.vault import PlaceholderInInputError, SessionNotFoundError
from pii_guard.visual.masking import (
    InvalidImageError,
    OcrUnavailableError,
    UnsupportedImageError,
)

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts.md"
# FastAPI's own validation schemas: unused by our routes (they declare ErrorResponse for 422).
FASTAPI_SCHEMAS = {"HTTPValidationError", "ValidationError"}
# The gateway's operations are documented separately (LAB-1256 is changing them).
GATEWAY_TAG = "gateway"


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return create_app(Settings(tenant_key=TEST_TENANT_KEY)).openapi()


def _operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (method.upper(), path, op)
        for path, ops in spec["paths"].items()
        for method, op in ops.items()
        if GATEWAY_TAG not in op.get("tags", [])
    ]


def _contracts_error_table() -> dict[str, int]:
    """``code -> status`` from the REST API "Errors" table of docs/contracts.md."""
    text = CONTRACTS.read_text(encoding="utf-8")
    section = text[text.index("## REST API") :]
    section = section[: section.index("### `POST /v1/analyze`")]
    return {
        code: int(status)
        for status, code in re.findall(r"^\| (\d{3}) \| `([a-z_]+)` \|", section, re.M)
    }


def test_the_docs_name_the_product(spec: dict[str, Any]) -> None:
    """The /docs page title is the wordmark; the command stays ``pii-guard`` (LAB-1486)."""
    assert spec["info"]["title"] == "PII Guard"


def test_every_schema_has_a_description(spec: dict[str, Any]) -> None:
    missing = [
        name
        for name, schema in spec["components"]["schemas"].items()
        if name not in FASTAPI_SCHEMAS and not schema.get("description", "").strip()
    ]
    assert missing == []


def test_every_property_has_a_description(spec: dict[str, Any]) -> None:
    missing = [
        f"{name}.{prop}"
        for name, schema in spec["components"]["schemas"].items()
        if name not in FASTAPI_SCHEMAS
        for prop, definition in schema.get("properties", {}).items()
        if not definition.get("description", "").strip()
    ]
    assert missing == []


def test_every_operation_has_a_summary_and_description(spec: dict[str, Any]) -> None:
    operations = _operations(spec)
    paths = {path for _, path, _ in operations}
    # The non-gateway surface: if one disappears from the schema, this test must notice.
    assert {
        "/healthz",
        "/v1/analyze",
        "/v1/mask",
        "/v1/mask/image",
        "/v1/unmask",
        "/v1/sessions",
        "/v1/sessions/{session_id}/known-values",
        "/v1/status",
        "/v1/traffic",
        "/v1/traffic/stream",
    } <= paths
    missing = [
        f"{method} {path}"
        for method, path, op in operations
        if not op.get("summary", "").strip() or not op.get("description", "").strip()
    ]
    assert missing == []


def test_every_parameter_has_a_description(spec: dict[str, Any]) -> None:
    missing = [
        f"{method} {path} {param['name']}"
        for method, path, op in _operations(spec)
        for param in op.get("parameters", [])
        if not param.get("description", "").strip()
    ]
    assert missing == []


def test_error_responses_use_the_error_envelope(spec: dict[str, Any]) -> None:
    for method, path, op in _operations(spec):
        errors = {s: r for s, r in op["responses"].items() if int(s) >= 400}
        assert errors, f"{method} {path} declares no error responses"
        for status, response in errors.items():
            body = response["content"]["application/json"]
            assert body["schema"] == {"$ref": "#/components/schemas/ErrorResponse"}
            for code, example in body["examples"].items():
                assert ERROR_CODES[code][0] == int(status), (path, code)
                assert example["value"]["error"]["code"] == code


def test_routes_declare_the_errors_they_raise(spec: dict[str, Any]) -> None:
    def codes(path: str, method: str = "post") -> set[str]:
        responses = spec["paths"][path][method]["responses"].values()
        return {
            code
            for r in responses
            for code in r.get("content", {}).get("application/json", {}).get("examples", {})
        }

    assert {"blocked_entity", "placeholder_in_input", "not_found"} <= codes("/v1/mask")
    assert {"unsupported_media_type", "invalid_image", "ocr_unavailable"} <= codes("/v1/mask/image")
    assert {"invalid_known_value", "too_many_known_values"} <= codes("/v1/sessions")
    assert "not_found" in codes("/v1/unmask")
    assert "traffic_log_disabled" in codes("/v1/traffic", "get")
    assert set(COMMON_ERRORS) <= codes("/v1/analyze")
    for path in (
        "/v1/analyze",
        "/v1/mask",
        "/v1/mask/image",
        "/v1/chat/completions",
        "/v1/responses",
    ):
        assert "detection_profile_denied" in codes(path)
    assert codes("/healthz", "get") == {"traffic_log_not_local"}  # no token on /healthz


def test_documented_error_codes_are_in_contracts(spec: dict[str, Any]) -> None:
    table = _contracts_error_table()
    declared = {
        code
        for _, _, op in _operations(spec)
        for response in op["responses"].values()
        for code in response.get("content", {}).get("application/json", {}).get("examples", {})
    }
    assert declared <= set(ERROR_CODES)
    assert {code: ERROR_CODES[code][0] for code in declared} == {
        code: table.get(code) for code in declared
    }
    # Every code in the registry is documented with the same status, used or not.
    assert {code: status for code, (status, _) in ERROR_CODES.items()} == {
        code: table.get(code) for code in ERROR_CODES
    }


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (PiiGuardError, "internal_error"),
        (DetectionError, "detection_failed"),
        (DetectionProfileError, "detection_profile_denied"),
        (DetectionUnavailableError, "detection_unavailable"),
        (MaskingError, "masking_failed"),
        (PlaceholderInInputError, "placeholder_in_input"),
        (SessionNotFoundError, "not_found"),
        (BlockedEntityError, "blocked_entity"),
        (PayloadTooLargeError, "payload_too_large"),
        (UnsupportedImageError, "unsupported_media_type"),
        (InvalidImageError, "invalid_image"),
        (OcrUnavailableError, "ocr_unavailable"),
        (TrafficLogDisabledError, "traffic_log_disabled"),
        (KnownValueError, "invalid_known_value"),
    ],
)
def test_error_codes_match_the_exception_classes(error: type[PiiGuardError], code: str) -> None:
    assert error.code == code
    assert ERROR_CODES[code][0] == error.status_code


def test_error_responses_rejects_undocumented_codes() -> None:
    with pytest.raises(KeyError):
        error_responses("no_such_code")


# --- ephemeral_session -------------------------------------------------------------------


def _vault() -> Vault:
    return Vault.from_settings(Settings(tenant_key=TEST_TENANT_KEY))


def _request() -> Request:
    return cast(Request, SimpleNamespace(state=SimpleNamespace(), headers={}))


def _blocked() -> BlockedEntityError:
    return BlockedEntityError({EntityType.EMAIL: 2, EntityType.PERSON: 1})


def test_ephemeral_session_keeps_a_new_session_on_success() -> None:
    vault = _vault()
    with ephemeral_session(vault, None, _request()) as session:
        pass
    assert len(vault) == 1
    assert vault.session(session.session_id) is session


@pytest.mark.parametrize(
    "error", [_blocked(), DetectionError("detector timed out"), asyncio.CancelledError()]
)
def test_ephemeral_session_drops_a_new_session_on_any_error(error: BaseException) -> None:
    vault = _vault()
    request = _request()
    with pytest.raises(type(error)), ephemeral_session(vault, None, request) as session:
        assert len(vault) == 1
        raise error
    assert len(vault) == 0
    with pytest.raises(SessionNotFoundError):
        vault.session(session.session_id)


def test_ephemeral_session_keeps_an_existing_session_on_error() -> None:
    vault = _vault()
    existing = vault.session()
    with (
        pytest.raises(BlockedEntityError),
        ephemeral_session(vault, existing.session_id, _request()) as session,
    ):
        assert session is existing
        raise _blocked()
    assert vault.session(existing.session_id) is existing


def test_ephemeral_session_logs_blocked_counts_only_for_blocked_errors() -> None:
    request = _request()
    with pytest.raises(BlockedEntityError), ephemeral_session(_vault(), None, request):
        raise _blocked()
    assert request.state.log_fields == {"blocked": "EMAIL:2,PERSON:1"}

    other = _request()
    with pytest.raises(DetectionError), ephemeral_session(_vault(), None, other):
        raise DetectionError("detector timed out")
    assert getattr(other.state, "log_fields", None) is None


def test_ephemeral_session_without_a_vault_still_logs_blocked() -> None:
    request = _request()
    with pytest.raises(BlockedEntityError), ephemeral_session(None, None, request) as session:
        assert session is None
        raise _blocked()
    assert request.state.log_fields == {"blocked": "EMAIL:2,PERSON:1"}


def test_ephemeral_session_unknown_id_is_404_before_the_block() -> None:
    ran = False
    with (
        pytest.raises(SessionNotFoundError),
        ephemeral_session(_vault(), "s_no_such_session", _request()),
    ):
        ran = True
    assert not ran
