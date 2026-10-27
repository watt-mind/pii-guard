# Models and partners

> Status: partly verified (2026-10-26). The Meta Model API facts below were checked with live
> calls on fictional text; the Baseten Muse Spark Open endpoint is configured but not yet
> called (no key yet). Credit amounts: see [roadmap.md](roadmap.md).

## Which model does what

| Job | Model | Where it runs | Sees real data? |
|---|---|---|---|
| Structured identifiers | Rules (no model) | pii-guard container | yes (inside the boundary) |
| Names, organizations, addresses (dates of birth when fine-tuned) | Multilingual NER encoder (XLM-RoBERTa-base, open) | pii-guard container (CPU / MPS / CUDA) | yes |
| Second-pass detection and adjudication | **Muse Spark Open** (open weights), optionally fine-tuned; **Muse Glimmer** as a smaller local candidate | Baseten (`meta-models/muse-spark-open-1026`), or your own hardware | yes |
| Faces, signatures, ID photos | **SAM 3.1** | GPU endpoint | yes |
| OCR | Open OCR engine | pii-guard container or GPU endpoint | yes |
| Synthetic corpus generation | **Muse** (Wonder for documents, Spark for variations) | Meta Model API | **no**: fictional data only |
| The downstream model in the demo | **Muse Spark** | Meta Model API | **no**: only masked data |

The rule behind this table: **anything that sees real personal data is an open-weights model
you can host yourself.** Hosted Meta models only ever see fictional data or masked data.

## NER detector

`pii_guard.detect.ner.NerDetector` (registry name `ner`) runs a Hugging Face token-classification
encoder in-process and reports `PERSON`, `ADDRESS`, `ORGANIZATION` and, with the fine-tuned
model, `DATE_OF_BIRTH`. Rules stay authoritative for structured identifiers in
`DetectionPipeline`. Install with `uv sync --extra ner` (torch, transformers, sentencepiece,
protobuf). Without the extra the registry reports `ner` as unavailable, so the gateway's fast
mode stays rules-only; with it, fast mode picks `ner` up automatically. A model that can't be
loaded and any inference error raise `DetectionError` (fail closed).

| Setting | Env var | Default |
|---|---|---|
| Model (hub id or directory) | `PII_GUARD_NER_MODEL` | `Davlan/xlm-roberta-base-ner-hrl` (pinned revision) |
| Revision | `PII_GUARD_NER_REVISION` | pinned for the default model |
| Device | `PII_GUARD_NER_DEVICE` | `auto`: CUDA, then Apple MPS, then CPU |

Constructor keywords: `thresholds` (`{language: {type: min_score}}`, default 0.5), `entity_types`,
`label_map`, `max_length`/`stride` (token windows for long inputs), `aggregation`, `preload`.
Offsets come from the fast tokenizer's offset mapping (code points), so they are exact for any
Unicode input. Warm the cache with `uv run --extra ner python -m pii_guard.detect.ner download`.

**Models and licences.**

- Zero-shot default: [`Davlan/xlm-roberta-base-ner-hrl`](https://huggingface.co/Davlan/xlm-roberta-base-ner-hrl)
  (AFL-3.0; XLM-RoBERTa-base trained on PER/ORG/LOC/DATE in ten languages, none of them
  Hungarian). `LOC` maps to `ADDRESS`, so addresses come out as fragments. It doesn't find
  dates of birth.
- Fine-tuned: [`FacebookAI/xlm-roberta-base`](https://huggingface.co/FacebookAI/xlm-roberta-base)
  (MIT) trained with `training/ner/train.py` (`training/ner/config.toml`) on 223 synthetic hu+en
  documents (`pii-guard eval generate --n 160 --seed 7`, train split). Labels are the pii-guard
  types (`B-PERSON`, …), with token-level aggregation so Hungarian case suffixes can stay
  outside the span. About 18 minutes on an M1 Max (MPS); `--device cuda` for a GPU. Weights
  are not committed or published yet: train locally and set `PII_GUARD_NER_MODEL`.
- Also evaluated zero-shot: `urchade/gliner_multi_pii-v1` (GLiNER, Apache-2.0). It finds dates
  of birth and whole addresses, but over-masked more (18–20 % on the synth samples), was 3–4×
  slower and needs its own package, so it isn't wired in.

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

What's left in the Hungarian leak is ID document and parcel numbers, which are out of scope for
the NER detector. On the hand-written English smoke set the fine-tuned model over-masks more
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

## LLM detector

`pii_guard.detect.llm.LlmDetector` (registry name `llm`) talks to any OpenAI-compatible Chat
Completions endpoint. It asks for strict JSON (`{"entities": [{"type", "text"}]}`), finds every
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
| Glimmer reasoning strength (`chat_template_kwargs.reasoning_strength`) | `PII_GUARD_LLM_DETECTOR_REASONING_STRENGTH` | unset (not sent) |

Constructor keywords (`base_url`, `api_key`, `model`, `timeout`, `max_retries`,
`reasoning_effort`, `json_mode`, `chunk_size`, `chunk_overlap`, `score`, `transport`) override
them. Prompts live in `src/pii_guard/detect/prompts/`.

**Languages.** `detect(text, language)` picks a language profile (`LANGUAGES` in
`detect/llm.py`): Hungarian (`hu`) and English (`en`) today. A profile sets the language notes
added to the prompt (`prompts/languages/<code>.md`), which entity types are requested
(country-specific types such as `NATIONAL_ID_HU_*` and `PARCEL_NUMBER_HU` only for their
language; the rules find Hungarian identifiers in any language), and how surface strings are
aligned: Hungarian lets a match run on into a suffix ("Teszt Elek" inside "Teszt Eleknek"),
English requires a word end ("Ann" does not match inside "Anne"). An unknown language is not an
error: it gets language-neutral notes, the generic types, and suffix-tolerant alignment
(scripts without word spaces, such as Japanese, skip word-boundary checks). Adding a language
= a notes file plus a `LanguageProfile` entry.

**Target: Muse Spark Open.** Meta's open-weight Muse Spark, served by Baseten
(`meta-models/muse-spark-open-1026`, OpenAI-compatible). Because the weights are open, the same
detector can run on your own GPUs (vLLM or similar: point `PII_GUARD_LLM_DETECTOR_URL` at it),
which is what lets it see real data. **Muse Glimmer** (30B, open weights, Apache-2.0) is
the smaller candidate. It is too slow for the request path (about 9 s per document at low
reasoning), so it serves as the teacher for the distilled NER model (see "Distilled from Muse
Glimmer" above).

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

Tests mock HTTP with recorded responses; `uv run pytest -m live` (with `META_API_KEY` set) runs
the one live check against the Meta Model API.

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
