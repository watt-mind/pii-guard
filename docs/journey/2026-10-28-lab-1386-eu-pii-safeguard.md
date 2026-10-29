# The closest public PII NER, benchmarked against ours: ours leaks less everywhere (2026-10-28)

LAB-1386, asked by the owner. [`tabularisai/eu-pii-safeguard`](https://huggingface.co/tabularisai/eu-pii-safeguard)
is an XLM-R **large** PII model for 26 EU languages (42 labels, self-reported F1 97.0 %). We had
never measured it. It now runs through pii-guard's own NER post-processing with a documented
label adapter (`pii_guard.eval.baselines.eu_pii_safeguard`), on the same commit, sets and CPU as
our published NER v2.0 (XLM-R base), alone and in place of our NER in fast mode.

| set (split) | fast mode leak: ours → with eu-pii-safeguard | recall | consistency |
| -- | -- | -- | -- |
| smoke (hand-written) | 0.0 → 5.8 % | 93.3 → 90.7 % | 96.5 → 86.7 % |
| hu-inflection | 2.0 → 22.0 % | 93.4 → 39.3 % | 67.9 → 64.3 % |
| agent-traffic (test) | 0.2 → 8.8 % | 97.4 → 79.8 % | 99.0 → 80.0 % |
| ai4privacy (test, in distribution for ours) | 0.4 → 7.5 % | 98.9 → 87.3 % | 99.3 → 86.5 % |
| nemotron-pii | 0.7 → 8.5 % | 87.8 → 73.6 % | 98.0 → 87.7 % |
| cee-pii | 0.4 → 2.8 % | 97.2 → 93.8 % | 98.8 → 93.8 % |
| gretel-finance | 19.0 → 29.8 % | 68.8 → 46.5 % | 75.6 → 55.7 % |

Every row, partial leak, over-masking, precision and the model-alone runs:
[eval/results/2026-10-28-eu-pii-safeguard](../../eval/results/2026-10-28-eu-pii-safeguard/README.md),
run records `2026-10-28-lab-1386-*`.

- **Honest wins for it:** more organizations found (smoke ORGANIZATION recall 88 vs 56 %),
  which our policy keeps anyway; precision within a point of ours on nemotron-pii and
  gretel-finance; alone, more Hungarian TAJ numbers found on cee-pii (93 vs 83 %), though it
  leaks 11 of them and ours none. None of it lowers a leak.
- **Cost:** 559M vs 277M parameters, 2.24 vs 1.11 GB, CPU p95 467 vs 147 ms per ~380-character
  message on the same loaded machine (about 3×), load 13 vs 11 s.
- **License:** the card's metadata says Apache-2.0, but its `LICENSE.md` is a commercial license
  (30-day evaluation, then paid). Evaluation only, pending the owner's decision; its weights are
  not in the repository.
- **Decision:** no change. Fast mode keeps NER v2.0; the model is not a candidate for a heavier
  mode, a distillation teacher or an ensemble: it is worse where it matters and its license
  doesn't allow it.
- **Cost of the run:** $0, offline after a one-off 2.2 GB download.
