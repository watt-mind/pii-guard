# Ai4Privacy no longer charges a masked title or bare town as over-masking (2026-10-30)

LAB-1222, the follow-up of LAB-1213. LAB-1213 taught the Ai4Privacy converter to keep the labels
PII Guard's policy doesn't mask (dates, ages, gender, sex, titles, a town on its own) as *ignore
regions*, so a prediction on one is neither credited nor charged; the committed sample predated
that, so the scorer only skipped `DATE_OF_BIRTH` on it. **Change:** the sample was rebuilt from the
pinned split (`fetch --source-file`, the 920 MB file checked against its SHA-256): the same 600
rows and gold spans, plus 1,452 ignore regions (de 452, en 504, hu 496); the
[manifest](../../eval/fixtures/public/ai4privacy-openpii-1m.json) is unchanged and `fetch --check`
passes.

Both runs on `develop` `323d859`, local CPU, `pii-guard eval --detectors …` on
`eval/fixtures/public/{de,en,hu}-ai4privacy.jsonl`; before is the earlier sample, after the
refreshed one ([rules](../../eval/results/runs/2026-10-30-lab-1222-ai4privacy-rules.json),
[fast](../../eval/results/runs/2026-10-29-lab-1222-ai4privacy-fast.json)):

| system | precision (overlap) | over-masking | unscored predictions | recall / leak |
| -- | -- | -- | -- | -- |
| rules | 98.5 % → 98.5 % | 0.1 % → 0.1 % | 0 → 0 | 36.5 % / 62.9 %, unchanged (63.0 % once re-recorded on later `develop` rules) |
| fast (rules + NER v2.0) | 98.1 % → **98.9 %** | 1.2 % → **0.3 %** (26 → 7 spans) | 250 → 269 | 96.9 % / 2.4 %, unchanged |

A change of method, not of the model: recall and leak can't move with ignore regions. The
comparison models and baselines are still on the earlier sample and show under the
earlier-fixture table in [benchmarks.md](../benchmarks.md#ai4privacy) until they are re-run.

Found on the way: fast mode's leak on this set is 2.4 %, not the 0.4 % of the LAB-1512 record
(`d2e710a`). The difference is all `ADDRESS` (4 → 49 of 379 leaked) and appears on the earlier
sample too, so it is not this change; the only detection commit in between is LAB-1477's
bare-number `ADDRESS` guard. Tracked in LAB-1599. Cost: $0.
