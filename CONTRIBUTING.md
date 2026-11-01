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
   cost of a recommended configuration), add a milestone to the
   [journey](docs/journey.md): a new file in [docs/journey/](docs/journey/README.md), not an
   edit to `journey.md`.

## Development setup

You need [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you if needed).

```bash
git clone https://github.com/watt-mind/pii-guard.git
cd pii-guard
make setup                 # uv sync + git hooks (ruff, commit message)
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

**Keep the uv cache small, especially with many worktrees or agents.** Run `uv sync` (with
the extras you need) once per worktree, then `uv run --no-sync ...`: a plain `uv run`
re-syncs first and rebuilds the project whenever its sources changed, and every rebuild
leaves another copy in `~/.cache/uv`. Run `uv cache prune` now and then to drop unused entries. Never delete
entries under `~/.cache/uv/archive-v0` by hand: virtualenvs link into them. Models that a
baseline needs but uv can't cache (the huSpaCy model, see
[docs/evaluation.md](docs/evaluation.md#comparison-with-open-source-tools)) are fetched once
with `pii-guard baselines download`, not listed as dependencies.

The interfaces other components depend on (core types, detector registry, REST, vault, eval
fixtures) are in [docs/contracts.md](docs/contracts.md). A change to one of them updates that
file in the same pull request.

## Recording a benchmark run

Adding a run to the [benchmark history](docs/benchmarks.md) is one command:

```bash
uv run pii-guard eval --fixtures eval/fixtures --detectors rules,ner --record ner-threshold-0.6
```

It runs the evaluation, writes `eval/results/runs/<today>-ner-threshold-0.6.json` (plus one
record per `--baselines` tool) and regenerates the charts in `docs/benchmarks/` and
`docs/benchmarks.md`. Commit the record; whether you commit the regenerated report too depends
on who renders it (next section).

Models, settings, hardware and cost that the harness can't see go in a small JSON file passed
with `--record-extra` (format in [docs/evaluation.md](docs/evaluation.md#run-records)). A
scorecard saved earlier with `--json` becomes a record with
`uv run pii-guard eval record SCORECARD.json --slug <slug>`. Run records hold only types,
counts and ratios, never a value or a document text.

## Generated files

Some committed files are generated from others, and two pull requests that both regenerate
one always conflict, even when their inputs don't overlap (LAB-1269). So:

| Generated | From | Committed? |
|---|---|---|
| the benchmark index (`eval/results/index.json`, the UI's copy) | run records | **no**: `pii-guard eval report` writes it locally, and the UI build gets it from `pii-guard eval report --print-index` (`ui/vite.config.ts`; run `uv sync` once) |
| `docs/benchmarks.md`, `docs/benchmarks/*.svg`, `docs/benchmarks/colours.json` | run records, `docs/benchmarks/config.json` | yes, so they read on GitHub |
| the intro and results blocks of `README.md` (between `<!-- intro:start -->`/`<!-- intro:end -->` and `<!-- results:start -->`/`<!-- results:end -->`) | run records, per-dataset counts, the `readme` section of `docs/benchmarks/config.json` | yes |
| the shareable images, `docs/benchmarks/<name>[-<size>][-dark].{svg,png}` ([list](docs/benchmarks/README.md)) | run records, the `share` section of `docs/benchmarks/config.json`; PNGs are rasterized by `resvg-py` (dependency group `report`, in dev) and `--check` compares their stamp | yes |
| the milestones block of `docs/journey.md` | `docs/journey/*.md`, one file per milestone | yes; numbers are given when it is rendered |

Who renders the committed ones depends on the repository variable `RENDER_DOCS_ON_MERGE`:

- **`true`:** the [`render-docs`](.github/workflows/render-docs.yml) workflow renders them
  on `develop` after every merge (`pii-guard eval report --journey`) and pushes the result.
  A pull request commits only its inputs (run records, journey entries) and CI runs
  `pii-guard eval report --validate`: every record and entry is valid and everything renders.
  Two pull requests that add runs and milestones never conflict.
- **unset (today):** a pull request that adds a run record commits the regenerated report,
  and CI runs `pii-guard eval report --check`. Journey entries are folded in by whoever next
  runs `pii-guard eval report --journey`; until then they read in `docs/journey/`.

To turn it on, a repository admin, once: in the `protect develop and main` ruleset (or a new
ruleset for `develop` only), add **GitHub Actions** to the bypass list; then set
`RENDER_DOCS_ON_MERGE` to `true` under Settings → Secrets and variables → Actions →
Variables. The workflow only ever pushes to `develop`, and only the generated files.

Not used, and why: a `.gitattributes` merge driver only helps local merges; GitHub ignores
custom merge drivers, so the pull request still shows the conflict.

## What CI checks

Every pull request runs [`.github/workflows/ci.yml`](.github/workflows/ci.yml). **`ci-ok`**
passes only when every job it needs passed or was skipped on purpose, so it is the one check
to require. Most jobs run in parallel on GitHub-hosted runners and need no secret. Two
delivery jobs sit outside `ci-ok`: `hosted-image-push` (develop pushes only, OIDC to the dev
registry) and `hosted-deployment` (called after `ci-ok`, off unless explicitly enabled).

Pull requests, the merge queue and pushes to `develop` run a **fast** suite; pushes to `main`,
the nightly run and manual runs run **everything**. The fast test step itself recently took
roughly 1.5-2.5 minutes, while a complete PR that also selects the hosted image took about
4-5 minutes end to end (measured 2026-10-29; runner load moves this by tens of percent):

| | Pull request, merge queue, `develop` | `main`, nightly, manual |
|---|---|---|
| Tests | `make test`: every test except those marked `@pytest.mark.slow` | `make test-all`: every test |
| Coverage | line coverage (faster to measure), floor `FAST_COV_FLOOR` in the `Makefile` | branch coverage, floor `fail_under` in `pyproject.toml` |
| Hypothesis | `ci` profile: 25 examples where a test sets no `max_examples` | `ci-full` profile: the default 100 |
| `docker` | on a pull request, only when the image's inputs changed (`src/`, `Dockerfile`, `pyproject.toml`, `uv.lock`, ...); always on the merge queue and `develop` | always |

Both run pytest in parallel (pytest-xdist, `-n auto`). Mark a test `slow` when it takes seconds
on its own and something else already covers the same ground on every pull request (the
`eval-gate` job, for example); `make test-all` runs the slow ones locally.

Superseded pull-request and `develop` push runs are cancelled so the latest commit gets
feedback first. Nightly and manual runs use separate concurrency groups, so a stream of merges
cannot cancel the scheduled full-suite check. Pushes to `main` and merge-queue runs retain
their full checks without cancelling a running check.

Report behavior tests use a small, fixed set of synthetic benchmark records; separate tests
still validate the complete committed report and recompute every stored dataset summary.
The summary checks are parametrized per file so parallel workers can share that work as the
benchmark history grows.

To measure coverage overhead on the same full suite without changing CI's coverage gates:

```bash
uv sync --locked
uv run --no-sync python scripts/ci/benchmark_coverage.py --workers 2 --repeats 1
```

This compares branch coverage, `sys.monitoring` line coverage, and no coverage, each with the
`ci-full` Hypothesis profile and the same worker count. It stops on a failing run, keeps the
configured coverage floor for measured coverage runs, and writes logs, coverage JSON and
`timings.json` to a fresh temporary directory printed at startup. Use `--repo PATH` for a
separately synced baseline checkout, or `--modes branch` for a full verification run. Compare
timings on an otherwise idle machine; worker contention and runner hardware affect them.
Measurement modes do not change `make test` or `make test-all`.

Only packaging jobs are path-filtered, using [`scripts/ci/changes.py`](scripts/ci/changes.py).
The UI and wheel include benchmark records, dataset counts and colour configuration; Python
source and package metadata changes select all five filtered jobs (`ui`, `docker`, `wheel`,
`hosted`, `hosted-image`). Unknown paths also select all five. `hosted-image` is narrower
than `hosted`: Azure policy files that cannot reach `Dockerfile.hosted` run only the fast
`hosted-infra` checks, while anything copied into the image still builds it. Removed and
renamed inputs are checked, and an unreadable PR diff fails CI. Prose-only changes still run
Python, report, security and PII checks. Smoke, evaluation and PII jobs install only runtime
dependencies; the test and type-check jobs keep their development dependencies.

| Job | What fails it | Locally |
|---|---|---|
| `changes` | an unreadable PR diff (packaging selection refuses to guess) | `EVENT=pull_request BASE=<sha> python3 scripts/ci/changes.py` |
| `lint` | ruff lint or format | `make lint` |
| `types` | a mypy error on `src/` not listed in `scripts/ci/mypy-baseline.txt` | `make types` |
| `test` | a failing test, or total coverage under the floor (see above) | `make test` or `make test-all` |
| `smoke` | the demo stack leaking on the mock upstream (`make smoke`), or a stale benchmark report (an invalid run record or journey entry when `RENDER_DOCS_ON_MERGE` is on; [Generated files](#generated-files)) | `make smoke` |
| `eval-gate` | leak or over-masking rising, or round trip falling, against the newest committed run record on the same fixtures, or past a limit in [`eval/gates.json`](eval/gates.json) | `make gate` |
| `docker` | the image over its size budget (`IMAGE_BUDGET_MB` in `scripts/ci/docker_smoke.sh`), an unhealthy container, or a masked request that leaks to the mock upstream; a fixable HIGH/CRITICAL vulnerability in the built image | `make docker-smoke` |
| `hosted-infra` | a Bicep compile error, a shellcheck finding in `deploy/azure/` scripts, or a failing deployment/TLS-proxy regression test | `az bicep build --file deploy/azure/main.bicep` + `python3 -m unittest discover -s deploy/azure -p 'test_*.py'` |
| `hosted-image` | the hosted image failing to build, or its offline bundled-UI/NER smoke failing; a fixable HIGH/CRITICAL vulnerability in the built image | `docker build -f Dockerfile.hosted .` |
| `audit` | a known vulnerability in `uv.lock` (`uv audit`), or a GPL/AGPL runtime dependency (the UI halves run in the `ui` job) | `make audit licences` |
| `ui` | UI lint, typecheck, tests, build, `pnpm audit --prod` (high or critical), GPL/AGPL production dependency; path-filtered like the other packaging jobs | `cd ui && pnpm lint && pnpm typecheck && pnpm test --run && pnpm build` |
| `wheel` | the bundled-UI wheel over its size budget, missing the UI, or failing the throwaway-install smoke | `make wheel && make wheel-smoke` |
| `workflows` | a failing CI-helper/hosted-deploy test, an actionlint or shellcheck finding, or a [zizmor](https://docs.zizmor.sh/) finding (unpinned actions, injection, excessive permissions) | `scripts/ci/actionlint.sh && shellcheck scripts/ci/*.sh && uvx zizmor@1.31.1 --min-severity=low .github/workflows` |
| `gitleaks` | a secret in the commits the change adds ([`.gitleaks.toml`](.gitleaks.toml)) | `make gitleaks` |
| `links` | a broken relative link in `README.md` or `docs/` ([`lychee.toml`](lychee.toml)) | `make links` |
| `ci-ok` | any job it needs failing or being cancelled (skipped-on-purpose jobs pass) | — (aggregator only) |
| `pii-in-diff` | pii-guard's own rules find a real-looking value on a line the PR adds: an e-mail outside the reserved example domains, or a validated identifier (tax, TAJ, IBAN, card, ID document, company number) not in `scripts/ci/pii-allowlist.txt` | `make pii-diff` |

Separately, [`codeql.yml`](.github/workflows/codeql.yml) runs CodeQL on Python,
JavaScript/TypeScript and the workflows (results under Security, code scanning),
[`links.yml`](.github/workflows/links.yml) checks external links weekly, and
[`release.yml`](.github/workflows/release.yml) publishes the image to GHCR and the wheel to the
GitHub release (and to PyPI when enabled) on a `v*` tag — but only after its `gate` job proves
the tagged commit passed `ci-ok` as a `main`/`develop` push. `hosted-deploy.yml` has no
standalone trigger; only `ci.yml` may call it, after `ci-ok`, and only when hosted deployments
are explicitly enabled. A failing `test` job uploads its JUnit/coverage reports for one day.

When a gate fails:

- **Coverage, mypy, eval gate:** the thresholds only move in the good direction. Raise the
  coverage floor, shrink the mypy baseline (`uv run python scripts/ci/mypy_baseline.py
  --update`) and record a new run when quality improves. Don't loosen a threshold to make your
  PR pass; if a regression is a deliberate trade-off, say so in the PR and change
  `eval/gates.json` in the same commit.
- **Hypothesis:** CI uses the derandomized `ci` profile on pull requests, the merge queue
  and `develop`, and `ci-full` on `main`, nightly and manual runs (`HYPOTHESIS_PROFILE`, in `tests/conftest.py`), so
  `HYPOTHESIS_PROFILE=ci uv run pytest <test>` (or `ci-full`) replays the same examples locally.
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

## Issues and tracking

- **Outside contributors:** open a [GitHub issue](https://github.com/watt-mind/pii-guard/issues)
  for a bug or an idea, and a pull request when you have a change. You don't need an account
  anywhere else. A leak is a security issue: see below.
- **Maintainers** track the same work in Linear, team `LAB`, project `PII Guard`. Pull
  requests that close a ticket say `Fixes LAB-XX` in the body, and their commits end in
  `(LAB-XX)`. Work discovered while doing something else becomes its own issue rather than
  growing the current pull request.
- Issues, commits and pull requests are public. Like the code, they must not contain real
  personal data, secrets, or names of customers, clients or private projects.

## Reporting a leak

A way to get personal data past the guard is a **security issue**. Do not open a public
issue; follow [SECURITY.md](SECURITY.md).
