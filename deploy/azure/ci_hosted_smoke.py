"""Verify hosted image packaging offline; deployed auth/readiness are separate release gates."""

import os
from pathlib import Path

import azure.identity
import azure.storage.blob

from pii_guard.app_bundle import ui_available
from pii_guard.detect.ner import NerDetector
from pii_guard.detect.ner_resolve import PUBLISHED
from pii_guard.projects.blob import BlobProjectStore
from pii_guard.visual.ocr import tesseract_available
from pii_guard.visual.sam import SamClient
from pii_guard.visual.segmenters import build_segmenter

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
# Hosted images (ADR 0014, ADR 0015): local Tesseract with its language packs, and SAM 3.1 on
# the Meta Model API for faces, ID photos and signatures. This smoke is offline by contract
# (LAB-1255): no key is set and no SAM request is made; it checks only that the default builds
# the built-in SAM client, that Meta's output parser is installed, and that no non-Meta
# on-device model was baked in (they are opt-in, PII_GUARD_ON_DEVICE_VISION).
if not tesseract_available():
    raise RuntimeError("hosted image OCR (Tesseract) is missing")
import pytesseract  # noqa: E402 - only after the availability check

missing = {"eng", "hun", "deu", "pol", "osd"} - set(pytesseract.get_languages(config=""))
if missing:
    raise RuntimeError(f"hosted image OCR language packs missing: {sorted(missing)}")
if os.environ.get("PII_GUARD_SEGMENTER") != "sam-api":
    raise RuntimeError("hosted images must default to SAM 3.1 (PII_GUARD_SEGMENTER=sam-api)")
if type(build_segmenter()) is not SamClient:
    raise RuntimeError("the hosted default segmenter is not the built-in SAM 3.1 client")
import meta_sam_parser  # noqa: E402, F401 - Meta's SAM 3.1 output parser (the sam extra)

baked = sorted(p.name for p in Path("/app/models").iterdir() if p.name != "ner")
if baked:
    raise RuntimeError(f"non-Meta on-device models baked in without opt-in: {baked}")
print(
    "Hosted packaging passed: bundled UI, CPU NER, local OCR, the SAM 3.1 client and Azure "
    "configuration imports work offline"
)
