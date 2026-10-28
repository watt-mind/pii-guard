"""One hosted process, bundled UI, mandatory local NER and no request access log."""

import os

import uvicorn

from pii_guard.app_bundle import Status, create_bundle_app, ui_available
from pii_guard.config import get_settings

if os.environ.get("PII_GUARD_HOSTED") != "true" or not ui_available():
    raise RuntimeError("hosted mode and bundled UI are required")
settings = get_settings()
if not getattr(settings, "hosted", False):
    raise RuntimeError("hosted backend support is required")
if settings.ner_model != "/app/models/ner" or settings.detectors != ("rules", "ner"):
    raise RuntimeError("hosted image requires the bundled local NER stack")
app = create_bundle_app(
    Status(upstream="https://api.meta.ai/v1", detectors=["rules", "ner"]), settings
)
uvicorn.run(
    app,
    host="0.0.0.0",  # noqa: S104 - container is exposed only through trusted ingress
    port=8787,
    workers=1,
    access_log=False,
    log_level="warning",
)
