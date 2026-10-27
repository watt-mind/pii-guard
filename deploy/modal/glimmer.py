"""Serve Muse Glimmer 30B (Meta open weights, Apache-2.0) with vLLM on one Modal H100.

OpenAI-compatible endpoint: ``https://<workspace>--pii-guard-glimmer-serve.<region>.modal.run/v1``
(model name ``muse-glimmer``). Used as the teacher for the NER student
(``training/distill/label.py``) and usable as the ``llm`` detector::

    PII_GUARD_LLM_DETECTOR_URL=https://<workspace>--pii-guard-glimmer-serve.us-east.modal.run/v1
    PII_GUARD_LLM_DETECTOR_MODEL=muse-glimmer
    PII_GUARD_LLM_DETECTOR_REASONING_STRENGTH=low   # Glimmer ignores reasoning_effort

Runbook (see docs/models.md, "Serving Muse Glimmer on Modal")::

    modal secret create pii-guard-glimmer GLIMMER_API_KEY=$(openssl rand -hex 24)
    modal deploy deploy/modal/glimmer.py     # first cold start ~26 min, later ~3-6 min
    modal app stop pii-guard-glimmer --yes   # always, when done: an idle H100 still bills
                                             # until the scale-down window ends

**LoRA adapter (LAB-1109).** ``GLIMMER_LORA=<name>`` at deploy time also serves the answer-only
fine-tune: vLLM loads ``/adapters/<name>`` (PEFT format, on the Modal volume
``pii-guard-lora-adapters``; upload with ``training/llm/fetch_adapter.py``) and exposes it as
model ``<name>`` next to the base model ``muse-glimmer``::

    GLIMMER_LORA=pii-guard-glimmer-lab1109-v1 modal deploy deploy/modal/glimmer.py
    PII_GUARD_LLM_DETECTOR_MODEL=pii-guard-glimmer-lab1109-v1
    PII_GUARD_LLM_DETECTOR_REASONING_STRENGTH=low   # the strength it was trained with

The API key reaches vLLM through the ``VLLM_API_KEY`` environment variable, never through
``--api-key``: vLLM logs its command line at startup. Weights (~60 GB) and the torch.compile
cache live on the Modal volumes ``pii-guard-hf-cache`` and ``pii-guard-vllm-cache``, so only
the first start downloads and compiles. The container scales to zero after ``SCALEDOWN``
seconds without requests.
"""

from __future__ import annotations

import os
import subprocess

import modal

MODEL = "meta-models/Muse-Glimmer-30B"
SERVED_NAME = "muse-glimmer"
PORT = 8000
SCALEDOWN = 300  # seconds idle before the H100 is released
MAX_INPUTS = 64  # concurrent requests per container (vLLM batches them)
MAX_MODEL_LEN = 32768
#: Name of the LoRA adapter directory on the adapters volume (unset: base model only). Read at
#: deploy time and baked into the image environment, so the container sees the same value.
LORA = os.environ.get("GLIMMER_LORA", "").strip()
MAX_LORA_RANK = 16
ADAPTERS_DIR = "/adapters"

image = (
    modal.Image.from_registry("vllm/vllm-openai:muse-glimmer", add_python="3.12")
    .entrypoint([])
    .env({"GLIMMER_LORA": LORA})
)
hf_cache = modal.Volume.from_name("pii-guard-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("pii-guard-vllm-cache", create_if_missing=True)
adapters = modal.Volume.from_name("pii-guard-lora-adapters", create_if_missing=True)

app = modal.App("pii-guard-glimmer")


def lora_args(lora: str = "") -> list[str]:
    """vLLM flags that add the adapter ``lora`` as a model of the same name (none if unset)."""
    if not lora:
        return []
    if "/" in lora or lora.startswith("."):
        raise ValueError("GLIMMER_LORA is a directory name on the adapters volume, not a path")
    return [
        "--enable-lora",
        "--max-lora-rank",
        str(MAX_LORA_RANK),
        "--max-loras",
        "1",
        "--lora-modules",
        f"{lora}={ADAPTERS_DIR}/{lora}",
    ]


def vllm_command(lora: str = LORA) -> list[str]:
    """The ``vllm serve`` argument list. No secrets: the key comes from ``VLLM_API_KEY``."""
    return [
        "vllm",
        "serve",
        MODEL,
        "--served-model-name",
        SERVED_NAME,
        "--host",
        "0.0.0.0",  # noqa: S104 - inside the container, behind Modal's HTTPS proxy
        "--port",
        str(PORT),
        "--max-model-len",
        str(MAX_MODEL_LEN),
        "--max-num-seqs",
        str(MAX_INPUTS * 2),
        "--generation-config",
        "auto",
        "--reasoning-parser",
        "muse_glimmer",
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        "muse_glimmer",
        *lora_args(lora),
    ]


@app.function(
    image=image,
    gpu="H100",
    timeout=60 * 60,
    scaledown_window=SCALEDOWN,
    secrets=[modal.Secret.from_name("pii-guard-glimmer")],
    volumes={
        "/root/.cache/huggingface": hf_cache,
        "/root/.cache/vllm": vllm_cache,
        ADAPTERS_DIR: adapters,
    },
)
@modal.concurrent(max_inputs=MAX_INPUTS)
@modal.web_server(port=PORT, startup_timeout=30 * 60)
def serve() -> None:
    env = dict(os.environ)
    env["VLLM_API_KEY"] = env.pop("GLIMMER_API_KEY")
    subprocess.Popen(vllm_command(), env=env)  # noqa: S603 - fixed argument list
