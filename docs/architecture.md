# Architecture

> Status: implemented on develop. Version 0.1.0 is planned as the first tagged release; nothing is tagged or published yet (see [CHANGELOG](../CHANGELOG.md)).

## Overview

```
                ┌───────────────────────────── pii-guard ──────────────────────────────┐
 request  ────► │ documents ──► detect ──────────► vault ──────► gateway (outbound)    │ ────► LLM
 (text,         │  text+layout   rules → NER → LLM   keyed          masked request     │
  files,        │                    │               pseudonyms                        │
  images)       │ visual ────────────┘                  ▲                              │
                │  OCR + YuNet + SAM 3.1 masks          │ mapping (never leaves)       │
 response ◄──── │ gateway (inbound) ◄── re-identify ────┘                              │ ◄──── stream
                └──────────────────────────────────────────────────────────────────────┘
```

Each stage is a separate module with a narrow interface, so it can be tested and benchmarked
on its own.

## Components

### `documents`: ingestion

Turns PDFs, DOCX files and images into **text plus layout**: each token has a position on the
page, so a detection in text can be mapped back to a pixel region. Born-digital PDFs keep
their text layer; scans go through OCR. The output is a `Document` with pages, text and word
boxes.

### `detect`: finding personal data

A pipeline of detectors, each returning candidate **spans** `(start, end, entity_type,
confidence, detector)`:

1. **Rules**: regular expressions plus validation (checksums, structural checks, address and
   cue context) for structured identifiers: IBAN, email, phone numbers and payment cards for
   every language, plus each language pack's national IDs and structured numbers (`hu`, `en`,
   `de`, `pl` — Hungarian tax ID, TAJ, company numbers and postcodes; UK/US phone formats,
   postcodes, ZIP codes, US SSN and UK NINO; German Steuer-ID, RVNR and postcodes; Polish
   PESEL, NIP, REGON, dowód osobisty and postcodes). High precision, deterministic, fast.
