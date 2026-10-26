"""Settings from the environment (and an optional ``.env`` file).

Every key in ``.env.example`` maps to a field here. Secrets are ``SecretStr`` so they never
appear in ``repr()`` or logs. Empty values (``PII_GUARD_SAM_URL=``) count as unset.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["DEFAULT_PORT", "Settings", "get_settings"]

DEFAULT_PORT = 8787


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

    # Upstream LLM the gateway forwards masked requests to (OpenAI-compatible).
    upstream_base_url: str | None = None
    upstream_api_key: SecretStr | None = None

    # Key for deriving pseudonyms (HMAC), hex encoded (openssl rand -hex 32).
    tenant_key: SecretStr | None = None

    # Model endpoints.
    llm_detector_url: str | None = None
    llm_detector_api_key: SecretStr | None = None
    sam_url: str | None = None

    # Corpus generation only (fictional data). Not prefixed: the provider's own name.
    meta_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("META_API_KEY", "meta_api_key")
    )

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
