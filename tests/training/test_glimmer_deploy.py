"""The Modal deployment never puts the API key on the vLLM command line (vLLM logs it)."""

from __future__ import annotations

import sys
import types

import pytest

from .conftest import load_script


class _Anything:
    def __call__(self, *args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return _Anything()

    def __getattr__(self, name):
        return _Anything()


@pytest.fixture
def glimmer(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    monkeypatch.setitem(sys.modules, "modal", _Anything())
    return load_script("deploy/modal/glimmer.py", "deploy_glimmer")


def test_command_has_no_api_key(glimmer) -> None:
    cmd = glimmer.vllm_command()
    assert "--api-key" not in cmd
    assert cmd[:3] == ["vllm", "serve", glimmer.MODEL]
    assert "muse_glimmer" in cmd


def test_serve_passes_the_key_through_the_environment(glimmer, monkeypatch) -> None:
    seen = {}

    def fake_popen(cmd, env):
        seen["cmd"], seen["env"] = cmd, env

    monkeypatch.setenv("GLIMMER_API_KEY", "secret-value")
    monkeypatch.setattr(glimmer.subprocess, "Popen", fake_popen)
    glimmer.serve()
    assert seen["env"]["VLLM_API_KEY"] == "secret-value"
    assert "GLIMMER_API_KEY" not in seen["env"]
    assert all("secret-value" not in part for part in seen["cmd"])


def test_base_model_only_by_default(glimmer) -> None:
    assert "--enable-lora" not in glimmer.vllm_command("")


def test_lora_adapter_is_served_under_its_own_name(glimmer) -> None:
    cmd = glimmer.vllm_command("pii-guard-glimmer-x")
    assert "--enable-lora" in cmd
    i = cmd.index("--lora-modules")
    assert cmd[i + 1] == "pii-guard-glimmer-x=/adapters/pii-guard-glimmer-x"
    assert int(cmd[cmd.index("--max-lora-rank") + 1]) >= 8


@pytest.mark.parametrize("bad", ["../etc", "a/b", "/abs"])
def test_lora_name_is_not_a_path(glimmer, bad) -> None:
    with pytest.raises(ValueError):
        glimmer.lora_args(bad)
