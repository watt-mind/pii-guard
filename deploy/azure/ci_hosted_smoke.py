"""Verify hosted image packaging offline; deployed auth/readiness are separate release gates."""

import os
from pathlib import Path

import azure.identity
import azure.storage.blob

from pii_guard.app_bundle import ui_available
from pii_guard.detect.ner import NerDetector
from pii_guard.detect.ner_resolve import PUBLISHED
from pii_guard.projects.blob import BlobProjectStore

# Import the actual optional SDK and persisted configuration backend without credentials or IO.
if not all(
    isinstance(component, type)
    for component in (
        azure.identity.ManagedIdentityCredential,
        azure.storage.blob.BlobClient,
        BlobProjectStore,
    )
):
    raise RuntimeError("hosted Azure configuration dependencies are unavailable")

if os.environ.get("PII_GUARD_HOSTED") != "true":
    raise RuntimeError("hosted image configuration is missing")
if not ui_available():
    raise RuntimeError("hosted UI is missing")
marker = Path("/app/models/ner/.pii-guard-verified")
if marker.read_text(encoding="utf-8").strip() != PUBLISHED.weights_sha256:
    raise RuntimeError("bundled NER verification marker differs from the pinned checkpoint")
# Constructor loads and warms the pinned local model; detect exercises the installed backend.
NerDetector(model="/app/models/ner", device="cpu").detect("Synthetic specimen.", language="en")
print("Hosted packaging passed: bundled UI, CPU NER and Azure configuration imports work offline")
