"""Shared input for the cURL and OpenAI SDK examples. All document data is fictional."""

from __future__ import annotations

import argparse
import base64
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

PROMPT = (
    "This is a synthetic integration check. Repeat this fictional contact email exactly: "
    "sample.person@example.com."
)


@dataclass(frozen=True)
class Request:
    base_url: str
    api_key: str = field(repr=False)
    body: dict


def read_request(argv: list[str] | None = None) -> Request:
    parser = argparse.ArgumentParser(description="Send synthetic data through pii-guard.")
    parser.add_argument("--stream", action="store_true", help="Receive a streamed answer")
    parser.add_argument("--image", type=Path, help="Synthetic PNG/JPEG; self-hosted root only")
    args = parser.parse_args(argv)
    base_url = os.environ.get("GUARD_BASE_URL", "http://127.0.0.1:8787/v1").rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith("/v1")
        or any(c in base_url for c in "\r\n")
    ):
        raise ValueError("GUARD_BASE_URL must be a guard HTTP(S) URL ending in /v1")
    api_key = os.environ.get("GUARD_API_KEY", "")
    if any(c in api_key for c in "\r\n"):
        raise ValueError("GUARD_API_KEY must be a single line")
    if "/e/" in parsed.path and not api_key:
        raise ValueError("Project endpoints require GUARD_API_KEY")
    model = os.environ.get("GUARD_MODEL", "")
    if not model:
        raise ValueError("Set GUARD_MODEL to the upstream model or exact endpoint model")
    content: str | list[dict] = PROMPT
    if args.image:
        if "/e/" in parsed.path:
            raise ValueError("Project endpoints do not support images; use a self-hosted root URL")
        image = args.image.read_bytes()
        if image.startswith(b"\x89PNG\r\n\x1a\n"):
            media_type = "image/png"
        elif image.startswith(b"\xff\xd8\xff"):
            media_type = "image/jpeg"
        else:
            raise ValueError("The synthetic image must be PNG or JPEG")
        content = [
            {"type": "text", "text": PROMPT + " Describe the masked synthetic image."},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{media_type};base64,{base64.b64encode(image).decode('ascii')}",
                    "detail": "low",
                },
            },
        ]
    return Request(
        base_url,
        api_key,
        {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "stream": args.stream,
            "max_completion_tokens": 256,
        },
    )
