# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-11-02

### Added

- Language packs for French, Spanish, Italian, Dutch and Romanian, each with rules, an allowlist
  and per-language smoke builders (LAB-1774, LAB-1775, LAB-1776, LAB-1777, LAB-1778, LAB-1779,
  LAB-1773).
- Escalate mode (opt-in): Muse Spark Open settles only the spans fast mode is unsure about
  (LAB-1766).
- `pii-guard run` shows how to open the web console (LAB-1771).

### Changed

- Meta-only runtime defaults (ADR 0015, ADR 0016): images use SAM 3.1 for faces, ID photos and
  signatures (`segmenter=sam-api`), and Muse Spark Open reads the text in images
  (`ocr_engine=muse`). YuNet and Tesseract stay available as opt-in engines; without the SAM or
  OCR key, images are refused rather than forwarded unchecked (LAB-1795, LAB-1796).
- The NER falls back to the published model, `watt-mind/pii-guard-ner-xlmr-base` (LAB-1795).
- Placeholder-labelled image masks: overlapping covers share one light border, each label sits in
  its own band with a hairline between stacked fields, and a stack shares one font size
  (LAB-1804).
- Packaging: CPU PyTorch on Linux and a rules-only install on Intel macOS, both covered by the
  judge-path check (LAB-1743).

### Fixed

- The post-publish smoke waits for the PyPI simple index, not the JSON API (LAB-1752).
- The judge-path macOS job runs on macOS 15; macOS 14 runners are retired (LAB-1782).

### Security

- Hardened gateway and local privacy controls (LAB-1753).

## [0.1.1] - 2026-11-01

### Added

- Judge-path check (LAB-1741): before a release is published, the wheel is installed with a fresh
  uv cache on Linux and macOS and must serve the web console, load the NER, mask and restore a
  request and accept an image; after the PyPI upload the published version is checked the same way.

### Changed

- OCR (`pytesseract`) and on-device vision (`opencv-python-headless`) are core dependencies, so
  `uvx --from wattmind-pii-guard pii-guard up` masks images without extras (#458).
- The README quickstart installs the PyPI wheel, which bundles the web console (LAB-1740).

### Fixed

- Hungarian triple-consonant names (`Mustermann` + `-nak` is written `Mustermannak`) are masked
  and restored without a stray letter, and short names such as `Ann` no longer mask words like
  `annak` (#458, LAB-1737).
- Coding-agent harness and local demo fixes for all five supported agents (#456).

## [0.1.0] - 2026-10-31

First tagged release.

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


### Changed

- The on-device NER is installed by default (LAB-1733): `torch`, `transformers` (>= 5.21), `sentencepiece` and `protobuf` are core dependencies, so `uvx wattmind-pii-guard` and `pii-guard up` run rules + NER without `[ner]`. The `ner` extra stays as an empty alias for existing commands.
- The base Docker image stays rules-only and inside its size budget: it skips the NER packages (`PII_GUARD_SKIP_PACKAGES`). The compose demo image and the hosted image keep them.

### Removed

- The `gliner` extra and the `[tool.uv] conflicts` it needed (`gliner` pins `transformers < 5.17`). The GLiNER comparison (LAB-1150) can be reproduced from commit `13e2aaf` or earlier.

[Unreleased]: https://github.com/watt-mind/pii-guard/compare/v0.2.0...develop
[0.2.0]: https://github.com/watt-mind/pii-guard/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/watt-mind/pii-guard/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/watt-mind/pii-guard/releases/tag/v0.1.0
