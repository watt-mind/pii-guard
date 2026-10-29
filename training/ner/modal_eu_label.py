"""Glimmer teacher pass for the phase-1 Muse corpus (LAB-1525), in one Modal H100 container.

``training/distill/label.py`` merges Muse Glimmer's spans with the planted gold (it adopts names
the writer added on its own and excludes disagreements from the loss). Instead of deploying
the public Glimmer endpoint (``deploy/modal/glimmer.py``) and calling it from this machine, this
job starts vLLM on loopback inside the container (same image, weights and compile caches,
same ``pii-guard-glimmer`` secret, which never leaves Modal) and runs ``label.py`` next to it,
then returns the labelled files. Nothing is listening on a public URL.

Upload: only the corpus files given (fictional Muse documents, checked by
``training/distill/modal_upload.check_payload``: no MAPA, TAB or other real text, LAB-1419),
the ``pii_guard`` package and ``label.py``::

    EU_CORPUS=phase1b/distill-eu-1b-s1525 uv run --no-sync --with modal --with huggingface-hub \\
        modal run training/ner/modal_eu_label.py

``EU_CORPUS`` is a folder under the data root (``PII_GUARD_DATA_DIR``, LAB-1542), or a
repo-relative path such as the old ``eval/generated/distill-eu-s1525``. Writes
``<corpus>/labelled/<lang>-distill-{train,dev}.jsonl``, ``label-stats.json`` and the teacher
cache ``<corpus>/teacher-cache.jsonl`` (so a rerun is local: ``label.py --cache-only``), then
pushes the corpus it lies in to the private HF dataset (``data_sync.py``; ``--no-push`` skips).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import modal

REMOTE = "/root/repo"
ROOT = Path(__file__).resolve().parents[2] if modal.is_local() else Path(REMOTE)
if modal.is_local():
    sys.path[:0] = [
        str(ROOT / "src"), str(ROOT / "training" / "distill"), str(ROOT / "training" / "ner")
    ]  # fmt: skip
PORT = 8000
#: As ``deploy/modal/glimmer.py`` (base model, no LoRA), bound to loopback only.
VLLM = [
    "vllm", "serve", "meta-models/Muse-Glimmer-30B", "--served-model-name", "muse-glimmer",
    "--host", "127.0.0.1", "--port", str(PORT), "--max-model-len", "32768",
    "--max-num-seqs", "128", "--generation-config", "auto", "--reasoning-parser", "muse_glimmer",
]  # fmt: skip

CORPUS = os.environ.get("EU_CORPUS", "phase1/distill-eu-s1525")


def _local_corpus() -> Path:
    """``EU_CORPUS``: absolute, repo-relative (``eval/generated/...``), else under the data root."""
    import data_sync

    p = Path(CORPUS).expanduser()
    if p.is_absolute():
        return p
    if (ROOT / p).is_dir():
        return ROOT / p
    return data_sync.data_root() / p


#: Where the corpus sits in the container, relative to ``REMOTE``.
REMOTE_CORPUS = f"corpus/{Path(CORPUS).name}"


def _corpus_files() -> list[str]:
    from modal_upload import check_payload

    base = _local_corpus()
    names = sorted(p.name for p in base.glob("*-distill-*.jsonl"))
    check_payload([f"corpora/{base.name}/{n}" for n in names])
    return names


image = (
    modal.Image.from_registry("vllm/vllm-openai:muse-glimmer", add_python="3.12")
    .entrypoint([])
    .pip_install(
        "cryptography>=46.0.0",
        "fastapi>=0.162.0",
        "httpx>=0.28.1",
        "pillow>=13.0.0",
        "pydantic>=2.14.1",
        "pydantic-settings>=2.16.1",
    )
    .add_local_dir(ROOT / "src" / "pii_guard", f"{REMOTE}/src/pii_guard", ignore=["__pycache__"])
    .add_local_file(
        ROOT / "training" / "distill" / "label.py", f"{REMOTE}/training/distill/label.py"
    )
)
if modal.is_local():
    for name in _corpus_files():
        image = image.add_local_file(_local_corpus() / name, f"{REMOTE}/{REMOTE_CORPUS}/{name}")

hf_cache = modal.Volume.from_name("pii-guard-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("pii-guard-vllm-cache", create_if_missing=True)
app = modal.App("pii-guard-eu-label")


@app.function(
    image=image,
    gpu="H100",
    timeout=3 * 60 * 60,
    secrets=[modal.Secret.from_name("pii-guard-glimmer")],
    volumes={"/root/.cache/huggingface": hf_cache, "/root/.cache/vllm": vllm_cache},
)
def label(corpus: str, workers: int = 64) -> dict[str, bytes]:
    import httpx

    env = dict(os.environ)
    key = env.pop("GLIMMER_API_KEY")
    env["VLLM_API_KEY"] = key
    server = subprocess.Popen(VLLM, env=env)  # noqa: S603 - fixed argument list
    url = f"http://127.0.0.1:{PORT}"
    for _ in range(30 * 60 // 5):
        if server.poll() is not None:
            raise RuntimeError("vLLM exited during startup")
        try:
            if httpx.get(f"{url}/health", timeout=5).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(5)
    else:
        raise RuntimeError("vLLM did not become ready in 30 minutes")
    run_env = {
        **{k: v for k, v in os.environ.items() if k != "GLIMMER_API_KEY"},
        "PYTHONPATH": f"{REMOTE}/src",
        "PII_GUARD_LLM_DETECTOR_URL": f"{url}/v1",
        "PII_GUARD_LLM_DETECTOR_API_KEY": key,
        "PII_GUARD_LLM_DETECTOR_MODEL": "muse-glimmer",
        "PII_GUARD_LLM_DETECTOR_REASONING_STRENGTH": "low",
    }
    subprocess.run(  # noqa: S603 - fixed argument list
        [sys.executable, "training/distill/label.py", "--corpus", corpus, "--workers", f"{workers}"],  # noqa: E501
        cwd=REMOTE, env=run_env, check=True,
    )  # fmt: skip
    server.terminate()
    base = Path(REMOTE) / corpus
    out = {str(p.relative_to(base)): p.read_bytes() for p in (base / "labelled").glob("*")}
    cache = base / "teacher-cache.jsonl"
    if cache.exists():
        out["teacher-cache.jsonl"] = cache.read_bytes()
    return out


@app.local_entrypoint()
def main(corpus: str = CORPUS, workers: int = 64, no_push: bool = False) -> None:
    import data_sync

    if corpus != CORPUS:
        raise SystemExit("set EU_CORPUS=<dir> in the environment: the image is built from it")
    files = label.remote(REMOTE_CORPUS, workers)
    base = _local_corpus()
    for name, data in files.items():
        target = base / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"wrote {target}")
    data_sync.push_after_run(base, enabled=not no_push, what="glimmer-label")
