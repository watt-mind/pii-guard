# Contributing to pii-guard

Thanks for helping. pii-guard is a privacy tool, so a few rules are stricter than in most
projects.

## Ground rules

1. **Never commit real personal data.** Not in tests, fixtures, docs, issues, screenshots or
   commit messages. Use the synthetic generator in `eval/`, or write obviously fictional data.
   If you found a bug on a real document, reproduce it with a synthetic one before filing.
2. **Fail closed.** Code paths that cannot finish masking must stop the request, not forward
   it.
3. **No raw values in logs or errors.** Log entity types, counts and placeholder ids.
4. **Measure detection changes.** If you touch detection, record a run and commit it with the
   change: `uv run pii-guard eval --fixtures eval/fixtures --detectors rules --record <slug>`
   (see [Recording a benchmark run](#recording-a-benchmark-run)), and put the before/after
   numbers in the pull request. If it changes a headline metric (leak rate, F1, latency or
   cost of a recommended configuration), add a milestone to [docs/journey.md](docs/journey.md).

## Development setup

You need [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you if needed).

```bash
git clone https://github.com/watt-mind/pii-guard.git
cd pii-guard
make setup                 # uv sync + pre-commit hook (ruff)
cp .env.example .env       # optional; nothing is required to run the tests
```

Day to day:

```bash
make check                 # what CI runs: ruff check, ruff format --check, pytest
make format                # apply ruff fixes and formatting
make serve                 # API on http://127.0.0.1:8787 with auto-reload
```

Or without `make`: `uv sync`, `uv run pytest`, `uv run ruff check . && uv run ruff format
--check .`, `uv run pii-guard serve`.

The interfaces other components depend on (core types, detector registry, REST, vault, eval
fixtures) are in [docs/contracts.md](docs/contracts.md). A change to one of them updates that
file in the same pull request.

## Recording a benchmark run

Adding a run to the [benchmark history](docs/benchmarks.md) is one command:

```bash
uv run pii-guard eval --fixtures eval/fixtures --detectors rules,ner --record ner-threshold-0.6
```

It runs the evaluation, writes `eval/results/runs/<today>-ner-threshold-0.6.json` (plus one
record per `--baselines` tool) and regenerates `eval/results/index.json`, the charts in
`docs/benchmarks/`, `docs/benchmarks.md` and the UI's copy of the index. Commit all of them; CI
runs `uv run pii-guard eval report --check` and fails if they are out of date.

Models, settings, hardware and cost that the harness can't see go in a small JSON file passed
with `--record-extra` (format in [docs/evaluation.md](docs/evaluation.md#run-records)). A
scorecard saved earlier with `--json` becomes a record with
`uv run pii-guard eval record SCORECARD.json --slug <slug>`. Run records hold only types,
counts and ratios, never a value or a document text.

## Commits and pull requests

- Conventional commit messages: `feat(detect): add IBAN checksum rule`,
  `fix(gateway): split placeholders across stream chunks`.
- Keep pull requests focused on one change. Describe what changed, why, and how you verified
  it.
- Design changes that are hard to reverse get an ADR in `docs/decisions/`.

## Reporting a leak

A way to get personal data past the guard is a **security issue**. Do not open a public
issue; follow [SECURITY.md](SECURITY.md).
