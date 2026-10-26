# 0004. Apache-2.0 license

- **Status:** accepted
- **Date:** 2026-10-26

## Context

pii-guard should be easy for companies to adopt, including inside proprietary products,
because a privacy layer helps most when it is widely used. It also includes code that may be
subject to patents in the detection and masking space.

## Decision

The project is licensed under **Apache-2.0**.

## Consequences

- Permissive use, including in closed-source products, with an explicit patent grant.
- Contributions are accepted under the same license (inbound = outbound).
- Model weights and datasets used by the project keep their own licenses; `docs/models.md`
  must list them before release.
