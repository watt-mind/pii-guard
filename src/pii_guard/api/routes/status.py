"""``GET /v1/status``: what this server runs, for the web UI's Overview, Connect and Policy.

Read-only and configuration only: detector names, whether NER and the audit mode can run, the
entity policies, the traffic-log level, the image pipeline's gaps and the upstream's origin.
Never a key, a token, a value or a session: secrets appear only as "configured or not". The
upstream is reported by origin (scheme, host, port), without a path, user or password.

``gateway_url`` is this request's own base URL plus ``/v1``: the address a client on the same
network path (the browser that asked) reaches the gateway at.

One route in both modes (ADR 0013). ``capabilities`` tells the UI which sections this server
offers. Hosted owners get :func:`hosted_projection`: an explicit allow-list of fields, with
``gateway.url`` from ``HOSTED_PUBLIC_ORIGIN`` and their own traffic-log and vault views.
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

__all__ = ["capabilities", "hosted_projection", "router", "server_status", "upstream_origin"]

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
        from pii_guard.detection_profile import DetectionProfileError

        detector = LlmDetector(settings=settings)
    except DetectionProfileError as exc:
        return None, f"disabled by detection profile: {type(exc).__name__}"
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
    # `up --mock` marks it through up_status; `make demo` through the settings (LAB-1311):
    # under `serve` there is no up_status, but the upstream is the separate mock process.
    mock = bool(getattr(up, "mock", False) or settings.upstream_mock)
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


def capabilities(
    *, hosted: bool, traffic_log: str, vault_inspect: str, hosted_images: bool = False
) -> dict[str, bool]:
    """Which console sections this server offers (ADR 0013): the UI's only source for them.

    ``traffic_log`` and ``vault_inspect`` are the caller's own view (the server's settings
    locally, the owner's runtime when hosted), so ``logs`` and ``vault`` are one expression in
    both modes. Hosted images (ADR 0014) are the Images screen's ``/v1/mask/image`` for
    signed-in owners, while the operator offers them (``PII_GUARD_HOSTED_IMAGES``)."""
    return {
        "text": True,
        "chat": True,
        "images": hosted_images if hosted else True,
        "logs": traffic_log != "off",
        "vault": vault_inspect != "off",
        "server_policy": not hosted,
        "projects": True,
        "connect": True,
        "evaluation": True,
        "accounts": hosted,
    }


def hosted_projection(status: dict[str, Any], public_origin: str) -> dict[str, Any]:
    """What a signed-in hosted owner may see of :func:`server_status` (ADR 0013).

    An allow-list, so a new field stays local until it is added here: no upstream, image
    pipeline, ``auth``, REST detector list, metrics or server-wide traffic-log level. Hosted
    requests run fast mode only, so audit is not listed. ``gateway.url`` is the public origin,
    never the request's ``Host`` (an internal one behind the hosted router)."""
    gateway, ner = status["gateway"], status["ner"]
    return {
        "version": status["version"],
        "gateway": {
            "default_mode": "fast",
            "url": f"{public_origin.rstrip('/')}/v1",
            "modes": {"fast": gateway["modes"]["fast"]},
        },
        # No model: PII_GUARD_NER_MODEL may name an operator's local directory.
        "ner": {k: ner[k] for k in ("available", "state", "error")},
        "policies": status["policies"],
        "default_language": status["default_language"],
        "traffic_log": status["traffic_log"],
        "vault_inspect": status["vault_inspect"],
        "capabilities": status["capabilities"],
    }


def _hosted_images_servable(state: Any) -> bool:
    """Hosted images run on the on-device segmenter only: offered only while the server's
    visual policies ask for nothing it cannot find (a masked signature refuses every image)."""
    from pii_guard.hosted.images import unservable_visual_types

    return not unservable_visual_types(state.policies)


def server_status(request: Request) -> dict[str, Any]:
    state = request.app.state
    cached = getattr(state, "status_static", None)
    if cached is None:
        with _lock:
            cached = getattr(state, "status_static", None)
            if cached is None:
                cached = _static_status(request)
                state.status_static = cached
    runtime = getattr(request.state, "hosted_runtime", None)
    hosted = bool(state.settings.hosted)
    # The caller's own view: a hosted owner's runtime, else the server's (as /v1/traffic).
    obs = runtime.observability if runtime is not None else getattr(state, "observability", None)
    traffic = getattr(obs, "traffic", None)
    level = getattr(getattr(traffic, "level", None), "value", "off")
    # Hosted runtimes always inspect masked (api/routes/vault.py).
    inspect = "masked" if hosted else str(getattr(state, "vault_inspect", "masked"))
    base = str(request.base_url).rstrip("/")
    warmup = getattr(state, "ner_warmup", None)
    status = {
        **cached,
        "gateway": {**cached["gateway"], "url": f"{base}/v1"},
        # Live (LAB-1303): off | loading | ready | failed, and why it failed (type only).
        "ner": {
            **cached["ner"],
            "state": getattr(warmup, "state", "off"),
            "error": getattr(warmup, "error", None),
        },
        "traffic_log": level,
        "vault_inspect": inspect,
        "metrics": getattr(obs, "metrics", None) is not None,
        "capabilities": capabilities(
            hosted=hosted,
            traffic_log=level,
            vault_inspect=inspect,
            hosted_images=bool(state.settings.hosted_images) and _hosted_images_servable(state),
        ),
    }
    if hosted:
        return hosted_projection(status, state.hosted.origin)
    return status


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
    not. ``gateway.url`` is this request's own base URL plus ``/v1``. ``capabilities`` lists the
    console sections this server offers. Hosted: signed-in owners only, and a projection without
    upstream, image, auth or server-wide log details (`docs/contracts.md`)."""
    return server_status(request)
