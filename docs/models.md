# Models and partners

> Status: partly verified (2026-10-26). The Meta Model API facts below were checked with live
> calls on fictional text; the Baseten Muse Spark Open endpoint is configured but not yet
> called (no key yet). Credit amounts: see [roadmap.md](roadmap.md).

## Which model does what

| Job | Model | Where it runs | Sees real data? |
|---|---|---|---|
| Structured identifiers | Rules (no model) | pii-guard container | yes (inside the boundary) |
| Names, organizations, locations | Multilingual NER model (open) | pii-guard container | yes |
| Second-pass detection and adjudication | **Muse Spark Open** (open weights), optionally fine-tuned; **Muse Glimmer** as a smaller local candidate | Baseten (`meta-models/muse-spark-open-1026`), or your own hardware | yes |
| Faces, signatures, ID photos | **SAM 3.1** | GPU endpoint | yes |
| OCR | Open OCR engine | pii-guard container or GPU endpoint | yes |
| Synthetic corpus generation | **Muse** (Wonder for documents, Spark for variations) | Meta Model API | **no**: fictional data only |
| The downstream model in the demo | **Muse Spark** | Meta Model API | **no**: only masked data |

The rule behind this table: **anything that sees real personal data is an open-weights model
you can host yourself.** Hosted Meta models only ever see fictional data or masked data.

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
which is what lets it see real data. **Muse Glimmer** is the candidate for a smaller,
CPU/edge-friendly local detector; not yet evaluated.

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
