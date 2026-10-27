# syntax=docker/dockerfile:1

# --- build: resolve dependencies and install the project into /app/.venv -----
FROM ghcr.io/astral-sh/uv:0.13.5-python3.12-trixie-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Dependencies first, so code changes don't invalidate this layer. The `ocr` extra
# (pytesseract) reads the text in images; without it image parts are refused (ADR 0006).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --extra ocr --no-install-project

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra ocr --no-editable

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

# 0.0.0.0 inside the container: publish the port on 127.0.0.1 only (compose.yaml does). The API
# has no authentication unless PII_GUARD_API_TOKEN is set (docs/operations.md, Exposure).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PII_GUARD_HOST=0.0.0.0 \
    PII_GUARD_PORT=8787

WORKDIR /app
USER piiguard
EXPOSE 8787

# Healthy = /healthz answers and OCR is available (or explicitly not required); prints "ocr on|off".
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, sys, urllib.request; from pii_guard.visual.ocr import tesseract_available as t; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PII_GUARD_PORT']}/healthz\", timeout=2); ok = t(); print('ocr', 'on' if ok else 'off'); sys.exit(0 if ok or os.environ.get('PII_GUARD_IMAGE_REQUIRE_OCR', 'true').lower() in ('false', '0', 'no', 'off') else 1)"]

CMD ["pii-guard", "serve"]
