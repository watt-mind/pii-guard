"""``GET /v1/status``: what this server runs, for the web UI's Overview, Connect and Policy.

Read-only and configuration only: detector names, whether NER and the audit mode can run, the
entity policies, the traffic-log level, the image pipeline's gaps and the upstream's origin.
Never a key, a token, a value or a session: secrets appear only as "configured or not". The
upstream is reported by origin (scheme, host, port), without a path, user or password.

``gateway_url`` is this request's own base URL plus ``/v1``: the address a client on the same
network path (the browser that asked) reaches the gateway at.
"""

from __future__ import annotations

import logging
import threading
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request

from pii_guard import __version__
from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import v1_router
from pii_guard.config import Settings
from pii_guard.types import DetectionError

__all__ = ["router", "server_status", "upstream_origin"]

logger = logging.getLogger("pii_guard.api")

router = v1_router()
router.tags = ["status"]

_lock = threading.Lock()


def upstream_origin(url: str | None) -> str | None:
    """``scheme://host[:port]`` of ``url``: no path, query, user or password."""
    if not url:
        return None
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if not parts.scheme or not host:
        return None
    if ":" in host:
        host = f"[{host}]"
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


def _fast_detectors(settings: Settings) -> tuple[list[str], str | None]:
    from pii_guard.detect import stack

    try:
        return list(stack.default_detector_names(settings)), None
    except DetectionError as exc:
        return [], str(exc)


def _audit(settings: Settings) -> tuple[str | None, str | None]:
    """``(model, unavailable reason)`` of the audit mode's LLM detector."""
    try:
        from pii_guard.detect.llm import LlmDetector

        detector = LlmDetector(settings=settings)
    except Exception as exc:  # a status page must not fail on a bad detector config
        return None, f"the LLM detector can't be configured: {type(exc).__name__}"
    model = getattr(detector, "model", None)
    return (model if isinstance(model, str) and model else None), detector.unavailable_reason


def _image_gaps(settings: Settings) -> list[str]:
    try:
        from pii_guard.app_bundle import image_gaps

        return image_gaps(settings)
    except Exception:  # reported as unknown, never a 500
        logger.debug("image gaps unavailable", exc_info=True)
        return ["unknown"]


def _static_status(request: Request) -> dict[str, Any]:
    """Everything that is fixed for the life of the app, built once."""
    from pii_guard.gateway.config import GatewayConfig
    from pii_guard.gateway.detection import gateway_policies

    state = request.app.state
    settings: Settings = state.settings
    config = getattr(state, "gateway_config", None) or GatewayConfig()
    fast, fast_error = _fast_detectors(settings)
    model, audit_reason = _audit(settings)
    policies = gateway_policies(settings, config)
    up = getattr(state, "up_status", None)
    mock = bool(getattr(up, "mock", False))
    origin = None if mock else upstream_origin(settings.upstream_base_url)
    gaps = _image_gaps(settings)
    return {
        "version": __version__,
        "gateway": {
            "default_mode": config.mode.value,
            "modes": {
                "fast": {
                    "detectors": fast,
                    "available": fast_error is None,
                    "reason": fast_error,
                },
                "audit": {
                    "detectors": [*fast, "llm"],
                    "available": fast_error is None and audit_reason is None,
                    "reason": fast_error or audit_reason,
                    "model": model,
                },
            },
        },
        "rest": {"detectors": list(getattr(state, "detector_names", fast))},
        "ner": {"available": "ner" in fast, "model": settings.ner_model},
        "upstream": {
            "configured": mock or origin is not None,
            "mock": mock,
            "origin": origin,
        },
        "images": {
            "segmenter": settings.segmenter,
            "sam": settings.meta_api_key is not None or bool(settings.sam_url),
            "ocr_required": settings.image_require_ocr,
            "gaps": gaps,
            "available": not gaps,
        },
        "policies": {t.value: p.value for t, p in sorted(policies.as_mapping().items())},
        "auth": {"token_required": settings.api_token is not None},
        "default_language": settings.default_language,
    }


def server_status(request: Request) -> dict[str, Any]:
    state = request.app.state
    cached = getattr(state, "status_static", None)
    if cached is None:
        with _lock:
            cached = getattr(state, "status_static", None)
            if cached is None:
                cached = _static_status(request)
                state.status_static = cached
    obs = getattr(state, "observability", None)
    traffic = getattr(obs, "traffic", None)
    level = getattr(getattr(traffic, "level", None), "value", "off")
    base = str(request.base_url).rstrip("/")
    return {
        **cached,
        "gateway": {**cached["gateway"], "url": f"{base}/v1"},
        "traffic_log": level,
        "vault_inspect": str(getattr(state, "vault_inspect", "masked")),
        "metrics": getattr(obs, "metrics", None) is not None,
    }


@router.get(
    "/v1/status",
    summary="What this server runs: detectors, modes, policies, upstream, images",
    responses=error_responses(),
)
def status(request: Request) -> dict[str, Any]:
    """Read-only configuration for the web UI's Overview, Connect and Policy pages.

    Detector names, whether NER and the audit mode can run, the entity policies, the
    traffic-log level, the image pipeline's gaps and the upstream's origin (scheme, host,
    port). Never a key, a token, a value or a session: secrets appear only as configured or
    not. ``gateway.url`` is this request's own base URL plus ``/v1``."""
    return server_status(request)
