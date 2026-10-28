# NER v3 candidates vs v2.0 (2026-10-28)

LAB-1393. Two candidates trained on a wider, decontaminated data mix, scored against the
published `hdkiller/pii-guard-ner-xlmr-base` **v2.0** (revision `95f612a9`) on the full
fast-mode suite plus pl-pii-bench and MAPA EUR-Lex (LAB-1392). **Recommendation: keep v2.0.**
No candidate passes the selection rule. The XLM-R base candidate comes closest, but it leaks
one Hungarian name on hu-smoke. Nothing was published and the production default is unchanged.

## Selection

The rule was fixed in the ticket before training: **lowest agent-traffic-dev leak, no
smoke-set regression, CPU p95 within 1.5× of v2.0.**

| Candidate | agent-traffic-dev leak | smoke leak / over-mask | CPU p95 vs v2.0 | Passes |
|---|--:|--:|--:|---|
| v2.0 (published) | 0.13 % | 0.0 % / 1.1 % | 1.00× (68.2 ms) | baseline |
| v3 XLM-R base | **0.0 %** | 0.6 % / 2.7 % | 0.98× (66.5 ms) | **no**: smoke regression (one hu PERSON leaked, over-masking 1.1 → 2.7 %) |
| v3 mmBERT-base | 0.0 % | 5.8 % / 3.4 % | 1.55× (105.7 ms) | **no**: smoke regression, and p95 over 1.5× |

**agent-traffic-dev is not a fair selector for v3.** The v3 mix includes 1,800 train-only
documents from the same agent-traffic generator (seed 1393). None of them is a near-copy of a
dev or test document (highest word 5-gram Jaccard 0.42 against the dev split, gate threshold
0.8). They do share its templates, though, so both candidates are in distribution on
agent-traffic and agent-traffic-dev. That explains their perfect 0.0 % leak and 0.0 %
over-masking there. The sets that are out of distribution for every model are a better guide.

## Results (rules + NER, fast mode, CPU)

Overlap matching. Run records are in `eval/results/runs/2026-10-28-lab-1393-<set>-<candidate>.json`;
the per-set summaries are in `summary-*.json`. The scoring ran on this branch, on a loaded
machine (load average 11 to 17). Compare the latency columns with each other only.

| set (docs) | system | leak % | partial leak % | over-mask % | recall % | precision % | detect p50 / p95 ms |
|---|---|--:|--:|--:|--:|--:|--:|
| smoke (51) | v2.0 (published) | 0.0 | 2.9 | 1.1 | 93.3 | 95.3 | 50 / 72 |
| smoke (51) | v3 XLM-R base | 0.6 | 2.3 | 2.7 | 93.8 | 94.3 | 35 / 59 |
| smoke (51) | v3 mmBERT-base | 5.8 | 5.8 | 3.4 | 86.6 | 93.4 | 54 / 78 |
| inflection (12) | v2.0 (published) | 2.0 | 30.0 | 0.0 | 93.4 | 100.0 | 62 / 71 |
| inflection (12) | v3 XLM-R base | 0.0 | 8.0 | 0.0 | 100.0 | 100.0 | 33 / 38 |
| inflection (12) | v3 mmBERT-base | 12.0 | 36.0 | 0.0 | 75.4 | 100.0 | 53 / 64 |
| agent-traffic-dev (300) | v2.0 (published) | 0.1 | 0.1 | 1.8 | 97.9 | 95.7 | 76 / 138 |
| agent-traffic-dev (300) | v3 XLM-R base | 0.0 | 0.0 | 0.0 | 99.7 | 99.6 | 48 / 74 |
| agent-traffic-dev (300) | v3 mmBERT-base | 0.0 | 0.0 | 0.0 | 99.7 | 99.6 | 89 / 138 |
| agent-traffic (990) | v2.0 (published) | 0.2 | 0.0 | 1.7 | 97.4 | 95.4 | 73 / 126 |
| agent-traffic (990) | v3 XLM-R base | 0.0 | 0.0 | 0.0 | 99.4 | 99.3 | 48 / 69 |
| agent-traffic (990) | v3 mmBERT-base | 0.0 | 0.0 | 0.0 | 99.7 | 99.6 | 83 / 131 |
| ai4privacy (600) | v2.0 (published) | 0.4 | 0.1 | 1.3 | 98.9 | 98.0 | 62 / 115 |
| ai4privacy (600) | v3 XLM-R base | 0.5 | 0.1 | 0.6 | 98.6 | 98.4 | 39 / 59 |
| ai4privacy (600) | v3 mmBERT-base | 1.0 | 1.1 | 2.0 | 98.2 | 97.1 | 63 / 121 |
| nemotron-pii (300) | v2.0 (published) | 0.7 | 0.4 | 1.4 | 87.8 | 90.9 | 100 / 275 |
| nemotron-pii (300) | v3 XLM-R base | 1.0 | 0.9 | 1.2 | 95.9 | 95.7 | 51 / 164 |
| nemotron-pii (300) | v3 mmBERT-base | 4.4 | 2.6 | 1.5 | 88.6 | 94.7 | 100 / 309 |
| cee-pii (451) | v2.0 (published) | 0.4 | 0.2 | 26.4 | 97.2 | 71.9 | 48 / 84 |
| cee-pii (451) | v3 XLM-R base | 0.4 | 0.0 | 20.2 | 97.0 | 73.6 | 32 / 46 |
| cee-pii (451) | v3 mmBERT-base | 5.6 | 1.8 | 34.6 | 91.9 | 63.4 | 56 / 89 |
| gretel-finance (400) | v2.0 (published) | 19.0 | 2.5 | 22.5 | 68.8 | 74.2 | 140 / 424 |
| gretel-finance (400) | v3 XLM-R base | 21.2 | 4.4 | 22.0 | 67.3 | 75.4 | 92 / 330 |
| gretel-finance (400) | v3 mmBERT-base | 26.5 | 10.0 | 24.4 | 57.7 | 72.0 | 183 / 392 |
| pl-pii-bench (346) | v2.0 (published) | 17.5 | 7.8 | 10.4 | 75.3 | 84.4 | 51 / 323 |
| pl-pii-bench (346) | v3 XLM-R base | 8.7 | 6.5 | 19.4 | 89.7 | 77.5 | 36 / 221 |
| pl-pii-bench (346) | v3 mmBERT-base | 31.8 | 8.5 | 59.3 | 65.7 | 40.0 | 50 / 689 |
| mapa-eur-lex (42) | v2.0 (published) | 8.5 | 0.1 | 55.6 | 77.3 | 41.8 | 4400 / 7278 |
| mapa-eur-lex (42) | v3 XLM-R base | 15.0 | 0.3 | 46.8 | 72.6 | 38.5 | 2620 / 3670 |
| mapa-eur-lex (42) | v3 mmBERT-base | 47.7 | 7.8 | 79.3 | 32.5 | 16.5 | 5109 / 8406 |

