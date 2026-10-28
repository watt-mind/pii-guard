# Three newer public PII encoders vs pii-guard NER v2.0 (2026-10-28)

LAB-1391. Four mmBERT (ModernBERT) token classifiers from three publishers, each pinned to a hub
revision and the SHA-256 of its weights, against the published
`hdkiller/pii-guard-ner-xlmr-base` v2.0 at `95f612a9ad65` (XLM-R base, 277M). All ran on one
commit (`97ee284` + this branch's evaluation-only code), fast mode, CPU
(`PII_GUARD_NER_DEVICE=cpu`), Apple M-series, 10 cores, offline after the downloads, $0.
Evaluation only: no model is in any product path and the production default is unchanged.

| Config | Checkpoint @ revision | Parameters | Weights | Licence, read from the files at that revision |
|---|---|--:|--:|---|
| `bardsai-v3` | [`bardsai/eu-pii-anonimization-multilang-v3`](https://huggingface.co/bardsai/eu-pii-anonimization-multilang-v3) @ `091984b5fbce4c161abc4776ed0f4e3206e1b374` | 308M | 1.23 GB | `apache-2.0` in the card metadata; **no LICENSE file** in the repository |
| `horizon-base` | [`Horizon-Labs/pii-redactor-base`](https://huggingface.co/Horizon-Labs/pii-redactor-base) @ `42dfb0dccb0864c889c99300265567ace9fa6e6d` | 308M | 1.23 GB | Apache-2.0: card, `LICENSE` (Apache 2.0 text) and `NOTICE` agree |
| `horizon-small` | [`Horizon-Labs/pii-redactor-small`](https://huggingface.co/Horizon-Labs/pii-redactor-small) @ `3f6a99b9906378f3faed3e6eeb3b396b0b8257c2` (v1.1) | 141M | 0.56 GB | as base |
| `wismut-nym` | [`Wismut/nym-pii-multilingual`](https://huggingface.co/Wismut/nym-pii-multilingual) @ `0ed0242d67a30ca6a83e5f118506ff1e1daf83ca` | 308M | 1.23 GB | `mit` in the card metadata and text; **no LICENSE file**; part of its training labels were made by an LLM teacher on CC-BY-SA Wikipedia text |
| `fast-fallback-v1` (reference) | [`bardsai/eu-pii-anonimization-multilang`](https://huggingface.co/bardsai/eu-pii-anonimization-multilang) @ `62ca57123687`, the current public fallback (LAB-1192) | XLM-R base | 1.11 GB | Apache-2.0 (LAB-1192) |

**Licence findings.** No file contradicts a card the way `eu-pii-safeguard`'s `LICENSE.md` did
(LAB-1386). Horizon-Labs is the only one whose licence is in a file; bardsai v3 and Wismut state
theirs only in the card, which is weaker evidence for redistribution or for training on their
outputs. None is gated and nothing was accepted. Weights stay in
`~/.cache/pii-guard/models/ner/` and are not in the repository.

**Hungarian.** Wismut's card lists 22 languages and **no Hungarian**: its `hu` rows (smoke,
inflection, agent-traffic-dev, ai4privacy, cee-pii) measure a language it was not trained for.

## How it was run

```
uv run --extra ner python -m pii_guard.eval.baselines.new_encoders download
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/bench_ner_encoders.py score \
  --configs fast-<model> <model> --record \
  --summary eval/results/2026-10-28-new-encoders/unmapped-<model>.json   # one model at a time
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/bench_ner_encoders.py score \
  --configs fast-v20 ner-v20 fast-fallback-v1 --record
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/bench_ner_encoders.py latency \
  --model <model> --json eval/results/2026-10-28-new-encoders/latency-<model>.json
```

LAB-1386's harness, generalised: `pii_guard.eval.baselines.encoders` (`EncoderSpec`,
`LabelAdapter`, `ComparisonDetector`, `WordLevelBackend`) now serves `eu-pii-safeguard` too.
Every model runs through pii-guard's own NER post-processing, resolver and vault, so every
metric (placeholder consistency included) is measured the same way. The mmBERT models are
**decoded word by word** (pii-guard's first-sub-token decoder cuts them into fragments, LAB-1192),
and `transformers` 5.21 from the `ner` extra already supports ModernBERT, so no pin changed.
Decoder, label maps and contamination: [docs/evaluation.md](../../../docs/evaluation.md#ner-comparison-public-encoders-lab-1391).
Labels dropped before scoring, per set: `unmapped-<model>.json` (bardsai v3's biggest are
`DATE_TIME`, `PERSON_ATTRIBUTE` and lone towns; a deployment masking them would over-mask more
than shown).

Run records: `eval/results/runs/2026-10-28-lab-1391-<set>-<config>.json`. The v2.0 rows were
re-run on this commit and match LAB-1386's to the digit.

## Results

Overlap matching; leak and partial leak per gold value; detection latency per document from the
scorecards (whole documents, a loaded machine: compare rows with each other only). The
**contamination** column says where a model's training data overlaps the set; Horizon's
ai4privacy rows are **possibly contaminated** (OpenPII-1.5M, split not stated) and are left out of
every comparison below.

### Fast mode leak at a glance (rules + the model)

| set | NER v2.0 | fallback v1 | bardsai v3 | Horizon base | Horizon small | Wismut nym |
|---|--:|--:|--:|--:|--:|--:|
| smoke | **0.0** | 1.2 | 9.8 | 9.2 | 8.7 | 4.0 |
| inflection (hu) | 2.0 | **0.0** | 34.0 | 18.0 | 16.0 | **0.0** |
| agent-traffic-dev | **0.1** | 2.2 | 3.5 | 12.9 | 9.5 | 0.3 |
| ai4privacy | **0.4** | 10.5 | 0.5 | (0.5)\* | (0.7)\* | 6.7 |
| nemotron-pii | **0.7** | 2.9 | 2.6 | 2.6 | 2.7 | 3.0 |
| cee-pii | **0.4** | 3.6 | 14.5 | 15.5 | 16.3 | 5.6 |
| gretel-finance | **19.0** | 21.2 | 23.3 | 23.9 | 23.7 | 21.8 |

\* possibly contaminated, not ranked.

### Every row

| set | system | contamination | leak % | partial leak % | over-mask % | recall % | precision % | consistency % | detect p50 / p95 ms |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|
| smoke (51) | rules + NER v2.0 |  | 0.0 | 2.9 | 1.1 | 93.3 | 95.3 | 96.5 | 41 / 76 |
| smoke (51) | rules + fallback v1 (bardsai v1) |  | 1.2 | 4.6 | 10.4 | 97.9 | 89.3 | 94.8 | 42 / 66 |
| smoke (51) | rules + bardsai v3 |  | 9.8 | 5.8 | 1.3 | 85.1 | 94.8 | 88.4 | 62 / 82 |
| smoke (51) | rules + Horizon base |  | 9.2 | 9.2 | 4.7 | 80.9 | 92.4 | 84.4 | 55 / 71 |
| smoke (51) | rules + Horizon small |  | 8.7 | 4.0 | 5.8 | 80.9 | 90.3 | 88.4 | 37 / 63 |
| smoke (51) | rules + Wismut nym | hu rows: no Hungarian | 4.0 | 1.2 | 6.0 | 91.8 | 89.5 | 94.8 | 128 / 380 |
| smoke (51) | NER v2.0 alone |  | 3.5 | 6.9 | 1.1 | 87.6 | 91.1 | 89.0 | 76 / 155 |
| smoke (51) | bardsai v3 alone |  | 21.4 | 4.6 | 1.4 | 68.0 | 88.0 | 76.9 | 68 / 177 |
| smoke (51) | Horizon base alone |  | 17.9 | 10.4 | 5.1 | 66.0 | 82.9 | 72.8 | 59 / 135 |
| smoke (51) | Horizon small alone |  | 14.5 | 8.1 | 5.4 | 69.1 | 81.7 | 78.6 | 60 / 178 |
| smoke (51) | Wismut nym alone | hu rows: no Hungarian | 11.0 | 2.9 | 6.4 | 78.9 | 81.7 | 86.1 | 75 / 219 |
| inflection (12) | rules + NER v2.0 |  | 2.0 | 30.0 | 0.0 | 93.4 | 100.0 | 67.9 | 35 / 47 |
| inflection (12) | rules + fallback v1 (bardsai v1) |  | 0.0 | 4.0 | 1.6 | 98.4 | 96.8 | 82.1 | 47 / 73 |
| inflection (12) | rules + bardsai v3 |  | 34.0 | 26.0 | 0.0 | 59.0 | 90.0 | 53.6 | 55 / 63 |
| inflection (12) | rules + Horizon base |  | 18.0 | 42.0 | 0.0 | 62.3 | 97.4 | 46.4 | 48 / 55 |
| inflection (12) | rules + Horizon small |  | 16.0 | 60.0 | 2.2 | 70.5 | 95.6 | 35.7 | 30 / 36 |
| inflection (12) | rules + Wismut nym | no Hungarian | 0.0 | 10.0 | 0.0 | 96.7 | 96.7 | 85.7 | 105 / 188 |
| inflection (12) | NER v2.0 alone |  | 4.0 | 30.0 | 0.0 | 88.5 | 98.2 | 64.3 | 70 / 94 |
| inflection (12) | bardsai v3 alone |  | 40.0 | 24.0 | 0.0 | 52.5 | 88.9 | 42.9 | 65 / 68 |
| inflection (12) | Horizon base alone |  | 20.0 | 42.0 | 0.0 | 57.4 | 94.6 | 42.9 | 51 / 57 |
| inflection (12) | Horizon small alone |  | 16.0 | 60.0 | 0.0 | 65.6 | 90.9 | 35.7 | 43 / 65 |
| inflection (12) | Wismut nym alone | no Hungarian | 4.0 | 10.0 | 0.0 | 91.8 | 96.6 | 78.6 | 62 / 77 |
| agent-traffic-dev (300) | rules + NER v2.0 | tuning split | 0.1 | 0.1 | 1.8 | 97.9 | 95.7 | 99.0 | 56 / 91 |
| agent-traffic-dev (300) | rules + fallback v1 (bardsai v1) |  | 2.2 | 11.2 | 4.9 | 93.5 | 85.5 | 87.2 | 59 / 88 |
| agent-traffic-dev (300) | rules + bardsai v3 |  | 3.5 | 3.5 | 6.8 | 94.8 | 88.5 | 93.0 | 83 / 139 |
| agent-traffic-dev (300) | rules + Horizon base |  | 12.9 | 14.1 | 8.5 | 83.4 | 90.1 | 78.3 | 77 / 131 |
| agent-traffic-dev (300) | rules + Horizon small |  | 9.5 | 10.4 | 7.9 | 85.5 | 89.3 | 83.0 | 58 / 117 |
| agent-traffic-dev (300) | rules + Wismut nym | hu rows: no Hungarian | 0.3 | 3.0 | 20.6 | 98.3 | 74.9 | 96.0 | 178 / 424 |
| agent-traffic-dev (300) | NER v2.0 alone | tuning split | 0.1 | 0.1 | 1.9 | 97.5 | 96.5 | 99.0 | 101 / 279 |
| agent-traffic-dev (300) | bardsai v3 alone |  | 5.0 | 3.6 | 3.1 | 89.8 | 88.2 | 91.4 | 95 / 168 |
| agent-traffic-dev (300) | Horizon base alone |  | 15.8 | 16.9 | 4.9 | 77.4 | 89.7 | 72.0 | 92 / 184 |
| agent-traffic-dev (300) | Horizon small alone |  | 14.0 | 11.3 | 4.5 | 78.1 | 88.9 | 77.1 | 90 / 187 |
| agent-traffic-dev (300) | Wismut nym alone | hu rows: no Hungarian | 0.6 | 3.0 | 18.2 | 94.8 | 74.5 | 95.6 | 97 / 153 |
| ai4privacy (600) | rules + NER v2.0 | in distribution (OpenPII train) | 0.4 | 0.1 | 1.3 | 98.9 | 98.0 | 99.3 | 50 / 85 |
| ai4privacy (600) | rules + fallback v1 (bardsai v1) | in distribution (OpenPII-1M) | 10.5 | 1.5 | 9.6 | 85.5 | 83.1 | 85.2 | 49 / 84 |
| ai4privacy (600) | rules + bardsai v3 | in distribution (OpenPII-1M train) | 0.5 | 0.1 | 0.3 | 96.1 | 96.2 | 99.0 | 77 / 160 |
| ai4privacy (600) | rules + Horizon base | **possibly contaminated** | 0.5 | 0.3 | 0.4 | 97.4 | 97.5 | 98.8 | 62 / 132 |
| ai4privacy (600) | rules + Horizon small | **possibly contaminated** | 0.7 | 0.2 | 0.3 | 97.2 | 97.5 | 98.8 | 44 / 84 |
| ai4privacy (600) | rules + Wismut nym | hu rows: no Hungarian | 6.7 | 1.9 | 1.4 | 88.8 | 91.4 | 91.0 | 202 / 565 |
| ai4privacy (600) | NER v2.0 alone | in distribution (OpenPII train) | 0.4 | 0.0 | 1.3 | 99.3 | 98.4 | 99.4 | 70 / 212 |
| ai4privacy (600) | bardsai v3 alone | in distribution (OpenPII-1M train) | 0.5 | 0.1 | 0.2 | 95.6 | 95.9 | 99.1 | 72 / 160 |
| ai4privacy (600) | Horizon base alone | **possibly contaminated** | 0.6 | 0.3 | 0.4 | 97.3 | 97.6 | 98.8 | 63 / 123 |
| ai4privacy (600) | Horizon small alone | **possibly contaminated** | 0.8 | 0.1 | 0.3 | 97.1 | 97.6 | 98.8 | 66 / 141 |
| ai4privacy (600) | Wismut nym alone | hu rows: no Hungarian | 10.2 | 1.9 | 1.4 | 84.5 | 90.3 | 87.6 | 70 / 132 |
| nemotron-pii (300) | rules + NER v2.0 |  | 0.7 | 0.4 | 1.4 | 87.8 | 90.9 | 98.0 | 60 / 192 |
| nemotron-pii (300) | rules + fallback v1 (bardsai v1) | in distribution (Nemotron) | 2.9 | 0.1 | 1.8 | 95.2 | 91.5 | 94.8 | 65 / 204 |
| nemotron-pii (300) | rules + bardsai v3 | in distribution (Nemotron train) | 2.6 | 1.3 | 0.6 | 96.4 | 99.2 | 96.8 | 102 / 321 |
| nemotron-pii (300) | rules + Horizon base | in distribution (Nemotron) | 2.6 | 1.4 | 0.6 | 96.6 | 98.5 | 96.8 | 94 / 282 |
| nemotron-pii (300) | rules + Horizon small | in distribution (Nemotron) | 2.7 | 2.2 | 0.7 | 96.4 | 98.6 | 96.6 | 64 / 197 |
| nemotron-pii (300) | rules + Wismut nym |  | 3.0 | 1.9 | 1.2 | 89.7 | 94.3 | 96.3 | 275 / 739 |
| nemotron-pii (300) | NER v2.0 alone |  | 1.1 | 0.4 | 1.2 | 86.4 | 90.0 | 93.7 | 72 / 219 |
| nemotron-pii (300) | bardsai v3 alone | in distribution (Nemotron train) | 2.7 | 1.4 | 0.5 | 96.4 | 99.4 | 96.7 | 82 / 262 |
| nemotron-pii (300) | Horizon base alone | in distribution (Nemotron) | 2.9 | 1.6 | 0.5 | 96.4 | 98.7 | 96.6 | 98 / 356 |
| nemotron-pii (300) | Horizon small alone | in distribution (Nemotron) | 3.0 | 2.3 | 0.6 | 95.9 | 98.6 | 96.3 | 86 / 230 |
| nemotron-pii (300) | Wismut nym alone |  | 3.4 | 2.0 | 1.1 | 88.3 | 93.5 | 95.8 | 92 / 311 |
| cee-pii (451) | rules + NER v2.0 |  | 0.4 | 0.2 | 26.4 | 97.2 | 71.9 | 98.8 | 35 / 50 |
| cee-pii (451) | rules + fallback v1 (bardsai v1) |  | 3.6 | 0.8 | 18.7 | 94.0 | 73.4 | 94.2 | 37 / 51 |
| cee-pii (451) | rules + bardsai v3 |  | 14.5 | 0.0 | 16.4 | 82.9 | 80.8 | 84.9 | 63 / 95 |
| cee-pii (451) | rules + Horizon base |  | 15.5 | 0.6 | 29.2 | 82.1 | 69.0 | 83.1 | 53 / 86 |
| cee-pii (451) | rules + Horizon small |  | 16.3 | 1.8 | 25.8 | 81.5 | 72.4 | 81.7 | 30 / 46 |
| cee-pii (451) | rules + Wismut nym | hu rows: no Hungarian | 5.6 | 0.2 | 23.3 | 92.1 | 73.3 | 94.0 | 78 / 156 |
| cee-pii (451) | NER v2.0 alone |  | 1.6 | 0.4 | 26.4 | 86.5 | 64.5 | 96.8 | 39 / 55 |
| cee-pii (451) | bardsai v3 alone |  | 24.8 | 0.0 | 18.2 | 44.8 | 48.7 | 74.6 | 51 / 68 |
| cee-pii (451) | Horizon base alone |  | 19.6 | 0.8 | 30.3 | 44.4 | 39.0 | 78.8 | 58 / 127 |
| cee-pii (451) | Horizon small alone |  | 20.2 | 2.0 | 26.8 | 43.5 | 40.1 | 77.6 | 40 / 67 |
| cee-pii (451) | Wismut nym alone | hu rows: no Hungarian | 24.8 | 0.2 | 27.7 | 54.6 | 51.4 | 74.8 | 54 / 74 |
| gretel-finance (400) | rules + NER v2.0 |  | 19.0 | 2.5 | 22.5 | 68.8 | 74.2 | 75.6 | 103 / 251 |
| gretel-finance (400) | rules + fallback v1 (bardsai v1) |  | 21.2 | 6.8 | 32.4 | 79.4 | 63.5 | 66.8 | 98 / 154 |
| gretel-finance (400) | rules + bardsai v3 |  | 23.3 | 4.7 | 16.4 | 64.2 | 82.3 | 70.4 | 173 / 364 |
| gretel-finance (400) | rules + Horizon base |  | 23.9 | 7.1 | 19.0 | 64.4 | 80.7 | 68.3 | 138 / 255 |
| gretel-finance (400) | rules + Horizon small |  | 23.7 | 6.2 | 18.8 | 61.6 | 79.8 | 69.5 | 94 / 210 |
| gretel-finance (400) | rules + Wismut nym |  | 21.8 | 5.2 | 27.2 | 73.3 | 71.9 | 64.6 | 187 / 444 |
| gretel-finance (400) | NER v2.0 alone |  | 20.3 | 2.5 | 22.4 | 67.6 | 74.3 | 73.7 | 102 / 173 |
| gretel-finance (400) | bardsai v3 alone |  | 27.8 | 4.9 | 15.1 | 60.8 | 83.6 | 66.7 | 132 / 249 |
| gretel-finance (400) | Horizon base alone |  | 27.6 | 7.0 | 17.9 | 61.8 | 81.7 | 64.0 | 146 / 272 |
| gretel-finance (400) | Horizon small alone |  | 27.0 | 6.5 | 18.1 | 59.0 | 80.6 | 65.8 | 133 / 256 |
| gretel-finance (400) | Wismut nym alone |  | 23.8 | 5.2 | 26.6 | 71.7 | 72.4 | 62.2 | 147 / 276 |

## Latency, load time and size (CPU)

`latency-<model>.json`: 122 messages of about 380 characters from the hu + en synth samples,
NER only, 8 torch threads. As LAB-1386: each run puts pii-guard NER v2.0 and one comparison
model in one process and alternates them per message, so load changes hit both; the models were
run one after another, never two runs at once. Load average 13–19 (1-minute) from unrelated
work during these runs, so absolute numbers are high; the ratio to v2.0 is the result.

| Model | Parameters | Weights | p50 | p95 | v2.0 in the same run, p50 / p95 | load average start → end |
|---|--:|--:|--:|--:|--:|--:|
| bardsai v3 | 308M | 1.23 GB | 88 ms | 144 ms | 55 / 82 ms | 13.0 → 16.7 |
| Horizon base | 308M | 1.23 GB | 88 ms | 119 ms | 53 / 70 ms | 16.7 → 18.9 |
| Horizon small | 141M | 0.56 GB | 51 ms | 82 ms | 50 / 66 ms | 18.9 → 16.6 |
| Wismut nym | 308M | 1.23 GB | 83 ms | 113 ms | 51 / 67 ms | 16.6 → 14.0 |

The base-size mmBERT models cost about 1.6–1.7× v2.0's CPU latency (a 256k-token vocabulary
and a Python word decoder that does not batch); Horizon small matches v2.0 at half its size.
Load times in the JSON (1–6 s) are not comparable: v2.0 loads first and pays the cold start.

## What it shows

- **None beats v2.0 where it matters.** Fast mode with v2.0 leaks 0.0–0.7 % on every
  uncontaminated set except gretel-finance; every comparison model leaks more on smoke,
  agent-traffic-dev, nemotron-pii and cee-pii, at 1.6× the latency (Horizon small: same latency).
- **Hungarian is their weak spot,** except Wismut's: on hu-inflection bardsai v3 leaks 34 % and
  Horizon 16–18 % with the rules, and all three lose Hungarian TAJ and tax numbers on cee-pii
  (alone 20–25 % leak). Wismut, never trained on Hungarian, still leaks 0 % on inflection with
  the rules. bardsai v3 also skips placeholder-looking smoke names ("Jane Example") and tags
  birth dates as `DATE_TIME`, which pii-guard drops.
- **Wismut is the closest on agent traffic** (0.3 % vs 0.1 % leak) but over-masks 20.6 % vs 1.8 %
  (mostly `SECRET`, `BANK_ACCOUNT`, `DATE_OF_BIRTH` and `ADDRESS` spans the gold doesn't mark), and its
  ai4privacy leak is 6.7 %.
- **Where they are ahead:** nemotron-pii recall 96 % (bardsai v3, Horizon) vs 88 % for v2.0, and
  precision 98.5–99.2 % vs 90.9 %; gretel-finance precision 80–82 % vs 74 %. Both are in
  distribution for them (Nemotron-PII train), and neither lowers the leak (2.6 % vs 0.7 %).
- **Against the current fallback** (bardsai v1): v1 leaks less than every new model on smoke,
  inflection and cee-pii; bardsai v3 and Wismut leak less on agent-traffic-dev and ai4privacy.
  No single model is better on the hand-written and Hungarian sets that chose v1 (LAB-1192).

## Recommendation

| Model | Replace the fallback | v3 distillation teacher (LAB-1393) | Otherwise |
|---|---|---|---|
| bardsai v3 | no: worse than v1 on smoke, inflection, cee-pii | **yes, for English and German document-style text** (nemotron-pii / gretel recall and precision), once the owner accepts a card-only Apache-2.0 | |
| Horizon base | no | **yes, same scope**; the cleanest licence (files agree) | |
| Horizon small | no | no: base is the better teacher, same licence | ignore |
| Wismut nym | no: no Hungarian, card-only licence | only as a check for structured agent-traffic text, not as a label source (over-masks, CC-BY-SA-derived labels) | ignore for now |

Neither teacher should label Hungarian, IDs on cee-pii or agent-traffic identifiers: v2.0 is
better there and should keep its own labels. Fast mode keeps NER v2.0; the fallback stays v1.
