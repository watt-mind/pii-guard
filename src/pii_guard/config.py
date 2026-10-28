"""Settings from the environment (and an optional ``.env`` file).

Every key in ``.env.example`` maps to a field here. Secrets are ``SecretStr`` so they never
appear in ``repr()`` or logs. Empty values (``PII_GUARD_SAM_URL=``) count as unset.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

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
    # Exposure (docs/operations.md). No authentication by default: run on loopback or behind an
    # authenticating proxy. Host headers answered besides localhost, 127.0.0.1, [::1] and
    # PII_GUARD_HOST (DNS-rebinding guard), comma-separated; "*" answers any host.
    allowed_hosts: Annotated[tuple[str, ...], NoDecode] = ()
    # Bearer token required on every route but /healthz; unset: no authentication.
    api_token: SecretStr | None = None
    # Durable project metadata and encrypted upstream credentials (raw mappings remain ephemeral).
    project_state_path: str = "~/.local/share/pii-guard/projects/state.sqlite3"
    hosted_project_store: Literal["sqlite", "azure_blob"] = "sqlite"
    hosted_project_account_url: str | None = None
    hosted_project_container: str = "project-configuration"
    hosted_project_environment: Literal["dev", "prod"] = "dev"
    hosted_project_managed_identity_client_id: str | None = None

    # Hosted mode requires the Azure Easy Auth sidecar to own the only ingress path.
    # Defaults deliberately retain the local/self-hosted behavior.
    hosted: bool = False
    hosted_public_origin: str | None = None
    hosted_trust_easy_auth: bool = False
    hosted_single_process: bool = False
    # Enable only after verifying direct ACA ingress and access-log privacy.
    hosted_client_ip_source: Literal["off", "aca_xff_rightmost"] = "off"
    hosted_max_principals: int = Field(default=256, ge=1, le=10000)
    hosted_runtime_ttl: int = Field(default=3600, ge=300, le=86400)
    hosted_max_sessions: int = Field(default=20, ge=1, le=100)
    hosted_max_body_bytes: int = Field(default=32768, ge=1024, le=262144)
    hosted_max_output_tokens: int = Field(default=8192, ge=1024, le=32768)
    hosted_request_timeout: float = Field(default=180, gt=0, le=240)
    hosted_models: Annotated[tuple[str, ...], NoDecode] = ("muse-spark-1.3",)
    hosted_sponsored_microdollars: int = Field(default=0, ge=0)
    hosted_sponsored_allocation_id: str | None = None
    hosted_allocation_directory: str | None = None
    hosted_allocation_expires_at: float | None = None
    hosted_spend_store: Literal["marker", "azure_blob"] = "marker"
    hosted_spend_account_url: str | None = None
    hosted_spend_container: str = "sponsored-allowance"
    hosted_spend_environment: Literal["dev", "prod"] = "dev"
    hosted_spend_managed_identity_client_id: str | None = None
    # Conservative ceilings, including reasoning tokens. Operator verifies against prices.
    hosted_input_microdollars_per_token: int = Field(default=100, ge=1)
    hosted_output_microdollars_per_token: int = Field(default=100, ge=1)
    # Hosted image masking (LAB-1390, ADR 0014): signed-in Google owners only, processed in
    # memory on the replica with Tesseract and the on-device segmenter; nothing remote. With it
    # on, readiness requires OCR and the local segmenter. Bounded separately from text: the
    # decoded upload, the decoded pixels, one image job per replica, a deadline and a per-owner
    # daily image count reserved before work.
    hosted_images: bool = True
    hosted_max_image_bytes: int = Field(default=4 * 1024 * 1024, ge=65536, le=10 * 1024 * 1024)
    hosted_image_max_pixels: int = Field(default=8_000_000, ge=65536, le=16_000_000)
    hosted_image_timeout: float = Field(default=60, gt=0, le=120)
    hosted_user_images_per_day: int = Field(default=20, ge=1, le=1000)
    hosted_global_images_per_day: int = Field(default=500, ge=1, le=100_000)

    # Detection and policies for the REST API (/v1/analyze, /v1/mask).
    # Comma-separated registry names, run through the DetectionPipeline: "rules,llm". Unset:
    # the gateway fast-mode stack, rules + ner when available (pii_guard.detect.stack).
    detectors: Annotated[tuple[str, ...] | None, NoDecode] = None
    # A processing constraint, independent of the masked downstream LLM destination.
    detection_profile: Literal["standard", "local-only"] = "standard"
    # "TYPE=mask|keep|block,..." on top of the defaults in docs/entities.md.
    policy_overrides: Annotated[dict[EntityType, Policy], NoDecode] = Field(default_factory=dict)
    # Deprecated (use policy_overrides): types to keep, the rest of the default keeps masked.
    # Applied by PolicySet.from_settings for the REST API and the gateway alike.
    gateway_keep_types: Annotated[frozenset[EntityType] | None, NoDecode] = None

    # NER detector (the "ner" extra): hub id or local directory, hub revision, and device
    # (auto|cpu|mps|cuda). A set model makes a missing "ner" extra stop startup (ADR 0006).
    # Unset, fast mode resolves (pii_guard.detect.ner_resolve, docs/models.md): the published
    # pii-guard checkpoint ("repo" or "repo@revision"; the default repo is pinned to v2.0), else
    # the public fallback (a stop-gap), fetched once into ~/.cache/pii-guard/models
    # (PII_GUARD_MODELS_DIR).
    # ner_fallback: "download" fetches it on first use, "cached" only uses it when already
    # there, "off" never uses it (fast mode is then rules only).
    ner_model: str | None = None
    ner_revision: str | None = None
    ner_device: str | None = None
    ner_published_model: str = "watt-mind/pii-guard-ner-xlmr-base"
    ner_fallback: Literal["download", "cached", "off"] = "download"
    # Without ner_model, the resolved model loads (and downloads) in the background at startup
    # (LAB-1303); a detecting request that arrives meanwhile waits up to this many seconds,
    # then gets 503 detector_loading.
    ner_warmup_timeout: float = Field(default=120.0, gt=0)

    # Upstream LLM the gateway forwards masked requests to (OpenAI-compatible).
    upstream_base_url: str | None = None
    upstream_api_key: SecretStr | None = None

    # Key for deriving pseudonyms (HMAC), hex encoded (openssl rand -hex 32).
    tenant_key: SecretStr | None = None

    # Values an application pre-loads into a session (POST /v1/sessions/{id}/known-values).
    known_values_max: int = Field(default=1000, ge=1)
    known_values_max_length: int = Field(default=256, ge=3)

    # Rules: mask a number right after a strong cue word (TAJ, passport, IBAN, telefon) as the
    # cued type even when its checksum fails, at a lower score (languages/cues.py, LAB-1170).
    rules_cued_numbers: bool = True

    # Vault: give each casing of a value (ALL CAPS, lower case) its own placeholder, so
    # unmask restores the casing exactly. Off: one placeholder, restored as first written.
    vault_case_sensitive_placeholders: bool = False

    # Images (POST /v1/mask/image and the gateway): "labels" prints each covered region's
    # session placeholder and returns a masked transcript + summary; "opaque": solid boxes.
    image_render: Literal["labels", "opaque"] = "labels"
    # Who finds faces, ID photos and signatures in images (pii_guard.visual.segmenters,
    # LAB-1245): "hybrid" = YuNet on the CPU for faces and ID photos, SAM 3.1 (Meta API) for
    # signatures; "sam-api" = SAM 3.1 for everything (the previous default); "local" = YuNet
    # only (refuses images while SIGNATURE is masked); "off" = refuse every image.
    segmenter: Literal["hybrid", "sam-api", "local", "off"] = "hybrid"
    # Fail closed without OCR (ADR 0006): with no OCR engine (Tesseract) an image's text can't
    # be checked, so image parts are refused with 503 ocr_unavailable. False forwards them
    # masked by SAM only, with X-PII-Guard-Image-OCR: off (text in the image unchecked).
    image_require_ocr: bool = True
    # Resource limits for image work (LAB-1207). Images above max_pixels are refused with 413
    # (OCR time and memory grow with pixels); at most image_concurrency images are masked at
    # once per app, each request within image_timeout seconds (POST /v1/mask/image; the
    # gateway uses PII_GUARD_GATEWAY_IMAGE_TIMEOUT), Tesseract killed when it runs out.
    image_max_pixels: int = Field(default=16_000_000, ge=1)
    image_concurrency: int = Field(default=2, ge=1)
    image_timeout: float = Field(default=120.0, gt=0)

    # Most live vault sessions; one more evicts the least recently used (docs/operations.md).
    vault_max_sessions: int = Field(default=10_000, ge=1)
    # Most placeholders in one get-or-create gateway session (the URL path, prompt_cache_key
    # and default sessions, LAB-1286); a full one moves on to a new generation.
    vault_max_entries: int = Field(default=10_000, ge=1)
    # The console's vault inspector (GET /v1/vault/sessions, LAB-1328): "masked" lists sessions
    # and placeholders with redacted hints, never an original; "full" can also reveal originals,
    # on a loopback bind only (like PII_GUARD_TRAFFIC_LOG=full); "off": the routes answer 404.
    vault_inspect: Literal["off", "masked", "full"] = "masked"
    # Most characters of original values one /v1/unmask call or one gateway response restores
    # (LAB-1350): a placeholder of a long value repeated in a short text would expand without
    # bound. Over it, 413 unmask_output_too_large (a stream ends with that error event).
    unmask_max_restored_chars: int = Field(default=1_000_000, ge=1)

    # Model endpoints.
    llm_detector_url: str | None = None
    llm_detector_api_key: SecretStr | None = None
    # Model name the LLM detector requests; unset uses the detector's built-in default.
    llm_detector_model: str | None = None
    # Sent as reasoning_effort (e.g. low|minimal); unset sends nothing. Muse Spark Open on
    # Baseten needs "low".
    llm_detector_reasoning_effort: str | None = None
    # Per-request limits of the LLM detector; unset uses 4096 tokens and 60 seconds.
    llm_detector_max_tokens: int | None = Field(default=None, ge=256)
    llm_detector_timeout: float | None = Field(default=None, gt=0)
    # Sent as chat_template_kwargs.reasoning_strength (low|medium|high|xhigh). Muse Glimmer on
    # vLLM reads this instead of reasoning_effort; unset sends nothing.
    llm_detector_reasoning_strength: str | None = None
    sam_url: str | None = None
    # NER detector (fast mode). "transformers": a token-classification checkpoint
    # (PII_GUARD_NER_MODEL); "gliner": a GLiNER checkpoint, default the public zero-shot
    # urchade/gliner_multi-v2.1 (needs the gliner extra). See docs/models.md.
    ner_backend: Literal["transformers", "gliner"] = "transformers"

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

    @field_validator("gateway_keep_types", mode="before")
    @classmethod
    def _split_keep_types(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(part.strip().upper() for part in value.split(",") if part.strip())
        return value

    @field_validator("allowed_hosts", "hosted_models", mode="before")
    @classmethod
    def _split_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
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
