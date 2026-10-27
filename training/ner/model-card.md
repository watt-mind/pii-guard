# pii-guard NER (`hdkiller/pii-guard-ner-xlmr-base`)

The token-classification encoder behind [pii-guard](https://github.com/watt-mind/pii-guard)'s
**fast mode** (rules + one NER encoder, in process, no API call). Published release: **v2.0**,
the LAB-1150 checkpoint `xlmr-base-v2-hn`, chosen over a v2.1 retrain in LAB-1306 (see
[Selection](#selection-v2-vs-v21)).

## What it is

- Base: [`FacebookAI/xlm-roberta-base`](https://huggingface.co/FacebookAI/xlm-roberta-base)
  (MIT), 278 M parameters, fine-tuned for 3 epochs (lr 5e-5, warmup 0.1, linear decay, bf16).
- BIO labels named after pii-guard entity types (`training/ner/train.py`, `TYPES_V2`):
  `PERSON`, `ORGANIZATION`, `ADDRESS`, `DATE_OF_BIRTH`, `EMAIL`, `PHONE`, `ID_DOCUMENT`,
  `NATIONAL_ID_HU_TAX`, `NATIONAL_ID_HU_TAJ`, `BANK_ACCOUNT`.
- `config.json` carries `pii_guard_aggregation = "token"` and `pii_guard_labels`, which the
  `ner` detector reads. Weights are `model.safetensors` only.
- **Languages:** Hungarian, English and German. Nothing else was trained or evaluated.

## Intended use

The fast-mode detector in front of an LLM call, **alongside pii-guard's rules**. The NER
proposes spans. The rules keep the final say on structured identifiers (checksums, formats,
legal forms), and `ORGANIZATION` is a keep type by default. It is not a standalone
anonymiser: on its own, without the rules, it is unmeasured.

```bash
# pii-guard downloads and SHA-256-checks it itself (docs/models.md, NER resolution order);
# by hand:
PII_GUARD_NER_MODEL=hdkiller/pii-guard-ner-xlmr-base PII_GUARD_NER_REVISION=v2.0 pii-guard up
```

## Training data

All training data is fictional or public synthetic text. None of it is real personal data.

| Part | Rows | Source | Licence |
|---|---:|---|---|
| Distillation corpus s11 (LAB-1128) | 4,223 train | pii-guard generator with a Muse Spark writer; Muse Glimmer teacher labels | generated |
| Distillation corpus s13 (lexicon packs) | 2,364 train | written and labelled by Muse Glimmer 30B | generated; Glimmer weights Apache-2.0 |
| Ai4Privacy OpenPII-1M **train split** | 5,000 per language (hu/en/de) | [`ai4privacy/pii-masking-openpii-1m`](https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m), pinned revision and file SHA-256 | CC-BY-4.0, Ai4Privacy / Ai Suisse SA |
| Hard negatives (`training/ner/negatives.py`) | 2,000 per language | seeded templates: order, invoice, tracking and case numbers, amounts; no spans | generated |

- **Disjointness.** None of the OpenPII rows is in pii-guard's ai4privacy evaluation sample
  (validation split). `training/ner/openpii.py` checks every uid and every text, and a test
  checks this too.
- **Dates.** OpenPII doesn't say which dates are birth dates, so its date spans are left out
  of the loss.
- `training_meta.json` lists every training file by repository path and SHA-256 prefix, with
  the settings and the per-epoch dev scores.

## Evaluation

rules + this model, scored by `pii-guard eval` (overlap F1, leak = gold values not fully
masked, over-masking = masked spans that aren't gold), in %. Run records and scorecards are in
the repository under `eval/results/2026-10-27-ner-v21/`.

**In-distribution** (the model saw OpenPII train rows, so these are *not* a held-out check):

| Set | F1 | Leak | Over-masking |
|---|---:|---:|---:|
| ai4privacy hu / en / de (validation sample) | 99.3 / 97.7 / 98.3 | 0.5 / 0.2 / 0.3 | 0.9 / 1.1 / 2.3 |

**Held out** (no rows of these sets were used for training or selection, except
`agent-traffic-dev`, which picked v2 over v2.1):

| Set | Leak | Over-masking |
|---|---:|---:|
| pii-guard smoke hu / en / de (hand-written) | 0.0 / 0.0 / 0.0 | 0.9 / 3.0 / 0.0 |
| hu-company-names | 0.0 | 5.7 |
| agent-traffic-dev (LAB-1226, hu+en+de, pooled; selection set) | 1.7 | 11.9 |
| agent-traffic test (LAB-1226, pooled) | 2.6 | 14.0 |
| cee-pii test (hu+en) | 0.4 | **39.4** |
| nemotron-pii test (en) | 0.7 | 1.6 |
| gretel-finance test (en+de) | **19.1** | 23.9 |

The 0.4 % ai4privacy leak is in-distribution. In LAB-1150, an ablation trained without any
Ai4Privacy rows leaked 12.5 % (large) and 13.8 % (base) on that set; that is the honest number
for unseen text in that style.

**Latency** (NER only, ~400-character messages, Apple M1 Max CPU under load 12): p50 47 ms,
p95 55 ms. In LAB-1150: p95 85 ms on a 4-vCPU cloud container, 16 ms on a T4 GPU.

## Limitations

- **Over-masks reference numbers without a cue word** (LAB-1293). Tracking numbers,
  timestamp-style references and order ids in tool output can come out as `BANK_ACCOUNT` or
  `ID_DOCUMENT`: 39 % over-masking on cee-pii, 12–14 % on agent traffic.
- **A street name on its own** can come out as `ADDRESS` (en-smoke "… Street"), because
  OpenPII labels a lone street as an address.
- **Family-firm suffixes:** "és Fia" in Hungarian company names can come out as `PERSON`.
- **Leaks on finance text** (gretel-finance, 19 %), mostly identifiers in unfamiliar formats.
- No username, IP address or URL types. Languages other than hu/en/de are unmeasured.
- In pii-guard a load or inference error raises `DetectionError`, and the gateway blocks the
  call (fail closed).

## Selection: v2 vs v2.1

LAB-1306 retrained the same recipe for 5 epochs, adding 1,500 hard negatives per language
(`training/ner/negatives_v21.py`: reference numbers without a cue, lone streets, family firms as
`ORGANIZATION`), and kept every epoch. The rule was: lowest leak on `agent-traffic-dev`, with
smoke over-masking no worse than v2; on a tie, v2.

| Candidate | agent-traffic-dev leak / over-masking | smoke leak, max | smoke over-masking, max |
|---|---:|---:|---:|
| **v2 (published)** | **1.7** / 11.9 | **0.0** | 3.0 |
| v2.1 epoch 1 | 2.5 / 16.6 | 0.9 | 5.9 |
| v2.1 epoch 2 | 4.8 / 14.3 | 0.9 | 6.1 |
| v2.1 epoch 3 | 3.1 / 12.1 | 1.9 | 0.0 |
| v2.1 epoch 4 | 4.3 / 9.1 | 1.9 | 3.1 |
| v2.1 epoch 5 | 2.4 / 11.2 | 0.9 | 3.0 |

Every v2.1 epoch leaks more than v2 on unseen agent traffic, and leaks on smoke. The new
negatives did fix what they targeted: "és Fia" as PERSON went from 4 spans to 0, the lone
street went away, and cee-pii over-masking dropped from 39.4 to 29.0 % (epoch 5). But they
also taught the model to drop real document ids and e-mails without a cue (uncued ID_DOCUMENT
leaks on agent-traffic-dev went from 5 to 11). v2.1 is not published. The s13 corpus was
regenerated for v2.1 (same seed and model, different LLM text), so the comparison also
includes that difference.

## Licence and attribution

- **This model:** Apache-2.0, the licence of pii-guard.
- XLM-RoBERTa base (Conneau et al. 2020): MIT.
- Ai4Privacy OpenPII-1M: CC-BY-4.0. **Attribution: "Ai4Privacy / Ai Suisse SA"**, which any
  redistribution of this model must carry.
- Muse Glimmer 30B (corpus writer and teacher labels): Apache-2.0 open weights.
- Hungarian name and place lexicons used to generate fictional text: KSH (CC-BY-4.0) and
  OpenStreetMap street names (© OpenStreetMap contributors, ODbL 1.0, non-substantial extract).

The details are in `NOTICE`.

## Reproduce

```bash
uv sync --extra ner
uv run --no-sync python training/ner/openpii.py --source data/public/openpii-train/train.jsonl
uv run --no-sync python training/ner/negatives.py --n 2000 --seed 1150
modal run training/distill/modal_train.py --config training/ner/v2-base-hn.toml --gpu A10G
PII_GUARD_NER_MODEL=models/ner/pii-guard-ner-xlmr-base-v2-hn uv run --no-sync \
    python training/ner/eval_candidates.py --set v21 --candidate xlmr-base-v2-hn --detectors rules,ner
```

The OpenPII rows are the same rows (the manifest's uid hash matches). The rebuilt OpenPII and
negative files don't match the SHA-256 prefixes in `training_meta.json`, because conversion code
and templates changed after this checkpoint was trained. The LLM-written corpora (s11, s13)
rebuild from their response cache; without it, the same plans give different text.
