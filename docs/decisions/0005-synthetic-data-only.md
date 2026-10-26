# 0005. Synthetic data only

- **Status:** accepted
- **Date:** 2026-10-26

## Context

A PII tool needs realistic test data, and the most realistic data is real documents. Using
them would put personal data into the repository, the issue tracker, CI logs and training
runs, which is exactly the harm the project exists to prevent.

## Decision

- All fixtures, evaluation data and fine-tuning data are **synthetic**: fictional identities
  from a seeded generator, documents written around them by a model.
- **No real personal data** may be committed, attached to issues, pasted into pull requests,
  or used to train or tune detectors. Bugs found on real documents are reproduced with
  synthetic ones.
- Generated data that is committed lives under `eval/fixtures/`; working data is gitignored.

## Consequences

- The benchmark can be published openly.
- Synthetic data can miss patterns that only occur in real documents. We mitigate this with a
  hand-written hard-case set and by encouraging users to report *patterns* (not documents)
  that the detectors miss.
