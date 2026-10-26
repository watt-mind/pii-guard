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

The code scaffold does not exist yet. Once it does, the expected commands are:

```bash
uv sync                      # install dependencies
uv run pytest                # tests
uv run ruff check .          # lint
uv run ruff format .         # format
uv run pii-guard serve       # run the API + gateway locally
uv run pii-guard eval        # run the evaluation set and print the scorecard
```

Update this section when the real commands land.

## Layout (planned)

| Path | Purpose |
|---|---|
| `src/pii_guard/detect/` | Detectors (rules, NER, LLM) and span merging |
| `src/pii_guard/visual/` | OCR boxes, SAM 3.1 segmentation, image masking |
| `src/pii_guard/documents/` | PDF / DOCX / image ingestion to text + layout |
| `src/pii_guard/vault/` | Keyed pseudonyms, mapping store, re-identification |
| `src/pii_guard/gateway/` | OpenAI-compatible proxy, streaming re-identification |
| `src/pii_guard/api/` | REST API (`/v1/analyze`, `/v1/mask`, `/v1/unmask`) |
| `eval/` | Synthetic corpus generator, scorer, committed synthetic fixtures |
| `docs/` | Design docs and ADRs |
