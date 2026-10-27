# NER v2.1 vs v2, and the published checkpoint (2026-10-27)

LAB-1306. Train a short v2.1, pick v2.1 or v2 on unseen data, publish the winner to Hugging
Face as `hdkiller/pii-guard-ner-xlmr-base`. **Winner: v2** (`xlmr-base-v2-hn`, LAB-1150),
published as release `v2.0`.

Every number comes from `scorecards/` (rules + NER, `training/ner/eval_candidates.py`) and the
run records `eval/results/runs/2026-10-27-ner-v21-<fixture>-<candidate>.json`. `table.md`
has every fixture × candidate row. All runs used the same tree (develop after LAB-1192,
LAB-1215, LAB-1226 and LAB-1279).

## v2.1

The v2 base + hard negatives recipe (`training/ner/v2-base-hn.toml`) with two changes
(`training/ner/v21-base-hn.toml`):

- **5 epochs instead of 3.** Warmup 0.1 and linear decay as before. Every epoch is saved
  (`save_epochs`), and the per-epoch dev scores are in `training_meta.json`.
- **1,500 more hard negatives per language** (`training/ner/negatives_v21.py`, seed 1306):
  - half are reference, tracking, order, invoice and ticket numbers in prose, JSON, CSV and
    log lines, with a generic cue (`Ref.`, `#`, `Nr.`) or none. A number that passes an
    IBAN, giro, TAJ, tax ID, personal ID or Luhn check is redrawn. No spans;
  - a quarter are a lone street name with no number and no town. A third of these also hold
    a full fictional address labelled `ADDRESS`;
  - a quarter are family firms (`Balogh és Fia Kft.`, `Ashcombe & Sons Ltd`,
    `Gebrüder Kessler GmbH`), labelled `ORGANIZATION` as a whole. In Hungarian the rules still
    mask the surname as `PERSON`, as docs/entities.md says.

  A street or firm name that occurs in any evaluation text (`eval/fixtures`, `eval/synthetic`,
  `eval/datasets`) is redrawn.

**Data rebuilt.** The v2 training files were not on disk any more (`eval/generated/` is
gitignored and the LAB-1150 worktree is gone). This is how each part was rebuilt:

- s11 was copied from the LAB-1128 worktree, and its hashes match v2's `training_meta.json`;
- the OpenPII rows were rebuilt from the pinned file. The manifest check passes (same uids),
  but the file bytes differ from v2's hashes because conversion code changed after LAB-1150;
- the v2 negatives were rebuilt from seed 1150. Their bytes differ too, because the templates
  changed after training;
- s13 was **regenerated** by Muse Glimmer on Modal with the same seed and plans: 1,381 hu and
  1,416 en documents accepted (v2: 1,371 / 1,409). The plans are the same, but the LLM text is
  not, so v2 vs v2.1 also differs in this corpus.

