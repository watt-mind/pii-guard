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
make check                 # ruff, mypy (baseline), pytest (coverage floor), eval gate
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

## What CI checks

Every pull request runs [`.github/workflows/ci.yml`](.github/workflows/ci.yml). Its last job,
**`ci-ok`**, passes only when every other job passed or was skipped on purpose, so it is the
one check to require. All jobs run in parallel on GitHub-hosted runners, cost nothing and need
no secret.

| Job | What fails it | Locally |
|---|---|---|
| `lint` | ruff lint or format | `make lint` |
| `types` | a mypy error on `src/` not listed in `scripts/ci/mypy-baseline.txt` | `make types` |
| `test` | a failing test, total coverage under the floor (`fail_under` in `pyproject.toml`), `make smoke`, or a stale benchmark report | `make test smoke` |
| `eval-gate` | leak or over-masking rising, or round trip falling, against the newest committed run record on the same fixtures, or past a limit in [`eval/gates.json`](eval/gates.json) | `make gate` |
| `docker` | the image over its size budget (375 MB unpacked, `scripts/ci/docker_smoke.sh`), an unhealthy container, or a masked request that leaks to the mock upstream | `make docker-smoke` |
| `audit` | a known vulnerability in `uv.lock` (`uv audit`), or a GPL/AGPL runtime dependency | `make audit licences` |
| `ui` | UI lint, typecheck, tests, build, `pnpm audit --prod` (high or critical), GPL/AGPL production dependency; runs when `ui/` changed | `cd ui && pnpm lint && pnpm typecheck && pnpm test --run` |
| `workflows` | a [zizmor](https://docs.zizmor.sh/) finding in `.github/workflows/` (unpinned actions, injection, excessive permissions) | `uvx zizmor .github/workflows` |
| `gitleaks` | a secret in the commits the change adds ([`.gitleaks.toml`](.gitleaks.toml)) | `make gitleaks` |
| `links` | a broken relative link in `README.md` or `docs/` ([`lychee.toml`](lychee.toml)) | `make links` |
| `pii-in-diff` | **report-only for now.** pii-guard's own rules find a real-looking value on a line the PR adds: an e-mail outside the reserved example domains, or a validated identifier (tax, TAJ, IBAN, card, ID document, company number) not in `scripts/ci/pii-allowlist.txt` | `make pii-diff` |

Separately, [`codeql.yml`](.github/workflows/codeql.yml) runs CodeQL on Python,
JavaScript/TypeScript and the workflows (results under Security, code scanning),
[`links.yml`](.github/workflows/links.yml) checks external links weekly, and
[`release.yml`](.github/workflows/release.yml) publishes the image to GHCR and the wheel to the
GitHub release on a `v*` tag.

When a gate fails:

- **Coverage, mypy, eval gate:** the thresholds only move in the good direction. Raise the
  coverage floor, shrink the mypy baseline (`uv run python scripts/ci/mypy_baseline.py
  --update`) and record a new run when quality improves. Don't loosen a threshold to make your
  PR pass; if a regression is a deliberate trade-off, say so in the PR and change
  `eval/gates.json` in the same commit.
- **Hypothesis:** CI uses the derandomized `ci` profile (`HYPOTHESIS_PROFILE=ci`, in
  `tests/conftest.py`), so `HYPOTHESIS_PROFILE=ci uv run pytest <test>` replays the same
  examples locally.
- **pii-in-diff:** replace the value with a fictional one (an `example.com` address, an
  identifier with a wrong check digit). If it is fictional and has to be valid, add it to
  `scripts/ci/pii-allowlist.txt` with a comment.
- **GitHub Actions** are pinned to commit SHAs with the version as a comment; Dependabot
  updates both.

## Commits and pull requests

- Conventional commit messages: `feat(detect): add IBAN checksum rule`,
  `fix(gateway): split placeholders across stream chunks`.
- Keep pull requests focused on one change. Describe what changed, why, and how you verified
  it.
- Design changes that are hard to reverse get an ADR in `docs/decisions/`.

## Reporting a leak

A way to get personal data past the guard is a **security issue**. Do not open a public
issue; follow [SECURITY.md](SECURITY.md).
