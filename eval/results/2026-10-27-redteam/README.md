# Re-identification red team (2026-10-27)

`pii-guard eval --redteam`: an attacker model gets the masked text, exactly what an upstream
model would receive, and tries to recover the original value behind every placeholder. Each
guess is scored against the hidden labelled value (`pii_guard.eval.redteam`; definitions in
[docs/evaluation.md](../../../docs/evaluation.md#re-identification-red-team)). Every document
and candidate value is fictional.

| | |
|---|---|
| Fixtures | full runs: `hu-smoke`, `en-smoke`, `de-smoke`, `hu-synth-sample`, `en-synth-sample` (81 documents, 426 distinct labelled values of `mask`-policy types); smoke runs: the three smoke sets (51 documents, 173 values). sha256 in each scorecard |
| Masking | `rules` (no model) or `rules,llm` (Muse Spark Open on Baseten, `reasoning_effort: low`, the production detector) |
| Attacker | Meta's open-weight **Muse Spark Open** on Baseten Model APIs (`meta-models/muse-spark-open-1026`, `reasoning_effort: low`, JSON mode, `temperature: 0`); once **Muse Spark 1.3** on the Meta Model API (`muse-spark-1.3`, `reasoning_effort: low`) for comparison |
| Contexts | `masked-only` (masked text alone); `decoys` (each placeholder comes with 5 shuffled candidates of its type: the true value and 4 decoys from the same corpus, same language first, seed 1088) |
| Code | `redteam-rules-baseten` and `redteam-rules-llm-baseten`: commit `f97eec600803` (the second is flagged dirty: the tree was edited while it ran, adding only the detector token counter of commit `7cde2fd8a061`; the code that ran is `f97eec6`); smoke runs: `7cde2fd8a061`, clean |
| NER | **not measured.** No fine-tuned or distilled NER checkpoint is published, so `rules,ner` is left out |

Reproduce (the full runs cost about $0.50–0.60 of Baseten attacker tokens each):

```bash
export PII_GUARD_LLM_DETECTOR_API_KEY=$BASETEN_API_KEY      # masking (rules,llm)
export PII_GUARD_LLM_DETECTOR_REASONING_EFFORT=low
export PII_GUARD_REDTEAM_API_KEY=$BASETEN_API_KEY           # attacker; URL and model default
uv run pii-guard eval --fixtures eval/fixtures/hu-smoke.jsonl --fixtures eval/fixtures/en-smoke.jsonl \
  --fixtures eval/fixtures/de-smoke.jsonl --fixtures eval/fixtures/hu-synth-sample.jsonl \
  --fixtures eval/fixtures/en-synth-sample.jsonl --detectors rules,llm --redteam \
  --json out.json --markdown out.md
# Muse Spark 1.3 as the attacker:
#   --attacker-url https://api.meta.ai/v1 --attacker-model muse-spark-1.3 \
#   --attacker-key-env META_API_KEY --attacker-reasoning-effort low
```

## Results (81 documents, Muse Spark Open as attacker)

*Leaked*: values that survive the masked text (no guess needed). *Re-id*: masked values the
attacker recovered (normalized match). *Chance*: expected re-id when picking a candidate at
random. *Exposure* (the leak score): (leaked + recovered) / values. Percentages.

| Masking | Context | Values | Leaked | Masked | Recovered | Re-id | Partial | Chance | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| rules | `masked-only` | 426 | 182 | 244 | 4 | 1.6 | 11.9 | – | **43.7** |
| rules | `decoys` | 426 | 182 | 244 | 103 | 42.2 | 3.3 | 20.0 | **66.9** |
| rules + LLM | `masked-only` | 426 | 5 | 421 | 1 | 0.2 | 3.8 | – | **1.4** |
| rules + LLM | `decoys` | 426 | 5 | 421 | 165 | 39.2 | 3.6 | 20.0 | **39.9** |

0 failed requests in both runs (144 and 145 attacker requests).

### Per language (exposure %, re-id % in brackets)

| Masking | Context | `hu` (279 values) | `en` (110) | `de` (37) |
|---|---|---:|---:|---:|
| rules | `masked-only` | 42.7 (2.4) | 46.4 (0.0) | 43.2 (0.0) |
| rules | `decoys` | 59.9 (31.7) | 81.8 (66.1) | 75.7 (57.1) |
| rules + LLM | `masked-only` | 0.7 (0.4) | 2.7 (0.0) | 2.7 (0.0) |
| rules + LLM | `decoys` | 34.4 (34.2) | 53.6 (52.3) | 40.5 (38.9) |

### Per entity type, rules + LLM (recovered / masked)

| Type | `masked-only` | `decoys` |
|---|---:|---:|
| `PERSON` | 0 / 141 | 72 / 141 |
| `ADDRESS` | 0 / 78 | 21 / 78 |
| `DATE_OF_BIRTH` | 0 / 34 | 11 / 34 |
| `PHONE` | 0 / 34 | 12 / 34 |
| `BANK_ACCOUNT` | 0 / 31 | 12 / 31 |
| `ID_DOCUMENT` | 0 / 28 | 10 / 28 |
| `EMAIL` | 0 / 25 | 19 / 25 |
| `NATIONAL_ID_HU_TAX` | 0 / 14 | 3 / 14 |
| `PARCEL_NUMBER_HU` | 0 / 13 | 2 / 13 |
| `VEHICLE_PLATE` | 0 / 13 | 2 / 13 |
| `NATIONAL_ID_HU_TAJ` | 1 / 10 | 1 / 10 |

Per document kind: `by_kind` in the JSON scorecards.

## Attacker comparison (51 smoke documents, rules + LLM masking)

Each run masks the documents itself, so the masked texts are from separate detector runs (both
left 1 of 173 values unmasked).

| Attacker | Context | Masked | Recovered | Re-id | Chance | Exposure | Failed requests (targets) |
|---|---|---:|---:|---:|---:|---:|---:|
| Muse Spark Open (Baseten) | `masked-only` | 172 | 2 | 1.2 | – | 1.7 | 0 |
| Muse Spark Open (Baseten) | `decoys` | 172 | 69 | 40.1 | 20.3 | 40.5 | 0 |
| Muse Spark 1.3 (Meta API) | `masked-only` | 172 | 0 | 0.0 | – | 0.6 | 0 |
| Muse Spark 1.3 (Meta API) | `decoys` | 172 | 56 | 41.8 | 20.3 | 42.2 | 8 (38) |

Muse Spark 1.3 failed 8 `decoys` requests (38 targets, excluded from its rates): it used
270,297 reasoning tokens in 113 requests (retries included), against 59,764 in 84 for Muse
Spark Open. The scorecard does not record why a request failed; the likely cause is answers
running into the 4,096-token completion limit.

## What this shows

- **Placeholders hold against reconstruction.** Given only the masked text, neither Meta model
  recovered more than 2 of 421 masked values (rules + LLM). The 4 recoveries with rules-only
  masking were Hungarian identifiers (TAJ, tax ID, ID document). The *partial* rate with
  rules-only masking (11.9 %, against 3.8 % with the LLM detector) comes from identifying
  tokens of values the rules left in the text, the plain leak problem the LLM detector solves.
- **Masking does not stop linkage.** With a candidate list, the attacker picked the right value
  about twice as often as chance (39–42 % vs 20 %), for both masking configurations and both
  attackers. Context that stays in the text (likely candidates: gender and role words,
  inflection, country formats, organisation names, which are kept by policy) narrows the
  candidates; the scorecards do not record which clue decided a guess. E-mail addresses were linked 19 of 25 times with rules + LLM. Placeholders
  protect values; they don't make a document anonymous against someone who already holds a
  short list of candidates.
- **Rules alone are not enough.** Exposure without the LLM detector is 43.7 % before any attack,
  because names and prose addresses survive.

## Spend

Token counts are in each scorecard (`redteam.usage`, `redteam.detector_usage`). Baseten prices
as in [models.md](../../../docs/models.md#baseten-model-apis-production-detector) ($1.25 per
million input tokens, $0.15 cached, $4.25 output).

| Run | Attacker | Masking detector |
|---|---:|---:|
| `redteam-rules-baseten` | $0.48 (Baseten) | – |
| `redteam-rules-llm-baseten` | $0.58 (Baseten) | not metered (run predates the counter) |
| `redteam-smoke-rules-llm-baseten` | $0.34 (Baseten) | $0.12 (Baseten) |
| `redteam-smoke-rules-llm-spark-1.3` | Meta Model API: 61,182 prompt and 282,026 completion tokens; price not published to us | $0.13 (Baseten) |

Baseten total about $1.9, including two pilot runs on `en-smoke` (about $0.05, not committed)
and an estimated $0.25 for the unmetered masking run.

## Limits

- Decoys come from the same small fictional corpus (10–141 masked values per type), so a decoy can
  differ from the truth in format (country code, postcode shape); that is a realistic clue,
  but a larger candidate pool would lower both chance and re-id.
- One run per configuration at `temperature: 0`; run-to-run variance is not measured here.
- Scoring is a normalized match (case, spacing and punctuation ignored, inflected surface forms
  accepted); a semantically right but differently written guess counts as missed.
