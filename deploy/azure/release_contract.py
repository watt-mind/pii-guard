"""Local capability handshake for the reviewed app-only release path; no login/cloud calls."""

import json
import re
import sys
from pathlib import Path


def capabilities(environment: str) -> dict:
    if environment not in {"dev", "prod"}:
        raise ValueError("unknown_environment")
    source = Path(__file__).with_name("release.bicep").read_text()
    allowed = {
        "Microsoft.App/containerApps",
        "Microsoft.App/containerApps/authConfigs",
        "Microsoft.Insights/metricAlerts",
    }
    declarations = re.findall(r"resource\s+\w+\s+'([^@']+)@[^']+'\s*(existing)?", source)
    if not declarations or any(
        kind not in allowed for kind, existing in declarations if not existing
    ):
        raise ValueError("release_writes_outside_app_scope")
    if re.search(r"\b(?:listKeys|listSecrets)\s*\(", source, re.I):
        raise ValueError("release_requires_storage_keys")
    for required in (
        "PII_GUARD_HOSTED_SPEND_STORE",
        "azure_blob",
        "privateDevReviewed",
        "customDomains",
    ):
        if required not in source:
            raise ValueError("release_contract_incomplete")
    return {
        "version": 1,
        "app_only": True,
        "no_storage_keys": True,
        "no_role_assignments": True,
        "durable_budget": True,
        "private_dev": environment == "dev",
    }


if __name__ == "__main__":
    try:
        print(json.dumps(capabilities(sys.argv[1]), sort_keys=True))
    except (ValueError, OSError, IndexError):
        raise SystemExit("reviewed_app_release_contract_unavailable") from None
