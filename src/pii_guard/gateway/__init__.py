"""OpenAI-compatible gateway: mask every request, forward it, restore the (streamed) answer.

``POST /v1/chat/completions`` is served by the API's chat route (``api/routes/chat.py``), which
hands the body to :class:`Gateway`; the gateway itself never imports the API layer. See
``docs/architecture.md`` (gateway) and the README quickstart.
"""

from pii_guard.gateway.cache import DetectionCache
from pii_guard.gateway.config import GatewayConfig, Mode
from pii_guard.gateway.detection import ModeDetector, build_mode_detectors
from pii_guard.gateway.request import (
    InvalidChatRequestError,
    TextSlot,
    UnsupportedContentError,
    collect_texts,
)
from pii_guard.gateway.service import (
    ECHO_HEADER,
    LANGUAGE_HEADER,
    MODE_HEADER,
    REQUEST_ID_HEADER,
    SESSION_HEADER,
    SESSION_SOURCE_HEADER,
    Gateway,
    UpstreamError,
    UpstreamNotConfiguredError,
)
from pii_guard.gateway.sessions import SessionPathMiddleware, SessionSource, resolve_session
from pii_guard.gateway.stream import SseRestorer

__all__ = [
    "ECHO_HEADER",
    "LANGUAGE_HEADER",
    "MODE_HEADER",
    "REQUEST_ID_HEADER",
    "SESSION_HEADER",
    "SESSION_SOURCE_HEADER",
    "DetectionCache",
    "Gateway",
    "GatewayConfig",
    "InvalidChatRequestError",
    "Mode",
    "ModeDetector",
    "SessionPathMiddleware",
    "SessionSource",
    "SseRestorer",
    "TextSlot",
    "UnsupportedContentError",
    "UpstreamError",
    "UpstreamNotConfiguredError",
    "build_mode_detectors",
    "collect_texts",
    "resolve_session",
]
