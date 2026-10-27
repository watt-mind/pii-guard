# Journey milestones, one file each

New milestones of the [journey](../journey.md) are written here, one file per milestone, and
folded into `docs/journey.md` after they merge. Two pull requests that each add a milestone
then add two different files, so they can't conflict, and neither has to guess the next
number (LAB-1269). Milestones 1–39 were written before this and stay in `journey.md` as they
are.

The files below are listed oldest first. Each one reads on its own.

## Adding a milestone

1. Name the file `<YYYY-MM-DD>-<ticket>-<slug>.md`, lower case: for example
   `2026-10-28-lab-1300-faster-ocr.md`. Use the date the pull request is opened.
2. The first line is the title and the date, with no number: `# Faster OCR on ID cards
   (2026-10-28)`. Then the body, as the milestones in `journey.md` are written: the ticket,
   before → after with links to the committed files the numbers come from, cost, the
   decision. Sub-headings (`##`) are fine.
3. Write links relative to this folder (`../../eval/results/...`, `../benchmarks.md`). They
   are rewritten when the entry is folded in. Refer to other milestones by ticket
   (`LAB-1256`), or by number once they have one.
4. Don't edit `docs/journey.md` for it. `uv run pii-guard eval report --check` (or
   `--validate`) checks that the file renders.

## How it is folded in

`uv run pii-guard eval report --journey` rebuilds the block between the
`<!-- journey:begin. ... -->` and `<!-- journey:end -->` lines of `journey.md`, after the
hand-written milestones. Each entry becomes `### <n>. <title>`:

- an entry that is already in the block keeps its number, for good;
- a new entry takes the next number after every number on the page, in file-name order.
  Rendered after each merge, that is merge order.

When the `render-docs` workflow is on (CONTRIBUTING.md, "Generated files"), it does this on
`develop` after every merge. Until then, entries here that aren't on the page yet are listed
by the line under the block.
