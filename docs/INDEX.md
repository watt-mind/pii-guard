# Documentation Portal

Welcome to the **PII Guard** documentation (`v0.1.0`). Use the audience-oriented sections below
to navigate the hackathon evaluation materials, developer integration guides, system
architecture, benchmarks, and operational runbooks.

---

## 1. Hackathon Submission & Walkthrough

*Start here if you are evaluating PII Guard for the Meta Hackathon: evidence-backed claims,
repeatable walkthrough steps, and the submission narrative.*

| Document | What it covers |
|---|---|
| [why-pii-guard.md](why-pii-guard.md) | 13 core differentiators, with every metric and status linked to committed run records and tests |
| [submission.md](submission.md) | Hackathon submission text, tagline, Meta model usage summary, and verification links |
| [demo-story.md](demo-story.md) | Repeatable judge walkthrough, hosted vs. self-hosted boundaries, and recorded visual fallback |
| [demo-script.md](demo-script.md) | Shot list and voice-over for the 3-minute submission video, citing the source of every number spoken |
| [vision.md](vision.md) | The problem statement, target users, core design goals, and explicit non-goals |

## 2. Using & Integrating PII Guard

*Guides for pointing OpenAI-compatible SDKs, CLI coding harnesses, and custom applications at
the PII Guard gateway or REST endpoints.*

