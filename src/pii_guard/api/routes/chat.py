"""``POST /v1/chat/completions``: the OpenAI-compatible gateway (see :mod:`pii_guard.gateway`).

The gateway is built once per app and cached on ``app.state.gateway``. Tests (and embedders)
can set ``app.state.gateway`` directly, or override pieces before the first request:
``app.state.gateway_config`` (:class:`~pii_guard.gateway.GatewayConfig`),
``app.state.gateway_detectors`` (mode -> :class:`~pii_guard.gateway.ModeDetector`) and
``app.state.gateway_transport`` (an ``httpx.AsyncBaseTransport`` for the upstream).
"""

from __future__ import annotations

import json
import math
import threading
import time

from fastapi import Request
from starlette.responses import Response

from pii_guard.api.deps import get_max_text_chars, get_vault
from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import (
    LoggedRoute,
    ensure_connected,
    log_extra,
    text_body_limit,
    v1_router,
)
from pii_guard.gateway import Gateway, InvalidChatRequestError
from pii_guard.gateway.sessions import path_session
from pii_guard.visual.masking import image_workers_for

__all__ = ["get_gateway", "router"]

_lock = threading.Lock()


class GatewayRoute(LoggedRoute):
    """Room for the configured number of inline images (base64) on top of the text limit."""

    def max_body_bytes(self, request: Request) -> int:
        config = get_gateway(request).config
        images = math.ceil(config.max_images * config.max_image_bytes / 3) * 4
        return text_body_limit(request) + images


router = v1_router(GatewayRoute)


def get_gateway(request: Request) -> Gateway:
    state = request.app.state
    if getattr(request.state, "project_routed_endpoint", False) or (
        getattr(request.state, "hosted_runtime", None) is not None and not state.settings.hosted
    ):
        return state.projects.gateway(request)
    hosted = getattr(state, "hosted", None)
    if hosted is not None:
        return hosted.gateway(request)
    gateway = getattr(state, "gateway", None)
    if gateway is None:
        vault = get_vault(request)  # fails closed without a tenant key
        with _lock:
            gateway = getattr(state, "gateway", None)
            if gateway is None:
                gateway = Gateway(
                    settings=state.settings,
                    vault=vault,
                    config=getattr(state, "gateway_config", None),
                    detectors=getattr(state, "gateway_detectors", None),
                    transport=getattr(state, "gateway_transport", None),
                    observability=getattr(state, "observability", None),
                    image_workers=image_workers_for(state, state.settings.image_concurrency),
                )
                gateway._detect_workers = state.projects.worker_pools(gateway.config.concurrency)
                state.gateway = gateway
    from pii_guard.detection_profile import DetectionProfileError, is_local_only

    if is_local_only(state.settings) and (
        type(gateway) is not Gateway or not is_local_only(gateway.settings)
    ):
        raise DetectionProfileError("local-only cannot reuse a gateway from another profile")
    return gateway


@router.post(
    "/v1/chat/completions",
    tags=["gateway"],
    responses=error_responses("detection_profile_denied", "outbound_check_failed"),
)
async def chat_completions(request: Request) -> Response:
    await ensure_connected(request)
    gateway = get_gateway(request)
    raw = await request.body()
    received_at = time.perf_counter()  # timing starts once the body is in
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        # Never the decoder's message: it quotes the body.
        raise InvalidChatRequestError("request body is not valid JSON") from None
    response, stats = await gateway.chat_completions(
        body,
        request.headers,
        max_text_chars=get_max_text_chars(request),
        received_at=received_at,
        path_session=path_session(request.scope),
    )
    log_extra(request, **stats.log_fields())
    return response
