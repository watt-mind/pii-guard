# syntax=docker/dockerfile:1

# --- build: resolve dependencies and install the project into /app/.venv -----
FROM ghcr.io/astral-sh/uv:0.13.5-python3.12-trixie-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Dependencies first, so code changes don't invalidate this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# --- runtime: just Python and the virtualenv, as a non-root user ------------
FROM python:3.12-slim-trixie AS runtime

RUN groupadd --system --gid 10001 piiguard \
    && useradd --system --uid 10001 --gid piiguard --no-create-home piiguard

COPY --from=build --chown=piiguard:piiguard /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PII_GUARD_HOST=0.0.0.0 \
    PII_GUARD_PORT=8787

WORKDIR /app
USER piiguard
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PII_GUARD_PORT']}/healthz\", timeout=2)"]

CMD ["pii-guard", "serve"]
