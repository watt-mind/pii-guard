# Execution Record & Roadmap

> Status: execution record. Dated PR and benchmark records live in [journey.md](journey.md).

## Hackathon Execution: October 26 – November 4, 2026

Submission deadline: **November 4, 21:00 ET** (03:00 Budapest time on November 5).

Dated milestones, with before/after metrics, are in [journey.md](journey.md); the original 9-day
plan is kept in git history.

### Key Architectural Pivot: Teacher–Student Distillation over LLM Request-Path Fine-Tuning

Our initial Day-1 plan envisioned fine-tuning a small Llama model to run as a second-pass
request-path detector on Days 4–5. During execution on Days 1–2, measurements changed the
design:

1. **Latency & Self-Hosting Constraint:** Even a small generative LLM on the synchronous
   request path adds hundreds of milliseconds to seconds of latency and requires a GPU
   endpoint, whereas an enterprise privacy gateway must run inline on standard CPU
   infrastructure with zero data leaving the boundary.
2. **Distilling Meta Muse Glimmer 30B into XLM-RoBERTa Base:** Zero-shot **Meta Muse Glimmer
   30B** achieved **99.3% F1 and 0.0% leak** on our Hungarian + English smoke benchmark, but
   took 9.4 s p50 on an H100. Instead of putting a generative LLM on the hot path, we used
   **Muse Spark 1.3** to generate a synthetic multilingual corpus, labeled it with **Muse
   Glimmer 30B**, combined it with curated multilingual PII sets and synthetic hard negatives,
   and distilled the knowledge into a lightweight **XLM-RoBERTa base** encoder
   ([`watt-mind/pii-guard-ner-xlmr-base`](https://huggingface.co/watt-mind/pii-guard-ner-xlmr-base)
   `v4.2`).
3. **Result:** Fast mode (`rules + distilled NER v4.2`) achieves **0.0% leak** and **1.3%
   over-masking** across the 62-document hand-written test set (`hu`, `en`, `de`, `pl`) with
   **43 ms p50 of NER time per message on CPU** and **$0 inference cost**. **Muse Spark Open** remains available in
   opt-in `audit` mode for offline quality checks and red-team evaluation
   ([models.md](models.md)).

## Verified Readiness Checks

- [x] **Meta Model API access & tiers verified:** Tested with live calls on fictional text;
      **Muse Spark 1.3** used for synthetic corpus generation ($1.05 for 5,004 billed calls)
      and downstream gateway demos ([models.md](models.md)).
- [x] **Partner credits activated & metered (Baseten, Modal):** Baseten Model APIs ($100
      credit) used for **Muse Spark Open** (`meta-models/muse-spark-open-1026`) audit-mode
      evaluation and red-teaming; Modal GPU credits used for Muse Glimmer 30B teacher
      labeling and XLM-RoBERTa student training (costs per milestone in [journey.md](journey.md)).
- [x] **Multilingual NER baseline selected & distilled:** Evaluated zero-shot encoders and
      shipped our own distilled checkpoint (`watt-mind/pii-guard-ner-xlmr-base` `v4.2`,
      Apache-2.0) with SHA-256 weight verification ([models.md](models.md#ner-detector)).
- [x] **SAM 3.1 weights, license & hybrid visual pipeline verified:** Integrated **Meta SAM
      3.1** with `meta-sam-parser` (SAM License) for signature segmentation alongside local
      CPU **YuNet** face detection and **Tesseract OCR** ([eval/results/visual/specimens.md](../eval/results/visual/specimens.md)).
- [x] **Language pack architecture & conformance suite shipped:** Shipped 4 built-in packs
      (`hu`, `en`, `de`, `pl`) with inflection matchers, checksum rules, and `pii-guard lang
      check` conformance gates ([languages.md](languages.md)).
- [x] **Open-source compliance & synthetic-only guarantee enforced:** Apache-2.0 repository
      license ([ADR 0004](decisions/0004-apache-2-license.md)), strict synthetic-data-only
      policy ([ADR 0005](decisions/0005-synthetic-data-only.md)), and automated dataset
      decontamination gates in CI ([datasets.md](datasets.md)).

## Post-Hackathon Roadmap

- **Full EU-24 Language Pack Rollout:** Expand deterministic rule, national-ID checksum, and
  morphological inflection packs beyond `hu`, `en`, `de`, and `pl` to all 24 official EU
  languages, building on the completed EU-24 data and identifier audit
  ([data-sources-eu24.md](data-sources-eu24.md), [training-data-eu-phase1.md](training-data-eu-phase1.md)).
- **Enterprise Encrypted Distributed Vault:** Add an optional Redis / PostgreSQL AEAD-encrypted
  session mapping store with per-tenant envelope keys and automatic TTL eviction so horizontal
  multi-instance gateway deployments can share session state without sticky routing.
- **Quasi-Identifier & Contextual Re-Identification Defense:** Extend detection beyond direct
  identifiers to rare attribute combinations (job title + small town + rare diagnosis) that
  enable indirect re-identification, informed by our automated red-team exposure harness
  ([why-pii-guard.md](why-pii-guard.md#7-honest-about-re-identification)).
- **True PDF Structural Redaction:** Rewrite PDF content streams and strip underlying text/font
  objects on export so redacted documents are safe for external distribution, not only visual
  rendering.
- **Standalone Open Benchmark & Leaderboard Package:** Publish the synthetic multilingual PII
  leak, inflection-consistency, and agent-traffic evaluation suites as a standalone package for
  reproducible comparison across privacy tools.
