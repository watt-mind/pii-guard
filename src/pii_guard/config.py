"""Settings from the environment (and an optional ``.env`` file).

Every key in ``.env.example`` maps to a field here. Secrets are ``SecretStr`` so they never
appear in ``repr()`` or logs. Empty values (``PII_GUARD_SAM_URL=``) count as unset.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from pii_guard.policy import Policy, parse_overrides
from pii_guard.types import EntityType

__all__ = ["DEFAULT_DETECTORS", "DEFAULT_PORT", "Settings", "get_settings"]

DEFAULT_PORT = 8787
DEFAULT_DETECTORS: tuple[str, ...] = ("rules",)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PII_GUARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # Server
    host: str = "127.0.0.1"
    port: int = Field(default=DEFAULT_PORT, ge=1, le=65535)
    log_level: str = "info"
    default_language: str = "hu"

    # Detection and policies for the REST API (/v1/analyze, /v1/mask).
    # Comma-separated registry names, run through the DetectionPipeline: "rules,llm".
    detectors: Annotated[tuple[str, ...], NoDecode] = DEFAULT_DETECTORS
    # "TYPE=mask|keep|block,..." on top of the defaults in docs/entities.md.
    policy_overrides: Annotated[dict[EntityType, Policy], NoDecode] = Field(default_factory=dict)

    # Upstream LLM the gateway forwards masked requests to (OpenAI-compatible).
    upstream_base_url: str | None = None
    upstream_api_key: SecretStr | None = None

    # Key for deriving pseudonyms (HMAC), hex encoded (openssl rand -hex 32).
    tenant_key: SecretStr | None = None

    # Values an application pre-loads into a session (POST /v1/sessions/{id}/known-values).
    known_values_max: int = Field(default=1000, ge=1)
    known_values_max_length: int = Field(default=256, ge=3)

    # Vault: give each casing of a value (ALL CAPS, lower case) its own placeholder, so
    # unmask restores the casing exactly. Off: one placeholder, restored as first written.
    vault_case_sensitive_placeholders: bool = False

    # Model endpoints.
    llm_detector_url: str | None = None
    llm_detector_api_key: SecretStr | None = None
    # Model name the LLM detector requests; unset uses the detector's built-in default.
    llm_detector_model: str | None = None
    # Sent as chat_template_kwargs.reasoning_strength (low|medium|high|xhigh). Muse Glimmer on
    # vLLM reads this instead of reasoning_effort; unset sends nothing.
    llm_detector_reasoning_strength: str | None = None
    sam_url: str | None = None

    # Corpus generation only (fictional data). Not prefixed: the provider's own name.
    meta_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("META_API_KEY", "meta_api_key")
    )

    @field_validator("detectors", mode="before")
    @classmethod
    def _split_detectors(cls, value: object) -> object:
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(value, list | tuple) and not value:
            raise ValueError("PII_GUARD_DETECTORS needs at least one detector name")
        return value

    @field_validator("policy_overrides", mode="before")
    @classmethod
    def _parse_policies(cls, value: object) -> object:
        if isinstance(value, str) or value is None:
            return parse_overrides(value)
        return value

    def tenant_key_bytes(self) -> bytes | None:
        """The tenant key decoded from hex, or ``None`` if unset.

        Raises ``ValueError`` (without echoing the key) if it is not valid hex.
        """
        if self.tenant_key is None:
            return None
        try:
            return bytes.fromhex(self.tenant_key.get_secret_value())
        except ValueError:
            raise ValueError("PII_GUARD_TENANT_KEY must be a hex string") from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Tests call ``get_settings.cache_clear()`` after changing env."""
    return Settings()
