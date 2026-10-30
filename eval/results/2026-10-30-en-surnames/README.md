# English surnames after a title (LAB-1138, 2026-10-30)

`rules,llm` with Muse Spark Open on Baseten (`meta-models/muse-spark-open-1026`, JSON mode,
`temperature: 0`), as in [2026-10-27-baseten](../2026-10-27-baseten/README.md). The scorecards
here were run on `d16b9ec326d2` plus this branch's change to
`src/pii_guard/languages/en/prompt.md` (hence "dirty"), with `reasoning_effort: low`. All
values in the fixtures are fictional.

## What was missed

A per-document diff of three `low` runs on `en-synth-sample` on the old prompt found 11 missed
`PERSON` occurrences, all of the same kind: a surname used on its own after a title ("Ms X",
"Mr X"), in documents `00002`, `00005`, `00008` and `00009`. In `00005` the full name was
found and only the later "Dear Mr X" was missed. Three runs out of three missed `00002`, so it
is mostly a prompt gap, with sampling deciding which of the other three documents leak. The
English notes said only to drop the title, never to keep the name after it, and
the system prompt's "list each distinct surface form once" let the model stop at the full name.

The fix adds two lines to the English notes: report the name after a title, and list a
surname or given name used on its own as its own surface form, even when the full name is
already listed.

## Results

| `en-synth-sample`, 10 docs, 59 gold PERSON | runs | missed PERSON occurrences | p50 s | p95 s | $ / 1k docs |
|---|---:|---:|---:|---:|---:|
| old prompt, `low` | 3 | 11 | 2.2 | 3.0 | 3.43 |
| old prompt, `medium` | 2 | 5 (+1 truncated reply, retried) | 3.1 | 8.0 | 6.39 |
| **new prompt, `low`** | 3 + 1 scored | **0** | 1.9 | 3.1 | 3.67 |

$ per 1k docs is from the token counts the endpoint reported (`LlmDetector.usage`) at the
[2026-10-27 prices](../2026-10-27-baseten/README.md). `medium` does not close the gap: it
misses the same names at twice the cost and almost three times the p95.

Scorecards (new prompt, `low`):

| Fixture | P | R | F1 | Leak | Partial leak | Over-masking | Before (2026-10-27) |
|---|---:|---:|---:|---:|---:|---:|---|
| [`en-synth-sample`](en-synth-sample-rules-llm.md) | 100.0 | 100.0 | 100.0 | **0.0** | 3.8 | 0.0 | F1 99.2, leak 2.5, partial 6.2 |
| [`en-smoke`](en-smoke-rules-llm.md) | 94.4 | 100.0 | 97.1 | 0.0 | 3.3 | 3.2 | the same |

The Hungarian fixtures do not use the English notes, so they were not rerun.

## Spend

About $0.40 of the Baseten credit: eight diagnostic runs of 10 documents (about $0.34) and the
two scorecards (about $0.06).
