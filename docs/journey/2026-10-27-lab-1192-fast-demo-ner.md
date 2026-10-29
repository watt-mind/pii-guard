# `make demo` runs fast mode with a NER anyone can download (2026-10-27)

LAB-1192. **Before:** `make demo` ran rules only unless `PII_GUARD_NER_MODEL` pointed at a
checkpoint you trained yourself, because the trained pii-guard NER isn't published (LAB-1137).
The demo's free-text name ("needs fast mode (NER)") reached the model as written: the one
expected miss. **After:** `make demo` installs the `ner` extra and, with no model configured,
downloads a public Apache-2.0 PII model once (1.1 GB, pinned revision, SHA-256 checked) into
`~/.cache/pii-guard/models`. The banner names it, and the name is masked.

- **Resolution order** (`pii_guard.detect.ner_resolve`): `PII_GUARD_NER_MODEL`, then the
  published pii-guard checkpoint (`hdkiller/pii-guard-ner-xlmr-base`, skipped until LAB-1306
  pins its revision), then the public fallback.
  `PII_GUARD_NER_FALLBACK=off` (`make demo MODE=rules`, `make smoke` in CI) keeps it rules
  only, offline.
- **Which public model.** LAB-1150 had picked GLiNER multi v2.1 over Davlan's XLM-R. A third
  candidate, [bards.ai's EU PII model](https://huggingface.co/bardsai/eu-pii-anonimization-multilang)
  (XLM-R base, 24 EU languages), leaks less than both on the same fixtures, rules + model
  ([scorecards](../../eval/results/2026-10-27-fast-demo-ner/README.md)):

  | | bards.ai EU PII v1 | GLiNER multi v2.1 | Davlan XLM-R |
  |---|---:|---:|---:|
  | smoke leak, max of hu/en/de | **1.9 %** | 5.4 % | 10.0 % |
  | ai4privacy leak, pooled | **10.4 %**\* | 22.5 % | 28.7 % |
  | smoke over-masking, max | 23.1 % | 10.0 % | 10.8 % |
  | installs with | `ner` extra | `gliner` extra (conflicts with `ner`) | `ner` extra |

  \* Its card lists OpenPII among its training data, so the ai4privacy rows are not an
  out-of-distribution check for it; the hand-written smoke sets are.
  It also costs what Davlan costs (both XLM-R base: 16.7 ms p50 per message on MPS) and needs
  no second environment, which GLiNER did. It is a **stop-gap**: it over-masks (23.1 % on
  en-smoke), and the trained checkpoint replaces it once LAB-1306 publishes it.
- **Checks.** `make smoke-fast` runs the demo traffic in fast mode and fails unless the NER ran
  on the labeled call and its name was masked; it passes from an empty model cache too.
  `make smoke` stays rules only, so CI installs no torch.
- **Docker.** The demo services build `pii-guard:demo` with the `ner` extra and download the
  model into a volume on the first start; `demo-api` turns healthy once it is loaded.
- **Cost:** $0. Everything ran locally; the model download is free.
