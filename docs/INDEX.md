# Documentation index

| Doc | What it covers |
|---|---|
| [why-pii-guard.md](why-pii-guard.md) | What is different about pii-guard, each claim with its evidence and status |
| [vision.md](vision.md) | The problem, who it is for, goals and non-goals |
| [architecture.md](architecture.md) | Components, data flow, APIs, the gateway and streaming re-identification |
| [private-dev.md](private-dev.md) | Tailnet-only dev networking, proxy credentials, app-only releases and live activation gates |
| [hosted.md](hosted.md) | Hosted deployment, trust boundary, actual retention, release gates and rollback |
| [projects.md](projects.md) | Projects, immutable policy versions, endpoint configuration and persistence boundaries |
| [privacy-model.md](privacy-model.md) | Threat model, what pii-guard guarantees and what it does not |
| [entities.md](entities.md) | The entity taxonomy: what counts as personal data, per language |
| [evaluation.md](evaluation.md) | Synthetic benchmark, metrics, baselines, how results are reported |
| [languages.md](languages.md) | Adding a language: the language pack, the conformance suite, what "done" means |
| [contracts.md](contracts.md) | Public interfaces between modules: types, detectors, registry, API errors |
| [models.md](models.md) | Which model does what, Meta models and hackathon partners |
| [journey.md](journey.md) | The project's story so far: dated milestones with before/after metrics, cost and the decisions made |
| [submission.md](submission.md) | Draft hackathon submission text, consistent with why-pii-guard.md |
| [demo-script.md](demo-script.md) | Shot list and voice-over for the 3-minute submission video, with the source of every number said aloud |
| [roadmap.md](roadmap.md) | The 9-day hackathon plan, day-1 checks, what comes after |
| [decisions/](decisions/) | Architecture decision records (ADRs) |

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
