"""Feed cURL configuration over stdin so the guard key is absent from process arguments."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

from common import Request, read_request


def curl_config(request: Request) -> str:
    # JSON string quoting also escapes the quotes/backslashes in cURL's config format.
    lines = [
        "url = " + json.dumps(request.base_url + "/chat/completions"),
        'header = "Content-Type: application/json"',
        "data = " + json.dumps(json.dumps(request.body, ensure_ascii=False), ensure_ascii=False),
    ]
    if request.api_key:
        lines.append("header = " + json.dumps("Authorization: Bearer " + request.api_key))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    try:
        request = read_request(argv)
        executable = shutil.which("curl")
        if executable is None:
            raise ValueError("Install cURL before running this example")
        # -q ignores ~/.curlrc (which may enable verbose traces or logging).
        result = subprocess.run(  # noqa: S603 - fixed command, data only on stdin
            [
                executable,
                "-q",
                "--silent",
                "--show-error",
                "--fail",
                "--no-buffer",
                "--config",
                "-",
            ],
            input=curl_config(request),
            text=True,
            check=False,
        )
        return result.returncode
    except (ValueError, OSError):
        print(
            "Example failed: check environment, cURL installation and synthetic image input.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
