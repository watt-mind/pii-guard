# AGENTS.md

## Project

**PII Guard** is an open-source privacy gateway for AI agents: it detects personal data in
text, documents and images, replaces it with reversible keyed pseudonyms before a request
reaches an LLM, and restores the real values in the (streamed) response. Language packs for Hungarian, English,
German and Polish; the NER model covers 24 EU languages. Built for the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Stack (see [ADR 0003](docs/decisions/0003-python-stack.md)): Python 3.12, `uv`, FastAPI,
pytest, ruff, mypy; the web console in `ui/` is TypeScript (pnpm, Vite). Models: rules +
fine-tuned XLM-R NER is the default (fast mode); Muse Spark Open / Glimmer is an opt-in second
pass (audit mode); YuNet (faces) and a local YOLOS detector (signatures) mask images on-device,
SAM 3.1 is optional. See [docs/models.md](docs/models.md).

Read [docs/INDEX.md](docs/INDEX.md) before changing anything non-trivial.

## Issue tracking (Linear)

Maintainers track work in Linear: team **`LAB`**, project **`PII Guard`**. The conventions
that apply in this repository are in
[CONTRIBUTING.md](CONTRIBUTING.md#issues-and-tracking). Follow-ups discovered mid-work →
file an issue in `Triage` (do not expand the current ticket's scope). PRs target `develop`
(`gh pr create --base develop`; the default branch `main` takes only release PRs). PR body:
`Fixes LAB-XX`. Commit format: `feat(scope): summary (LAB-XX)`.

## Non-negotiables

1. **No real personal data in the repository. Ever.** Not in fixtures, tests, docs, logs,
   screenshots or commit messages. All test data is synthetic and generated
   (see [ADR 0005](docs/decisions/0005-synthetic-data-only.md)). If you are handed a real
   document to debug, reproduce the problem with a synthetic one.
2. **Fail closed.** Any error in extraction, detection or masking must block the outbound
   request, never forward it unmasked (see [ADR 0006](docs/decisions/0006-fail-closed.md)).
3. **Raw values never leave the guard.** Not in logs, metrics, traces, error messages or
   exception text. Log entity types, counts and placeholder ids only.
4. **This repository will be public.** Do not mention clients, customers, other internal
   products or private repositories in code, docs, commits or PRs. Reference only this
   repo's own Linear team key (`LAB`).
5. **Clean room.** This is a fresh implementation; do not copy code from other internal PII
   projects (see [ADR 0002](docs/decisions/0002-clean-room-start.md)).
6. **Every detection change reports its effect** on the evaluation set (precision, recall,
   leak rate). A change that lowers recall needs an explicit justification in the PR.
7. **No secrets in the repo.** Configuration comes from the environment; `.env.example`
   documents the keys.

## Commands

```bash
uv sync                          # install dependencies (Python 3.12, from uv.lock; includes CPU torch for NER)
make setup                       # also installs the pre-commit and commit-msg hooks
uv run pytest                    # every test, serial, branch coverage (make test = fast CI suite)
uv run ruff check .              # lint
uv run ruff format .             # format (CI runs --check)
uv run pii-guard up              # API + gateway + console on http://127.0.0.1:8787 (start here)
uv run pii-guard serve           # REST API only (GET /healthz)
uv run pii-guard eval            # evaluation scorecard (eval/fixtures, rules detector)
make check                       # lint + types + fast tests + eval gate (subset of CI)
make openapi                     # regenerate docs/openapi.json + docs/api.md after a route change
docker compose up --build        # the API in a container on 127.0.0.1:8787
```

Full verification before a PR:

```bash
uv sync && make check && uv run pii-guard --help
```

## CI gates and images

CI (`.github/workflows/ci.yml`, table in [CONTRIBUTING.md](CONTRIBUTING.md)) adds to
`make check`:

- **eval-gate** (`make gate`): rules-only, offline; leak, round-trip and over-masking rates
  must stay within `eval/gates.json` against the committed runs in `eval/results/`.
- **pii-in-diff** (`make pii-diff`) and **gitleaks**: test data uses `example.com` e-mail
  addresses and identifiers with wrong check digits; a fictional value that must validate goes
  in `scripts/ci/pii-allowlist.txt` with a comment.
- **types**: new mypy errors fail (`scripts/ci/mypy-baseline.txt`); coverage floors are in the
  `Makefile` and `pyproject.toml`.
- **docker**: the base `Dockerfile` is rules-only (`PII_GUARD_SKIP_PACKAGES` drops torch and
  transformers) and must stay under the 650 MB budget in `scripts/ci/docker_smoke.sh`.
  `Dockerfile.hosted` is the hosted image (console and CPU NER baked in), deployed to Azure
  Container Apps from `deploy/azure/` ([docs/deployment-pipeline.md](docs/deployment-pipeline.md),
  [docs/releasing.md](docs/releasing.md)).

Model weights are pinned by revision and SHA-256: the NER model downloads on first use,
`pii-guard models fetch` fetches the image models.
Environment keys are documented in `.env.example`.

Shared interfaces (core types, detector registry, config, REST, vault, eval fixtures) are
specified in [docs/contracts.md](docs/contracts.md). Read it before adding a detector, a
router or a vault implementation.

## Layout

| Path | Purpose |
|---|---|
| `src/pii_guard/types.py` | `Span`, `EntityType`, `Detector`, errors (implemented) |
| `src/pii_guard/registry.py` | Detector registry, lazy name → class (implemented) |
| `src/pii_guard/config.py` | Settings from the environment (implemented) |
| `src/pii_guard/cli.py` | `pii-guard` CLI: `up`, `serve`, `run`, `connect`, `login`, `eval`, `bench`, `lang`, `models` |
| `src/pii_guard/policy.py`, `detection_profile.py`, `upstreams.py` | Masking policy, fast/audit detection profiles, upstream providers |
| `src/pii_guard/languages/` | Language packs (`hu`, `en`, `de`, `pl`), registry, conformance checks; add one with `pii-guard lang new` ([docs/languages.md](docs/languages.md), ADRs 0008–0010) |
| `src/pii_guard/lang/` | Third-party lexicons ([ADR 0009](docs/decisions/0009-third-party-lexicons.md)) |
| `src/pii_guard/detect/` | Detectors (rules, NER, LLM), known values and span merging |
| `src/pii_guard/visual/` | OCR boxes, MRZ, local face/signature segmenters, SAM 3.1, image masking |
| `src/pii_guard/documents/` | Planned, does not exist yet: PDF / DOCX ingestion to text + layout (images are handled in `visual/`) |
| `src/pii_guard/vault/` | Keyed pseudonyms ([ADR 0007](docs/decisions/0007-keyed-pseudonyms.md)), mapping store, re-identification, inflection-aware restore |
| `src/pii_guard/gateway/` | OpenAI-compatible proxy, streaming re-identification |
| `src/pii_guard/api/` | App factory and the `/v1/*` routers in `api/routes/` (mask, unmask, chat, messages, responses, image, sessions, projects, traffic, ...) |
| `src/pii_guard/hosted/` | Hosted multi-user mode: identity, quotas, spend, egress, abuse limits ([ADR 0011](docs/decisions/0011-hosted-saas.md)–[0014](docs/decisions/0014-hosted-local-images.md), [docs/hosted.md](docs/hosted.md)) |
| `src/pii_guard/integrations/` | `pii-guard run` / `connect` for coding agents (Claude Code, Codex, Muse Code, ...) ([docs/integrations.md](docs/integrations.md)) |
| `src/pii_guard/projects/`, `observability/` | Projects and endpoint configuration; metrics and telemetry |
| `src/pii_guard/eval/`, `bench/` | Synthetic corpus generator, scorer, eval gate; benchmarks |
| `eval/` | Committed fixtures, public benchmark manifests (`datasets/`), run records (`results/`), `gates.json` |
| `ui/` | Web console (React, pnpm) |
| `deploy/azure/` | Bicep templates and deploy scripts for the hosted service |
| `training/` | NER and LLM fine-tuning and distillation scripts |
| `scripts/ci/` | CI helpers (docker smoke, PII-in-diff, gitleaks, commit-msg, mypy baseline) |
| `docs/` | Design docs and ADRs |
