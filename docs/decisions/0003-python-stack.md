# 0003. Python 3.12, uv and FastAPI

- **Status:** accepted
- **Date:** 2026-10-26

## Context

Most of the work is model-adjacent: NER, OCR, image segmentation, fine-tuning data preparation
and evaluation. Those ecosystems are Python-first. The gateway also needs solid async HTTP and
streaming support.

## Decision

- **Python 3.12**, packaged with **uv** (`pyproject.toml`, `uv.lock`).
- **FastAPI** + **httpx** for the API and the gateway, including streaming (SSE).
- **pytest** for tests, **ruff** for linting and formatting.
- A `src/` layout with the package `pii_guard` and a `pii-guard` CLI entry point.

## Consequences

- One language for detection, gateway and evaluation, so the eval harness can call the same
  code paths the gateway uses.
- A demo UI, if built, may use a separate web stack under its own directory; the core stays
  Python.
- Gateway throughput is bounded by Python; acceptable for the hackathon, revisit if latency
  measurements say otherwise.
