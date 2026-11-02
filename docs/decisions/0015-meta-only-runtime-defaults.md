# 0015. Meta-only runtime defaults: SAM 3.1 for images, no non-Meta model unless configured

- **Status:** accepted
- **Date:** 2026-11-02
- **Overrides:** [ADR 0014](0014-hosted-local-images.md): "hosted never SAM", and its amendment
  saying hosted images use the on-device segmenter only
- **Builds on:** [ADR 0006](0006-fail-closed.md)
- **Ticket:** LAB-1795

## Context

On 2026-11-02 the Meta hackathon organisers ruled that only Meta models may run at runtime.
Any non-Meta model that runs in the project is not allowed. By default PII Guard ran three
non-Meta models:

- **YuNet** (OpenCV model zoo, MIT) for faces and ID photos: the self-hosted default `hybrid`
  segmenter, and hosted's `local` one;
- the **YOLOS-tiny** signature detector (`mdefrance/yolos-tiny-signature-detection`,
  Apache-2.0) on hosted, and on self-hosted `hybrid` without a SAM key;
- the **public fallback NER** (`bardsai/eu-pii-anonimization-multilang`), used when the
  published fine-tune of Meta's XLM-RoBERTa can't be had (`PII_GUARD_NER_FALLBACK=download`
  was the default).

SAM 3.1, a Meta model, already does all three image jobs (`PII_GUARD_SEGMENTER=sam-api`,
`pii_guard.visual.sam`). It ran by default before LAB-1245 made `hybrid` the default.

## Decision

The owner decided that the defaults are Meta-only. The non-Meta engines stay configurable and
are off by default.

- **Images, self-hosted and hosted:** `PII_GUARD_SEGMENTER` defaults to `sam-api`, so SAM 3.1
  on the Meta Model API finds faces, ID photos, signatures and stamps. `hybrid` and `local`
  still work when set explicitly.
- **Hosted** accepts `sam-api` (the default) or `local` (opt-in). It refuses `hybrid` and `off`
  at startup, as before. The SAM key is the same Key Vault Meta key the sponsored route already
  uses (`PII_GUARD_SAM_API_KEY` from the `meta-key` secret). Readiness fails without it. Hosted
  project policies do not choose their detection: the hosted API stores
  `visual_detection: local` only, so the operator's segmenter serves every policy.
- **Self-hosted project policies:** a policy with `visual_detection: local` asks for the
  on-device engines. On a `sam-api` server (the default) its images are refused. They are not
  sent to SAM instead, because the policy asked for no egress. On a `hybrid` or `local` server,
  which has opted in, it works as before.
- **NER:** `PII_GUARD_NER_FALLBACK` gains `published`, the new default. The published
  checkpoint is still fetched on first use, and the public fallback is never used. When there
  is no published model, fast mode runs rules only and the startup line says so. `download`
  (the old default) opts back in to the fallback. `cached` and `off` keep their meaning.
- **Docker:** neither `Dockerfile` nor `Dockerfile.hosted` fetches YuNet or YOLOS-tiny by
  default. `--build-arg PII_GUARD_ON_DEVICE_VISION=true` bakes them in. The hosted image runs
  with `PII_GUARD_SEGMENTER=sam-api`.

**Fail closed (ADR 0006) is unchanged.** If SAM is not configured, or a SAM call fails, the
image is refused (`503`). On hosted, the replica is not ready. Nothing falls back silently to
a non-Meta model. The one existing silent switch, `hybrid` using YOLOS-tiny for signatures
without a SAM key, applies only when `hybrid` was configured.

## Consequences

- **Data boundary.** With the defaults, every image's original pixels go to the Meta Model API
  (or to the operator's `PII_GUARD_SAM_URL`). On self-hosted this was already the case for
  signatures under `hybrid`. On hosted it is new: ADR 0014's "no image leaves the process" no
  longer holds by default, and owners must be told before they upload. Text is unchanged:
  rules and the NER still run in the container, and only masked text goes upstream.
- **Cost.** `sam-api` sends one SAM request per prompt: 5 per image with the default policies
  (`face`, `signature`, `squiggly line`, `photo of a person`, `stamp`), against 2 under
  `hybrid`. On hosted, the per-owner and global daily image counts
  (`PII_GUARD_HOSTED_USER_IMAGES_PER_DAY`, `PII_GUARD_HOSTED_GLOBAL_IMAGES_PER_DAY`) bound the
  SAM spend. No separate per-image SAM reservation exists yet.
- **Quality and latency.** On the 65 specimens, SAM 3.1 alone leaks 47.7 % of portraits against
  `hybrid`'s 10.8 %, at about twice the latency (p50 7.9 s against 4.1 s). Signatures are the
  same (`docs/models.md`, *Hybrid vs SAM-only*). That cost was accepted to comply with the rule.
  `hybrid` stays one setting away for deployments the rule does not bind.
- **Offline stacks.** A stack without a SAM key refuses images, as the CI smoke stacks do by
  contract (LAB-1255: an emptied `PII_GUARD_SAM_API_KEY` disables SAM). Tests that exercise the
  on-device engines set the segmenter explicitly.
- **OCR** is not part of this decision. Tesseract is not a Meta model. LAB-1796 covers it.
