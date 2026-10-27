# syntax=docker/dockerfile:1

# --- build: resolve dependencies and install the project into /app/.venv -----
FROM ghcr.io/astral-sh/uv:0.13.6-python3.12-trixie-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Extras installed into the image. The `ocr` extra (pytesseract) reads the text in images;
# without it image parts are refused (ADR 0006). The `local-vision` extra (OpenCV headless)
# runs YuNet, the on-device face and ID-photo detector of the default hybrid segmenter
# (PII_GUARD_SEGMENTER, LAB-1245). The demo image (compose.yaml, profile demo) adds `ner`
# (torch + transformers) for fast mode with the NER; its model is fetched at run time into a
# volume, never baked in (LAB-1192).
ARG PII_GUARD_EXTRAS="ocr local-vision"

# Dependencies first, so code changes don't invalidate this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev $(for e in $PII_GUARD_EXTRAS; do printf -- '--extra %s ' "$e"; done) \
        --no-install-project

COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev $(for e in $PII_GUARD_EXTRAS; do printf -- '--extra %s ' "$e"; done) \
        --no-editable

# The YuNet model (0.23 MB, MIT, OpenCV model zoo): fetched from its pinned URL and checked
# against its pinned SHA-256 (pii_guard.visual.segment.YUNET); the build fails on a mismatch.
RUN PII_GUARD_MODEL_DIR=/app/models /app/.venv/bin/python -m pii_guard.visual.segment fetch

# --- runtime: Python, Tesseract and the virtualenv, as a non-root user -------
FROM python:3.12-slim-trixie AS runtime

# Tesseract reads the text in images (a TAJ, a name) so it can be masked; the Hungarian,
# English and German packs match the language packs (docs/languages.md). Adds ~115 MB
# (the apt layer; docs/operations.md).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-osd tesseract-ocr-eng tesseract-ocr-hun tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 piiguard \
    && useradd --system --uid 10001 --gid piiguard --no-create-home piiguard

COPY --from=build --chown=piiguard:piiguard /app/.venv /app/.venv
COPY --from=build --chown=piiguard:piiguard /app/models /app/models
# Writable mount point for downloaded models (the demo's NER volume), owned by the app user so
# a fresh named volume mounted here is too.
RUN mkdir -p /app/cache && chown piiguard:piiguard /app/cache

# 0.0.0.0 inside the container: publish the port on 127.0.0.1 only (compose.yaml does). The API
# has no authentication unless PII_GUARD_API_TOKEN is set (docs/operations.md, Exposure).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PII_GUARD_HOST=0.0.0.0 \
    PII_GUARD_PORT=8787 \
    PII_GUARD_MODEL_DIR=/app/models

WORKDIR /app
USER piiguard
EXPOSE 8787

# Healthy = /healthz answers and OCR is available (or explicitly not required); prints "ocr on|off".
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, sys, urllib.request; from pii_guard.visual.ocr import tesseract_available as t; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PII_GUARD_PORT']}/healthz\", timeout=2); ok = t(); print('ocr', 'on' if ok else 'off'); sys.exit(0 if ok or os.environ.get('PII_GUARD_IMAGE_REQUIRE_OCR', 'true').lower() in ('false', '0', 'no', 'off') else 1)"]

CMD ["pii-guard", "serve"]
