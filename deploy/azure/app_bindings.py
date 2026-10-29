"""Read existing app bindings without turning authorization/transport errors into deletion."""

import json
import re
import subprocess
import sys


def existing_bindings(app: str, group: str, mode: str, *, run=subprocess.run) -> list:
    result = run(
        [
            "az",
            "containerapp",
            "show",
            "--name",
            app,
            "--resource-group",
            group,
            "--query",
            "properties.configuration.ingress.customDomains",
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        # Only explicit provider not-found codes establish an initial app. Never echo stderr.
        absent = re.search(
            r"^ERROR:\s+\((ResourceNotFound|ContainerAppNotFound)\)", result.stderr, re.M
        )
        if absent and mode == "stage":
            return []
        raise ValueError("existing_app_bindings_unavailable")
    if not result.stdout.strip():
        # az prints nothing, not "null", for an app without custom domains (LAB-1432).
        return []
    value = json.loads(result.stdout)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("existing_app_bindings_invalid")
    return value


if __name__ == "__main__":
    try:
        print(json.dumps(existing_bindings(*sys.argv[1:4])))
    except (ValueError, TypeError, OSError):
        raise SystemExit("existing_app_bindings_unavailable; release refused") from None
