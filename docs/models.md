# Models and partners

> Status: partly verified. The Meta Model API facts below were checked with live calls on
> fictional text (2026-10-26); Muse Spark Open on Baseten Model APIs was called, recorded and
> evaluated on fictional text (2026-10-27). Credit amounts: see [roadmap.md](roadmap.md).

## Which model does what

| Job | Model | Where it runs | Sees real data? |
|---|---|---|---|
| Structured identifiers | Rules (no model) | pii-guard container | yes (inside the boundary) |
| Names, organizations, addresses, dates of birth and (NER v2) contact and ID numbers the rules can't validate | Multilingual NER encoder (XLM-RoBERTa-base, open; GLiNER as an alternative backend) | pii-guard container (CPU / MPS / CUDA) | yes |
| Second-pass detection and adjudication (audit mode, opt-in; fast mode, rules + NER, is the production default) | **Muse Spark Open** (open weights), optionally fine-tuned; **Muse Glimmer** as a smaller local candidate | Baseten (`meta-models/muse-spark-open-1026`), or your own hardware | yes |
| Faces, ID photos | **YuNet** (OpenCV model zoo, 0.23 MB, MIT; the default `hybrid` segmenter, see [Local segmentation](#local-segmentation)) | pii-guard container (CPU) | yes |
| Signatures (and faces with `PII_GUARD_SEGMENTER=sam-api`) | **SAM 3.1** | Meta Model API, or a GPU endpoint (`PII_GUARD_SAM_URL`) | yes |
| OCR | Open OCR engine | pii-guard container or GPU endpoint | yes |
| Synthetic corpus generation | **Muse** (Wonder for documents, Spark for variations) | Meta Model API | **no**: fictional data only |
| The downstream model in the demo | **Muse Spark** | Meta Model API | **no**: only masked data |

The rule behind this table: **anything that sees real personal data is an open-weights model
you can host yourself.** Hosted Meta models only ever see fictional data or masked data.

## NER detector

`pii_guard.detect.ner.NerDetector` (registry name `ner`) runs a Hugging Face token-classification
encoder in-process and reports `PERSON`, `ADDRESS`, `ORGANIZATION` and, with the fine-tuned
model, `DATE_OF_BIRTH`. NER v2 checkpoints also report `EMAIL`, `PHONE`, `ID_DOCUMENT`,
`NATIONAL_ID_HU_TAX`, `NATIONAL_ID_HU_TAJ` and `BANK_ACCOUNT`; see
[NER v2](#ner-v2-wider-labels-openpii-train-split-hard-negatives). Rules stay authoritative for structured identifiers in
`DetectionPipeline`. Install with `uv sync --extra ner` (torch, transformers, sentencepiece,
protobuf). Without the extra the registry reports `ner` as unavailable, so the gateway's fast
mode stays rules-only; with it, fast mode picks `ner` up automatically. A model that can't be
loaded and any inference error raise `DetectionError` (fail closed).

| Setting | Env var | Default |
|---|---|---|
| Model (hub id or directory) | `PII_GUARD_NER_MODEL` | unset: the published checkpoint, else the public fallback ([below](#which-ner-model-fast-mode-runs)) |
| Revision | `PII_GUARD_NER_REVISION` | pinned for the published and fallback models |
| Published checkpoint | `PII_GUARD_NER_PUBLISHED_MODEL` | `hdkiller/pii-guard-ner-xlmr-base`, used once pinned (LAB-1306); `repo` or `repo@revision` |
| Fallback | `PII_GUARD_NER_FALLBACK` | `download`: fetch it on first use; `cached`: only if already downloaded; `off`: never |
| Model cache | `PII_GUARD_MODELS_DIR` | `~/.cache/pii-guard/models` |
| Device | `PII_GUARD_NER_DEVICE` | `auto`: CUDA, then Apple MPS, then CPU |
| Backend | `PII_GUARD_NER_BACKEND` | `transformers`; `gliner` runs a GLiNER model instead (needs the `gliner` extra) |
| GLiNER model | `PII_GUARD_GLINER_MODEL` | `urchade/gliner_multi-v2.1` (pinned revision) |

Constructor keywords: `thresholds` (`{language: {type: min_score}}`, default 0.5), `entity_types`,
`label_map`, `max_length`/`stride` (token windows for long inputs), `aggregation`, `preload`.
Offsets come from the fast tokenizer's offset mapping (code points), so they are exact for any
Unicode input. Fetch the model ahead of time with
`uv run --extra ner python -m pii_guard.detect.ner_resolve fetch` (`status` prints which model
would run, without downloading).

### Which NER model fast mode runs

`pii_guard.detect.ner_resolve` picks the model, first match wins (LAB-1192):

1. **`PII_GUARD_NER_MODEL`**, a local directory or a hub id (with `PII_GUARD_NER_REVISION`).
   If it is set and can't load, startup stops (fail closed, ADR 0006).
2. **The published pii-guard checkpoint**, `hdkiller/pii-guard-ner-xlmr-base`
   (`PII_GUARD_NER_PUBLISHED_MODEL`). The owner decided to publish the trained XLM-R base
   NER there; LAB-1306 trains it and pins its revision and SHA-256 in
   `pii_guard.detect.ner_resolve.PUBLISHED`. A checkpoint is never loaded unpinned, so until
   that lands this step is skipped (or set `repo@revision` yourself).
3. **The public fallback**, a **stop-gap** so that fast mode is rules + NER from a clean
   checkout until step 2 is pinned:
   [`bardsai/eu-pii-anonimization-multilang`](https://huggingface.co/bardsai/eu-pii-anonimization-multilang)
   at revision `62ca5712368705bac11b8fea19e42e65cce088dd`. It leaks little but **over-masks:
   about 23 % on en-smoke** (below).

`make demo`, `make smoke-fast`, `docker compose --profile demo up` and the banners print the
line `rules + NER: <model>@<revision> (public fallback, Apache-2.0)`, or why it is rules only.
The fallback is downloaded on first use with `huggingface_hub.snapshot_download` at the pinned
revision, only the four files the detector reads (1.1 GB, mostly `model.safetensors`), into
`~/.cache/pii-guard/models/ner/bardsai--eu-pii-anonimization-multilang-62ca57123687/`. The
weights are then checked against their pinned SHA-256 and loaded from that directory, so later
runs are offline. No weights are committed to this repository. `PII_GUARD_NER_FALLBACK=off`
(what `make demo MODE=rules` and `make smoke` set) keeps fast mode rules only.

**Licence and attribution.** The model card at the pinned revision declares
`license: apache-2.0`. The model is by [bards.ai](https://bards.ai): XLM-RoBERTa base
(FacebookAI, MIT) fine-tuned for 36 PII classes in the 24 official EU languages, Hungarian,
English and German among them. Its card names the training data:
`ai4privacy/pii-masking-openpii-1m`, `piimb/privy` and `nvidia/Nemotron-PII`, plus proprietary
data. Its labels are mapped in `LABEL_MAP` (`src/pii_guard/detect/ner.py`): `PERSON_NAME` →
`PERSON`, `ORGANIZATION_NAME` → `ORGANIZATION`, `POSTAL_ADDRESS` and `LOCATION` → `ADDRESS`,
`EMAIL_ADDRESS`, `PHONE_NUMBER`, `DOCUMENT_IDENTIFIER` and `PERSON_IDENTIFIER` →
`ID_DOCUMENT`, `BANK_ACCOUNT_IDENTIFIER` and `PAYMENT_CARD` → `BANK_ACCOUNT`, `DATE_OF_BIRTH`.
Its other classes (health data, IP addresses, amounts…) are not pii-guard types and are
ignored.

**Why this model.** The ticket's three options were GLiNER multi v2.1 through the `gliner`
extra, Davlan's XLM-R through the existing `ner` extra, or another Apache/MIT token
classifier. All three run zero-shot here (rules + model, the LAB-1150 fixture list,
[eval/results/2026-10-27-fast-demo-ner/](../eval/results/2026-10-27-fast-demo-ner/README.md)):

| | bardsai EU PII v1 (chosen) | GLiNER multi v2.1 | Davlan XLM-R base (old default) |
|---|---:|---:|---:|
| smoke leak, hu / en / de | **1.9 / 0.0 / 0.0 %** | 2.8 / 3.3 / 5.4 % | 7.5 / 10.0 / 8.1 % |
| smoke F1, hu / en / de | 91.7 / 88.3 / 98.8 | 95.1 / 94.4 / 91.6 | 93.7 / 90.7 / 96.1 |
| smoke over-masking, max | 23.1 % (en) | 10.0 % | 10.8 % |
| ai4privacy leak, pooled | **10.4 %**\* | 22.5 % | 28.7 % |
| ai4privacy F1, mean | **84.6**\* | 75.9 | 77.0 |
| NER per ~400-char message, M1 Max CPU p50 / p95 | 54 / 101 ms† | 107 / 126 ms | 48 / 56 ms† |
| Installs with | `ner` extra | `gliner` extra (conflicts with `ner`) | `ner` extra |
| Licence | Apache-2.0 | Apache-2.0 | AFL-3.0 |

\* Not an out-of-distribution check: its card lists OpenPII among its training data, and the
ai4privacy fixtures are OpenPII validation rows. The hand-written smoke sets are the fair
comparison, and it leaks least there too.
† Same session, machine loaded (load average 70–100 from other jobs); MPS p50 16.7 vs
16.4 ms. GLiNER's figure is from LAB-1150 on an idle machine.

Leak is the selection rule, so it wins on every set. It also installs with the existing `ner`
extra, so `uvx`, `make demo` and the demo image need no second environment, unlike GLiNER
(`gliner` 0.2.29 pins `transformers<5.17`). The cost is over-masking on the English smoke set
(23.1 %): 9 of its 39 masked spans there are not in the gold (4 place names as `ADDRESS`,
3 `PERSON`, 2 `ID_DOCUMENT`). Not chosen:

- its v2 and v3 successors (Apache-2.0, mmBERT base, 1.2 GB) score higher on their own card,
  but need the card's word-level decoder; with pii-guard's first-sub-token decoder they cut
  names into fragments (LAB-1192 sanity check), so they would need a decoder change first;
- `iiiorg/piiranha-v1-detect-personal-information`: CC BY-NC-ND 4.0, not open for this use.

**Older models and licences.**

- Previous zero-shot default (until LAB-1192):
  [`Davlan/xlm-roberta-base-ner-hrl`](https://huggingface.co/Davlan/xlm-roberta-base-ner-hrl)
  (AFL-3.0; XLM-RoBERTa-base trained on PER/ORG/LOC/DATE in ten languages, none of them
  Hungarian). `LOC` maps to `ADDRESS`, so addresses come out as fragments. It doesn't find
  dates of birth. It still loads with `PII_GUARD_NER_MODEL=Davlan/xlm-roberta-base-ner-hrl`.
- Fine-tuned: [`FacebookAI/xlm-roberta-base`](https://huggingface.co/FacebookAI/xlm-roberta-base)
  (MIT) trained with `training/ner/train.py` (`training/ner/config.toml`) on 223 synthetic hu+en
  documents (`pii-guard eval generate --n 160 --seed 7`, train split). Labels are the pii-guard
  types (`B-PERSON`, …), with token-level aggregation so Hungarian case suffixes can stay
  outside the span. About 18 minutes on an M1 Max (MPS); `--device cuda` for a GPU. Weights
  are not committed or published yet: train locally and set `PII_GUARD_NER_MODEL`.
- Also evaluated zero-shot: `urchade/gliner_multi_pii-v1` (GLiNER, Apache-2.0). It finds dates
  of birth and whole addresses, but over-masked more (18–20 % on the synth samples) and was 3–4×
  slower. GLiNER multi v2.1 is now wired in as `ner_gliner` (LAB-1150, below).

**Results** (rules vs rules + NER, overlap F1 / leak rate, %; full scorecards in
`eval/results/ner/`):

| Fixture | rules | + NER zero-shot | + NER fine-tuned |
|---|---|---|---|
| hu-smoke | 62.1 / 52.6 | 89.7 / 17.5 | 94.3 / 12.4 |
| en-smoke | 64.0 / 46.7 | 90.7 / 10.0 | 86.5 / 3.3 |
| hu-synth-sample | 57.7 / 50.3 | 92.0 / 18.5 | 96.6 / 8.7 |
| en-synth-sample | 54.5 / 46.2 | 96.8 / 7.5 | 100.0 / 0.0 |
| hu-synth dev split (seed 7) | 60.7 / 50.0 | 91.5 / 18.0 | 96.9 / 8.6 |
| en-synth dev split (seed 7) | 55.9 / 46.8 | 94.8 / 8.1 | 99.5 / 0.5 |

The figures above were measured on 2026-10-26 on the 28-document `hu-smoke`, before the
Hungarian ID document and parcel number rules (LAB-1127). `hu-smoke` has 31 documents now, and
the current numbers per configuration are in the leak-history table in
[journey.md](journey.md#leak-rate-over-time).

What was left in the Hungarian leak at that point was ID document and parcel numbers. The NER
detector doesn't label them (`LABEL_MAP` in `src/pii_guard/detect/ner.py` maps no label to
them); the Hungarian rule pack does, and rules run alongside the NER in every mode (see
`ID_DOCUMENT` and `PARCEL_NUMBER_HU` in [entities.md](entities.md)). With those rules on, the
distilled models below leave far less of the Hungarian leak (see
[Distilled from Muse Glimmer](#distilled-from-muse-glimmer)).

On the hand-written English smoke set the fine-tuned model over-masks more
(16 % vs 11 %) and loses some person precision: the synthetic training data is narrow, so this
is the set to watch.

**Latency** per ~400-character message (`training/ner/bench_latency.py`, M1 Max, torch 2.14):
CPU p50 46 ms / p95 53 ms; MPS p50 17 ms / p95 23 ms (same for both models). CUDA hasn't been
measured.

### Distilled from Muse Glimmer

A bigger, more varied corpus labelled by Muse Glimmer 30B (low reasoning) as the teacher, used
to retrain the student. Everything is fictional and reproducible from the seed; data and
weights stay out of git (`eval/generated/`, `models/` are ignored), and the hashes of every
corpus, label and cache file are in `eval/results/ner/distilled/corpus.json` and each model's
`training_meta.json`.

1. **Corpus** (`training/distill/corpus.py --seed 11 --n 2500` per language): the generator's
   kinds plus ten more per language (`training/distill/templates/<lang>.toml`): tool output,
   forms, logs, CSV, support chat, SMS, meeting notes, messages full of look-alike words, and
   two hard-negative kinds with no personal data at all. Written by
   `muse-spark-1.3-contributor` (fictional data, so any tier is fine) through the response
   cache, with a hard cost cap. 4,964 of 5,000 accepted (hu 2,472, en 2,492), none duplicated.
2. **Teacher labels** (`training/distill/label.py`, 64 requests in flight): rules + Glimmer
   (`reasoning_strength` low, served as below) over every document. Planted gold always wins;
   where Glimmer's span runs past gold or has another type, those characters are excluded from
   the loss (`meta.loss_ignore`) rather than guessed. New names Glimmer found are adopted
   (319 people, 145 organizations); new addresses and dates are ignored. Of 26,799 planted
   values Glimmer found 26,406; 499 disagreements were excluded.
3. **Student** (`training/distill/modal_train.py`, `training/ner/distilled-{base,large}.toml`):
   4 epochs, bf16 autocast on CUDA. xlm-roberta-base on an A10G took 5 minutes,
   xlm-roberta-large on an L40S 6 minutes.

Results, rules + NER (overlap F1 / recall / leak / over-masking, %). The evaluation sets are
the hand-written smoke sets, which the generator did not write, plus the distillation dev
split. Scorecards are in `eval/results/ner/distilled/`. *Fine-tuned* is the LAB-1106
checkpoint above.

| Fixture | fine-tuned | distilled base | distilled large |
|---|---|---|---|
| hu-smoke | 94.3 / 89.2 / 12.4 / 0.0 | 92.9 / 88.3 / 13.4 / 1.2 | 93.5 / 90.1 / 10.3 / 2.2 |
| en-smoke | 86.5 / 94.1 / 3.3 / **16.2** | 98.5 / 97.1 / 3.3 / **0.0** | 98.5 / 97.1 / 0.0 / **0.0** |
| hu distill dev (seed 11) | – | 97.7 / 96.3 / 5.2 / 0.5 | 97.5 / 96.3 / 5.2 / 0.9 |
| en distill dev (seed 11) | – | 99.3 / 99.8 / 0.1 / 1.3 | 98.2 / 99.8 / 0.1 / 3.4 |

- On English the over-masking problem is gone (16 % → 0 %) and recall went up for both
  sizes.
- On hu-smoke the base model finds one name fewer than the fine-tuned one (98 of 111 gold
  spans vs 99). The large model finds one more (100) and leaks fewer people, but masks two
  harmless spans.
- Most of what still leaks in Hungarian is ID document and parcel numbers, which are for the
  rules, not the NER model. With the Hungarian ID and parcel rules (LAB-1127) also on, hu-smoke
  scores 97.5 / 96.7 / 3.8 / 1.0 with base and 97.9 / 98.3 / 0.9 / 0.9 with large. The table
  keeps the earlier rules so the comparison with the fine-tuned model is like for like.

**Recommendation:** use the distilled large model where its latency fits and the base model
otherwise. Neither becomes the built-in default: the weights aren't published yet, so you
point `PII_GUARD_NER_MODEL` at a checkpoint you trained.

**Latency**, per ~400-character message (`eval/results/ner/distilled/latency-*.json`, M1 Max).
The machine was under heavy unrelated load (load average 30–50), so read these as relative
numbers:

| Model | MPS p50 / p95 | CPU p50 / p95 |
|---|---|---|
| distilled base | 24 / 41 ms | 76–98 / 106–200 ms |
| distilled large | 36 / 54 ms | 241 / 323 ms |

Large costs about 1.5× base on MPS and 2.5× on CPU. Base has the same architecture as the
fine-tuned model, so with the machine idle it should match that model's 17 ms (MPS) and
46 ms (CPU).

**Spend:** Meta Model API $1.05 (5,004 billed calls, contributor tier at $0.10 per million
input and $0.20 per million output tokens). Modal GPU about 38 H100 minutes for Glimmer, plus
about 8 A10G and 10 L40S minutes for training: roughly $3 in total.

### NER v2: wider labels, OpenPII train split, hard negatives

LAB-1150. The full method, every candidate and the latency tables are in
[eval/results/2026-10-27-ner-v2](../eval/results/2026-10-27-ner-v2/README.md). The model card is
[training/ner/model-card.md](../training/ner/model-card.md).

- **Labels:** the 10 types listed above (`training/ner/train.py`, `TYPES_V2`). The NER proposes
  identifier spans that the rules can't validate (most Ai4Privacy numbers fail their
  checksums). Validated rule spans keep their boundaries in the resolver. The mapping is in
  [entities.md](entities.md#ner-label-set).
- **Data:**
  - distillation s11 (LAB-1128);
  - s13, written from the lexicon packs and labelled by Muse Glimmer on Modal;
  - 5,000 rows per language from the Ai4Privacy OpenPII-1M **train** split
    (`training/ner/openpii.py`). The script asserts these are disjoint from the evaluated
    validation rows; only its manifest is committed;
  - 2,000 seeded hard negatives per language (`training/ner/negatives.py`): order, invoice,
    tracking and case numbers, and amounts, with no spans.
- **Training:** on Modal, 3 epochs, bf16: base on an A10G took 11 minutes, large on an L40S 14 minutes (with hard negatives).

| rules + NER, % | ai4privacy leak (pooled) | smoke leak, max | smoke over-masking, max | CPU p95 (M1) |
|---|---:|---:|---:|---:|
| v1 large (before) | 27.6 | 0.9 | 0.9 | 147 ms |
| **v2 base + hard negatives** (default) | **0.4** | **0.0** | 3.0 | **50 ms** |
| v2 large + hard negatives (best quality) | 0.4 | 0.0 | 3.0 | 145 ms |
| v2 large, no Ai4Privacy rows (held-out ablation) | 12.5 | 0.0 | 0.9 | 149 ms |
| GLiNER multi v2.1, zero-shot | 22.5 | 5.4 | 10.0 | 126 ms |

**The ai4privacy numbers are in-distribution** for models trained on OpenPII rows. The
ablation, which never saw those rows, is the held-out figure.

**Recommendation:**
- Use `xlmr-base-v2-hn` for fast mode. It meets the ~150 ms CPU p95 limit everywhere,
  including 85 ms on a 4-vCPU T4 container.
- Use large + hard negatives on GPU or MPS hosts.
- Neither checkpoint is published yet. The owner decided to publish the trained base model as
  `hdkiller/pii-guard-ner-xlmr-base` (LAB-1306, step 2 of [the resolution order](#which-ner-model-fast-mode-runs));
  until then point `PII_GUARD_NER_MODEL` at one you trained.

**GLiNER:**
- GLiNER is not adopted as the default. It leaks and over-masks more zero-shot, over-masks
  21 % on en-smoke fine-tuned, and is 2–5× slower.
- Adding GLiNER's spans to the default's in a union doesn't lower the leak, but it raises
  smoke over-masking to 9.5 %.
- LAB-1150 named it the best public **fallback** of the two it compared: zero-shot it leaks
  22.5 % vs Davlan's 28.7 % on ai4privacy, and 2.8–5.4 % vs 7.5–10 % on smoke. LAB-1192 then
  measured a third, the bards.ai EU PII model, which leaks less than both and installs with the
  `ner` extra, so that is the fallback ([above](#which-ner-model-fast-mode-runs)).
- The `gliner` extra pins `transformers<5.17`, so it can't be installed alongside `ner`.

**Spend:** about $4.85 of Modal: Glimmer for the corpus and labels, 8 XLM-R trainings, 1
GLiNER fine-tune and a T4 latency bench.

## LLM detector

`pii_guard.detect.llm.LlmDetector` (registry name `llm`) talks to any OpenAI-compatible Chat
Completions endpoint. It asks for JSON only (`{"entities": [{"type", "text"}]}`), finds every
returned surface string in the input itself (Unicode-safe, NFC/NFD tolerant, whitespace
tolerant, never inside a longer word), and drops values that are not in the text. It never
uses model offsets. Long inputs are split into overlapping chunks. Timeouts, HTTP errors and
output that is still not JSON after one retry raise `DetectionError` (fail closed).
`pii_guard.detect.pipeline.DetectionPipeline(["rules", "llm"])` merges the results: validated
rule spans keep their boundaries, masked types beat `keep` types, and the LLM adjudicates type
disagreements.

| Setting | Env var | Default |
|---|---|---|
| Base URL | `PII_GUARD_LLM_DETECTOR_URL` | `https://inference.baseten.co/v1` |
| API key | `PII_GUARD_LLM_DETECTOR_API_KEY` | unset |
| Model | `PII_GUARD_LLM_DETECTOR_MODEL` | `meta-models/muse-spark-open-1026` |
| Reasoning effort (`reasoning_effort`) | `PII_GUARD_LLM_DETECTOR_REASONING_EFFORT` | unset (not sent); use `low` on Baseten |
| Max tokens (`max_tokens`) | `PII_GUARD_LLM_DETECTOR_MAX_TOKENS` | unset (`4096`; at least 256) |
| Timeout per request, seconds | `PII_GUARD_LLM_DETECTOR_TIMEOUT` | unset (`60`; above 0) |
| Glimmer reasoning strength (`chat_template_kwargs.reasoning_strength`) | `PII_GUARD_LLM_DETECTOR_REASONING_STRENGTH` | unset (not sent) |

Constructor keywords (`base_url`, `api_key`, `model`, `timeout`, `max_retries`,
`reasoning_effort`, `max_tokens`, `json_mode`, `chunk_size`, `chunk_overlap`, `score`,
`transport`) override them; all of these settings are read from the environment and `.env`.
`max_tokens=None` sends no limit. `LlmDetector.usage` counts requests, reported tokens (prompt, cached, completion,
reasoning), invalid outputs and refusals per instance, for cost and refusal reporting; it never
holds text. Prompts live in `src/pii_guard/detect/prompts/`.

**Languages.** `detect(text, language)` picks a language profile built from the language
pack (`language_profile` in `detect/llm.py`, [languages.md](languages.md)): Hungarian (`hu`),
English (`en`) and German (`de`) today. A profile sets the language notes added to the prompt
(the pack's `prompt.md`), which entity types are requested
(country-specific types such as `NATIONAL_ID_HU_*` and `PARCEL_NUMBER_HU` only for their
language; the rules find Hungarian identifiers in any language), and how surface strings are
aligned: Hungarian lets a match run on into a suffix ("Teszt Elek" inside "Teszt Eleknek"),
English requires a word end ("Ann" does not match inside "Anne"). An unknown language is not an
error: it gets language-neutral notes (`prompts/languages/default.md`), the generic types, and
suffix-tolerant alignment (scripts without word spaces, such as Japanese, skip word-boundary
checks). Adding a language = a language pack ([languages.md](languages.md)).

**Target: Muse Spark Open.** Meta's open-weight Muse Spark, served by Baseten
(`meta-models/muse-spark-open-1026`, OpenAI-compatible). Because the weights are open, the same
detector can run on your own GPUs (vLLM or similar: point `PII_GUARD_LLM_DETECTOR_URL` at it),
which is what lets it see real data. **Muse Glimmer** (30B, open weights, Apache-2.0) is
the smaller candidate. It is too slow for the request path (about 9 s per document at low
reasoning), so it serves as the teacher for the distilled NER model (see "Distilled from Muse
Glimmer" above).

<a id="baseten-model-apis-production-detector"></a>

### Baseten Model APIs (the audit-mode detector)

Muse Spark Open runs on Baseten's shared **Model APIs** (no dedicated deployment, so no GPU
type or scale-to-zero to choose). Verified on 2026-10-27 with live calls on fictional text:

```bash
export PII_GUARD_LLM_DETECTOR_API_KEY=$BASETEN_API_KEY     # URL and model are the defaults
export PII_GUARD_LLM_DETECTOR_REASONING_EFFORT=low          # required, see below
```

- Base URL `https://inference.baseten.co/v1`, Bearer key, OpenAI-compatible
  `POST /chat/completions`. The model id must be exactly `meta-models/muse-spark-open-1026`
  (Baseten's docs show `muse-spark-open`, which hackathon keys reject).
- **Set `reasoning_effort: "low"`.** At the default effort the model spent all of a 2,048-token
  `max_tokens` budget on reasoning and returned empty `content` (the detector then fails
  closed: `finish_reason=length`). `low` is honoured. `chat_template_kwargs.reasoning_strength`
  (the Glimmer knob) has no effect here. With the detector's prompt, `low` still reasons about
  400–500 tokens per short document.
- The message carries `content` (the JSON answer) and a separate `reasoning_content`; the
  detector parses `content` only. `response_format: {"type": "json_object"}` and
  `temperature: 0` are accepted; usage reports `prompt_tokens_details.cached_tokens` (the
  system prompt is cached across requests) and `completion_tokens_details.reasoning_tokens`.
- Refusals: a bare extraction prompt with no system framing was refused once in probing. With
  the detector's system prompt, 0 of 284 requests over four eval runs were refused or invalid.
- Price (Baseten pricing page, 2026-10-27): $1.25 per million input tokens, $0.15 cached input,
  $4.25 output (reasoning tokens are output tokens). Measured cost and latency:
  [eval/results/2026-10-27-baseten](../eval/results/2026-10-27-baseten/README.md).
- Recorded responses: `tests/detect/fixtures/muse_spark_open_baseten_recorded.json` (response
  bodies only). Live check: `BASETEN_API_KEY=... uv run pytest -m live tests/detect/test_llm.py`.

**Data handling on Baseten (as of 2026-10-27).** Baseten's security documentation states that
Baseten "does not store model inputs, outputs, or weights by default" and that this zero data
retention policy applies to synchronous inference
([docs.baseten.co/observability/security](https://docs.baseten.co/observability/security)).
The page does not say whether that covers the shared Model APIs as well as dedicated
deployments, and does not say anything about training on customer traffic. **Until that is
confirmed in writing with Baseten (for example in a DPA), treat the Baseten Model API like any
hosted API: fictional or masked data only.** For real data, run the same open weights on an
endpoint you control (a dedicated deployment whose terms you have checked, or your own GPUs).
Everything in this repository sent to Baseten so far is fictional.

### Serving Muse Glimmer on Modal

`deploy/modal/glimmer.py` serves Glimmer with vLLM on one H100 (image
`vllm/vllm-openai:muse-glimmer`). It is an OpenAI-compatible endpoint, model name
`muse-glimmer`. Glimmer ignores `reasoning_effort`, so set
`PII_GUARD_LLM_DETECTOR_REASONING_STRENGTH=low`.

```
modal secret create pii-guard-glimmer GLIMMER_API_KEY=$(openssl rand -hex 24)   # once
modal deploy deploy/modal/glimmer.py
# PII_GUARD_LLM_DETECTOR_URL=https://<workspace>--pii-guard-glimmer-serve.<region>.modal.run/v1
# PII_GUARD_LLM_DETECTOR_MODEL=muse-glimmer
# PII_GUARD_LLM_DETECTOR_API_KEY=<the secret's value>
modal app stop pii-guard-glimmer --yes   # always, when done
```

- The key reaches vLLM as `VLLM_API_KEY`, never `--api-key`: vLLM logs its command line.
- Weights and the compile cache live on the volumes `pii-guard-hf-cache` and
  `pii-guard-vllm-cache`. The first start takes about 26 minutes; later starts take about
  3 minutes.
- The container scales to zero after 300 s idle, and the next request pays another cold
  start. Stop the app as soon as the job is done.
- Keep the key somewhere local: a Modal secret can't be read back. If the key is lost,
  overwrite the secret and redeploy.

**Development: Meta Model API.** Verified on 2026-10-26:

- Base URL `https://api.meta.ai/v1`, Bearer key from `META_API_KEY`, OpenAI-compatible
  `POST /chat/completions`. Detection was developed against `muse-spark-1.3`.
- Muse Spark always reasons. `reasoning_effort` accepts `minimal`, `low`, `medium`, `high`,
  `xhigh`, `max`; `none` returns HTTP 400. Use `minimal` (or `low`) for detection. Reasoning
  tokens are reported in `usage.completion_tokens_details.reasoning_tokens`; the message
  content itself is the clean answer.
- `response_format: {"type": "json_object"}` and `temperature: 0` are accepted.
- Observed on two ~400-character fictional Hungarian texts: about 4–6 s per request at
  `minimal` (500–750 reasoning tokens), 9–12 s at `low`. Both found every name, inflected
  name (including stem changes such as "Zsuzsannának"), date of birth, address, email, phone,
  IBAN, parcel number, ID card number and plate. On a ~300-character fictional English letter:
  about 3.7 s at `minimal`; every name (titles and possessive "'s" left out), date of birth,
  full address with postcode, passport number, phone, email and the employer's name.
- `GET /v1/models` lists `muse-spark-1.3`, `muse-spark-1.2`, `muse-spark-1.1`, `muse-wonder-1.0`,
  `muse-image-1.0`, `muse-voice-transcribe-1.0` and `sam-3.1` (plus `-contributor` variants).
  **SAM 3.1** is served on the same API through `POST /v1/responses` (not exercised here).
- Do not use the `-contributor` model variants: their tier allows the provider to use traffic.

**Privacy rule for the hosted API.** Hosted Meta API models only ever see **fictional or
masked** data: tests, fixtures and the corpus generator send synthetic text only. Real data is
analysed only by open-weights models on endpoints you control (Muse Spark Open on your own
hardware, or a dedicated partner deployment whose terms exclude training on your data). The
recorded test fixtures in `tests/detect/fixtures/` are responses to fictional text.

Tests mock HTTP with recorded responses; `uv run pytest -m live` runs the live checks against
the Meta Model API (with `META_API_KEY` set) and Baseten (with `BASETEN_API_KEY` set).

## Local segmentation

LAB-1229 asked whether faces, ID photos and signatures can be found **on the device** instead of
with SAM 3.1 on the Meta API (four API calls and 5-6 s per image, and the image leaves the
machine). **Answer: faces and ID photos yes, signatures no.** So since LAB-1245 the default
segmenter is **`hybrid`** (`PII_GUARD_SEGMENTER`, see
[operations.md](operations.md#segmenter-faces-on-the-device-signatures-on-sam-31)): YuNet
(`pii_guard.visual.segment.LocalSegmenter`) finds faces and ID photos on the CPU, and SAM 3.1
only the signatures.

### Hybrid vs SAM-only (LAB-1245)

| Set | Segmenter | Portrait recall | Portrait leak | Signature recall | Signature leak | SAM calls / image | `/v1/mask/image` p50 / p95 |
|---|---|---:|---:|---:|---:|---:|---:|
| specimens (65) | `sam-api` (SAM 3.1 for everything, the previous default) | 90.8 % | 47.7 % | 83.8 % | 51.4 % | 5 | 7.9 s / 11.6 s |
| | **`hybrid`** (YuNet + SAM 3.1 for signatures, the default) | 92.3 % | **10.8 %** | 83.8 % | 48.6 % | **2** | **4.1 s / 6.1 s** |
| fictional (24) | `sam-api` | 100.0 % | 0.0 % | 100.0 % | 6.7 % | 5 | 7.2 s / 8.1 s |
| | **`hybrid`** | 100.0 % | 0.0 % | 100.0 % | 6.7 % | **2** | **3.8 s / 5.0 s** |

- **Calls:** `/v1/mask/image` with `sam-api` sends 5 SAM requests per image (`face`,
  `signature`, `squiggly line`, `photo of a person`, and `stamp`, whose regions are `keep`), not
  the 4 the eval harness counts; `hybrid` sends 2 (`signature`, `squiggly line`), measured on
  every image. Stamps are only segmented when their policy is not `keep`.
- **Latency:** end to end through the app (`python -m pii_guard.visual.segment_eval
  --e2e-bench`: Tesseract OCR, rules detector, `render=opaque`), the two modes alternating per
  image, live SAM, 3 rounds; medians of the per-round p50 / p95 on a laptop shared with other
  jobs (load average 10-12). Per round, specimens: hybrid p50 4.14 / 4.23 / 4.04 s, sam-api
  8.10 / 7.85 / 7.20 s; fictional: hybrid 3.96 / 3.26 / 3.77 s, sam-api 7.24 / 6.80 / 7.61 s.
  Segmentation alone (no OCR, replayed SAM latency): p50 2.51 s vs 5.23 s (specimens), 2.26 s
  vs 4.78 s (fictional).
- **Signatures** come from the same SAM prompts in both modes: the same 40 boxes on the
  specimens, the same recall (83.8 %) and precision (77.5 %). The leak is slightly lower with
  `hybrid` (48.6 % vs 51.4 %, 1 of 37 signatures) only because YuNet's ID-photo box also covers
  a signature printed next to the portrait.
- **Portraits:** on the specimens `hybrid` leaks 10.8 % of portraits against SAM's 47.7 %, at
  higher recall (92.3 % vs 90.8 %). YuNet's boxes over-mask around the photo (precision 61 % on
  the specimens, 81 % on the fictional set, vs SAM's 90-100 %), the safe side.
- **Acceptance (LAB-1245):** met on both sets. Portrait leak ≤ `sam-api`'s, signatures equal
  (same prompts, same boxes), fewer API calls (2 vs 5) and a lower p50 (−47 % specimens, −48 %
  fictional).
- **Specimen data:** fetched locally into `PII_GUARD_SPECIMENS_DIR` (outside the worktree,
  see [evaluation.md](evaluation.md#where-the-specimen-images-live-visual)), never committed.
- The labelled-image eval (LAB-1156 placeholders) and the "which parties have an ID?" demo do
  not depend on the segmenter's portraits and are unchanged (fuzzy 50/51 values, 0 false
  merges, 24/24 transcripts; demo 3/3 with `hybrid` and with `sam-api`).
- Run records: `eval/results/runs/2026-10-27-segment-hybrid-{fictional,specimens}` (segment-only
  metrics plus the end-to-end medians in `latency_ms.mask_image_per_image_*`).

### The LAB-1229 spike

Measured with `python -m pii_guard.visual.segment_eval` on the portrait and signature regions of
the fictional set (24 images, committed) and the official specimen set (65 images, fetched
locally, never committed), without OCR. Run records: `eval/results/runs/2026-10-27-segment-*`;
chart and table: [benchmarks.md](benchmarks.md#segmenters-sam-31-api-vs-on-device).

| Candidate | Set | Portrait recall (IoU ≥ 0.5) | Portrait leak | Signature recall | Signature leak | p50 / p95 per image | Weights | Licence |
|---|---|---:|---:|---:|---:|---:|---:|---|
| **SAM 3.1, Meta API** (baseline) | fictional | 100.0 % | 0.0 % | 100.0 % | 6.7 % | 5.1 s / 6.9 s | hosted | hosted API |
| | specimens | 90.8 % | 47.7 % | 83.8 % | 51.3 % | 5.5 s / 8.6 s | | |
| **YuNet** (`local`) | fictional | 100.0 % | 0.0 % | — | — | 176 / 238 ms | 0.23 MB | MIT (weights), Apache-2.0 (OpenCV) |
| | specimens | 92.3 % | 10.8 % | — | — | 116 / 348 ms | | |
| YuNet + YOLOS-tiny signatures (`small-detectors`) | fictional | 100.0 % | 0.0 % | 100.0 % | 13.3 % | 1.1 s / 1.6 s | 26 MB | MIT, Apache-2.0 |
| | specimens | 93.8 % | 6.2 % | 51.3 % | 46.0 % | 727 ms / 1.6 s | | |
| YuNet + EfficientSAM-ViT-T photo refinement (`efficientsam`) | fictional | 100.0 % | 0.0 % | — | — | 1.5 s / 4.4 s | 42 MB | MIT, Apache-2.0 |
| | specimens | 92.3 % | 16.9 % | — | — | 2.2 s / 3.3 s | | |
| SAM 3 locally | — | not run | | | | | 3.4 GB | gated |

- **Leak** is a labelled region less than 95 % covered by the boxes returned (the specimen
  labels are hand-drawn to about ±1-2 % of the image side; with a 100 % threshold every
  candidate "leaks" through label slack: SAM 83 % of specimen portraits, YuNet 12 %). Each
  run's notes also give that strict figure and **precision** (boxes that hit a labelled region
  of their kind): portraits 90 % SAM vs 61 % YuNet on the specimens. YuNet's ID-photo box is
  the face box grown by a fixed margin, so it over-masks around the photo; over-masking is the
  safe side.
- **Latency** is CPU wall time on an Apple M-series laptop that was running other jobs (load
  average 15-23, in each record's hardware note), so it is pessimistic; SAM's is the sum of its
  four sequential API calls. Model load: YuNet 0.1-0.2 s, YOLOS 3.7-6.7 s. Peak RSS of the whole
  eval process: 0.4-0.9 GB (YuNet), 0.7-1.1 GB (with YOLOS), 1.5-1.9 GB (EfficientSAM). Not
  measured: the CI runner, MPS/GPU (OpenCV's YuNet runs on the CPU only).
- **YuNet's ID-photo margin** (`PHOTO_PADDING`) was picked among four settings on these same
  two sets, so its numbers are slightly optimistic; recall does not depend on it.

**Against the "close enough" rule** (on both sets: face/ID-photo leak ≤ SAM's and recall within
2 pp; signature recall within 5 pp; p50 ≤ 500 ms on CPU; weights ≤ 200 MB, permissive):

| Rule | YuNet (`local`) | `small-detectors` | `efficientsam` |
|---|---|---|---|
| Face/ID-photo leak ≤ SAM, recall within 2 pp | pass (0.0 / 10.8 % vs 0.0 / 47.7 %; recall +0 / +1.5 pp) | pass | pass |
| Signature recall within 5 pp | **fail** (finds none) | **fail** (−32.4 pp on specimens) | **fail** (finds none) |
| p50 ≤ 500 ms on CPU | pass | **fail** | **fail** |
| ≤ 200 MB, permissive licence | pass | pass | pass |

Why the rest fell short:

- **Signatures.** The permissively licensed small detectors on Hugging Face (YOLOS-tiny and
  YOLOS-small by `mdefrance`, Conditional-DETR-50 by `tech4humans`, all Apache-2.0, trained on
  scanned pages) find 16-32 % of the specimen signatures on the whole image; 2×2 tiles raise
  YOLOS-tiny to 51 % at 9 % precision (288 boxes for 37 signatures). The YOLOv8 signature
  detectors are AGPL (Ultralytics) and were not used.
- **EfficientSAM** (Apache-2.0, ONNX export from the authors' repository), prompted with the
  grown face box, did not raise portrait recall and costs 1.5-2.2 s per image.
- **SAM 3 locally**: the Hugging Face weights (`facebook/sam3`) are gated and this account has
  no access (HTTP 403); the owner has to request it. At 3.4 GB they would also miss the 200 MB
  bar.

**Model pin.** YuNet `face_detection_yunet_2023mar.onnx` from the OpenCV model zoo
(`https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx`),
232,589 bytes, SHA-256 `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`,
licence **MIT** (weights; OpenCV itself is Apache-2.0). The Docker build fetches it from that URL
and fails on a checksum mismatch; `LocalSegmenter` refuses a file whose SHA-256 differs.

Use `LocalSegmenter` directly (it raises `DetectionError` if asked for `SIGNATURE`):

```bash
uv sync --extra local-vision                     # opencv-python-headless
uv run python -m pii_guard.visual.segment fetch  # YuNet from the OpenCV model zoo, SHA-256 checked
```

```python
from pii_guard.visual.segment import LocalSegmenter

regions = LocalSegmenter().segment(png_bytes)  # FACE + ID_PHOTO, on the CPU
```

Reproduce the table (specimens: `uv run python eval/visual/fetch_specimens.py` first, with
`PII_GUARD_SPECIMENS_DIR` outside the worktree, see
[evaluation.md](evaluation.md#where-the-specimen-images-live-visual); the SAM
rows replay the eval's response cache, `--offline`):

```bash
uv run python -m pii_guard.visual.segment_eval --candidate local --set specimens --record segment-local-specimens
# LAB-1245: hybrid vs sam-api end to end (live SAM, free credits), then the hybrid record
uv run python -m pii_guard.visual.segment_eval --e2e-bench --set fictional --rounds 3 --json e2e.json
uv run python -m pii_guard.visual.segment_eval --candidate hybrid --set fictional --e2e e2e.json --record segment-hybrid-fictional
```

## Hackathon partners

| Partner | What we use it for |
|---|---|
| **Fireworks** | Supervised fine-tuning of the detector model on the synthetic train split |
| **Modal** | GPU serving for SAM 3.1, and experiment runs |
| **Baseten** | Serving Muse Spark Open (`meta-models/muse-spark-open-1026`) for the LLM detector |

Any of the three can stand in for another; the code talks to model endpoints through
configuration, not vendor SDKs, wherever possible.

## Data-use note

Provider tiers differ in whether traffic may be used to improve the provider's products. For
corpus generation (fictional data) any tier is acceptable. For anything else, use a tier whose
terms exclude training on your data. See [privacy-model.md](privacy-model.md).