| Document | What it covers |
|---|---|
| [architecture-gateway.md](architecture-gateway.md) | Gateway modes (`fast` vs. `audit`), session continuity, traffic inspection, and streaming re-identification |
| [integrations.md](integrations.md) | Connect an application: base URLs, endpoint keys, runnable `curl` and Python/TypeScript SDK examples, and image masking |
| [integrations/README.md](integrations/README.md) | Client harness guides and compatibility matrices for Claude Code, Codex, OpenCode, `pi`, and Muse Code |
| [api.md](api.md) | Direct REST & OpenAI-compatible API guide (`/v1/analyze`, `/v1/mask`, `/v1/unmask`, `/v1/chat/completions`), auth tokens, and error codes; interactive spec at [guard.watt-mind.com/#api](https://guard.watt-mind.com/#api) ([openapi.json](openapi.json)) |
| [projects.md](projects.md) | Multi-project management, immutable policy versions, endpoint keys (`pg_ep_...`), and persistence boundaries |
| [entities.md](entities.md) | Entity taxonomy: personal data categories, structured identifiers, and per-language coverage (`hu`, `en`, `de`, `pl`) |

## 3. System Architecture, Privacy & Regulation

*Deep dives into module boundaries, cryptographic pseudonymization, threat modeling, and EU
regulatory alignment.*

| Document | What it covers |
|---|---|
| [architecture.md](architecture.md) | Implemented `v0.1.0` specification: `documents`, `detect`, `visual`, `vault`, `gateway`, `api`, and resolved architectural decisions |
| [privacy-model.md](privacy-model.md) | Threat model, trust boundaries, what PII Guard guarantees, and residual risks (including indirect re-identification) |
| [eu-regulation.md](eu-regulation.md) | EU regulatory context: GDPR pseudonymization, cross-border transfers, sector rules, and the EU AI Act mapped to primary sources |
| [contracts.md](contracts.md) | Public interfaces between internal modules: types, detector protocols, language registry, and REST API error contracts |
| [decisions/](decisions/) | Architecture Decision Records (ADRs 0001–0014; indexed [below](#decision-records)) |

## 4. Models, Benchmarks & Research

*How Meta's models (**Muse Glimmer 30B**, **Muse Spark Open**, **Muse Spark 1.3**, **Muse
Image**, **SAM 3.1**, and **XLM-RoBERTa**) power PII Guard, plus reproducible benchmarks and
dataset audits.*

| Document | What it covers |
|---|---|
| [models.md](models.md) | Model roster, **Muse Glimmer 30B → XLM-RoBERTa (`v4.2`)** distillation, local **YuNet** + **SAM 3.1** visual segmentation, and partner infrastructure |
| [benchmarks.md](benchmarks.md) | Generated benchmark report: leak rates, over-masking, F1, latency, and head-to-head comparisons against Presidio, LLM Guard, and PrivAiTe |
| [evaluation.md](evaluation.md) | Evaluation methodology: synthetic corpus generator, overlap & strict scorers, decontamination gates, and end-to-end leak tests |
| [datasets.md](datasets.md) | Registered evaluation datasets, `test` vs. `dev` split policy, SHA-256 disjointness enforcement, and 5-gram decontamination |
| [languages.md](languages.md) | Language pack architecture (`hu`, `en`, `de`, `pl`), inflection matchers, conformance suite (`pii-guard lang check`), and plugin guide |
| [data-sources-eu24.md](data-sources-eu24.md) | License and coverage audit of NER/PII datasets and national identifiers across all 24 official EU languages |
| [training-data-eu-phase1.md](training-data-eu-phase1.md) | Multilingual NER Phase 1 (LAB-1525): training sources, licenses, per-language counts, and fictional gate sets |
| [training-data-v41.md](training-data-v41.md) | NER v4.1 data (LAB-1539): fictional court-style documents in 24 languages, mined error patterns, and teacher agreement |

## 5. Operations, Deployment & Releasing

*Runbooks for self-hosting on CPU, operating the hosted demo environment, CI/CD pipelines, and
publishing releases.*

| Document | What it covers |
|---|---|
| [operations.md](operations.md) | Operations runbook: CLI commands, wheel builds, smoke tests, Prometheus metrics, and local demo stack |
| [hosted.md](hosted.md) | Hosted deployment architecture, owner-scoped trust boundary, retention rules, release gates, and rollback procedures |
| [deployment-pipeline.md](deployment-pipeline.md) | Reviewed `develop → dev` and `main → prod` deployment automation, image digest provenance, and smoke evidence gates |
| [releasing.md](releasing.md) | Semantic versioning, CI provenance checks, and tag-driven publishing to PyPI and GHCR |
| [private-dev.md](private-dev.md) | Tailnet-only dev networking, proxy credentials, app-only releases, and live activation gates |

## 6. Project History & Milestones

*Chronological execution logs, compute spend accounting, and future roadmap.*

| Document | What it covers |
|---|---|
| [journey.md](journey.md) | Dated engineering log: every PR milestone with before/after leak metrics, latency charts, and itemized ~$22 compute spend |
| [roadmap.md](roadmap.md) | Hackathon execution record (Days 1–6 completed), the Glimmer → XLM-RoBERTa distillation pivot, and post-hackathon roadmap |

---

## Decision records

| ADR | Decision |
|---|---|
| [0001](decisions/0001-record-architecture-decisions.md) | Record architecture decisions as ADRs |
| [0002](decisions/0002-clean-room-start.md) | Start from a clean room, decoupled from earlier internal work |
| [0003](decisions/0003-python-stack.md) | Python 3.12 + uv + FastAPI |
| [0004](decisions/0004-apache-2-license.md) | Apache-2.0 license |
| [0005](decisions/0005-synthetic-data-only.md) | Synthetic data only, never real personal data |
| [0006](decisions/0006-fail-closed.md) | Fail closed on every error path |
| [0007](decisions/0007-keyed-pseudonyms.md) | Keyed, reversible pseudonyms instead of one-way redaction |
| [0008](decisions/0008-language-packs.md) | Language packs: per-language rules, inflection, prompts and eval forms, with fallbacks |
| [0009](decisions/0009-third-party-lexicons.md) | Third-party lexicons: committed only where terms allow, used by the generator and the address rule |
| [0010](decisions/0010-language-pack-plugins.md) | Language packs as one plugin unit: one `LanguagePack`, entry-point discovery, a conformance suite |
| [0011](decisions/0011-hosted-saas.md) | Opt-in hosted demo: Google-first identity, scoped ephemeral state and conservative sponsored allocations |
| [0012](decisions/0012-hosted-projects-and-endpoint-configuration.md) | Persist project configuration separately from ephemeral request state |
| [0013](decisions/0013-one-console-owner-scoped-api.md) | One console, one API: owner-scoped runtime, hosted projections and server-declared capabilities |
| [0014](decisions/0014-hosted-local-images.md) | Hosted image masking for signed-in owners, processed locally and in memory only |
