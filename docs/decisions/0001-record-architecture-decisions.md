# 0001. Record architecture decisions

- **Status:** accepted
- **Date:** 2026-10-26

## Context

pii-guard makes decisions that are hard to reverse and matter for safety: how pseudonyms are
derived, what happens on errors, what data may enter the repository. Contributors and agents
need to know *why* these choices were made before changing them.

## Decision

Significant decisions are recorded as short ADRs in `docs/decisions/`, numbered sequentially,
with Status, Date, Context, Decision and Consequences. An ADR is never edited to reverse it; a
new ADR supersedes it and the old one is marked `superseded by NNNN`.

## Consequences

- Every change to a non-negotiable in `AGENTS.md` needs an ADR.
- The index in `docs/INDEX.md` lists every ADR.
