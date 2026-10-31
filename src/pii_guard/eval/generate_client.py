"""OpenAI-compatible Chat Completions client and on-disk response cache for corpus generation."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from pii_guard.types import EntityType

GENERATOR_VERSION = 3
DEFAULT_BASE_URL = "https://api.meta.ai/v1"
#: The corpus is entirely fictional, so it may use the contributor tier (cheaper; its traffic
#: may be used by Meta to improve its products). Never use this tier for real or masked data:
#: the detector and gateway defaults stay on non-contributor / open-weights models.
DEFAULT_MODEL = "muse-spark-1.3-contributor"
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_CACHE = "eval/generated/cache"

#: Structured types the rule detector finds reliably (checksums, formats). A hit of one of
#: these that doesn't overlap a supplied value means the model invented an identifier.
UNSUPPLIED_CHECK_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.EMAIL,
        EntityType.PHONE,
        EntityType.BANK_ACCOUNT,
        EntityType.PAYMENT_CARD,
        EntityType.NATIONAL_ID_HU_TAX,
        EntityType.NATIONAL_ID_HU_TAJ,
        EntityType.COMPANY_ID_HU,
        EntityType.VEHICLE_PLATE,
    }
)

_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class GenerationError(RuntimeError):
    """A configuration or endpoint problem that stops the whole run."""


class ModelError(GenerationError):
    """The model call failed. ``retryable`` failures discard one document; others abort."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


# --- Model client ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Completion:
    content: str
    finish_reason: str | None
    usage: Mapping[str, int]
    latency_s: float
    model: str
    cached: bool = False

    def __repr__(self) -> str:  # never the content
        return (
            f"Completion(model={self.model!r}, chars={len(self.content)}, "
            f"finish_reason={self.finish_reason!r}, cached={self.cached})"
        )

    def to_cache(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "finish_reason": self.finish_reason,
            "usage": dict(self.usage),
            "latency_s": self.latency_s,
            "model": self.model,
        }


def _usage(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    out = {
        k: int(raw[k])
        for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        if isinstance(raw.get(k), int)
    }
    details = raw.get("completion_tokens_details")
    if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), int):
        out["reasoning_tokens"] = int(details["reasoning_tokens"])
    return out


class ChatClient:
    """Minimal OpenAI-compatible Chat Completions client for document generation.

    ``base_url`` is the API root (``.../v1``) or the full ``.../chat/completions`` URL.
    ``reasoning_effort`` is sent when set (Muse Spark always reasons and rejects ``"none"``).
    ``transport`` is an ``httpx.BaseTransport`` (tests use ``httpx.MockTransport``).
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        reasoning_effort: str | None = DEFAULT_REASONING_EFFORT,
        temperature: float | None = 0.8,
        max_tokens: int | None = 8192,
        timeout: float = 180.0,
        max_retries: int = 2,
        backoff_s: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if reasoning_effort == "none":
            raise ValueError("Muse models always reason; use 'minimal' or 'low', not 'none'")
        url = base_url.rstrip("/")
        self.url = url if url.endswith("/chat/completions") else url + "/chat/completions"
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self._sleep = sleep
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout), headers=headers, transport=transport
        )

    def __repr__(self) -> str:  # never the key
        return f"ChatClient(url={self.url!r}, model={self.model!r})"

    def close(self) -> None:
        self._client.close()

    def payload(self, messages: Sequence[Mapping[str, str]]) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "messages": [dict(m) for m in messages]}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        return body

    def complete(self, messages: Sequence[Mapping[str, str]]) -> Completion:
        body = self.payload(messages)
        last = "no attempt"
        for attempt in range(self.max_retries + 1):
            if attempt:
                self._sleep(self.backoff_s * 2 ** (attempt - 1))
            started = time.monotonic()
            try:
                response = self._client.post(self.url, json=body)
            except httpx.TimeoutException:
                last = "timeout"
                continue
            except httpx.HTTPError as exc:
                last = f"transport error ({type(exc).__name__})"
                continue
            latency = time.monotonic() - started
            if response.status_code in _RETRYABLE_STATUS:
                last = f"HTTP {response.status_code}"
                continue
            if response.status_code >= 400:
                raise ModelError(
                    f"model endpoint returned HTTP {response.status_code}", retryable=False
                )
            try:
                data = response.json()
                choice = data["choices"][0]
                content = choice["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError):
                last = "malformed response"
                continue
            if not isinstance(content, str):
                last = "malformed response"
                continue
            return Completion(
                content=content,
                finish_reason=choice.get("finish_reason"),
                usage=_usage(data.get("usage")),
                latency_s=round(latency, 3),
                model=str(data.get("model") or self.model),
            )
        raise ModelError(
            f"model call failed after {self.max_retries + 1} attempts: {last}", retryable=True
        )


class ResponseCache:
    """Raw model outputs on disk, one JSON file per request hash."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    @staticmethod
    def key(payload: Mapping[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"

    def get(self, key: str) -> Completion | None:
        path = self._path(key)
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Completion(
            content=raw["content"],
            finish_reason=raw.get("finish_reason"),
            usage=raw.get("usage", {}),
            latency_s=float(raw.get("latency_s", 0.0)),
            model=raw.get("model", ""),
            cached=True,
        )

    def put(self, key: str, completion: Completion) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(completion.to_cache(), ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
