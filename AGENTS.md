# AGENTS.md

## Project

**pii-guard** is an open-source privacy firewall for AI agents: it detects personal data in
text, documents and images, replaces it with reversible keyed pseudonyms before a request
reaches an LLM, and restores the real values in the (streamed) response. Hungarian first, other
EU languages next. Built for the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Stack (see [ADR 0003](docs/decisions/0003-python-stack.md)): Python 3.12, `uv`, FastAPI,
pytest, ruff. Models: rules + multilingual NER + a fine-tuned small Llama model; SAM 3.1 for
images. See [docs/models.md](docs/models.md).

Read [docs/INDEX.md](docs/INDEX.md) before changing anything non-trivial.

## Issue tracking (Linear)

Team **`LAB`**, project **`PII Guard`**. Full protocol:
`~/Develop/hdkiller/docs/orgs/linear.md` — read before claiming or filing tickets.
Follow-ups discovered mid-work → file a Linear issue in `Triage` (do not expand the
current ticket's scope). PR body: `Fixes LAB-XX`. Commit format:
`feat(scope): summary (LAB-XX)`.

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
uv sync                          # install dependencies (Python 3.12, from uv.lock)
uv run pytest                    # tests + coverage
uv run ruff check .              # lint
uv run ruff format .             # format (CI runs --check)
uv run pii-guard serve           # REST API on http://127.0.0.1:8787 (GET /healthz)
uv run pii-guard eval            # evaluation scorecard (eval/fixtures, rules detector)
make check                       # lint + format check + tests, same as CI
docker compose up --build        # the API in a container on 127.0.0.1:8787
```

Full verification before a PR:

```bash
uv sync && uv run ruff check . && uv run ruff format --check . && uv run pytest && uv run pii-guard --help
```

Shared interfaces (core types, detector registry, config, REST, vault, eval fixtures) are
specified in [docs/contracts.md](docs/contracts.md). Read it before adding a detector, a
router or a vault implementation.

## Layout

| Path | Purpose |
|---|---|
| `src/pii_guard/types.py` | `Span`, `EntityType`, `Detector`, errors (implemented) |
| `src/pii_guard/registry.py` | Detector registry, lazy name → class (implemented) |
| `src/pii_guard/config.py` | Settings from the environment (implemented) |
| `src/pii_guard/cli.py` | `pii-guard` CLI: `serve`, `eval`, `lang` (implemented) |
| `src/pii_guard/languages/` | Language packs (`hu`, `en`, `de`), registry, conformance checks ([docs/languages.md](docs/languages.md)) |
| `src/pii_guard/detect/` | Detectors (rules, NER, LLM) and span merging |
| `src/pii_guard/visual/` | OCR boxes, SAM 3.1 segmentation, image masking |
| `src/pii_guard/documents/` | PDF / DOCX / image ingestion to text + layout |
| `src/pii_guard/vault/` | Keyed pseudonyms, mapping store, re-identification |
| `src/pii_guard/gateway/` | OpenAI-compatible proxy, streaming re-identification |
| `src/pii_guard/api/` | App factory and `/healthz` (implemented); `/v1/*` routers in `api/routes/` (planned) |
| `eval/` | Synthetic corpus generator, scorer, committed synthetic fixtures |
| `docs/` | Design docs and ADRs |
