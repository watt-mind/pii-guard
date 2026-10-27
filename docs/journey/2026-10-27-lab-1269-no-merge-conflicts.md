# Pull requests stop conflicting on generated files (2026-10-27)

LAB-1269. **On 2026-10-27, PRs #61, #78, #79, #80 and #81 each conflicted with `develop`,**
always in the same places: the benchmark index (`eval/results/index.json` and the UI's copy),
the rendered report ([benchmarks.md](../benchmarks.md) and its charts), and the next
milestone number at the end of [journey.md](../journey.md). Each one cost a hand merge and
another CI run of about 5 minutes.

- **The index is a build output now.** It is no longer committed. The UI build asks
  `pii-guard eval report --print-index` for it, so the Benchmarks tab still ships with the data
  of every committed run record.
- **One file per milestone.** New milestones are files in [journey/](README.md), numbered when
  they are folded into `journey.md`, in merge order. Milestones 1–39 are unchanged.
- **The report can be rendered after the merge.** With the `render-docs` workflow on, pull
  requests only add run records and entries, and CI checks that they render
  (`--validate`). The workflow renders `benchmarks.md`, the charts and the journey on
  `develop`. It needs a ruleset bypass for GitHub Actions on `develop`, so it is off until the
  owner turns it on (CONTRIBUTING.md, "Generated files").
- **Cost:** $0.
