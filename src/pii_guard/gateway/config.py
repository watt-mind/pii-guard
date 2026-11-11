"""Gateway settings from the environment (and ``.env``), like :class:`pii_guard.config.Settings`.

These live here, not in ``pii_guard.config``, until the settings work (LAB-1095) folds them in.

| Env var | Field | Default |
|---|---|---|
| ``PII_GUARD_GATEWAY_MODE`` | ``mode`` (``fast``, ``escalate`` or ``audit``) | ``fast`` |
| ``PII_GUARD_GATEWAY_DETECTION_TIMEOUT`` | ``detection_timeout`` (s) | ``30`` |
| ``PII_GUARD_GATEWAY_UPSTREAM_TIMEOUT`` | ``upstream_timeout`` (s, per read) | ``120`` |
| ``PII_GUARD_GATEWAY_UPSTREAM_STREAM_TIMEOUT`` | ``upstream_stream_timeout`` (s) | ``600`` |
| ``PII_GUARD_GATEWAY_UPSTREAM_MAX_RESPONSE_BYTES`` | ``upstream_max_response_bytes`` | 16 MiB |
| ``PII_GUARD_GATEWAY_UPSTREAM_MAX_CONNECTIONS`` | ``upstream_max_connections`` | ``100`` |
| ``PII_GUARD_GATEWAY_UPSTREAM_MAX_KEEPALIVE`` | ``upstream_max_keepalive`` (idle kept) | ``20`` |
| ``PII_GUARD_GATEWAY_UPSTREAM_KEEPALIVE_EXPIRY`` | ``upstream_keepalive_expiry`` (s) | ``30`` |
| ``PII_GUARD_GATEWAY_CACHE_SIZE`` | ``cache_size`` (entries) | ``4096`` |
| ``PII_GUARD_GATEWAY_CONCURRENCY`` | ``concurrency`` (parallel detections, per mode) | ``4`` |
| ``PII_GUARD_GATEWAY_MAX_IMAGES`` | ``max_images`` (inline images per request) | ``4`` |
| ``PII_GUARD_GATEWAY_MAX_IMAGE_BYTES`` | ``max_image_bytes`` (per image, decoded) | ``10485760`` |
| ``PII_GUARD_GATEWAY_IMAGE_TIMEOUT`` | ``image_timeout`` (s, all images of a request) | ``120`` |
| ``PII_GUARD_GATEWAY_KEEP_TYPES`` | ``keep_types`` (deprecated) | unset |
| ``PII_GUARD_LLM_DETECTOR_REASONING_EFFORT`` | ``llm_reasoning_effort`` | unset |
| ``PII_GUARD_GATEWAY_ESCALATE_WINDOW`` | ``escalate_window`` (chars each side) | ``200`` |
| ``PII_GUARD_GATEWAY_ESCALATE_MAX_WINDOWS`` | ``escalate_max_windows`` (per text) | ``4`` |
| ``PII_GUARD_GATEWAY_ESCALATE_MAX_TEXTS`` | ``escalate_max_texts`` (per request) | ``8`` |
| ``PII_GUARD_GATEWAY_ESCALATE_LOW_SCORE`` | ``escalate_low_score`` (NER) | ``0.75`` |
| ``PII_GUARD_GATEWAY_ESCALATE_TIMEOUT`` | ``escalate_timeout`` (s, per LLM call) | ``10`` |
| ``PII_GUARD_GATEWAY_ESCALATE_ON_FAILURE`` | ``escalate_on_failure`` (mask, keep) | ``mask`` |

Entity policies (mask / keep / block) come from ``PII_GUARD_POLICY_OVERRIDES`` in
:class:`pii_guard.config.Settings`, shared with the REST API. ``PII_GUARD_GATEWAY_KEEP_TYPES``
is a deprecated alias kept for compatibility: when set, it is the exact set of types the
gateway keeps (the other default-``keep`` types are masked), and ``PII_GUARD_POLICY_OVERRIDES``
still wins over it. See :func:`pii_guard.gateway.detection.gateway_policies`.

``strict`` is the deprecated name of ``audit`` (renamed in LAB-1186, because it read as the
safer production setting and collided with policy strictness): it is still accepted wherever a
mode is, maps to :attr:`Mode.AUDIT` and logs a one-time deprecation warning.
"""

