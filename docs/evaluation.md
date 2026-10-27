# Evaluation

> Status: proposed. The evaluation set is the first thing to build, before the detectors are
> tuned, so every change is measured against the same baseline.

## Why synthetic

We can't publish real documents with personal data, and we shouldn't train or test on them
either ([ADR 0005](decisions/0005-synthetic-data-only.md)). Synthetic documents solve both
problems, and they come with **exact labels for free**: we know which values we inserted and
where.

## The corpus

1. **Fictional identities.** A generator produces people, addresses, ID numbers (with valid
   checksums), bank accounts and companies. All values are fictional and generated from a
   seed, so runs are reproducible. Hungarian names, settlements, postcodes and streets are
   drawn by frequency from the language pack's lexicons
   ([ADR 0009](decisions/0009-third-party-lexicons.md)) and combined at random; every address
   uses one of its settlement's own postcodes. Each prompt also asks for a few **hard
   negatives** that are never labelled: a surname that is a common word, used as the word
   ("egy nagy doboz"), a town outside an address ("a Szeged felé tartó vonat"), a capitalised
   phrase ("Eladó lakás", "Fekete Péntek").
2. **Documents.** A Meta Muse model writes realistic documents around those identities, from
   templates that cover the real shapes of the work:
   - sale and lease contracts, powers of attorney, land registry extracts;
   - letters, court notices, invoices;
   - emails and chat messages in informal register, with typos.
   The model is told which values to use; the generator then **locates every inserted value,
   including inflected forms**, and records the spans as labels. Documents where a value
   can't be located are discarded rather than hand-fixed.
3. **Images.** Synthetic ID cards and scanned pages are rendered from the same identities
   (with blur, rotation, noise and JPEG artefacts), labelled with text boxes and region masks.
4. **Hard cases.** A smaller hand-written set of adversarial examples: names that are also
   common words, numbers that look like IDs but aren't, addresses split across lines, mixed
   languages.

The corpus is split into **train** (for fine-tuning the LLM detector), **dev** and **test**.
The test split is never used for training or prompt tuning.

## Metrics

| Metric | Definition |
|---|---|
| **Precision / recall / F1, per entity type** | Span-level, exact match and overlap match |
| **Leak rate (end to end)** | Share of labelled values that appear, in any surface form, in the request the gateway sends upstream. This is the number that matters most. |
| **Over-masking rate** | Share of masked spans that weren't personal data (hurts answer quality) |
| **Re-identification accuracy** | Share of placeholders in responses restored to the correct, correctly inflected value |
| **Placeholder consistency** | Share of gold entities (per document; the gold spans of one type that are surface forms of each other, `Minta Anna` / `Minta Annának`) whose occurrences are all masked by one and the same placeholder. An unmasked occurrence counts as inconsistent. Also reported over entities with 2+ occurrences (`multi_rate`). |
| **Visual recall** | Share of labelled image regions covered by a mask (IoU threshold) |
| **Latency** | p50 / p95 per request, per pipeline stage |

## Baselines

Each detection change reports against these:

1. **Rules only.**
2. **Rules + NER.**
3. **Rules + NER + prompted LLM** (no fine-tuning).
4. **Rules + NER + fine-tuned LLM.**

The hackathon claim is the difference between 2 and 4, on the test split.

## Languages

Evaluation is multilingual from the start: every fixture record carries a `language`, which
is passed to detectors and the vault, and fixtures are kept one file per language and set
(`eval/fixtures/hu-smoke.jsonl`, `eval/fixtures/en-smoke.jsonl`;
`eval/fixtures/hu-inflection.jsonl` holds names whose stem changes before a suffix, in several
cases). Leak-rate matching goes
through a per-language surface-form hook (`pii_guard.eval.forms`): Hungarian case suffixes
and stem changes (`Annának`, `Kováccsal`) for `hu`, exact matching as the default elsewhere.
The scorecard reports every metric per language and per entity type, plus an overall row.

## Leak rate in practice

