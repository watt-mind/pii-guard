"""Upstream presets: ``pii-guard up --upstream <name>`` instead of a base URL and a key variable.

Each preset is an OpenAI-compatible base URL, the environment variable that holds its key, and
the model a quickstart suggests when the provider lists it. ``--upstream-url`` and
``--api-key-env`` keep working for anything else.

| Preset | Base URL | Key | Suggested model |
| --- | --- | --- | --- |
| ``meta`` | ``https://api.meta.ai/v1`` (Meta Model API) | ``META_API_KEY`` | ``muse-spark-1.3`` |
| ``openai`` | ``https://api.openai.com/v1`` | ``OPENAI_API_KEY`` | the first listed |
| ``fireworks`` | ``https://api.fireworks.ai/inference/v1`` | ``FIREWORKS_API_KEY`` | first |
| ``openrouter`` | ``https://openrouter.ai/api/v1`` | ``OPENROUTER_API_KEY`` | first |

The Meta row was checked against the live API (``GET /v1/models`` lists ``muse-spark-1.3``, the
model Muse Code defaults to, next to image, voice and segmentation models a chat client can't
use). The other providers list hundreds of models, so no id is pinned here: the quickstart
offers the first one the gateway lists and says where to change it.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

__all__ = ["PRESETS", "Upstream", "by_url", "get"]


@dataclass(frozen=True)
class Upstream:
    """One OpenAI-compatible provider."""

    id: str
    label: str
    base_url: str
    key_env: str
    #: The model a quickstart suggests when the provider lists it (``None``: the first listed).
    default_model: str | None = None

    def command(self) -> str:
        """The two lines that start the gateway in front of this provider."""
        return f"export {self.key_env}=<your-key>\npii-guard up --upstream {self.id}"

    def public(self) -> dict[str, str | None]:
        """What the API and the UI may show: never a key, only the variable's name."""
        return {
            "id": self.id,
            "label": self.label,
            "base_url": self.base_url,
            "key_env": self.key_env,
            "default_model": self.default_model,
            "command": self.command(),
        }


PRESETS: dict[str, Upstream] = {
    p.id: p
    for p in (
        Upstream(
            "meta", "Meta Model API", "https://api.meta.ai/v1", "META_API_KEY", "muse-spark-1.3"
        ),
        Upstream("openai", "OpenAI", "https://api.openai.com/v1", "OPENAI_API_KEY"),
        Upstream(
            "fireworks",
            "Fireworks AI",
            "https://api.fireworks.ai/inference/v1",
            "FIREWORKS_API_KEY",
        ),
        Upstream("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    )
}


def get(name: str) -> Upstream:
    """The preset called ``name``. :class:`KeyError` names the known ones."""
    try:
        return PRESETS[name]
    except KeyError:
        raise KeyError(f"unknown upstream {name!r}; known: {', '.join(PRESETS)}") from None


def _origin(url: str) -> tuple[str, str, int | None] | None:
    try:
        parts = urlsplit(url)
        return parts.scheme, (parts.hostname or "").lower(), parts.port
    except ValueError:
        return None


def by_url(url: str | None) -> Upstream | None:
    """The preset whose host serves ``url`` (``None`` for anything else)."""
    if not url:
        return None
    origin = _origin(url)
    for preset in PRESETS.values():
        if origin is not None and origin == _origin(preset.base_url):
            return preset
    return None