Dev scores during training (P / R / F1 overlap, the training loop's own pick):

| Epoch | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| v2 (3 epochs) | .919/.991/.954 | .916/.996/.954 | .935/.996/.965 | | |
| v2.1 | .920/.994/.956 | .913/.994/.952 | **.955/.988/.971** | .920/.996/.957 | .928/.997/.961 |

## Selection (rules + NER, %)

The rule was set before training: **lowest leak on `agent-traffic-dev`** (LAB-1226's dev split,
300 tool-call, log, CSV and chat documents, 100 per language, never trained on), with smoke
over-masking ≤ v2; on a tie, v2.

| Candidate | agent-traffic-dev leak / over-masking | smoke leak, max | smoke over-masking, max | hu-company-names over-masking | ai4privacy leak, pooled (in-distribution) |
|---|---:|---:|---:|---:|---:|
| **v2** | **1.7** / 11.9 | **0.0** | 3.0 | 5.7 | 0.4 |
| v2.1 e1 | 2.5 / 16.6 | 0.9 | 5.9 | | 0.5 |
| v2.1 e2 | 4.8 / 14.3 | 0.9 | 6.1 | | 0.5 |
| v2.1 e3 | 3.1 / 12.1 | 1.9 | 0.0 | 0.0 | 0.8 |
| v2.1 e4 | 4.3 / 9.1 | 1.9 | 3.1 | | 0.4 |
| v2.1 e5 | 2.4 / 11.2 | 0.9 | 3.0 | 0.0 | 0.3 |

Every v2.1 epoch leaks more than v2 on unseen agent traffic and leaks on smoke, so **v2 wins**.

**What changed.** The new negatives fixed the LAB-1220 cases:

- "Fia" / "Fiai" as `PERSON` went from 4 spans to 0;
- the lone en-smoke street went away at epoch 3.

They also taught the model that a number or address without a cue is not personal data:

- uncued `ID_DOCUMENT` leaks on agent-traffic-dev went from 5 to 11–12 values;
- e-mail leaks went from 12 to 15–16;
- hu-smoke leaked one or two names.

The negatives' reference numbers are too close to real document ids in tool output. A next
try should keep the uncued numbers out (or pair each one with a labelled id in the same
document) and keep the street and firm negatives.

## Held out (scored once, after the choice)

The LAB-1226 **test** sets, pooled over their languages, for v2 and the best v2.1 epoch. They
played no part in the choice.

| Candidate | agent-traffic | cee-pii | nemotron-pii | gretel-finance |
|---|---:|---:|---:|---:|
| v2 | 2.6 / 14.0 | 0.4 / **39.4** | 0.7 / 1.6 | **19.1** / 23.9 |
| v2.1 e5 | 3.4 / 12.4 | 0.4 / 29.0 | 0.7 / 2.4 | 19.9 / 24.4 |

(leak / over-masking). They agree with the selection on leak. v2.1 would help on cee-pii
over-masking (LAB-1293), but not enough to accept the extra leak.

## Latency

`training/ner/bench_latency.py --devices cpu`, M1 Max CPU at load average 12, NER only:

| Model | p50 | p95 |
|---|---:|---:|
| v2 | 46.6 ms | 54.9 ms |
| v2.1 e5 | 44.6 ms | 54.6 ms |
| v2.1 e3 | 43.2 ms | 51.9 ms |

The architecture is the same, so the latency is the same. JSON is in `latency/`.

## Published

| | |
|---|---|
| Repo | [`hdkiller/pii-guard-ner-xlmr-base`](https://huggingface.co/hdkiller/pii-guard-ner-xlmr-base) (public) |
| Release tag | `v2.0` |
| Revision | `95f612a9ad65cc5ade5b9248bd152020541e7097` |
| `model.safetensors` SHA-256 | `4a9a598f6be493fab8bf81916e8c5d775e2559c91f42f58891dfe2ab7a2543e9` |
| Files | `model.safetensors`, `config.json`, `tokenizer.json`, `tokenizer_config.json`, `training_meta.json` (no local paths), `README.md` (the model card), `NOTICE` |
| Licence | Apache-2.0; trained on Ai4Privacy OpenPII-1M (CC-BY-4.0), attribution "Ai4Privacy / Ai Suisse SA" |

`training/ner/publish_hf.py` stages and uploads it with the local Hugging Face login, then
tags the commit. `pii_guard.detect.ner_resolve.PUBLISHED` pins the revision and the hash.
From an empty model cache, `make smoke-fast` downloads the model, checks it and masks the
NER-only scenario (`hu-needs-ner`).

## Spend

Modal month-to-date was $11.36 before and $14.28 after: **$2.92**, all free credits.

- Muse Glimmer on an H100 regenerated and labelled s13: 21:11–21:49 plus the scale-down, $2.67.
- One A10G training run, 18 minutes: $0.25.

No other paid APIs. Evals and latency ran locally. No Modal app is left running.

## Reproduce

```bash
uv run --no-sync python training/ner/openpii.py --source data/public/openpii-train/train.jsonl
uv run --no-sync python training/ner/negatives.py --n 2000 --seed 1150
uv run --no-sync python training/ner/negatives_v21.py --n 1500 --seed 1306
modal run training/distill/modal_train.py --config training/ner/v21-base-hn.toml --gpu A10G
modal volume get pii-guard-ner-runs pii-guard-ner-xlmr-base-v21-hn models/ner/
PII_GUARD_NER_MODEL=models/ner/pii-guard-ner-xlmr-base-v21-hn/epoch-5 uv run --no-sync \
    python training/ner/eval_candidates.py --set v21 --candidate xlmr-base-v21-hn-e5 \
    --detectors rules,ner --out eval/results/2026-10-27-ner-v21/scorecards
uv run --no-sync python training/ner/table.py eval/results/2026-10-27-ner-v21/scorecards \
    --out eval/results/2026-10-27-ner-v21/table.md
uv run --no-sync python training/ner/records.py eval/results/2026-10-27-ner-v21/scorecards --prefix ner-v21
```