The harness masks each document with the vault (only `mask`-policy predictions, as the
gateway would) and searches the masked text for each labelled value: case- and
whitespace-insensitive, through the language's surface forms, and for structured identifiers
on their letters and digits with any separators (a phone number also by its national number,
a Hungarian IBAN also by the giro number inside it). A value is **leaked** if any form
survives. It is **partially leaked** if not, but an identifying token of it survives (for
example the street of an address whose postcode alone was masked). Tokens that also occur
outside the labelled spans, and generic words such as `utca` or month names, don't count.

## Reporting

`uv run pii-guard eval --fixtures eval/fixtures --detectors rules --json OUT` prints a
Markdown scorecard and writes the JSON one (format in [contracts.md](contracts.md)), with the
commit hash, detector names and the SHA-256 of every fixture file. `--language en` restricts
the run to one language. Results for every release are committed under `eval/results/` with
the model versions, corpus seed and commit hash, so anyone can reproduce them.

The hand-written smoke sets are built by `eval/fixtures/build_smoke.py` (inline
`{{TYPE|value}}` labels, checksum-valid fictional identifiers); a test fails if the committed
JSONL is stale.

## Lexicons: diversity and the address rule

Measured when the lexicons landed ([ADR 0009](decisions/0009-third-party-lexicons.md)).

**Generator diversity.** Distinct values in the 50 documents `plan_document("hu", seed, i)`
plans for `i < 50` (no model call; surnames count people and mothers):

| Seed | Generator | Surname slots | Distinct surnames | Address slots | Distinct settlements | Hard negatives |
|---|---|---:|---:|---:|---:|---:|
| 42 | v1 (hand lists: 54 surnames, 20 towns) | 106 | 45 | 78 | 19 | 0 |
| 42 | v2 (lexicons) | 116 | 85 | 79 | 69 | 122 |
| 7 | v1 | 113 | 45 | 83 | 18 | 0 |
| 7 | v2 | 113 | 82 | 90 | 77 | 129 |

A 50-document sample can't show 10× more distinct values than before: it has only ~110
surname and ~80-90 address slots, and the old lists already filled 45 and 19 of them. v2
fills ~73% of surname slots and ~86% of address slots with distinct values, against 40-42%
and 22-24%;
the lists behind them are 227 surnames (4×) and 3155 settlements (158×). Budapest still makes
up about a sixth of addresses, as in real life.

**Rules-only ADDRESS detection** (`uv run pii-guard eval --fixtures eval/fixtures/hu-<set>.jsonl
--detectors rules`), before and after the full-address recogniser:

| Set | | Exact P | Exact R | Overlap P | Overlap R | Leaked | Partially leaked | Over-masked |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| hu-smoke (13 addresses) | before | 0.00 | 0.00 | 1.00 | 0.92 | 1 | 12 | 0 |
| | after | **1.00** | **1.00** | 1.00 | **1.00** | **0** | **0** | 0 |
| hu-synth-sample (39) | before | 0.00 | 0.00 | 1.00 | 1.00 | 0 | 37 | 0 |
| | after | **1.00** | **1.00** | 1.00 | 1.00 | 0 | **0** | 0 |

