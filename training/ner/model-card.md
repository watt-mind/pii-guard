# Model card: pii-guard NER v2 (`xlmr-base-v2-hn`)

> **Not published.** The weights from this ticket (LAB-1150) live only under the gitignored `models/` directory.
> They are not committed, and they are not uploaded to Hugging Face or anywhere else. The owner decides
> whether to publish them. Everything below is enough to retrain the model from public and synthetic data.

## What it is

A token-classification encoder for the `ner` detector in pii-guard's fast mode, which runs as
rules + NER. The base is [`FacebookAI/xlm-roberta-base`](https://huggingface.co/FacebookAI/xlm-roberta-base)
(MIT), with 278 M parameters. BIO labels are named after pii-guard entity types
(`training/ner/train.py`, `TYPES_V2`):

`PERSON`, `ORGANIZATION`, `ADDRESS`, `DATE_OF_BIRTH`, `EMAIL`, `PHONE`, `ID_DOCUMENT`,
`NATIONAL_ID_HU_TAX`, `NATIONAL_ID_HU_TAJ`, `BANK_ACCOUNT`.

The NER **proposes** spans, and the rules keep the final say on structured identifiers. When a
validated rule span overlaps an NER span of the same type, the rule's boundaries win
(`DetectionPipeline`). See [docs/entities.md](../../docs/entities.md#ner-label-set) for how the
labels map.

**Languages:** Hungarian, English and German. The tokenizer and base model cover about 100
languages, but no other language was trained or evaluated.

The large variant, `xlmr-large-v2-hn`, has 560 M parameters and was trained the same way with
lr 2e-5. It is the "best quality" option where latency allows.

## Training data

All training data is fictional or public. None of it is real customer data.

| Part | Rows | Source | Licence |
|---|---:|---|---|
| Distillation corpus s11 (LAB-1128) | 4,223 train | Generator + Muse Spark writer, Muse Glimmer teacher labels | fictional, generated |
| Distillation corpus s13 (lexicon packs, LAB-1126) | 2,364 train (+416 dev) | Written and labelled by Muse Glimmer 30B on Modal | fictional, generated; Glimmer weights Apache-2.0 |
| Ai4Privacy OpenPII-1M **train split** | 5,000 per language (hu/en/de) + 150 dev | [`ai4privacy/pii-masking-openpii-1m`](https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m), pinned revision and file SHA-256 | CC-BY-4.0, © Ai4Privacy / Ai Suisse SA |
| Hard negatives (`training/ner/negatives.py`) | 2,000 per language | Seeded templates: order, invoice, tracking and case numbers, amounts; no gold spans | generated |

- **Disjointness.** None of the OpenPII rows is in the evaluated validation sample
  (`eval/fixtures/public/ai4privacy-openpii-1m.json`). `training/ner/openpii.py` checks every
  uid and every text and refuses to write on any overlap, and
  `tests/training/test_openpii_train.py` checks this too. The manifest
  (`training/ner/openpii-train-manifest.json`) records 0 overlaps. Only the manifest and the
  script are committed, never the rows.
- **Dates.** OpenPII marks every date as DATE but doesn't say which ones are birth dates. Its
  date spans are therefore left out of the loss (`meta.loss_ignore`) rather than trained as
  `DATE_OF_BIRTH` or as "not personal data".
- **Hard negatives.** These exist because OpenPII alone taught the model to mask every
  reference number (6–11 % over-masking on the smoke sets). Their cue words are generic
  business terms, and some also appear in the smoke sets (for example `Rendelésszám`,
  `Bestellnummer`, `Tracking number`). The smoke over-masking gain should be read with that in
  mind.

## Evaluation

The full tables and method are in
[eval/results/2026-10-27-ner-v2/README.md](../../eval/results/2026-10-27-ner-v2/README.md).

**Caveat:** the model saw Ai4Privacy *train* rows, so its ai4privacy scorecards are in-distribution
and are **not** an out-of-distribution check. The `xlmr-large-v2-no-ai4privacy` ablation is the
honest held-out number on that set.

## Intended use and limits

- **Intended use:** the self-hosted fast-mode detector in front of an LLM call, alongside the
  rules. It is not a standalone anonymiser.
- **Known misses:**
  - It can mark a street name standing alone as `ADDRESS`, because OpenPII labels a lone
    STREET as an address, which conflicts with policy.
  - It can mark "és Fia" in Hungarian company names as `PERSON`.
  - It has no username, IP or URL types.
  - Leak on running-text identifiers outside its three languages is unmeasured.
- **Fail closed:** a load or inference error raises `DetectionError`, and the gateway blocks the call.

## Reproduce

```bash
uv sync --extra ner
uv run --no-sync python training/ner/openpii.py            # needs data/public/openpii-train/train.jsonl (pinned SHA-256)
uv run --no-sync python training/ner/negatives.py --n 2000 --seed 1150
modal run training/distill/modal_train.py --config training/ner/v2-base-hn.toml --gpu A10G
modal volume get pii-guard-ner-runs pii-guard-ner-xlmr-base-v2-hn models/ner/
PII_GUARD_NER_MODEL=models/ner/pii-guard-ner-xlmr-base-v2-hn uv run --no-sync \
    python training/ner/eval_candidates.py --candidate xlmr-base-v2-hn --detectors rules,ner
```

## Attribution and licences

- XLM-RoBERTa: Conneau et al. 2020; weights `FacebookAI/xlm-roberta-base` / `-large`, MIT.
- Ai4Privacy OpenPII-1M: CC-BY-4.0, attribution "Ai4Privacy / Ai Suisse SA". A model trained on
  it and redistributed must carry this attribution.
- GLiNER multi v2.1 (`urchade/gliner_multi-v2.1`, evaluated as an alternative and wired in as
  `ner_gliner`): Apache-2.0. Zaratiana et al. 2024.
- Muse Glimmer 30B (corpus writer and teacher, served on our own Modal GPU): Apache-2.0 open weights.
