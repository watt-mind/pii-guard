# 0006. Fail closed

- **Status:** accepted
- **Date:** 2026-10-26

## Context

In a privacy gateway, the dangerous failure is not an error, it is a request that goes through
unmasked because a detector timed out, a model endpoint was down, or a file type was not
understood. "Retry without masking" fallbacks are tempting during development and
catastrophic in production.

## Decision

Every error path blocks the outbound request:

- extraction, detection, masking or re-identification errors → the request is rejected with an
  explicit error code, nothing is sent upstream;
- timeouts count as errors;
- unsupported content types are rejected, not passed through;
- there is no configuration flag that forwards unmasked data. A deployment that wants no
  masking should not route through pii-guard.

## Consequences

- Availability of pii-guard and its model endpoints directly affects availability of the
  application. Health checks and readiness must reflect model availability.
- Tests must cover each failure path and assert that nothing reached the upstream.
