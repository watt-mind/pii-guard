"""Hosted startup requires an explicit, fail-closed deployment boundary."""

import asyncio
import time

import pytest

from pii_guard.config import Settings
from pii_guard.hosted.runtime import HostedService


def configured(**updates):
    values = {
        "hosted": True,
        "hosted_public_origin": "https://guard.example",
        "hosted_trust_easy_auth": True,
        "hosted_single_process": True,
        "tenant_key": "42" * 32,
        "ner_fallback": "off",
        "detectors": ("rules",),
    }
    values.update(updates)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    "updates",
    [
        {"hosted_trust_easy_auth": False},
        {"hosted_single_process": False},
        {"tenant_key": None},
        {"tenant_key": "42" * 16},
        {"hosted_public_origin": "http://guard.example"},
        {"hosted_public_origin": "https://guard.example:444"},
        {"hosted_public_origin": "https://guard.example/path"},
        {"hosted_public_origin": "https://user@guard.example"},
        {"hosted_public_origin": "https://guard.example/?query=unsafe"},
        {"hosted_public_origin": "https://guard.example/#unsafe"},
        {"api_token": "synthetic-local-token"},
        {"detectors": ("llm",)},
        {"hosted_models": ()},
    ],
)
def test_incomplete_boundary_cannot_start(updates):
    with pytest.raises(ValueError):
        HostedService(configured(**updates))


def test_default_mode_remains_local():
    assert not Settings(_env_file=None).hosted


def test_blob_mode_never_claims_a_marker_and_missing_store_keeps_app_available(tmp_path):
    service = HostedService(
        configured(
            hosted_spend_store="azure_blob",
            hosted_sponsored_microdollars=1_000_000,
            hosted_sponsored_allocation_id="synthetic-approved",
            hosted_allocation_directory=str(tmp_path),
            hosted_allocation_expires_at=int(time.time()) + 3600,
        )
    )
    assert not service.sponsored_enabled
    assert not list(tmp_path.iterdir())
    assert service.spend is not None
    asyncio.run(service.close())


def test_hosted_model_allowlist_environment(monkeypatch):
    monkeypatch.setenv("PII_GUARD_HOSTED_MODELS", "model-one, model-two")
    assert Settings(_env_file=None).hosted_models == ("model-one", "model-two")


def test_hosted_client_ip_source_is_explicit_and_defaults_off(monkeypatch):
    assert Settings(_env_file=None).hosted_client_ip_source == "off"
    monkeypatch.setenv("PII_GUARD_HOSTED_CLIENT_IP_SOURCE", "aca_xff_rightmost")
    assert Settings(_env_file=None).hosted_client_ip_source == "aca_xff_rightmost"
    monkeypatch.setenv("PII_GUARD_HOSTED_CLIENT_IP_SOURCE", "x_real_ip")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_hosted_source_tag_is_configurable_and_restricted(monkeypatch) -> None:
    import pydantic

    from pii_guard.config import Settings

    assert Settings(_env_file=None).hosted_source_tag == "pii-guard-hosted-demo"
    monkeypatch.setenv("PII_GUARD_HOSTED_SOURCE_TAG", "pii-guard.judges_2026")
    assert Settings(_env_file=None).hosted_source_tag == "pii-guard.judges_2026"
    for bad in ("has space", "a" * 65, "user@example.com", "tag\r\nX-Injected: 1", "ü"):
        monkeypatch.setenv("PII_GUARD_HOSTED_SOURCE_TAG", bad)
        try:
            Settings(_env_file=None)
        except pydantic.ValidationError:
            continue
        raise AssertionError(f"accepted invalid source tag {bad!r}")
