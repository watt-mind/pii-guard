"""Hosted startup requires an explicit, fail-closed deployment boundary."""

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


def test_hosted_model_allowlist_environment(monkeypatch):
    monkeypatch.setenv("PII_GUARD_HOSTED_MODELS", "model-one, model-two")
    assert Settings(_env_file=None).hosted_models == ("model-one", "model-two")
