"""The segmenters' end-to-end bench: ``POST /v1/mask/image`` through the real app.

``python -m pii_guard.visual.segment_eval --e2e-bench`` runs :func:`e2e_bench` (LAB-1245); see
that module's docstring for what it measures. It lives here, not in :mod:`pii_guard.visual`,
because it drives the HTTP app and the visual package never imports the API (LAB-1271).

Output holds numbers, region types and specimen ids only, never images or text.
"""

from __future__ import annotations

import os
import platform
import time
from collections.abc import Callable, Sequence
from typing import Any

from pii_guard.types import DetectionError
from pii_guard.visual.segment_eval import E2E_MODES, _CountingTransport, e2e_summary, set_paths

__all__ = ["e2e_bench"]


def e2e_bench(
    set_name: str,
    *,
    rounds: int = 3,
    modes: Sequence[str] = E2E_MODES,
    log: Callable[[str], None] = lambda _m: None,
) -> dict[str, Any]:  # pragma: no cover - live SAM calls and the data sets
    """``POST /v1/mask/image`` per image, ``modes`` alternating; see the module docstring."""
    from fastapi.testclient import TestClient

    from pii_guard.api.app import create_app
    from pii_guard.config import Settings
    from pii_guard.eval.visual import DEFAULT_MAX_SIDE, load_specimens, prepare_image
    from pii_guard.visual.ocr import tesseract_available
    from pii_guard.visual.sam import SamClient
    from pii_guard.visual.segmenters import HybridSegmenter, build_segmenter

    if not tesseract_available():
        raise DetectionError("the end-to-end bench needs Tesseract (OCR on, as served)")
    specimens = load_specimens(*set_paths(set_name), log=log)
    if not specimens:
        raise DetectionError(f"no labelled images found for {set_name}")
    images = [prepare_image(s.path.read_bytes(), DEFAULT_MAX_SIDE) for s in specimens]
    settings = Settings()
    transport = _CountingTransport()
    sam = SamClient(settings=settings, transport=transport, max_retries=2)
    segmenters: dict[str, Any] = {}
    for mode in modes:
        built = build_segmenter(settings, mode=mode)
        if isinstance(built, HybridSegmenter):
            if built.local is None:
                raise DetectionError("hybrid bench needs YuNet (uv sync --extra local-vision)")
            built = HybridSegmenter(sam=sam, local=built.local)
        elif isinstance(built, SamClient):
            built = sam
        segmenters[mode] = built
    apps = {}
    for mode in modes:
        app = create_app(settings)
        app.state.sam_client = segmenters[mode]
        apps[mode] = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
    per_mode: dict[str, list[list[float]]] = {m: [] for m in modes}
    calls: dict[str, list[int]] = {m: [] for m in modes}
    errors: dict[str, int] = {}
    try:
        for r in range(rounds):
            times: dict[str, list[float]] = {m: [] for m in modes}
            for i, data in enumerate(images):
                order = list(modes) if (i + r) % 2 == 0 else list(reversed(modes))
                for mode in order:
                    before = transport.calls
                    start = time.perf_counter()
                    response = apps[mode].post(
                        "/v1/mask/image?render=opaque",
                        content=data,
                        headers={"Content-Type": "image/png"},
                    )
                    times[mode].append((time.perf_counter() - start) * 1000)
                    calls[mode].append(transport.calls - before)
                    if response.status_code != 200:
                        errors[mode] = errors.get(mode, 0) + 1
                        code = response.json().get("error", {}).get("code", response.status_code)
                        log(f"{specimens[i].id} {mode}: {code}")
            for mode in modes:
                per_mode[mode].append(times[mode])
            log(f"round {r + 1}/{rounds} done")
    finally:
        transport.close()
        for client in apps.values():
            client.close()
    load = os.getloadavg()[0] if hasattr(os, "getloadavg") else None
    return {
        "set": set_name,
        "images": len(images),
        "endpoint": "POST /v1/mask/image (render=opaque, OCR tesseract, detectors rules)",
        "platform": f"{platform.system()} {platform.machine()}",
        "host_load_average": round(load, 1) if load is not None else None,
        "modes": e2e_summary(per_mode, calls, errors),
    }