2. **NER**: **XLM-RoBERTa base** distilled from **Meta Muse Glimmer 30B**, combined with
   curated multilingual PII datasets and synthetic hard negatives. Runs locally in-process on
   CPU in fast mode at **43 ms p50** per ~400-character message, published on Hugging Face as
   [`watt-mind/pii-guard-ner-xlmr-base`](https://huggingface.co/watt-mind/pii-guard-ner-xlmr-base)
   (`v4.2`; see [models.md](models.md#ner-detector)).
3. **LLM detector** *(optional audit mode)*: **Muse Spark Open** (`meta-models/muse-spark-open-1026`)
   or **Muse Spark 1.3** via the Baseten or Meta Model API, used for offline/sampled quality
   measurement, re-identification red-teaming, and benchmark upper bounds.
   The LLM only returns candidate surface strings as JSON and never rewrites user text.

A deterministic **resolver** merges overlapping spans (giving checksum-validated rules
priority on structured IDs, promoting brand/company spans via organization lexicons, and
dropping ungrounded LLM strings), applies per-entity policies (`mask`, `keep`, `block`), and
expands each confirmed value to all of its occurrences in the request, **including inflected
forms** (language-specific morphology such as Hungarian and Polish case suffixes, German
genitives, and English possessives).

### Language packs

Everything language-specific is one **language pack** per language code: a `LanguagePack` in
`src/pii_guard/languages/<code>/`, or from another distribution through the
`pii_guard.languages` entry point ([ADR 0008](decisions/0008-language-packs.md),
[ADR 0010](decisions/0010-language-pack-plugins.md)). The components ask the pack registry for
the primary language's pack (`en-GB` → `en`) and keep their own logic:

| Pack part | Used by | Fallback without a pack |
|---|---|---|
| `everywhere` + `rules` | `detect/rules` `RuleDetector` | language-independent rules (`detect/rules/common.py`) + every pack's `everywhere` rules |
| `inflection` matcher | `vault/inflection.py` `inflection_for`, LLM alignment | exact word-boundary matching |
| `prompt` notes, `country_entity_types`, `allow_suffix`/`word_boundary` | `detect/llm.py` `language_profile` | `default.md`, generic types |
| `surface_forms` | `eval/forms.py` `language_forms` | the vault matcher's suffixes |
| `lexicons` | `pii_guard.lang` | `LexiconUnavailable` |
| `smoke_fixtures` | conformance suite (`tests/languages/`, `pii-guard lang check`) | — (required) |

Built-in packs: `hu` (Hungarian rules, case-suffix matcher, prompt notes, stem-changing surface
forms, lexicons), `en` (English rules, possessive matcher, prompt notes, stopwords), `de`
(German rules, genitive matcher, prompt notes, stopwords; the worked example of
[languages.md](languages.md)), and `pl` (Polish rules for PESEL/NIP/REGON/ID card, case-suffix
inflection matcher, prompt notes, surface forms, and cues).

### `visual`: images and scans

PII Guard ships a **hybrid visual pipeline** combining local OCR, local face detection, and
remote/self-hosted signature segmentation:

- **Text in images (`Tesseract OCR`):** OCR word boxes + `detect` → the bounding boxes of
  detected spans are masked; values adjacent to known document field captions (`Név`,
  `Date of birth`, `Geburtsdatum`, `PESEL`) are masked via language-pack caption tables
  (`visual/captions.py`), and machine-readable zones (MRZ) are detected structurally by layout
  (`visual/mrz.py`). Small images are upscaled to 2000 px before OCR.
- **Faces and ID photos (`YuNet`):** Local OpenCV **YuNet** (0.23 MB, MIT) runs in-process on
  CPU in the default `hybrid` segmenter to detect faces and ID card portraits with zero
  external API calls.
- **Signatures (`Meta SAM 3.1`):** **Meta SAM 3.1** (via the Meta Model API or a configured GPU
  endpoint, decoded with `meta-sam-parser`) segments handwritten signatures (and faces when
  `PII_GUARD_SEGMENTER=sam-api` is selected).
- **Hosted:** Hosted deployments run `local` only: YuNet faces and a pinned YOLOS-tiny signature
  detector, no SAM ([hosted.md](hosted.md)).
- **Pixel-level sanitization:** The output image is re-encoded from pixels (no layers, no
  original metadata; EXIF is stripped) and masked regions carry the text session's placeholder
  labels where linked, so masked content cannot be recovered.

### `vault`: pseudonyms and re-identification

- Each confirmed value gets a **typed, keyed placeholder**: `[[PERSON_7f3a]]`. The id is an
  HMAC of the normalized value under a per-tenant (and optionally per-session) key, so the
  same person gets the same placeholder within a session, and placeholders are neither
  guessable nor linkable across tenants. See [ADR 0007](decisions/0007-keyed-pseudonyms.md).
- The **mapping** (placeholder → original value, plus its inflected surface forms) is held in
  memory or an encrypted store with a TTL. It never leaves PII Guard.
- **Re-identification** replaces placeholders in the response with the original value,
  re-applying the inflection the model used where the language needs it.

### `gateway`: the proxy

An OpenAI-compatible HTTP proxy (Chat Completions and Responses API, streaming and
non-streaming):

1. Receive the request, extract every text and image part.
2. Run `documents` / `visual` / `detect`, then `vault` to mask.
3. **Fail closed**: if any step errors or times out, return an error and send nothing
   upstream ([ADR 0006](decisions/0006-fail-closed.md)).
4. Forward the masked request to the configured upstream.
5. Re-identify the response. For streams, keep a small buffer so a placeholder split across
   two chunks (`[[PERS` + `ON_7f3a]]`) is restored correctly before the text is emitted.

### `api`: direct use

For applications that want to control the flow themselves:

| Endpoint | Purpose |
|---|---|
| `POST /v1/analyze` | Return detected spans and regions, without masking |
| `POST /v1/mask` | Return masked text/images and a session handle |
| `POST /v1/unmask` | Re-identify text produced with a session handle |
| `GET /healthz` | Liveness and model readiness |

### `eval`: measurement

The synthetic corpus generator, the scorer, and the end-to-end leak test. Described in
[evaluation.md](evaluation.md).

## Deployment shape

- **Text in fast mode (default) runs self-hosted on CPU:** one container runs the API, gateway,
  checksum rules and the NER (`watt-mind/pii-guard-ner-xlmr-base` `v4.2`); no GPU and no
  detector API call for text. Images add Tesseract OCR and YuNet on the CPU; the default
  `hybrid` segmenter sends signatures to SAM 3.1 (unmasked pixels), and
  `PII_GUARD_SEGMENTER=local` keeps images on the machine.
- **Remote / GPU endpoints:** audit mode (Muse Spark Open on Baseten, or self-hosted vLLM) is
  opt-in; SAM 3.1 is used by the default `hybrid` image segmenter for signatures (or for every
  type with `sam-api`).
- **Configuration and state boundaries:** Runtime settings are configured via environment
  variables (`.env.example`), while project, policy, and endpoint configurations are persisted
  separately from ephemeral in-memory vault state ([projects.md](projects.md)).

## Engineering choices

Moved here from the README.

- **Fail closed, everywhere** ([ADR 0006](decisions/0006-fail-closed.md)). A detector
  timeout, a model error or a malformed answer blocks the request; nothing is sent unmasked.
- **Keyed, reversible pseudonyms** ([ADR 0007](decisions/0007-keyed-pseudonyms.md)).
  HMAC-derived placeholders, the same within a conversation, unlinkable across sessions and
  tenants. The mapping lives only in PII Guard's session vault, with a TTL.
- **Streaming-safe restore.** Placeholders split across chunks (`[[PERS` + `ON_7f3a]]`) are
  held back until complete, in content and in tool-call arguments.
- **Layered detection with one resolver:** rules with checksums (Hungarian tax and TAJ
  numbers, Polish PESEL/NIP/REGON, German Steuer-ID/RVNR, IBAN, giro accounts, company IDs,
  US SSN, UK NINO, payment cards…), the distilled NER model (fast mode, the default), and the
  LLM detector (audit mode, opt-in), merged by one deterministic resolver.
- **The LLM never rewrites your text.** It only names spans; PII Guard finds them in the
  original, drops anything the model invented, and lets checksum-validated rules win on
  structured IDs. A hallucination can't add text, and a disagreement can't unmask anything.
- **Grammar-aware placeholders.** Hungarian and Polish case endings stay outside the placeholder
  (`[[PERSON_x]]nek`), so the model still writes grammatical answers and restoration is exact.
- **Language packs** ([languages.md](languages.md)): Hungarian (`hu`), English (`en`), German
  (`de`), and Polish (`pl`) ship built in. A language is one plugin unit (an entry point for
  separate distributions) with a conformance suite that says what is missing:
  `pii-guard lang new <code>` to start.
- **Entity policies:** mask, keep (organizations stay readable so the model can reason) or
  block (refuse the request).
- **Per-message detection cache.** Chat clients resend the whole history every turn; only the
  new message is detected.
- **Synthetic data only** ([ADR 0005](decisions/0005-synthetic-data-only.md)). No real
  personal data in the repo, in tests or in prompts to hosted models; CI on every change.

Which Meta model does which job: [why-pii-guard.md](why-pii-guard.md#3-built-on-metas-models-end-to-end).
Using the gateway from a client: [architecture-gateway.md](architecture-gateway.md).

## Architectural decisions & resolved choices

The initial design questions from the start of the hackathon were resolved in the implemented
design:

- **NER baseline resolved:** Instead of relying on an off-the-shelf checkpoint that over-masked
  23.1% on en-smoke, we distilled **Meta Muse Glimmer 30B** (combined with multilingual PII
  corpora and synthetic hard negatives) into an **XLM-RoBERTa base** student
  ([`watt-mind/pii-guard-ner-xlmr-base`](https://huggingface.co/watt-mind/pii-guard-ner-xlmr-base)
  `v4.2`), achieving **0.0% leak** on the 4-language hand-written smoke set at **43 ms p50** on
  CPU (NER alone) ([models.md](models.md#ner-detector)).
- **Hybrid vision resolved:** Visual masking uses a hybrid pipeline (`PII_GUARD_SEGMENTER=hybrid`)
  combining local **YuNet** for fast, zero-API face/ID-photo detection on CPU, **Meta SAM 3.1**
  for signature segmentation, and **Tesseract OCR** (plus caption and MRZ layout rules) for
  text in images ([models.md](models.md#which-model-does-what)).
- **Mismatched or invented placeholders:** A placeholder the model invents or mangles is left as
  written and counted (`X-PII-Guard-Unresolved`); it is never guessed into a value. Input that
  already contains a placeholder this session issued is refused (`placeholder_in_input`, 422),
  and other placeholder-shaped tokens are reserved so they are never issued later
  ([api.md](api.md)).
- **Persistence and multi-project isolation:** Ephemeral placeholder-to-PII mappings live only
  in the in-memory session vault with a strict TTL and never touch disk, while project policies,
  immutable policy versions, and endpoint credentials are persisted separately in SQLite
  ([ADR 0012](decisions/0012-hosted-projects-and-endpoint-configuration.md),
  [projects.md](projects.md)).
