# 0002. Start from a clean room

- **Status:** accepted
- **Date:** 2026-10-26

## Context

The author has worked on PII masking before, in internal, non-public code. That code was
designed for one product, carries its assumptions and history, and is not licensed for
publication.

## Decision

pii-guard is a fresh implementation. No code, fixtures, configuration or history is copied
from earlier internal work. Knowledge and lessons learned may be reused; artifacts may not.

## Consequences

- The repository can be published under Apache-2.0 without a provenance audit of imported
  code.
- Nothing in this repository depends on, or refers to, a specific downstream product.
  Integrations are configuration on the consumer's side.
- Some problems already solved elsewhere are solved again here, deliberately, with tests and
  measurements from the start.