from __future__ import annotations

import logging
import sys
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from pii_guard.types import EntityType

__all__ = ["DEPRECATED_MODE_ALIASES", "GatewayConfig", "Mode", "cli_mode", "parse_mode"]

logger = logging.getLogger("pii_guard.gateway")


class Mode(StrEnum):
    """``fast`` (the default): rules + NER, local, nothing leaves the machine.

    ``escalate``: fast, then only the spans fast mode is unsure about (low-confidence NER,
    capitalised words next to a form of address or a name, numbers without a checksum or a
    cue, rules-vs-NER type conflicts) go to the LLM detector, as small windows (about 200
    characters each side) with every span already found masked. The LLM can only add spans
    or settle a type; on a timeout or error the uncertain words are masked (fail closed).
    Text with nothing uncertain makes no remote call (:mod:`pii_guard.detect.escalate`).

    ``audit``: the fast detectors + an LLM detector per message, waiting for both. A second
    opinion for sampled or offline quality checks, label generation and the benchmark upper
    bound, not the production path: it costs a remote call (about 2 s and $2.5-3 per 1k
    messages) and the text goes to the detector endpoint.
    """

    FAST = "fast"
    ESCALATE = "escalate"
    AUDIT = "audit"

    @classmethod
    def _missing_(cls, value: object) -> Mode | None:
        if isinstance(value, str):
            name = DEPRECATED_MODE_ALIASES.get(value.strip().lower())
            if name is not None:
                warn_deprecated_mode(value.strip().lower())
                return cls(name)
        return None


#: Old mode names that still work, mapped to the current one.
DEPRECATED_MODE_ALIASES: dict[str, str] = {"strict": "audit"}
_warned: set[str] = set()


def warn_deprecated_mode(alias: str) -> None:
    """Log once per process that ``alias`` is a deprecated mode name."""
    if alias in _warned:
        return
    _warned.add(alias)
    logger.warning(
        "mode %r is deprecated and will be removed: use %r",
        alias,
        DEPRECATED_MODE_ALIASES[alias],
    )


def parse_mode(raw: str) -> tuple[Mode, bool]:
    """``(mode, deprecated)`` for a mode name; ``deprecated`` when ``raw`` is an old alias.

    Raises :class:`ValueError` for an unknown name.
    """
    name = raw.strip().lower()
    return Mode(name), name in DEPRECATED_MODE_ALIASES


def cli_mode(raw: str, prog: str) -> str:
    """A command-line mode value: an old alias becomes its new name, with a stderr warning.

    Unknown names are returned unchanged for the caller to reject.
    """
    name = raw.strip().lower()
    new = DEPRECATED_MODE_ALIASES.get(name)
    if new is None:
        return name
    print(f"{prog}: mode {name!r} is deprecated, use {new!r}", file=sys.stderr)
    return new


class GatewayConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PII_GUARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        populate_by_name=True,
    )

    mode: Mode = Field(default=Mode.FAST, validation_alias="PII_GUARD_GATEWAY_MODE")
    detection_timeout: float = Field(
        default=30.0, gt=0, validation_alias="PII_GUARD_GATEWAY_DETECTION_TIMEOUT"
    )
    upstream_timeout: float = Field(
        default=120.0, gt=0, validation_alias="PII_GUARD_GATEWAY_UPSTREAM_TIMEOUT"
    )
    # Whole-stream deadline (LAB-1566): upstream_timeout is per read, so a trickling
    # upstream could otherwise hold a stream (and its session) forever.
    upstream_stream_timeout: float = Field(
        default=600.0, gt=0, validation_alias="PII_GUARD_GATEWAY_UPSTREAM_STREAM_TIMEOUT"
    )
    # Largest non-streamed upstream success body buffered in any mode (LAB-1566).
    upstream_max_response_bytes: int = Field(
        default=16 * 1024 * 1024,
        ge=1,
        validation_alias="PII_GUARD_GATEWAY_UPSTREAM_MAX_RESPONSE_BYTES",
    )
    # The one shared upstream client's pool (LAB-1176): connections are kept alive between calls.
    upstream_max_connections: int = Field(
        default=100, ge=1, validation_alias="PII_GUARD_GATEWAY_UPSTREAM_MAX_CONNECTIONS"
    )
    upstream_max_keepalive: int = Field(
        default=20, ge=0, validation_alias="PII_GUARD_GATEWAY_UPSTREAM_MAX_KEEPALIVE"
    )
    upstream_keepalive_expiry: float = Field(
        default=30.0, ge=0, validation_alias="PII_GUARD_GATEWAY_UPSTREAM_KEEPALIVE_EXPIRY"
    )
    cache_size: int = Field(default=4096, ge=0, validation_alias="PII_GUARD_GATEWAY_CACHE_SIZE")
    concurrency: int = Field(default=4, ge=1, validation_alias="PII_GUARD_GATEWAY_CONCURRENCY")
    max_images: int = Field(default=4, ge=0, validation_alias="PII_GUARD_GATEWAY_MAX_IMAGES")
    max_image_bytes: int = Field(
        default=10 * 1024 * 1024, ge=1, validation_alias="PII_GUARD_GATEWAY_MAX_IMAGE_BYTES"
    )
    image_timeout: float = Field(
        default=120.0, gt=0, validation_alias="PII_GUARD_GATEWAY_IMAGE_TIMEOUT"
    )
    # Deprecated: use PII_GUARD_POLICY_OVERRIDES. None = not set (the policies decide).
    keep_types: Annotated[frozenset[EntityType] | None, NoDecode] = Field(
        default=None, validation_alias="PII_GUARD_GATEWAY_KEEP_TYPES"
    )
    # Tell the model placeholders are opaque tokens to copy as written (LAB-1471).
    placeholder_note: bool = Field(
        default=True, validation_alias="PII_GUARD_GATEWAY_PLACEHOLDER_NOTE"
    )
    llm_reasoning_effort: str | None = Field(
        default=None, validation_alias="PII_GUARD_LLM_DETECTOR_REASONING_EFFORT"
    )
    # Escalate mode (LAB-1766): which spans go to the LLM, how much text around them, and
    # what a failed LLM call does.
    escalate_window: int = Field(
        default=200, ge=20, le=2000, validation_alias="PII_GUARD_GATEWAY_ESCALATE_WINDOW"
    )
    escalate_max_windows: int = Field(
        default=4, ge=1, le=32, validation_alias="PII_GUARD_GATEWAY_ESCALATE_MAX_WINDOWS"
    )
    escalate_max_texts: int = Field(
        default=8, ge=1, le=256, validation_alias="PII_GUARD_GATEWAY_ESCALATE_MAX_TEXTS"
    )
    escalate_low_score: float = Field(
        default=0.75, ge=0.0, le=1.0, validation_alias="PII_GUARD_GATEWAY_ESCALATE_LOW_SCORE"
    )
    escalate_timeout: float = Field(
        default=10.0, gt=0, validation_alias="PII_GUARD_GATEWAY_ESCALATE_TIMEOUT"
    )
    escalate_on_failure: Literal["mask", "keep"] = Field(
        default="mask", validation_alias="PII_GUARD_GATEWAY_ESCALATE_ON_FAILURE"
    )

    @field_validator("keep_types", mode="before")
    @classmethod
    def _split_types(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(part.strip().upper() for part in value.split(",") if part.strip())
        return value
