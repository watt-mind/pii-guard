"""Train the NER student (``training/ner/train.py``) on a Modal GPU.

Fictional data only. The labelled corpus files named in the config are uploaded with the job,
and the image carries only the synthetic evaluation files the decontamination gate needs
(``modal_upload.py``, LAB-1527: never MAPA, TAB or other real text);
the checkpoint is written to the Modal volume ``pii-guard-ner-runs`` and fetched back with
``modal volume get``::

    modal run training/distill/modal_train.py --config training/ner/distilled-base.toml
    modal volume get pii-guard-ner-runs pii-guard-ner-xlmr-base-distilled models/ner/
    modal app stop pii-guard-ner-train --yes   # if a run was interrupted

``--gpu`` picks the card (default ``A10G``; ``L40S`` or ``A100`` for xlm-roberta-large).

**Data on the volume (LAB-1542).** Config paths ``data:<corpus>/<file>`` are read from the data
root (``PII_GUARD_DATA_DIR``, ``training/ner/data_sync.py``) and uploaded with the call, unless
``--data <corpus>@<rev>[,...]`` names that corpus: then the job reads it from the volume copy
``data/<corpus>@<rev>`` (made once with ``data_sync.py volume <corpus> --revision <rev>``) and
nothing of it is uploaded::

    modal run training/distill/modal_train.py --config <toml> --data phase1b@6fbb52b62d99
The app is ephemeral (``modal run``): it stops when the function returns.
``PII_GUARD_TRAIN_TIMEOUT_S=<seconds>`` sets a hard timeout on the run (default 3 h).
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

import modal

REMOTE = "/root/pii-guard"
# Inside the container this file is /root/modal_train.py; the repo root only exists locally.
ROOT = Path(__file__).resolve().parents[2] if modal.is_local() else Path(REMOTE)
RUNS = "/runs"
#: ``PII_GUARD_DATA_DIR`` inside the container: ``data:`` config paths resolve here.
DATA = "/root/data"
DATA_PREFIX = "data:"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch==2.14.1",
        "transformers==5.21.0",
        "tokenizers==0.23.3",
        "safetensors==0.8.0",
        "huggingface-hub==2.3.0",
        "sentencepiece==0.2.2",
        "protobuf==7.36.2",
        "numpy==2.5.4",
        "pydantic==2.14.1",
        "pydantic-settings==2.16.1",
        "httpx==0.28.1",
    )
    .env({"PYTHONPATH": f"{REMOTE}/src", "TOKENIZERS_PARALLELISM": "false"})
    .add_local_dir(ROOT / "src" / "pii_guard", f"{REMOTE}/src/pii_guard", ignore=["__pycache__"])
    .add_local_dir(ROOT / "training" / "ner", f"{REMOTE}/training/ner", ignore=["__pycache__"])
)
if modal.is_local():
    # LAB-1527: an allowlist of files, never a directory. The decontamination gate (LAB-1392)
    # gets every synthetic evaluation text and every manifest; real text (MAPA, TAB, dataset
    # downloads, mining pools) never leaves the machine (LAB-1419). The gate compares training
    # documents with the real sets by their manifest hashes only; see modal_upload.py.
    sys.path[:0] = [str(ROOT / "src"), str(Path(__file__).resolve().parent)]
    from modal_upload import eval_upload_files

    for rel in eval_upload_files(ROOT):
        image = image.add_local_file(ROOT / rel, f"{REMOTE}/{rel}")
runs = modal.Volume.from_name("pii-guard-ner-runs", create_if_missing=True)
app = modal.App("pii-guard-ner-train", image=image)


def _train(config_text: str, files: dict[str, bytes], data: tuple[str, ...] = ()) -> str:
    import os
    import subprocess

    os.chdir(REMOTE)
    Path(DATA).mkdir(parents=True, exist_ok=True)
    for spec in data:  # corpus@rev on the volume, linked where data:<corpus>/ resolves
        source = Path(RUNS) / "data" / spec
        if not source.is_dir():
            raise FileNotFoundError(
                f"{source}: run data_sync.py volume {spec.replace('@', ' --revision ')}"
            )
        (Path(DATA) / spec.split("@", 1)[0]).symlink_to(source)
    for rel, blob in files.items():
        if rel.startswith(DATA_PREFIX):
            path = Path(DATA) / rel[len(DATA_PREFIX) :]
        else:
            path = Path(REMOTE) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    cfg = tomllib.loads(config_text)
    name = Path(cfg["out"]).name
    out = f"{RUNS}/{name}"
    Path("run.toml").write_text(config_text, encoding="utf-8")
    subprocess.run(  # noqa: S603 - fixed argument list
        [
            sys.executable,
            "training/ner/train.py",
            "--config",
            "run.toml",
            "--out",
            out,
            "--device",
            "cuda",
        ],
        check=True,
        env={**os.environ, "PII_GUARD_DATA_DIR": DATA},
    )
    runs.commit()
    return name


_kwargs = {
    # LAB-1547: a hard cap per run when Modal credit is short (seconds; default 3 h).
    "timeout": int(os.environ.get("PII_GUARD_TRAIN_TIMEOUT_S", 3 * 60 * 60)),
    "volumes": {RUNS: runs},
}


@app.function(gpu="A10G", **_kwargs)
def train_a10g(config_text: str, files: dict[str, bytes], data: tuple[str, ...] = ()) -> str:
    return _train(config_text, files, data)


@app.function(gpu="L40S", **_kwargs)
def train_l40s(config_text: str, files: dict[str, bytes], data: tuple[str, ...] = ()) -> str:
    return _train(config_text, files, data)


@app.function(gpu="A100", **_kwargs)
def train_a100(config_text: str, files: dict[str, bytes], data: tuple[str, ...] = ()) -> str:
    return _train(config_text, files, data)


@app.local_entrypoint()
def main(config: str, gpu: str = "A10G", data: str = "") -> None:
    text = (ROOT / config).read_text(encoding="utf-8")
    cfg = tomllib.loads(text)
    # The config's train/dev files go with the call; refuse any that could be real text.
    sys.path.insert(0, str(ROOT / "training" / "ner"))
    import data_sync
    from modal_upload import check_payload

    mounted = tuple(s for s in data.split(",") if s)
    if any("@" not in s for s in mounted):
        raise SystemExit("--data takes <corpus>@<rev>[,...]")
    on_volume = {s.split("@", 1)[0] for s in mounted}
    files: dict[str, bytes] = {}
    # LAB-1625: report-only dev files (``report_dev``) go with the call too.
    for rel in dict.fromkeys([*cfg["train"], *cfg["dev"], *cfg.get("report_dev", [])]):
        if not rel.startswith(DATA_PREFIX):
            check_payload([rel])
            files[rel] = (ROOT / rel).read_bytes()
            continue
        inner = rel[len(DATA_PREFIX) :]
        check_payload([f"corpora/{inner}"])
        if inner.split("/", 1)[0] not in on_volume:
            files[rel] = data_sync.resolve(rel).read_bytes()
    fn = {"A10G": train_a10g, "L40S": train_l40s, "A100": train_a100}[gpu.upper()]
    name = fn.remote(text, files, mounted)
    print(f"checkpoint on volume pii-guard-ner-runs: {name}")