What v3 XLM-R base changes, against v2.0:

- **Better.** pl-pii-bench leak goes 17.5 → 8.7 %; the new Polish OpenPII and Wismut rows
  help. nemotron-pii recall goes up (F1 0.89 → 0.96) at about the same leak (0.7 → 1.0 %).
  cee-pii over-masking falls 26.4 → 20.2 %, hu-inflection leak 2.0 → 0.0 % and partial leak
  30 → 8 %. ai4privacy over-masking falls 1.3 → 0.6 %.
- **Worse.** hu-smoke leaks one PERSON value (v2.0 none). MAPA EUR-Lex leak goes
  8.5 → 15.0 % (42 long legal documents, mostly names; the spans in languages other than
  English are LLM projections). gretel-finance leak goes 19.0 → 21.2 %, and pl-pii-bench
  over-masking goes 10.4 → 19.4 %.
- **mmBERT-base is worse on almost every set** that is out of distribution. pl-pii-bench leak
  is 31.8 %, MAPA 47.7 % and cee-pii 5.6 %, and it is 1.5× slower on CPU. With the same data,
  the encoder choice matters: XLM-R base stays.

## CPU latency

[`latency-cpu.json`](latency-cpu.json): 122 messages of about 380 characters from the hu and en
synth samples. The three models run in one process, alternating per message, NER only, with 8
torch threads, on an Apple M-series machine at load average 12 to 18.

| Model | p50 | p95 | p95 vs v2.0 |
|---|--:|--:|--:|
| v2.0 | 48.7 ms | 68.2 ms | 1.00× |
| v3 XLM-R base | 48.3 ms | 66.5 ms | 0.98× |
| v3 mmBERT-base | 71.8 ms | 105.7 ms | 1.55× |

## Data

The manifests are [`training/ner/v3-data-manifest.json`](../../../training/ner/v3-data-manifest.json)
(every source with its revision, file SHA-256, licence, attribution, counts and id hashes) and
[`training/ner/v3-openpii-train-manifest.json`](../../../training/ner/v3-openpii-train-manifest.json).
No rows are committed.

| Source | Licence | Train docs | XLM-R tokens | Share |
|---|---|--:|--:|--:|
| Ai4Privacy OpenPII-1M **train**, hu/en/de 5,000 each, pl/cs/sk/ro/hr/sl 2,500 each | CC-BY-4.0 | 30,000 | 2.69 M | 36.5 % |
| `piimb/privy` (JSON, SQL, HTML, XML traces) | MIT | 12,000 | 1.39 M | 18.9 % |
| pii-guard distillation corpus s11 (LAB-1128) | Apache-2.0 | 4,223 | 1.21 M | 16.4 % |
| `Wismut/nym-pii-multilingual-data`, en/de/pl/cs/ro | MIT | 13,000 | 1.00 M | 13.6 % |
| `nvidia/Nemotron-PII` **train** | CC-BY-4.0 | 1,500 | 0.36 M | 4.8 % |
| `gretelai/gretel-pii-masking-en-v1` **train** | Apache-2.0 | 2,500 | 0.16 M | 2.2 % |
| v2 hard negatives (seed 1150) | Apache-2.0 | 6,000 | 0.29 M | 4.0 % |
| agent-traffic generator, train-only seed 1393 | Apache-2.0 | 1,800 | 0.27 M | 3.6 % |

