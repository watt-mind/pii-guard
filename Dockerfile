# syntax=docker/dockerfile:1

# --- build: resolve dependencies and install the project into /app/.venv -----
FROM ghcr.io/astral-sh/uv:0.13.7-python3.12-trixie-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Extras installed into the image. The `ocr` extra (pytesseract) is the Python side of the
# opt-in Tesseract OCR engine (PII_GUARD_TESSERACT below); the default OCR, Muse Spark Open
# (ADR 0016), needs no extra. The `sam` extra is Meta's official SAM 3.1
# output parser (meta-sam-parser, SAM License, LAB-1665): SAM 3.1 on the Meta Model API is the
# default segmenter (PII_GUARD_SEGMENTER=sam-api, ADR 0015). The `local-vision` extra (OpenCV
# headless) runs YuNet, the optional on-device face and ID-photo detector (hybrid / local
# segmenters, LAB-1245); its model is fetched only with PII_GUARD_ON_DEVICE_VISION=true below.
ARG PII_GUARD_EXTRAS="ocr local-vision sam"
# The NER (torch + transformers) is a core dependency (LAB-1733), but this base image stays
# rules-only and inside its size budget (LAB-1192): these packages are skipped, so the default
# stack falls back to rules. The list is the NER packages plus the dependencies only they pull
# in (nothing else in the image imports them; `uv tree --no-dev` shows the graph). The demo
# image (compose.yaml, profile demo) sets this empty for fast mode with the NER; its model is
# fetched at run time into a volume, never baked in.
ARG PII_GUARD_SKIP_PACKAGES="torch transformers sentencepiece protobuf tokenizers safetensors \
sympy mpmath networkx setuptools jinja2 markupsafe filelock fsspec \
huggingface-hub hf-xet httpx2 httpcore2 truststore pyyaml regex tqdm \
typer rich markdown-it-py mdurl pygments shellingham"

# Dependencies first, so code changes don't invalidate this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev $(for e in $PII_GUARD_EXTRAS; do printf -- '--extra %s ' "$e"; done) \
        $(for p in $PII_GUARD_SKIP_PACKAGES; do printf -- '--no-install-package %s ' "$p"; done) \
        --no-install-project

COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev $(for e in $PII_GUARD_EXTRAS; do printf -- '--extra %s ' "$e"; done) \
        $(for p in $PII_GUARD_SKIP_PACKAGES; do printf -- '--no-install-package %s ' "$p"; done) \
        --no-editable

# Only Meta models run by default (ADR 0015, LAB-1795), so the non-Meta on-device engines are
# opt-in: --build-arg PII_GUARD_ON_DEVICE_VISION=true fetches the YuNet model (0.23 MB, MIT,
# OpenCV model zoo) from its pinned URL and checks its pinned SHA-256
# (pii_guard.visual.segment.YUNET); the build fails on a mismatch. Run such an image with
# PII_GUARD_SEGMENTER=hybrid or local to use it. (The YOLOS-tiny signature detector needs torch,
# which this rules-only base image skips; Dockerfile.hosted has the same build argument.)
ARG PII_GUARD_ON_DEVICE_VISION=false
RUN mkdir -p /app/models \
    && if [ "$PII_GUARD_ON_DEVICE_VISION" = "true" ]; then \
        PII_GUARD_MODEL_DIR=/app/models /app/.venv/bin/python -m pii_guard.visual.segment fetch; \
    elif [ "$PII_GUARD_ON_DEVICE_VISION" != "false" ]; then \
        echo "PII_GUARD_ON_DEVICE_VISION must be true or false" >&2; exit 1; \
    fi

# --- runtime: Python and the virtualenv (Tesseract opt-in), as a non-root user -
FROM python:3.12-slim-trixie AS runtime
# The base can lag trixie-security: zlib1g 1.3.1-1+b1 carries CVE-2026-85091 and CVE-2026-76844
# (LAB-2349), which the CI Trivy scan fails on. Take the fix until the base image ships it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade zlib1g \
    && rm -rf /var/lib/apt/lists/*

# The text in images (a TAJ, a name) is read by Muse Spark Open by default (ADR 0016,
# PII_GUARD_OCR_ENGINE=muse), which receives the unmasked image. Tesseract is not a Meta model,
# so it is opt-in: --build-arg PII_GUARD_TESSERACT=true installs it with the Hungarian, English
# and German packs (the language packs, docs/languages.md; ~115 MB). Run such an image with
# PII_GUARD_OCR_ENGINE=tesseract to use it.
ARG PII_GUARD_TESSERACT=false
RUN if [ "$PII_GUARD_TESSERACT" = "true" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends \
            tesseract-ocr tesseract-ocr-osd tesseract-ocr-eng tesseract-ocr-hun tesseract-ocr-deu \
        && rm -rf /var/lib/apt/lists/*; \
    elif [ "$PII_GUARD_TESSERACT" != "false" ]; then \
        echo "PII_GUARD_TESSERACT must be true or false" >&2; exit 1; \
    fi

RUN groupadd --system --gid 10001 piiguard \
    && useradd --system --uid 10001 --gid piiguard --no-create-home piiguard \
    && install -d -m 0700 -o piiguard -g piiguard /var/lib/pii-guard/projects

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
    PII_GUARD_PROJECT_STATE_PATH=/var/lib/pii-guard/projects/state.sqlite3 \
    PII_GUARD_MODEL_DIR=/app/models

WORKDIR /app
USER piiguard
EXPOSE 8787

# Healthy = /healthz answers, and Tesseract is present when it is the configured OCR engine
# (or OCR is explicitly not required): the OCR state comes from /healthz itself ("ocr",
# "ocr_engine", "image_require_ocr"), so the check needs no app import. A missing Muse OCR key
# is a configuration gap (/v1/status images.gaps "ocr_key", like the SAM key), not an
# unhealthy container: images are refused, text works. Prints "ocr <engine> on|off".
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import json, os, sys, urllib.request; r = json.load(urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PII_GUARD_PORT']}/healthz\", timeout=2)); print('ocr', r.get('ocr_engine'), r.get('ocr')); sys.exit(0 if r.get('ocr') == 'on' or r.get('ocr_engine') == 'muse' or not r.get('image_require_ocr', True) else 1)"]

CMD ["pii-guard", "serve"]
