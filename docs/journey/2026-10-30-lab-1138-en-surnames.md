# English surnames after a title stop leaking in strict mode (2026-10-30)

LAB-1138. Strict mode (rules plus Muse Spark Open) leaked 2.5–5.0 % of the values on the
Muse-generated English sample, all of them names. A per-document diff showed one pattern: a
surname on its own after a title ("Ms X", "Dear Mr X"), sometimes in a document where the
full name had been found. The English prompt notes said to drop the title but not to keep the
name after it. Two lines in `languages/en/prompt.md` now say both.

| `en-synth-sample`, `rules,llm` | Leak | Partial leak | PERSON recall | p50 s | p95 s | $ / 1k docs |
|---|---:|---:|---:|---:|---:|---:|
| before, `low` ([2026-10-27](../../eval/results/2026-10-27-baseten/en-synth-sample-rules-llm.md)) | 2.5 | 6.2 | 96.6 | 2.1 | 2.6 | 2.91 |
| `medium`, old prompt (2 runs) | misses the same names | | | 3.1 | 8.0 | 6.39 |
| **after, `low`** ([2026-10-30](../../eval/results/2026-10-30-en-surnames/en-synth-sample-rules-llm.md)) | **0.0** | 3.8 | 100.0 | 1.9 | 3.1 | 3.67 |

No missed name in four runs on the new prompt (11 missed occurrences in three runs before);
`en-smoke` scores the same as before. Raising the reasoning effort was not the fix: it cost
twice as much and still missed. About $0.40 of Baseten credit. Details in
[the run README](../../eval/results/2026-10-30-en-surnames/README.md).
