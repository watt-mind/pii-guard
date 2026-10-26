"""Gateway settings from the environment (and ``.env``), like :class:`pii_guard.config.Settings`.

These live here, not in ``pii_guard.config``, until the settings work (LAB-1095) folds them in.

| Env var | Field | Default |
|---|---|---|
| ``PII_GUARD_GATEWAY_MODE`` | ``mode`` | ``strict`` |
| ``PII_GUARD_GATEWAY_DETECTION_TIMEOUT`` | ``detection_timeout`` (s) | ``30`` |
| ``PII_GUARD_GATEWAY_UPSTREAM_TIMEOUT`` | ``upstream_timeout`` (s) | ``120`` |
| ``PII_GUARD_GATEWAY_CACHE_SIZE`` | ``cache_size`` (entries) | ``4096`` |
| ``PII_GUARD_GATEWAY_CONCURRENCY`` | ``concurrency`` (parallel detections) | ``4`` |
| ``PII_GUARD_GATEWAY_KEEP_TYPES`` | ``keep_types`` | ``ORGANIZATION,COMPANY_ID_HU`` |
| ``PII_GUARD_LLM_DETECTOR_REASONING_EFFORT`` | ``llm_reasoning_effort`` | unset |
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from pii_guard.detect.pipeline import DEFAULT_KEEP_TYPES
from pii_guard.types import EntityType

__all__ = ["GatewayConfig", "Mode"]


class Mode(StrEnum):
    """``strict``: rules + LLM detector, wait for both. ``fast``: rules (+ NER) only."""

    STRICT = "strict"
    FAST = "fast"


class GatewayConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PII_GUARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        populate_by_name=True,
    )

    mode: Mode = Field(default=Mode.STRICT, validation_alias="PII_GUARD_GATEWAY_MODE")
    detection_timeout: float = Field(
        default=30.0, gt=0, validation_alias="PII_GUARD_GATEWAY_DETECTION_TIMEOUT"
    )
    upstream_timeout: float = Field(
        default=120.0, gt=0, validation_alias="PII_GUARD_GATEWAY_UPSTREAM_TIMEOUT"
    )
    cache_size: int = Field(default=4096, ge=0, validation_alias="PII_GUARD_GATEWAY_CACHE_SIZE")
    concurrency: int = Field(default=4, ge=1, validation_alias="PII_GUARD_GATEWAY_CONCURRENCY")
    keep_types: Annotated[frozenset[EntityType], NoDecode] = Field(
        default=DEFAULT_KEEP_TYPES, validation_alias="PII_GUARD_GATEWAY_KEEP_TYPES"
    )
    llm_reasoning_effort: str | None = Field(
        default=None, validation_alias="PII_GUARD_LLM_DETECTOR_REASONING_EFFORT"
    )

    @field_validator("keep_types", mode="before")
    @classmethod
    def _split_types(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(part.strip().upper() for part in value.split(",") if part.strip())
        return value
