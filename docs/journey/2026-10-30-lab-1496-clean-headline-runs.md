# Headline runs recorded from a clean commit (2026-10-30)

LAB-1496, found in LAB-1493's critique. **Before:** the run log marked 693 of 870 run records
"(uncommitted changes)", the fast-mode rows behind the headline among them. The flag already
ignored untracked files (models, scratch). It came from tracked files that `pii-guard eval
report` rewrites while runs are recorded: `docs/benchmarks.md`, the charts, the README and
the run records themselves. So a run looked unreproducible even when its detection code was
exactly the commit's.

- **The dirty flag now covers code only**
  ([`eval/report.py`](../../src/pii_guard/eval/report.py)): a tracked change under `src/`,
  `eval/fixtures/`, `scripts/`, `pyproject.toml` or `uv.lock`. A new `code.dirty_paths` field
  in the run record says which files differed, so a dirty run says why.
- **The headline rows are re-recorded** from a clean checkout of `develop` `62799b5`: fast
  mode, rules only, Presidio, LLM Guard and PrivAiTe on `smoke` (hu/en/de), `cee-pii` and
  `nemotron-pii`, 15 records `eval/results/runs/2026-10-30-lab-1496-*.json`, none dirty.

Leaked values, before (the latest earlier record) → after:

| set | fast | rules only | Presidio | LLM Guard | PrivAiTe |
| -- | -- | -- | -- | -- | -- |
| smoke (173 values) | 0 → 0 | 72 → 71 | 42 → 42 | 78 → 78 | 22 → 22 |
| cee-pii (504) | 2 → 2 | 208 → 208 | 184 → 184 | 382 → 382 | 22 → 22 |
| nemotron-pii (697) | 5 → 5 | 390 → 390 | 89 → 89 | 201 → 201 | 28 → 28 |

Every count reproduces; the one change is a rules-only smoke value that later rule changes on
`develop` now catch. Latency moved (fast smoke p50 45 → 38 ms) because these runs share a
loaded laptop: compare latency rows loosely. The older records keep their flag, which was
computed the old way; 693 of 885 records still say dirty. Cost: $0, local CPU.