The dev split, used only by the training loop to pick an epoch, is OpenPII dev (100 per
language) plus the s11 dev files. XLM-R picked epoch 2 and mmBERT epoch 3.

- **Labels.** Conversion goes through the evaluation's own converter, so the merge rules
  match the scorer. Every label without a pii-guard NER type goes into the loss-ignore
  regions: it is taught neither as an entity nor as `O`. That covers SECRET, URL, IP and
  passwords (they stay with the rules), dates that aren't birth dates, and the GDPR special
  categories, such as medical record numbers.
- **Teacher.** `Horizon-Labs/pii-redactor-base` @ `42dfb0d` (Apache-2.0, with LICENSE and
  NOTICE files) read the English and German documents of Privy, Wismut, Nemotron and Gretel.
  Wherever it tagged personal data outside every gold span, the region left the loss. Gold
  spans were never changed. Polish, Czech and Romanian rows, and all Hungarian text, keep
  their generated gold. The regions added per file are in [`teacher-audit.json`](teacher-audit.json):
  19,629 in Privy, 5,146 in Wismut en/de, 241 in Nemotron and 483 in Gretel. LAB-1391 picked
  this teacher; bardsai v3 is not used.
- **Decontamination.** [`decontam.json`](decontam.json) shows that the gate dropped
  **0 of 72,664** train and dev documents. It compared them with 3,416 evaluation documents
  (every test set and every `eval/fixtures` file). `train.py` ran the gate again on Modal and
  also dropped 0. That gate did not index the agent-traffic **dev** split, so it was checked
  by hand: no near-copies, highest J = 0.42. Since LAB-1409 the gate indexes it (300
  documents, set `agent-traffic-dev`). Re-run on the 1,800 regenerated agent-traffic train
  documents of this config (`decontam.py --config training/ner/v3-xlmr-base.toml
  --allow-missing`; the downloaded sources were not on disk): 0 exact and 0 near copies of
  agent-traffic-dev, highest exact J = 0.423.

**Left out:**

- **FineWeb-2 teacher-labelled text** (planned at 15 %). It is real web text, and ADR 0005
  allows no real personal data in training. The owner decides that in a follow-up issue.
- **distill-s13.** It is not on disk, and it would have to be regenerated by an LLM.
- **The v2.1 uncued-ID negatives.** They caused the v2.1 ID and e-mail leaks.
- No CC-BY-SA, non-commercial or gated data was used: no NerKor and no Universal NER.

## Training and compute

`training/distill/modal_train.py` ran each candidate on one A10G for 3 epochs, using the same
settings as v2 (lr 5e-5, warmup 0.1, bf16, batch 16, 512 tokens, stride 128). Their
`training_meta-*.json` files are here.

- **XLM-R base**: `FacebookAI/xlm-roberta-base` @ `e73636d`, 35.5 min.
- **mmBERT-base**: `jhu-clsp/mmBERT-base` @ `ca5b84b`. That is the safetensors revision from
  the conversion pull request, so nothing was unpickled. It took 33.7 min. Its exact-span dev
  F1 is low (0.41) only because its tokenizer's offsets include the leading space. The
  detector trims that, and overlap F1 is 0.97.

Modal used free credits only: **about $2.8 in total, of which 2.3 A10G-hours** went to
training, the teacher audit and data preparation. The total includes two trainings, about
0.9 A10G-hours, that were stopped after the teacher changed. Every app is stopped. The volume
keeps only the two final checkpoints; the per-epoch copies and the intermediate data were
deleted.

## Reproduce

```
modal run training/ner/modal_v3.py                      # prep (CPU) + teacher audit (A10G)
modal volume get pii-guard-ner-runs v3-data <dir>       # then assemble eval/generated/v3-pregate
# decontam.gate over every file -> eval/generated/v3-final (see decontam.json)
modal run training/distill/modal_train.py --config training/ner/v3-xlmr-base.toml --gpu A10G
modal run training/distill/modal_train.py --config training/ner/v3-mmbert-base.toml --gpu A10G
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/eval_v3.py score --candidate v20 --record
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/eval_v3.py score \
    --candidate xlmr-v3 --model models/ner/pii-guard-ner-xlmr-base-v3 --record
uv run --no-sync python training/ner/eval_v3.py latency --model v20= \
    --model xlmr-v3=models/ner/pii-guard-ner-xlmr-base-v3 --model mmbert-v3=models/ner/pii-guard-ner-mmbert-base-v3
```

## Next

v3 XLM-R base is the starting point for a v3.1:

- fix the Hungarian person leak and the MAPA and gretel regressions, for example with more
  Hungarian gold and a higher share of the v2 mix;
- choose a selection set that no candidate trains on.

Both are filed as follow-ups.
