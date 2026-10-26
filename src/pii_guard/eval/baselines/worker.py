"""Baselines that run in their own virtual environment, behind a line protocol.

LLM Guard pins ``transformers==4.51.3`` and ``presidio==2.2.358``; PrivAiTe needs
``transformers>=5.3``. Neither can share pii-guard's environment with the other, so each runs
as a worker process (``workers/*.py``) in an ephemeral ``uv`` environment built from the
pinned requirements in ``envs/*.txt``::

    uv run --isolated --no-project --python 3.12 --with-requirements envs/<tool>.txt \\
        python workers/<tool>_worker.py

The first run downloads the packages and the tool's models (Hugging Face Hub, spaCy model
wheels); later runs reuse ``uv``'s and Hugging Face's caches. Documents go to the worker over
a local pipe and never leave the machine. The protocol is in ``workers/_protocol.py``.

The worker's stderr is discarded (the tools log detected values) unless
``PII_GUARD_BASELINE_DEBUG=1``. Credentials in the environment (``*KEY*``, ``*TOKEN*``,
``*SECRET*``, ``PII_GUARD_*``) are not passed to it.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval.baselines.base import BaselineOutput, BaselineUnavailable
from pii_guard.eval.baselines.mapping import to_spans
from pii_guard.types import DetectionError

__all__ = ["ENVS_DIR", "WORKERS_DIR", "WorkerBaseline", "llm_guard", "privaite", "worker_env"]

_HERE = Path(__file__).resolve().parent
ENVS_DIR = _HERE / "envs"
WORKERS_DIR = _HERE / "workers"

_TELEMETRY_OFF = {
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "ANONYMIZED_TELEMETRY": "False",
    "ORT_DISABLE_TELEMETRY": "1",
    "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    "TOKENIZERS_PARALLELISM": "false",
    "PYTHONUNBUFFERED": "1",
}
_CREDENTIAL_RE = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|^PII_GUARD_", re.IGNORECASE)


def worker_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """The worker's environment: ours minus credentials, plus telemetry switches."""
    source = dict(os.environ if base is None else base)
    env = {k: v for k, v in source.items() if not _CREDENTIAL_RE.search(k)}
    env.update(_TELEMETRY_OFF)
    return env


def uv_command(requirements: Path, script: Path) -> list[str]:
    uv = shutil.which("uv")
    if uv is None:
        raise BaselineUnavailable("`uv` is not on PATH (needed to build the worker environment)")
    return [
        uv,
        "run",
        "--quiet",
        "--isolated",
        "--no-project",
        "--python",
        "3.12",
        "--with-requirements",
        str(requirements),
        "python",
        str(script),
    ]


class WorkerBaseline:
    """A baseline served by a worker process. Starting it blocks until the worker is ready."""

    def __init__(
        self,
        name: str,
        command: Sequence[str],
        *,
        placeholder_re: re.Pattern[str],
        reversible: bool = True,
        env: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.placeholder_re = placeholder_re
        self.reversible = reversible
        debug = os.environ.get("PII_GUARD_BASELINE_DEBUG") == "1"
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                list(command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None if debug else subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                env=worker_env() if env is None else env,
            )
        except OSError as exc:
            raise BaselineUnavailable(f"worker could not start ({type(exc).__name__})") from None
        ready = self._read()
        if not ready or not ready.get("ready"):
            code = self.close()
            raise BaselineUnavailable(
                f"worker exited (code {code}) before it was ready; "
                "rerun with PII_GUARD_BASELINE_DEBUG=1 to see its output"
            )
        self.info: dict[str, Any] = ready.get("info", {})
        self._next_id = 0

    def _read(self) -> dict[str, Any] | None:
        stdout = self._proc.stdout
        line = stdout.readline() if stdout is not None else ""
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    def process(self, text: str, language: str) -> BaselineOutput:
        self._next_id += 1
        request = {"id": self._next_id, "text": text, "language": language}
        try:
            if self._proc.stdin is None:
                raise OSError("no stdin")
            self._proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except OSError:
            raise DetectionError(f"{self.name} baseline worker is gone") from None
        reply = self._read()
        if reply is None or reply.get("id") != self._next_id:
            raise DetectionError(f"{self.name} baseline worker sent no valid reply")
        if "error" in reply:
            raise DetectionError(f"{self.name} baseline failed on a document ({reply['error']})")
        spans, unmapped = to_spans(text, reply["spans"], self.name)
        return BaselineOutput(
            spans=tuple(spans),
            masked_text=reply["masked"],
            restored_text=reply.get("restored"),
            detect_ms=float(reply["detect_ms"]),
            mask_ms=float(reply["mask_ms"]),
            unmapped=unmapped,
        )

    def _stop(self) -> int | None:
        if self._proc.stdin is not None:
            with contextlib.suppress(OSError):
                self._proc.stdin.close()
        try:
            return self._proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            return self._proc.wait()

    def close(self) -> int | None:
        """Stop the worker; returns its exit code."""
        code = self._stop()
        if self._proc.stdout is not None:
            self._proc.stdout.close()
        return code


def llm_guard() -> WorkerBaseline:
    """LLM Guard ``Anonymize`` + ``Deanonymize`` with defaults (``workers/llm_guard_worker.py``)."""
    return WorkerBaseline(
        "llm-guard",
        uv_command(ENVS_DIR / "llm-guard.txt", WORKERS_DIR / "llm_guard_worker.py"),
        placeholder_re=re.compile(r"\[REDACTED_[A-Z][A-Z0-9_]*_\d+\]"),
    )


def privaite() -> WorkerBaseline:
    """PrivAiTe's PII engine with its shipped config (``workers/privaite_worker.py``)."""
    return WorkerBaseline(
        "privaite",
        uv_command(ENVS_DIR / "privaite.txt", WORKERS_DIR / "privaite_worker.py"),
        placeholder_re=re.compile(r"<[A-Z][A-Z0-9_]*_\d+>|\[SECRET\]"),
    )
