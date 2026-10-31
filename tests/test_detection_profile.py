"""The local-only profile controls raw processing, independently of masked inference."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.detect import ner, stack
from pii_guard.detect.llm import LlmDetector
from pii_guard.detection_profile import DetectionProfileError
from pii_guard.gateway.config import GatewayConfig, Mode
from pii_guard.gateway.detection import build_mode_detectors
from pii_guard.types import DetectionError

EMAIL = "synthetic.reader@example.com"


def local(**overrides):
    return Settings(
        _env_file=None,
        **{
            "detection_profile": "local-only",
            "detectors": ("rules",),
            "tenant_key": "42" * 32,
            "ner_fallback": "off",
            "upstream_base_url": "https://synthetic-model.example/v1",
            **overrides,
        },
    )


def test_default_profile_preserves_standard():
    assert Settings(_env_file=None).detection_profile == "standard"


def test_rules_selection_ignores_unused_endpoint_defaults(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("an unused remote detector or NER fallback was constructed")

    monkeypatch.setattr(stack, "_ner_available", forbidden)
    monkeypatch.setattr("pii_guard.detect.llm.LlmDetector", forbidden)
    settings = local(llm_detector_url="https://unused.example/v1", sam_url="https://unused.example")
    assert stack.rest_detector_names(settings) == ("rules",)
    assert stack.default_detector_names(settings) == ("rules",)
    assert set(build_mode_detectors(settings, GatewayConfig())) == {Mode.FAST}
    assert not stack.warm_up(settings)


@pytest.mark.parametrize("name", ["llm", "custom-network-detector"])
def test_selected_remote_or_unknown_detector_fails_before_creation(name, monkeypatch):
    monkeypatch.setattr(stack, "create_detector", lambda *a, **kw: pytest.fail("constructed"))
    with pytest.raises(DetectionProfileError):
        stack.build_detector(name, local(detectors=(name,)))
    with pytest.raises(DetectionProfileError):
        create_app(local(detectors=(name,)))


@pytest.mark.parametrize("model", [None, "fictional-hub/model", "/nonexistent/synthetic-model"])
def test_default_ner_requires_explicit_provisioned_directory(model, monkeypatch):
    monkeypatch.setattr(stack, "_ner_available", lambda: pytest.fail("resolved before path check"))
    with pytest.raises(DetectionProfileError):
        stack.default_detector_names(local(detectors=None, ner_model=model))


def test_missing_local_dependency_does_not_downgrade_to_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(stack, "_ner_available", lambda: False)
    with pytest.raises(DetectionError, match="not installed"):
        stack.default_detector_names(local(detectors=None, ner_model=str(tmp_path)))


@pytest.mark.parametrize("backend,gliner_config", [("gliner", False), ("transformers", True)])
def test_unsupported_local_ner_backend_refused(tmp_path, backend, gliner_config):
    if gliner_config:
        (tmp_path / "gliner_config.json").write_text("{}")
    with pytest.raises(DetectionProfileError):
        stack.default_detector_names(
            local(detectors=None, ner_model=str(tmp_path), ner_backend=backend)
        )


def test_lazy_local_load_cannot_download_and_uses_local_files_only(tmp_path, monkeypatch):
    loaded = []

    class SyntheticBackend:
        def __init__(self, model, **kwargs):
            loaded.append((model, kwargs))

        def predict(self, text):
            return []

    monkeypatch.setattr(ner, "_shared_backends", {})
    monkeypatch.setattr(ner, "dependencies_available", lambda: True)
    monkeypatch.setattr(ner, "TransformersBackend", SyntheticBackend)
    monkeypatch.setattr(ner.ner_resolve, "ensure", lambda *a: pytest.fail("model download"))
    detector = ner.NerDetector(model=str(tmp_path), preload=False, local_files_only=True)
    assert not loaded
    assert detector.detect(EMAIL) == []
    assert loaded[0][1]["local_files_only"] is True
    assert loaded[0][0] == str(tmp_path)


def test_stack_passes_local_load_constraint(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(stack, "create_detector", lambda name, **kw: seen.append(kw))
    stack.build_detector("ner", local(ner_model=str(tmp_path)))
    assert seen[0]["local_files_only"] is True
    assert seen[0]["backend_kind"] == "transformers"


@pytest.mark.parametrize("url", ["https://raw-detector.example/v1", "http://127.0.0.1:8765/v1"])
def test_direct_llm_overrides_cannot_escape_profile(url):
    transport = httpx.MockTransport(lambda request: pytest.fail("raw input was transmitted"))
    with pytest.raises(DetectionProfileError):
        LlmDetector(settings=local(), base_url=url, api_key="synthetic", transport=transport)


def test_preconstructed_llm_checks_authoritative_settings_before_send():
    settings = Settings(_env_file=None)
    detector = LlmDetector(
        settings=settings,
        api_key="synthetic",
        transport=httpx.MockTransport(lambda request: pytest.fail("network")),
    )
    settings.detection_profile = "local-only"
    with pytest.raises(DetectionProfileError):
        detector.detect(EMAIL)


@pytest.mark.parametrize("endpoint", ["/v1/chat/completions", "/v1/responses"])
def test_local_detection_still_forwards_only_masked_input_to_selected_external_model(endpoint):
    sent = []

    def upstream(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "model": "synthetic-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "Accepted"}}],
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Accepted"}],
                    }
                ],
            },
        )

    app = create_app(local())
    app.state.gateway_transport = httpx.MockTransport(upstream)
    body = {"model": "synthetic-model", "messages": [{"role": "user", "content": EMAIL}]}
    if endpoint == "/v1/responses":
        body = {"model": "synthetic-model", "input": EMAIL}
    with TestClient(app) as client:
        response = client.post(endpoint, json=body)
    assert response.status_code == 200, response.text
    assert len(sent) == 1
    assert EMAIL not in json.dumps(sent)
    assert "[[EMAIL_" in json.dumps(sent)


@pytest.mark.parametrize("mode,default", [("audit", False), ("strict", False), ("audit", True)])
def test_audit_mode_is_refused_before_any_upstream_call(mode, default):
    app = create_app(local())
    app.state.gateway_transport = httpx.MockTransport(lambda request: pytest.fail("network"))
    if default:
        app.state.gateway_config = GatewayConfig(mode=Mode.AUDIT)
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={} if default else {"X-PII-Guard-Mode": mode},
            json={"model": "synthetic-model", "messages": [{"role": "user", "content": EMAIL}]},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "detection_profile_denied"


@pytest.mark.parametrize("endpoint", ["/v1/analyze", "/v1/mask"])
def test_cached_standard_analyzer_cannot_send_raw_input(endpoint):
    from pii_guard.api.deps import RegistryAnalyzer
    from pii_guard.detect.pipeline import DetectionPipeline

    remote = LlmDetector(
        settings=Settings(_env_file=None),
        api_key="synthetic-key",
        transport=httpx.MockTransport(lambda request: pytest.fail("raw detector network")),
    )
    analyzer = RegistryAnalyzer(("rules",), settings=Settings(_env_file=None))
    analyzer.detectors = [remote]
    analyzer.pipeline = DetectionPipeline([remote])
    app = create_app(local())
    app.state.analyzer = analyzer
    with TestClient(app) as client:
        response = client.post(endpoint, json={"text": EMAIL})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "detection_profile_denied"
    assert EMAIL not in response.text and "synthetic-key" not in response.text


@pytest.mark.parametrize("endpoint", ["/v1/chat/completions", "/v1/responses"])
@pytest.mark.parametrize("cached_gateway", [False, True])
def test_cached_remote_gateway_components_refused(endpoint, cached_gateway):
    from pii_guard.gateway import Gateway
    from pii_guard.gateway.detection import ModeDetector
    from pii_guard.policy import PolicySet
    from pii_guard.vault import Vault

    remote = LlmDetector(
        settings=Settings(_env_file=None),
        api_key="synthetic-key",
        transport=httpx.MockTransport(lambda request: pytest.fail("raw detector network")),
    )
    modes = {Mode.FAST: ModeDetector(Mode.FAST, remote, "standard-reuse", PolicySet())}
    app = create_app(local())
    transport = httpx.MockTransport(lambda request: pytest.fail("downstream network"))
    if cached_gateway:
        app.state.gateway = Gateway(
            settings=local(detection_profile="standard"),
            vault=Vault.from_settings(local()),
            detectors=modes,
            transport=transport,
        )
    else:
        app.state.gateway_detectors = modes
        app.state.gateway_transport = transport
    body = {"model": "synthetic-model", "messages": [{"role": "user", "content": EMAIL}]}
    if endpoint == "/v1/responses":
        body = {"model": "synthetic-model", "input": EMAIL}
    with TestClient(app) as client:
        response = client.post(endpoint, json=body)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "detection_profile_denied"
    assert EMAIL not in response.text and "synthetic-key" not in response.text


def test_prebuilt_ner_with_downloads_enabled_refused_without_loading(tmp_path, monkeypatch):
    from pii_guard.detection_profile import require_detector_instance

    detector = ner.NerDetector(model=str(tmp_path), preload=False)
    monkeypatch.setattr(detector, "load", lambda: pytest.fail("model loading started"))
    with pytest.raises(DetectionProfileError, match="downloads"):
        require_detector_instance(local(), detector)
    with pytest.raises(DetectionProfileError):
        build_mode_detectors(local(), GatewayConfig(), base=[detector])
