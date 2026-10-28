# tabularisai/eu-pii-safeguard vs pii-guard NER v2.0 (2026-10-28)

LAB-1386. The comparison model is
[`tabularisai/eu-pii-safeguard`](https://huggingface.co/tabularisai/eu-pii-safeguard) at
revision `c928cd51d4f28723289098a4ad59955413afcc05` (XLM-R large, 559M parameters, 42 BIO
labels, weights `sha256:206f8317…770e33`, 2.24 GB). Ours is the published
`hdkiller/pii-guard-ner-xlmr-base` v2.0 at `95f612a9ad65` (XLM-R base, 277M parameters,
1.11 GB). Both ran on one commit (`36a78e3`), fast mode, CPU (`PII_GUARD_NER_DEVICE=cpu`),
Apple M-series, 10 cores, offline, $0. Evaluation only: the model is not in any product path.

**Licence: conflicting, pending the owner's decision.** The model card's metadata says
`apache-2.0`, but the repository's `LICENSE.md` at this revision is the "Tabularis AI
Commercial License" v1.0: a 30-day free evaluation, free academic research, and an annual paid
licence for commercial use. The card also shows an "Accept License & Download" prompt, which
the hub does not enforce (`gated: false`); nothing was accepted, and the files were fetched
with `huggingface_hub` like any public model. The weights stay in the local model cache
(`~/.cache/pii-guard/models/ner/`) and are not in the repository. The ticket assumed
Apache-2.0; the run records carry the corrected licence string.

## How it was run

```
uv run --extra ner python -m pii_guard.eval.baselines.eu_pii_safeguard download
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/bench_eu_pii_safeguard.py score --record \
  --summary eval/results/2026-10-28-eu-pii-safeguard/unmapped.json
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/bench_eu_pii_safeguard.py latency \
  --json eval/results/2026-10-28-eu-pii-safeguard/latency-cpu.json
```

Both models go through pii-guard's own NER post-processing, resolver and vault, so every metric
(placeholder consistency included) is measured the same way. The label mapping, the merging of
name and address parts, and the labels dropped before scoring are in
[docs/evaluation.md](../../../docs/evaluation.md#ner-comparison-tabularisaieu-pii-safeguard-lab-1386);
the dropped-label counts per set are in [`unmapped.json`](unmapped.json).

Run records: `eval/results/runs/2026-10-28-lab-1386-<set>-<config>.json`, configs `fast-v20`
(rules + NER v2.0), `fast-eu-pii-safeguard` (rules + the comparison model in place of ours),
`ner-v20` and `eu-pii-safeguard` (each model alone). Their `code.dirty` is true because docs
and result files changed during the run; the detection code was the commit's.

## Results

Overlap matching; leak and partial leak per gold value; detection latency per document from the
scorecards (whole documents, a loaded machine: compare rows with each other only).

| set | system | leak % | partial leak % | over-mask % | recall % | precision % | consistency % | detect p50 / p95 ms |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| smoke (51) | rules + NER v2.0 | 0.0 | 2.9 | 1.1 | 93.3 | 95.3 | 96.5 | 33 / 47 |
| smoke (51) | rules + eu-pii-safeguard | 5.8 | 11.0 | 4.6 | 90.7 | 93.1 | 86.7 | 111 / 147 |
| smoke (51) | NER v2.0 alone | 3.5 | 6.9 | 1.1 | 87.6 | 91.1 | 89.0 | 39 / 52 |
| smoke (51) | eu-pii-safeguard alone | 12.7 | 18.5 | 4.7 | 72.7 | 77.7 | 69.4 | 115 / 160 |
| inflection (12) | rules + NER v2.0 | 2.0 | 30.0 | 0.0 | 93.4 | 100.0 | 67.9 | 35 / 43 |
| inflection (12) | rules + eu-pii-safeguard | 22.0 | 22.0 | 0.0 | 39.3 | 100.0 | 64.3 | 102 / 130 |
| inflection (12) | NER v2.0 alone | 4.0 | 30.0 | 0.0 | 88.5 | 98.2 | 64.3 | 33 / 40 |
| inflection (12) | eu-pii-safeguard alone | 22.0 | 24.0 | 0.0 | 34.4 | 91.7 | 60.7 | 110 / 168 |
| agent-traffic-dev (300) | rules + NER v2.0 | 0.1 | 0.1 | 1.8 | 97.9 | 95.7 | 99.0 | 51 / 79 |
| agent-traffic-dev (300) | rules + eu-pii-safeguard | 8.2 | 13.8 | 3.5 | 80.7 | 91.9 | 81.0 | 164 / 326 |
| agent-traffic-dev (300) | NER v2.0 alone | 0.1 | 0.1 | 1.9 | 97.5 | 96.5 | 99.0 | 52 / 76 |
| agent-traffic-dev (300) | eu-pii-safeguard alone | 32.9 | 24.1 | 3.3 | 45.8 | 78.4 | 43.0 | 157 / 260 |
| agent-traffic (990) | rules + NER v2.0 | 0.2 | 0.0 | 1.7 | 97.4 | 95.4 | 99.0 | 51 / 76 |
| agent-traffic (990) | rules + eu-pii-safeguard | 8.8 | 14.1 | 3.9 | 79.8 | 91.6 | 80.0 | 166 / 264 |
| agent-traffic (990) | NER v2.0 alone | 0.3 | 0.0 | 1.7 | 96.7 | 96.2 | 99.1 | 52 / 84 |
| agent-traffic (990) | eu-pii-safeguard alone | 33.4 | 24.2 | 3.6 | 44.4 | 76.1 | 42.1 | 159 / 249 |
| ai4privacy (600) | rules + NER v2.0 | 0.4 | 0.1 | 1.3 | 98.9 | 98.0 | 99.3 | 42 / 66 |
| ai4privacy (600) | rules + eu-pii-safeguard | 7.5 | 4.9 | 1.8 | 87.3 | 90.8 | 86.5 | 126 / 229 |
| ai4privacy (600) | NER v2.0 alone | 0.4 | 0.0 | 1.3 | 99.3 | 98.4 | 99.4 | 43 / 71 |
| ai4privacy (600) | eu-pii-safeguard alone | 11.7 | 5.1 | 1.9 | 82.8 | 90.0 | 82.1 | 131 / 211 |
| nemotron-pii (300) | rules + NER v2.0 | 0.7 | 0.4 | 1.4 | 87.8 | 90.9 | 98.0 | 57 / 177 |
| nemotron-pii (300) | rules + eu-pii-safeguard | 8.5 | 5.7 | 2.1 | 73.6 | 91.9 | 87.7 | 304 / 978 |
| nemotron-pii (300) | NER v2.0 alone | 1.1 | 0.4 | 1.2 | 86.4 | 90.0 | 93.7 | 57 / 178 |
| nemotron-pii (300) | eu-pii-safeguard alone | 13.1 | 8.5 | 2.0 | 63.1 | 87.8 | 79.3 | 208 / 731 |
| cee-pii (451) | rules + NER v2.0 | 0.4 | 0.2 | 26.4 | 97.2 | 71.9 | 98.8 | 34 / 46 |
| cee-pii (451) | rules + eu-pii-safeguard | 2.8 | 1.0 | 25.6 | 93.8 | 71.6 | 93.8 | 288 / 616 |
| cee-pii (451) | NER v2.0 alone | 1.6 | 0.4 | 26.4 | 86.5 | 64.5 | 96.8 | 34 / 46 |
| cee-pii (451) | eu-pii-safeguard alone | 8.7 | 3.0 | 26.5 | 85.7 | 67.8 | 85.7 | 118 / 186 |
| gretel-finance (400) | rules + NER v2.0 | 19.0 | 2.5 | 22.5 | 68.8 | 74.2 | 75.6 | 83 / 128 |
| gretel-finance (400) | rules + eu-pii-safeguard | 29.8 | 14.2 | 25.6 | 46.5 | 74.6 | 55.7 | 843 / 1598 |
| gretel-finance (400) | NER v2.0 alone | 20.3 | 2.5 | 22.4 | 67.6 | 74.3 | 73.7 | 82 / 147 |
| gretel-finance (400) | eu-pii-safeguard alone | 35.1 | 14.3 | 25.7 | 41.7 | 74.3 | 49.6 | 286 / 574 |

## Latency, load time and size (CPU)

[`latency-cpu.json`](latency-cpu.json): 122 messages of about 380 characters from the hu + en
synth samples, both models in one process, alternating per message (so load changes hit both),
8 torch threads, NER only. Load average 28–48 from unrelated work, so absolute numbers are
high; the ratio is the result.

| Model | Parameters | Weights | Load (new process) | p50 | p95 |
|---|--:|--:|--:|--:|--:|
| pii-guard NER v2.0 (XLM-R base) | 277M | 1.11 GB | 10.5–11.2 s | 74 ms | 147 ms |
| eu-pii-safeguard (XLM-R large) | 559M | 2.24 GB | 12.9–13.4 s | 213 ms | 467 ms |

## What it shows

- **Ours wins on leak on every set,** alone and with the rules. Fast mode leaks 0.0–0.7 % on the
  synthetic and public sets; with the comparison model in place of our NER it leaks 2.8–8.8 %
  (and 22 % on hu-inflection). Its biggest misses are agent-traffic identifiers and inflected
  Hungarian names (inflection recall 39 % vs 93 %).
- **Where it is ahead, it doesn't change what leaks.** It finds more organisations (smoke
  ORGANIZATION recall 88 % vs 56 %, agent-traffic 100 % vs 95 %), which pii-guard's policy keeps
  anyway; precision on nemotron-pii and gretel-finance is within a point of ours (91.9 vs 90.9,
  74.6 vs 74.2). Alone on cee-pii it finds more TAJ numbers (93 % vs 83 % recall) but leaks 11 of
  them where ours leaks none: with the rules both are near 99 %.
- **Partial leak** on hu-inflection is lower for it (22 % vs 30 %) only because it misses those
  names entirely (leak 22 % vs 2 %).
- **Cost:** 2× the parameters and weights, about 3× the CPU latency (p95 467 vs 147 ms here). On a
  quiet machine an XLM-R large model measured 145–291 ms p95 on CPU (LAB-1150), at or over the
  ~150 ms fast-mode limit, which is why fast mode runs a base model.
- **Caveats.** Our v2.0 trained on OpenPII rows, so ai4privacy is in distribution for ours; the
  comparison model's training data is not disclosed. agent-traffic-dev was our tuning split.
  The comparison model also detects types pii-guard has no type for (age, salary, job title,
  GDPR Art. 9 categories); they are dropped before scoring, so a deployment masking them would
  over-mask more than shown.
