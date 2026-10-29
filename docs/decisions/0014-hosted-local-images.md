# 0014. Hosted image masking for signed-in owners, local and in memory only

- **Status:** accepted
- **Date:** 2026-10-28
- **Amends:** [ADR 0011](0011-hosted-saas.md) (hosted images were disabled),
  [ADR 0013](0013-one-console-owner-scoped-api.md) (hosted `images` capability)
- **Builds on:** [ADR 0006](0006-fail-closed.md)
- **Amended:** 2026-10-29 (LAB-1444): on-device signatures; visual actions in project policies

## Context

Image masking (`POST /v1/mask/image`) is a self-hosted differentiator, and the hosted console
should offer the same sections. ADR 0011 kept hosted images off: the hosted body limit is
text-sized, and the self-hosted default segmenter (`hybrid`) sends the original image to SAM
3.1 on the Meta API for signatures, a remote processor of originals with its own cost that
the hosted sponsored accounting does not reserve. A remote LLM detector would see originals
too.

## Decision

**Who.** Signed-in Google owners only, through the hosted middleware's allow-list, on
`POST /v1/mask/image`. Guests, guard API keys, endpoint keys and
`/e/<endpoint>/...` paths are refused. Origin/CSRF checks are unchanged. The vault is the
owner's runtime vault, so another owner's session id is `404`, and text and image placeholders
are shared within the owner's session.

**Where.** On the replica only: the built-in Tesseract (`eng`, `hun`, `deu`, `pol`, `osd` in
`Dockerfile.hosted`), the on-device segmenter (YuNet, `local-vision`) and, since LAB-1444, the
pinned YOLOS-tiny signature detector (see *Amendment* below). Hosted mode builds
the segmenter as `local` regardless of `PII_GUARD_SEGMENTER`, and refuses to start when that
setting names anything else or `PII_GUARD_IMAGE_REQUIRE_OCR=false`. Any other segmenter or OCR
object found on the app is refused (`detection_profile_denied`). Hosted detectors were already
limited to local rules and NER. No image leaves the process, so no image spend allocation exists
and none is needed.

**Signatures.** The on-device segmenter finds faces and ID photos, not signatures or stamps.
Project policies hold text types only, so the visual policies are the operator's
(`PII_GUARD_POLICY_OVERRIDES`). While the server masks a type the segmenter can't find, every
image is refused before work (fail closed) and `images` is not offered. The Azure release sets
`SIGNATURE=keep`: signatures stay visible, which the Images screen discloses.

**Bounds before work.** A separate ingress limit sized for a base64 image
(`PII_GUARD_HOSTED_MAX_IMAGE_BYTES`, default 4 MiB decoded) while text routes keep the text
limit; PNG/JPEG sniffed from the bytes (`415` otherwise); a decoded pixel cap of the lower of
`image_max_pixels` and `PII_GUARD_HOSTED_IMAGE_MAX_PIXELS` (8 MP); one image job per replica,
a busy or still-finishing slot answering `429 hosted_capacity` instead of queueing; a deadline
of the lower of `image_timeout` and `PII_GUARD_HOSTED_IMAGE_TIMEOUT` (60 s). The middleware
reserves a fixed compute charge plus one from a separate per-owner daily image count
(`PII_GUARD_HOSTED_USER_IMAGES_PER_DAY`, global `PII_GUARD_HOSTED_GLOBAL_IMAGES_PER_DAY`)
before the route runs; the token allowance never covers images, guests have no image
allowance, and unavailable accounting denies the request. Charges are never refunded.

**Memory only.** The original image is never written or logged; the route logs region counts
only, error messages carry no values, and responses are `no-store`. The masked image, its
value-free region list and the owner's session mappings are all that remain, in memory, under
the ADR 0011 retention rules (owner purge or restart frees them).

**Readiness.** With `PII_GUARD_HOSTED_IMAGES=true` (the default), `/readyz` fails unless
Tesseract and the on-device segmenter are available, so a replica that would refuse images is
not admitted. `PII_GUARD_HOSTED_IMAGES=false` turns the route, the capability and the readiness
requirement off.

**Capability.** `/v1/status` reports hosted `images: true` while images are on and servable;
the hosted projection still drops the image pipeline's internals.

## Not in this decision

Gateway image parts in hosted chat stay off (`max_images=0`): an image sent upstream to a
sponsored or BYOK model needs its own provider cost reservation and a body limit for chat, and
the token allowance must not stand in for it. API-key image access is also left for a later,
separately reviewed change.

## Consequences

Hosted owners can mask images without any remote processor of originals. Signatures are not
covered on hosted; owners who need them covered use self-hosting with SAM. OCR makes the image
larger and a cold start slower; the container size (2 vCPU, 4 GiB) is unchanged since only one
image is processed at a time. A deployment smoke of OCR and readiness is still required before
public enablement.

## Amendment (2026-10-29, LAB-1444): signatures on-device, visual actions per project policy

The segmentation benchmarks (LAB-1229, `docs/models.md`) measured YuNet plus a YOLOS-tiny
signature detector at 0.7 s p50, free and with no egress, against SAM 3.1 hybrid at 2.5 s p50 and
about $0.005 per image with the original image sent to Meta. The owner decided that visual
detection is configured per project policy and that SAM is opt-in.

- **Signatures are masked on the replica.** `Dockerfile.hosted` ships
  `mdefrance/yolos-tiny-signature-detection` (Apache-2.0, 26 MB, safetensors only) at a pinned
  revision, each file checked against its pinned SHA-256 and loaded once at build time; the
  runtime loads it offline. Readiness loads it while the server's own policies mask signatures.
  The release no longer sets `PII_GUARD_POLICY_OVERRIDES=SIGNATURE=keep`.
- **Project policies hold visual actions.** `FACE`, `ID_PHOTO`, `SIGNATURE` and `STAMP` are
  `mask` or `keep` in `entity_policies`, versioned like text types. The operator's explicit
  overrides still win when stricter. Versions saved before this amendment take the server's
  visual actions. Stamps cannot be found on the replica, so a policy that masks them refuses
  images before work.
- **`visual_detection`** is `local` (default) or `sam`. Hosted accepts `local` only for now:
  `sam` on hosted needs a per-image SAM spend reservation inside the daily image cap, the Meta
  key from Key Vault and a pre-upload disclosure that the original goes to Meta. That is a
  separately reviewed follow-up; until then no hosted image leaves the process.

This replaces the *Signatures* paragraph above: hosted owners now get signatures masked without
any remote processor.
