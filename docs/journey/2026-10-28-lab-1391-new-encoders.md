# Three newer public PII encoders benchmarked: none beats ours, two can teach v3 (2026-10-28)

LAB-1391. A Hugging Face survey found three Apache/MIT PII encoders newer than anything we had
measured, all mmBERT (ModernBERT): `bardsai/eu-pii-anonimization-multilang-v3` (the successor of
our public fallback), `Horizon-Labs/pii-redactor-base` and `-small`, and
`Wismut/nym-pii-multilingual`. Each is now pinned to a revision and its weights' SHA-256 and runs
through pii-guard's own NER post-processing on the same commit, sets and CPU as our published
NER v2.0, alone and in place of our NER in fast mode. LAB-1386's harness became one shared module
(`pii_guard.eval.baselines.encoders`) with a word-level decoder for the mmBERT tokenizer, which our
first-sub-token decoder cut into fragments (LAB-1192).

| set | fast mode leak: ours | fallback v1 | bardsai v3 | Horizon base / small | Wismut |
| -- | --: | --: | --: | --: | --: |
| smoke (hand-written) | **0.0 %** | 1.2 % | 9.8 % | 9.2 / 8.7 % | 4.0 % |
| hu-inflection | 2.0 % | **0.0 %** | 34.0 % | 18.0 / 16.0 % | **0.0 %** |
| agent-traffic-dev | **0.1 %** | 2.2 % | 3.5 % | 12.9 / 9.5 % | 0.3 % |
| nemotron-pii | **0.7 %** | 2.9 % | 2.6 % | 2.6 / 2.7 % | 3.0 % |
| cee-pii | **0.4 %** | 3.6 % | 14.5 % | 15.5 / 16.3 % | 5.6 % |

Every row (ai4privacy and gretel-finance too, partial leak, over-masking, recall, precision,
consistency, contamination) and the latency runs:
[eval/results/2026-10-28-new-encoders](../../eval/results/2026-10-28-new-encoders/README.md), run
records `2026-10-28-lab-1391-*`.

- **Contamination, said up front:** Horizon trained on OpenPII-1.5M with no split stated, so its
  ai4privacy numbers may include our fixtures; they are shown, marked and not ranked. bardsai v3
  and Horizon trained on Nemotron-PII, so nemotron-pii is in distribution for them. Wismut has
  no Hungarian.
- **Honest wins for them:** nemotron-pii recall 96 % vs 88 % and precision about 99 % vs 91 %
  (bardsai v3, Horizon); Wismut leaks nothing on hu-inflection despite never seeing Hungarian.
- **Cost:** base-size models about 1.6× v2.0's CPU latency (p95 113–144 vs 66–82 ms per
  ~380-character message on the same loaded machine); Horizon small matches v2.0 at 141M.
- **Licence:** Horizon's `LICENSE` and `NOTICE` agree with its card (Apache-2.0). bardsai v3 and
  Wismut have no LICENSE file, only card metadata; no file contradicts a card.
- **Decision:** no product change. Fast mode keeps NER v2.0 and the fallback stays v1. bardsai v3
  and Horizon base are the distillation-teacher candidates for English and German document text
  in LAB-1393; Hungarian and identifiers keep our own labels.
- **Cost of the run:** $0, offline after a one-off 4.3 GB of downloads.
