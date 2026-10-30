"""Smoke tests for the skeleton: CLI, API, config, types and registry."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel

from pii_guard import __version__, cli, registry
from pii_guard.api.app import create_app
from pii_guard.api.routes import discover_routers
from pii_guard.config import DEFAULT_PORT, Settings
from pii_guard.types import (
    TEXT_ENTITY_TYPES,
    VISUAL_ENTITY_TYPES,
    DetectionError,
    Detector,
    EntityType,
    MaskingError,
    PiiGuardError,
    Span,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Obviously fictional value, used only to check it never leaks into reprs or errors.
FAKE_NAME = "Teszt Elek"


# --- CLI --------------------------------------------------------------------


def test_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "serve" in out
    assert "eval" in out


def test_cli_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0
    assert "usage: pii-guard" in capsys.readouterr().out


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_cli_eval_delegates_to_the_eval_cli(capsys: pytest.CaptureFixture[str]) -> None:
    # Everything after "eval" goes to pii_guard.eval.cli; its own errors exit with 2.
    assert cli.main(["eval", "--fixtures", "missing.jsonl"]) == 2
    assert "pii-guard eval:" in capsys.readouterr().err


def test_cli_serve_runs_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(app: str, **kwargs: object) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setattr("uvicorn.run", fake_run)
    assert cli.main(["serve"]) == 0
    assert calls[0]["app"] == "pii_guard.api.app:create_app"
    assert calls[0]["factory"] is True
    assert calls[0]["port"] == 8787

    monkeypatch.setenv("PII_GUARD_PORT", "9999")
    from pii_guard.config import get_settings

    get_settings.cache_clear()
    assert cli.main(["serve", "--host", "0.0.0.0"]) == 0  # noqa: S104
    assert calls[1]["port"] == 9999
    assert calls[1]["host"] == "0.0.0.0"  # noqa: S104


def test_python_dash_m() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pii_guard", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "usage: pii-guard" in result.stdout
    assert "PII Guard, a privacy firewall" in result.stdout  # the wordmark (LAB-1486)


# --- API --------------------------------------------------------------------


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    # OCR availability depends on the host's Tesseract (LAB-1219); the rest is fixed.
    assert body.pop("ocr") in {"on", "off"}
    assert isinstance(body.pop("image_require_ocr"), bool)
    assert body == {"status": "ok", "version": __version__, "ner": "off"}


def test_unknown_route_uses_error_body(client: TestClient) -> None:
    response = client.get("/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_v1_routers_are_mounted() -> None:
    paths = {route.path for router in discover_routers() for route in router.routes}
    assert {"/v1/analyze", "/v1/mask", "/v1/unmask"} <= paths


class _Body(BaseModel):
    text: str
    count: int


def _app_with_test_routes() -> TestClient:
    router = APIRouter()

    @router.post("/test/validate")
    def validate(body: _Body) -> dict[str, str]:
        return {"ok": "yes"}

    @router.get("/test/masking-error")
    def masking_error() -> None:
        raise MaskingError("could not mask 1 PERSON span")

    @router.get("/test/crash")
    def crash() -> None:
        raise RuntimeError(f"boom {FAKE_NAME}")

    app = create_app(Settings())
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_validation_error_does_not_echo_input() -> None:
    client = _app_with_test_routes()
    response = client.post("/test/validate", json={"text": FAKE_NAME, "count": FAKE_NAME})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert "body.count" in body["error"]["message"]
    assert FAKE_NAME not in response.text


def test_pii_guard_error_maps_to_error_body() -> None:
    client = _app_with_test_routes()
    response = client.get("/test/masking-error")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "masking_failed", "message": "could not mask 1 PERSON span"}
    }


def test_unhandled_error_hides_details() -> None:
    client = _app_with_test_routes()
    response = client.get("/test/crash")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert FAKE_NAME not in response.text


# --- Config -----------------------------------------------------------------


def _env_example_keys() -> list[str]:
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    return re.findall(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE)


def test_config_defaults(settings: Settings) -> None:
    assert settings.port == DEFAULT_PORT == 8787
    assert settings.host == "127.0.0.1"
    assert settings.tenant_key is None
    assert settings.tenant_key_bytes() is None


def test_config_covers_env_example(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = _env_example_keys()
    assert keys, ".env.example has no keys"
    samples = {
        "PII_GUARD_HOSTED_PROJECT_STORE": "azure_blob",
        "PII_GUARD_HOSTED_PROJECT_ENVIRONMENT": "prod",
    }
    for key in keys:
        monkeypatch.setenv(key, samples.get(key, "00ff"))
    settings = Settings()
    for key in keys:
        field = key.removeprefix("PII_GUARD_").lower()
        value = getattr(settings, field)
        raw = value.get_secret_value() if hasattr(value, "get_secret_value") else value
        assert raw == samples.get(key, "00ff"), key


def test_config_empty_values_are_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_SAM_URL", "")
    monkeypatch.setenv("META_API_KEY", "")
    settings = Settings()
    assert settings.sam_url is None
    assert settings.meta_api_key is None


def test_config_secrets_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_TENANT_KEY", "ab" * 32)
    monkeypatch.setenv("PII_GUARD_PORT", "9000")
    settings = Settings()
    assert settings.port == 9000
    assert "ab" * 32 not in repr(settings)
    assert settings.tenant_key_bytes() == bytes.fromhex("ab" * 32)


def test_config_bad_tenant_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_TENANT_KEY", "not-hex-secret")
    with pytest.raises(ValueError, match="hex") as exc:
        Settings().tenant_key_bytes()
    assert "not-hex-secret" not in str(exc.value)


# --- Types ------------------------------------------------------------------


def test_entity_types_match_docs() -> None:
    text = (REPO_ROOT / "docs" / "entities.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `([A-Z][A-Z0-9_]*)` \|", text, flags=re.MULTILINE))
    assert documented == {t.value for t in EntityType}
    assert {t.value for t in VISUAL_ENTITY_TYPES} == {"FACE", "SIGNATURE", "ID_PHOTO", "STAMP"}
    assert set(EntityType) == TEXT_ENTITY_TYPES | VISUAL_ENTITY_TYPES
    assert EntityType.FACE.is_visual
    assert not EntityType.PERSON.is_visual


def test_span_repr_hides_text() -> None:
    span = Span(0, len(FAKE_NAME), EntityType.PERSON, FAKE_NAME, 0.9, "rules")
    assert FAKE_NAME not in repr(span)
    assert FAKE_NAME not in str(span)
    assert FAKE_NAME not in repr([span])
    assert span.length == len(FAKE_NAME)
    assert span.to_public_dict() == {
        "start": 0,
        "end": len(FAKE_NAME),
        "entity_type": "PERSON",
        "score": 0.9,
        "detector": "rules",
    }


def test_span_is_frozen_and_hashable() -> None:
    span = Span(0, 4, "EMAIL", "a@b.", 1.0, "rules")  # type: ignore[arg-type]
    assert span.entity_type is EntityType.EMAIL
    assert span == Span(0, 4, EntityType.EMAIL, "a@b.", 1.0, "rules")
    assert len({span, Span(0, 4, EntityType.EMAIL, "a@b.", 1.0, "rules")}) == 1
    with pytest.raises(AttributeError):
        span.start = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    ("start", "end", "entity_type", "text", "score", "detector"),
    [
        (-1, 2, EntityType.PERSON, "abc", 0.5, "x"),
        (2, 2, EntityType.PERSON, "", 0.5, "x"),
        (0, 3, EntityType.PERSON, "ab", 0.5, "x"),
        (0, 2, EntityType.PERSON, "ab", 1.5, "x"),
        (0, 2, EntityType.PERSON, "ab", 0.5, ""),
        (0, 2, "NOT_A_TYPE", "ab", 0.5, "x"),
    ],
)
def test_span_validation(
    start: int, end: int, entity_type: str, text: str, score: float, detector: str
) -> None:
    with pytest.raises(ValueError):
        Span(start, end, entity_type, text, score, detector)  # type: ignore[arg-type]


def test_span_overlaps() -> None:
    a = Span(0, 5, EntityType.PERSON, "aaaaa", 1.0, "x")
    b = Span(4, 6, EntityType.PERSON, "bb", 1.0, "x")
    c = Span(5, 6, EntityType.PERSON, "c", 1.0, "x")
    assert a.overlaps(b)
    assert not a.overlaps(c)


class _EchoDetector:
    name = "echo"

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        return [Span(0, len(text), EntityType.PERSON, text, 1.0, self.name)] if text else []


def test_detector_protocol() -> None:
    assert isinstance(_EchoDetector(), Detector)
    assert not isinstance(object(), Detector)


def test_errors() -> None:
    assert issubclass(MaskingError, PiiGuardError)
    assert issubclass(DetectionError, PiiGuardError)
    assert MaskingError().code == "masking_failed"
    assert MaskingError().message == "masking_failed"
    assert DetectionError("x", code="detector_timeout").code == "detector_timeout"
    assert DetectionError.status_code == 503


# --- Registry ---------------------------------------------------------------


def test_registry_builtin_names() -> None:
    assert "rules" in registry.detector_names()


def test_registry_register_and_create(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_registry", dict(registry._registry))
    registry.register_detector("echo", f"{__name__}:_EchoDetector")
    assert registry.resolve_detector("echo") is _EchoDetector
    detector = registry.create_detector("echo")
    assert detector.detect("ab")[0].detector == "echo"
    with pytest.raises(ValueError, match="already registered"):
        registry.register_detector("echo", "other.module:Other")
    registry.register_detector("echo", "other.module:Other", replace=True)
    with pytest.raises(DetectionError):
        registry.resolve_detector("echo")
    with pytest.raises(ValueError, match="ClassName"):
        registry.register_detector("bad", "no_colon")


def test_registry_unknown_name() -> None:
    with pytest.raises(DetectionError, match="unknown detector"):
        registry.resolve_detector("no_such_detector_xyz")
    with pytest.raises(DetectionError, match="unknown detector"):
        registry.resolve_detector("not an identifier")


def test_routes_are_discovered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import pii_guard.api.routes as routes_pkg

    (tmp_path / "zz_demo.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.get('/v1/demo')\n"
        "def demo():\n"
        "    return {'demo': True}\n",
        encoding="utf-8",
    )
    (tmp_path / "_private.py").write_text("raise RuntimeError('not imported')\n")
    (tmp_path / "no_router.py").write_text("X = 1\n")
    monkeypatch.setattr(routes_pkg, "__path__", [*routes_pkg.__path__, str(tmp_path)])
    for name in ("zz_demo", "no_router"):
        monkeypatch.delitem(sys.modules, f"pii_guard.api.routes.{name}", raising=False)

    with TestClient(create_app(Settings())) as client:
        assert client.get("/v1/demo").json() == {"demo": True}


def test_registry_module_convention(monkeypatch: pytest.MonkeyPatch) -> None:
    import types as pytypes

    module = pytypes.ModuleType("pii_guard.detect.conventional")
    module.DETECTOR_CLASS = _EchoDetector  # type: ignore[attr-defined]
    package = pytypes.ModuleType("pii_guard.detect")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, "pii_guard.detect", package)
    monkeypatch.setitem(sys.modules, "pii_guard.detect.conventional", module)
    assert registry.resolve_detector("conventional") is _EchoDetector

    empty = pytypes.ModuleType("pii_guard.detect.empty")
    monkeypatch.setitem(sys.modules, "pii_guard.detect.empty", empty)
    with pytest.raises(DetectionError, match="DETECTOR_CLASS"):
        registry.resolve_detector("empty")
