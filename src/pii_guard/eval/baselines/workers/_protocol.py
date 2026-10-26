"""Line protocol shared by the baseline workers (stdlib only, no pii-guard imports).

A worker runs in its own virtual environment (see ``../envs``), because LLM Guard and
PrivAiTe pin dependency versions that cannot share an environment with each other.

1. The worker loads its tool, runs one warm-up call and writes
   ``{"ready": true, "info": {...}}`` (tool versions, models, configuration).
2. For each request line ``{"id": n, "text": str, "language": str}`` it writes
   ``{"id": n, "spans": [[start, end, label, score], ...], "masked": str,
   "restored": str | null, "detect_ms": float, "mask_ms": float}`` or, on failure,
   ``{"id": n, "error": "<exception class name>"}``. Error replies never carry text.
3. End of input ends the worker.

The protocol uses the original stdout file descriptor only; anything a library prints is
redirected to stderr, which the client discards unless ``PII_GUARD_BASELINE_DEBUG`` is set.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections.abc import Callable
from typing import Any

#: ``handle(text, language) -> (spans, masked, restored, detect_ms, mask_ms)``
Handler = Callable[[str, str], tuple[list[list[Any]], str, str | None, float, float]]


def quiet_logging() -> None:
    """Tools log detections with their raw values; keep only errors."""
    logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
    for name in ("presidio-analyzer", "presidio-anonymizer", "llm_guard", "privaite"):
        logging.getLogger(name).setLevel(logging.ERROR)


def protocol_stdout() -> Any:
    """A private handle on stdout, after pointing fd 1 at stderr for library chatter."""
    out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return out


def ms_since(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def serve(out: Any, info: dict[str, Any], handle: Handler) -> int:
    handle("warm up: Jane Doe, jane.doe@example.com", "en")
    out.write(json.dumps({"ready": True, "info": info}) + "\n")
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        try:
            spans, masked, restored, detect_ms, mask_ms = handle(
                request["text"], request["language"]
            )
            reply: dict[str, Any] = {
                "id": request["id"],
                "spans": spans,
                "masked": masked,
                "restored": restored,
                "detect_ms": detect_ms,
                "mask_ms": mask_ms,
            }
        except Exception as exc:  # report the type only: messages may contain the text
            reply = {"id": request["id"], "error": type(exc).__name__}
        out.write(json.dumps(reply, ensure_ascii=False) + "\n")
    return 0