Before, only the postcode was masked, so the street and house number survived ("partially
leaked"); now the whole address is one span. A postcode that belongs to another settlement
keeps the address shape but isn't boosted above a bare postcode's score.

## Comparison with open-source tools

pii-guard is also scored against the closest open-source alternatives, on the same fixtures
and with the same scorer (`pii_guard.eval.baselines`):

```bash
uv sync --extra baselines            # Presidio + spaCy models, in-process
uv run pii-guard eval --fixtures eval/fixtures/hu-smoke.jsonl --fixtures eval/fixtures/en-smoke.jsonl \
    --detectors rules --baselines presidio,llm-guard,privaite --json OUT.json
python -m pii_guard.eval.baselines.compare OUT.json [MORE.json ...] --out comparison.md
make baselines                       # the same, plus the live baseline tests
```

`--baselines` adds a `baselines` object to the scorecard (one section per tool: `info` with
tool versions, model names and the configuration, `reversible`, `unmapped_labels`, and
`overall` / `languages` blocks in the usual format) and `meta.skipped_baselines`; the
Markdown gets a comparison table per language and per entity type. A tool that can't start
is skipped with a reason, like a detector; a tool that fails on a document fails the run.
Committed results live in `eval/results/` (see its README for the current numbers).

### The tools and their configuration

Every tool runs with its **default configuration**. The only choices we made are the ones a
default doesn't cover, listed here.

| Tool | How it runs | Configuration |
|---|---|---|
| **Presidio** 2.2.365 | in-process (`--extra baselines`) | `AnalyzerEngine` with the predefined recognizers and default threshold, `AnonymizerEngine` default operator (`<ENTITY_TYPE>`). spaCy `en_core_web_lg` for `en` (Presidio's default); Presidio ships nothing for Hungarian, so `hu` uses huSpaCy `hu_core_news_lg` 3.8.1, the strongest spaCy pipeline for Hungarian, with the language-independent recognizers Presidio registers for a non-English language. |
| **LLM Guard** 0.3.16 | worker process, own environment | `Anonymize(Vault())` with defaults: the `Isotonic/deberta-v3-base_finetuned_ai4privacy_v2` NER model, threshold 0.5, its default entity list, language `en` (it supports only `en` and `zh`, so Hungarian documents also go through `en`). `Deanonymize` restores. A fresh vault per document. |
| **PrivAiTe** 0.7.3 | worker process, own environment | The proxy's `PIIEngine` in-process with the `pii` section of its shipped `config/privaite.openai.yaml`: preset `onnx` (Presidio with `fr_core_news_md` + `en_core_web_lg`, plus the ONNX `openai/privacy-filter` model), placeholder anonymization, cards masked, secrets redacted. Each document is one user message through `process_request`, as the proxy does; `process_response` restores. Its detection doesn't take a language: every text goes through its French and English configuration. |

LLM Guard pins `transformers==4.51.3` and Presidio 2.2.358; PrivAiTe needs
`transformers>=5.3`. They can't share an environment with each other, so each runs as a
worker (`src/pii_guard/eval/baselines/workers/`) in an ephemeral `uv` environment built from
pinned requirements (`src/pii_guard/eval/baselines/envs/*.txt`, compiled from `*.in` with
`uv pip compile --universal --python-version 3.12 --no-header --no-annotate X.in -o X.txt`).
pii-guard's own dependencies are unchanged. Presidio caps `numpy` below 2.5, so the `baselines` extra is declared as conflicting with the `ner` extra (`[tool.uv] conflicts`): uv resolves each on its own and the two can't be installed together. Documents reach a worker over a local pipe; the
only network traffic is the first-run download of packages and models (Hugging Face Hub,
spaCy wheels). Workers get no credentials from the environment, telemetry switches are set,
and their stderr is discarded (the tools log detected values) unless
`PII_GUARD_BASELINE_DEBUG=1`.

### Scoring rules

- **Spans.** P/R/F1 use the spans the tool actually replaced: LLM Guard's and PrivAiTe's
  are captured from the call into their own replacement step, Presidio's are the analyzer
  results. Where spans overlap (Presidio), pii-guard's own resolver applies
  (`detect.pipeline.resolve_spans`, with no detector authoritative): same-type overlaps
  merge, otherwise `keep` types lose, then longer spans and higher scores win.
- **Leak rate** is measured on the text the tool itself produces (its own masking), with its
  placeholders blanked out like pii-guard's. Leak checking doesn't look at types, so a value
  the tool masked under the wrong type counts as protected for leak rate while costing it a
  false positive and a miss in P/R.
- **Over-masking** counts the tool's mapped spans that overlap no gold span. A tool masks
  everything it detects, including organisations, which pii-guard's policy keeps; masked
  organisations overlap gold spans, so they don't count as over-masking.
- **Round trip** uses the tool's own restore (LLM Guard `Deanonymize`, PrivAiTe
  `process_response`). Presidio's default operator is irreversible: shown as n/a.
- **Latency** is detection time measured inside the tool, after one warm-up call, CPU only,
  without the pipe to the worker; masking time is recorded separately in the JSON.

### Entity-label mapping

All three tools use Presidio's label vocabulary plus a few labels of their own. One table
(`pii_guard.eval.baselines.mapping.LABEL_MAP`) maps them for every tool; LLM Guard's regex
variants (`EMAIL_ADDRESS_RE`, `CREDIT_CARD_RE`, `US_SSN_RE`) map like the label without `_RE`.

| Tool label | pii-guard type | Emitted by | Note |
|---|---|---|---|
| `PERSON` | `PERSON` | all | |
| `EMAIL_ADDRESS` | `EMAIL` | all | |
| `PHONE_NUMBER` | `PHONE` | all | |
| `LOCATION` | `ADDRESS` | Presidio, PrivAiTe | cities, countries and streets; overlap matching credits a city inside an address |
| `DATE_TIME` | `DATE_OF_BIRTH` | Presidio, PrivAiTe | no tool separates birth dates from other dates: recall for the birth dates it masks, a false positive for every other date |
| `IBAN_CODE` | `BANK_ACCOUNT` | all | |
| `CREDIT_CARD` | `BANK_ACCOUNT` | all | cards are `BANK_ACCOUNT` in pii-guard's taxonomy |
| `US_BANK_NUMBER` | `BANK_ACCOUNT` | Presidio, LLM Guard | |
| `FINANCIAL` | `BANK_ACCOUNT` | PrivAiTe | privacy-filter `account_number` |
| `US_SSN` | `ID_DOCUMENT` | all | national numbers without a type of their own |
| `US_ITIN` | `ID_DOCUMENT` | Presidio | |
| `US_PASSPORT` | `ID_DOCUMENT` | Presidio | |
| `US_DRIVER_LICENSE` | `ID_DOCUMENT` | Presidio | |
| `UK_NHS` | `ID_DOCUMENT` | Presidio, PrivAiTe | |
| `UK_NINO` | `ID_DOCUMENT` | none by default | not in the default recognizer set; mapped for completeness |
| `UK_PASSPORT` | `ID_DOCUMENT` | none by default | as above |
| `ORGANIZATION` | `ORGANIZATION` | Presidio | `keep` policy in pii-guard |
| `ORG` | `ORGANIZATION` | none by default | alias, mapped for completeness |
| `URL` | unmapped | all | |
| `IP_ADDRESS` | unmapped | all | |
| `MAC_ADDRESS` | unmapped | Presidio | |
| `CRYPTO` | unmapped | Presidio, LLM Guard | |
| `UUID` | unmapped | Presidio, LLM Guard | |
| `NRP` | unmapped | Presidio | nationality, religious or political group |
| `MEDICAL_LICENSE` | unmapped | Presidio | |
| `SECRET` | unmapped | PrivAiTe | credentials |
| `CUSTOM` | unmapped | LLM Guard | hidden names; none by default |

**Unmapped** labels (and any label not in the table) have no pii-guard counterpart: they are
left out of P/R and over-masking, but the tool still masks them, so the leak rate sees what
it sent. Their counts per label are in the scorecard (`unmapped_labels`).

Nothing a tool emits maps to `NATIONAL_ID_HU_TAX`, `NATIONAL_ID_HU_TAJ`, `COMPANY_ID_HU`,
`PARCEL_NUMBER_HU` or `VEHICLE_PLATE`: the tools have no such recognizers, so their recall on
those types is 0 by construction, while their leak rate still credits a value they masked
under another label (a tax number caught as `PHONE_NUMBER`, say).

### Reading the numbers

- The **Muse-generated** fixtures (`*-synth-sample.jsonl`) were written by the same model
  family pii-guard's LLM detector uses, which flatters Muse-based detection. The hand-written
  smoke sets don't have that bias.
- The fixture sets are small (38 smoke, 30 synthetic documents): differences of a few
  points are noise.
- `pii-guard rules` is the rules-only pass, with no name detection; names come from the NER
  and LLM passes. Compare it with the tools for structured identifiers, not for `PERSON`.
