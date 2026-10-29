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

## Note: OCR for images (2026-10-27, LAB-1209)

An image whose text can't be read is an unchecked input: without Tesseract a card with a TAJ
reached the upstream readable, with `200` and `X-PII-Guard-Image-OCR: off`, and that was the
default Docker deployment. Now the image ships Tesseract (`hun`/`eng`/`deu`), and without an
OCR engine image parts are refused with `503 ocr_unavailable` (gateway and `/v1/mask/image`).
`PII_GUARD_IMAGE_REQUIRE_OCR=false` is an explicit, documented opt-out to SAM-only masking:
the image is still masked (faces, signatures), but its text is not checked, and the response
says so (`X-PII-Guard-Image-OCR: off`). The container healthcheck fails while OCR is required
and unavailable.

## Note: the outbound re-check (2026-10-29, LAB-1500)

Every error path above blocks a request that could not be masked. One more check closes the
case where masking ran without error and still left a value: after masking, the gateway reads
the masked request again and searches it for every value its vault session holds, with the
vault's own occurrence patterns. A value found there refuses the request with
`422 outbound_check_failed` (types and counts only, `X-PII-Guard-Outbound-Check: blocked`) and
nothing is sent; a request that passes says `passed`. Values too short to tell from common
tokens are counted but do not block; the policy is in
[architecture-gateway.md](../architecture-gateway.md#outbound-re-check).
