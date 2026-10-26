# Documentation index

| Doc | What it covers |
|---|---|
| [vision.md](vision.md) | The problem, who it is for, goals and non-goals |
| [architecture.md](architecture.md) | Components, data flow, APIs, the gateway and streaming re-identification |
| [privacy-model.md](privacy-model.md) | Threat model, what pii-guard guarantees and what it does not |
| [entities.md](entities.md) | The entity taxonomy: what counts as personal data, per language |
| [evaluation.md](evaluation.md) | Synthetic benchmark, metrics, baselines, how results are reported |
| [contracts.md](contracts.md) | Public interfaces between modules: types, detectors, registry, API errors |
| [models.md](models.md) | Which model does what, Meta models and hackathon partners |
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
