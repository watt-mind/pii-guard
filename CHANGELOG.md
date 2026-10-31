# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

## [0.1.0] - 2026-10-31

Initial open-source release of PII Guard (`wattmind-pii-guard`).

### Added

- **Reverse PII Masking Gateway**:
  - OpenAI-compatible reverse proxy with SSE streaming re-identification and request/response masking.
  - In-memory and persisted HMAC-SHA256 pseudonym vault ensuring zero raw PII leaks to upstream LLM providers.
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
  - One-command integration via `pii-guard connect` for coding agents: Codex, Claude Code, OpenCode, and Pi.
  - Direct execution via `uvx wattmind-pii-guard` and `uvx --from wattmind-pii-guard pii-guard`.
- **Packaging & Delivery**:
  - Python package published to PyPI as `wattmind-pii-guard` via GitHub Actions OpenID Connect (OIDC) Trusted Publishing.
  - Container images published to GitHub Container Registry (`ghcr.io/watt-mind/pii-guard`).
  - Size-budgeted wheel builds with automated isolated smoke tests (`scripts/ci/wheel_smoke.sh`).

[Unreleased]: https://github.com/watt-mind/pii-guard/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/watt-mind/pii-guard/releases/tag/v0.1.0
