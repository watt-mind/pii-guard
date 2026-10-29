# Architecture

> Status: proposed. This describes the target design for the hackathon build; sections will
> be updated as the code lands.

## Overview

```
                ┌──────────────────────────── pii-guard ─────────────────────────────┐
 request  ────► │ documents ──► detect ──────────► vault ──────► gateway (outbound)   │ ───► LLM
 (text,         │  text+layout   rules → NER → LLM   keyed          masked request     │
  files,        │                    │               pseudonyms                        │
  images)       │ visual ────────────┘                  ▲                              │
                │  OCR boxes + SAM 3.1 masks            │ mapping (never leaves)       │
 response ◄──── │ gateway (inbound) ◄── re-identify ────┘                              │ ◄─── stream
                └────────────────────────────────────────────────────────────────────┘
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

1. **Rules**: regular expressions plus validation (checksums, structural checks, address
   context) for structured identifiers: IBAN, email, phone numbers and payment cards for every
   language, plus each language pack's identifiers (Hungarian tax ID, TAJ, company numbers,
   postcodes; UK/US phone formats, postcodes and ZIP codes, US SSN, UK NINO). High precision,
   deterministic, fast.
2. **NER**: a multilingual named-entity model for names, organizations and locations.
3. **LLM detector**: a small open-weights Llama model, fine-tuned on the synthetic corpus. It
   runs as a second pass that finds what the first two miss (addresses written in prose, names
   in unusual positions) and **adjudicates** disagreements between them.

A **resolver** merges overlapping spans, applies per-entity policies (mask, keep, block), and
expands each confirmed value to all of its occurrences in the request, **including inflected
forms** (language-specific morphology, e.g. Hungarian case suffixes).

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

Built-in packs: `hu` (rules, case-suffix matcher, prompt notes, stem-changing surface forms,
lexicons), `en` (rules, possessive matcher, prompt notes, stopwords) and `de` (rules, genitive
matcher, prompt notes, stopwords; the worked example of [languages.md](languages.md)).

### `visual`: images and scans

- Text in images: OCR word boxes + `detect` → the boxes of detected spans are masked; the
  value next to a known field caption (`Név`, `Date of birth`) is masked as well
  (`visual/captions.py`, captions from the language packs), and machine-readable zones are
  found by their layout (`visual/mrz.py`). Tesseract reads small images enlarged to 2000 px.
- Non-text personal data: **SAM 3.1** segments faces, signatures, ID photos and stamps, which
  are masked as regions.
- The output image is re-encoded from pixels (no layers, no original metadata; EXIF is
  stripped), so masked content can't be recovered.

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

- One container for the API and gateway (CPU), which can run rules and NER locally.
- Model servers for the LLM detector and SAM 3.1, either local GPU or a hosted GPU endpoint
  (Modal, Baseten). Model endpoints are configuration, so self-hosters can keep everything
  on their own machines.
- Configuration through environment variables only; `.env.example` lists them.

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
  numbers, IBAN, giro accounts, company IDs, US SSN, UK NINO, payment cards…), the NER model
  (fast mode, the default), the LLM detector (audit mode, opt-in), merged by one
  deterministic resolver.
- **The LLM never rewrites your text.** It only names spans; PII Guard finds them in the
  original, drops anything the model invented, and lets checksum-validated rules win on
  structured IDs. A hallucination can't add text, and a disagreement can't unmask anything.
- **Grammar-aware placeholders.** Hungarian case endings stay outside the placeholder
  (`[[PERSON_x]]nek`), so the model still writes grammatical answers and restoration is exact.
- **Language packs** ([languages.md](languages.md)): Hungarian, English and German today. A
  language is one plugin unit (an entry point for separate distributions) with a conformance
  suite that says what is missing: `pii-guard lang new <code>` to start.
- **Entity policies:** mask, keep (organizations stay readable so the model can reason) or
  block (refuse the request).
- **Per-message detection cache.** Chat clients resend the whole history every turn; only the
  new message is detected.
- **Synthetic data only** ([ADR 0005](decisions/0005-synthetic-data-only.md)). No real
  personal data in the repo, in tests or in prompts to hosted models; CI on every change.

Which Meta model does which job: [why-pii-guard.md](why-pii-guard.md#3-built-on-metas-models-end-to-end).
Using the gateway from a client: [architecture-gateway.md](architecture-gateway.md).

## Open questions

- Which multilingual NER model gives the best Hungarian baseline at acceptable latency?
- Latency budget for the gateway: what is acceptable per request with the LLM pass enabled?
- How to handle placeholders the model invents or mangles (e.g. `PERSON_7f3b`)? Proposed:
  leave them visible and flag the response.
- Mapping store for multi-instance deployments: in-memory with sticky sessions first, an
  encrypted shared store later.
