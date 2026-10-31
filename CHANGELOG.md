# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Planned as the first tagged release, `0.1.0` (the version in `pyproject.toml`). Nothing is
tagged or published yet; move these entries under `## [0.1.0] - <date>` when the tag is pushed.

### Added

- **Reverse PII Masking Gateway**:
  - OpenAI-compatible (`/v1/chat/completions`, `/v1/responses`) and Anthropic-compatible (`/v1/messages`) reverse proxy with SSE streaming re-identification and request/response masking.
  - Pseudonym vault with placeholders derived from a keyed HMAC-SHA256, in memory or persisted, so detected values are replaced before anything reaches the upstream LLM provider.
  - Fail-closed security architecture stopping requests when detection or masking cannot complete safely.
  - Mock upstream mode (`--mock`) enabling local offline development and demonstrations without third-party API keys.
- **Multi-Model Detection Engine**:
  - Deterministic rules and checksum validators for European national identifiers (tax numbers, TAJ, PESEL, IBAN, payment cards).
  - Language pack system with initial coverage for English (`en`), German (`de`), and Hungarian (`hu`), including inflection handling.
  - On-device Named Entity Recognition (NER) with fast CPU-optimized inference.
  - Pluggable OCR (`pytesseract`) and on-device face detection (`local-vision` / YuNet) for image redaction.
- **Unified Single-Process Console (`pii-guard up`)**:
  - Interactive web console bundled directly into the distribution wheel and served on port 8787.
  - Interactive playground, live traffic viewer, masking scorecard, and audit inspector.
- **Agent Integrations & CLI**:
  - One-command integration via `pii-guard connect` for coding agents: Muse Code, pi, Codex, and OpenCode, with Anthropic `/v1/messages` proxying for Claude Code.
  - Direct execution via `uvx wattmind-pii-guard` and `uvx --from wattmind-pii-guard pii-guard`.
- **Packaging & Delivery**:
  - Tag-driven release workflow (`.github/workflows/release.yml`) for PyPI as `wattmind-pii-guard` via OIDC Trusted Publishing and for container images on `ghcr.io/watt-mind/pii-guard`, behind a CI provenance gate.
  - Size-budgeted wheel builds with automated isolated smoke tests (`scripts/ci/wheel_smoke.sh`).

[Unreleased]: https://github.com/watt-mind/pii-guard/commits/develop
