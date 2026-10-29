"""OpenAI Python SDK against pii-guard, including restored text deltas and inline images."""

from __future__ import annotations

import sys

from common import Request, read_request
from openai import OpenAI, OpenAIError


def chat(client: OpenAI, request: Request) -> None:
    if request.body["stream"]:
        finished = False
        with client.chat.completions.create(**request.body) as stream:
            for chunk in stream:
                # Role-only and usage-only events may have no text/choices.
                for choice in chunk.choices:
                    if choice.delta.content:
                        print(choice.delta.content, end="", flush=True)
                    finished = finished or choice.finish_reason is not None
        if not finished:
            raise ValueError("Stream ended before a finish event")
        print()
    else:
        completion = client.chat.completions.create(**request.body)
        print(completion.choices[0].message.content or "")


def main(argv: list[str] | None = None) -> int:
    try:
        request = read_request(argv)
        with OpenAI(
            base_url=request.base_url,
            # The SDK requires a value even when local guard authentication is disabled.
            api_key=request.api_key or "local-development",
            max_retries=0,
            timeout=180.0,
        ) as client:
            chat(client, request)
        return 0
    except (OpenAIError, ValueError, OSError):
        # Do not print SDK exceptions: they can carry HTTP bodies or request details.
        print(
            "Guard request failed; any streamed output is incomplete. Check guard configuration.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
