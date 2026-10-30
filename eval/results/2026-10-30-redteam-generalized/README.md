# Linkage red team with context generalization (2026-10-30)

LAB-1152. The [2026-10-27 red team](../2026-10-27-redteam/README.md) found that with a
five-value candidate list, Muse Spark Open picked the true value 39.2 % of the time against
20.0 % chance (rules + LLM masking). This run tests whether the opt-in linkage protection
lowers that, and how much of the linkage comes from the candidate lists agreeing with each
other rather than from the masked text. Every document and candidate is fictional.

| | |
|---|---|
| Fixtures | the same 5 sets as the full 2026-10-27 runs: 81 documents, 426 distinct values of `mask`-policy types (sha256 in the scorecard) |
| Masking | `rules,llm` (Muse Spark Open on Baseten, `reasoning_effort: low`), one detector run shared by all three contexts |
| Attacker | Muse Spark Open on Baseten (`meta-models/muse-spark-open-1026`, `reasoning_effort: low`, JSON mode, `temperature: 0`), 4 decoys, seed 1088 |
| Contexts | `decoys` (as on 2026-10-27); `decoys+generalized` (same detections re-masked with `ORGANIZATION` and `COMPANY_ID_HU` masked, then `generalize_context`); `decoys-isolated` (one request per entity type, candidates for that type only) |
| Code | branch `feat/LAB-1152-context-generalization`, commit `3734005` (the scorecard says `a48a2c8`, dirty: the run used that tree before it was committed) |

Reproduce:

```bash
export PII_GUARD_LLM_DETECTOR_API_KEY=$BASETEN_API_KEY PII_GUARD_LLM_DETECTOR_REASONING_EFFORT=low
export PII_GUARD_REDTEAM_API_KEY=$BASETEN_API_KEY
uv run pii-guard eval --fixtures eval/fixtures/hu-smoke.jsonl --fixtures eval/fixtures/en-smoke.jsonl \
  --fixtures eval/fixtures/de-smoke.jsonl --fixtures eval/fixtures/hu-synth-sample.jsonl \
  --fixtures eval/fixtures/en-synth-sample.jsonl --detectors rules,llm --redteam \
  --redteam-contexts decoys,decoys+generalized,decoys-isolated --json out.json --markdown out.md
```

## Results

Re-id = recovered / attacked (masked minus failed). Percentages.

| Context | Masked | Failed | Recovered | Re-id | Chance | Exposure |
|---|---:|---:|---:|---:|---:|---:|
| `decoys` (2026-10-27) | 421 | 0 | 165 | 39.2 | 20.0 | 39.9 |
| `decoys` (this run) | 420 | 0 | 165 | **39.3** | 20.0 | 40.1 |
| `decoys+generalized` | 420 | 4 | 152 | **36.5** | 20.0 | 37.4 |
| `decoys-isolated` | 420 | 0 | 152 | **36.2** | 20.0 | 37.1 |

Per entity type (recovered / attacked):

| Type | `decoys` | `decoys+generalized` | `decoys-isolated` |
|---|---:|---:|---:|
| `PERSON` | 67 / 140 (47.9) | 60 / 139 (43.2) | 69 / 140 (49.3) |
| `EMAIL` | 19 / 25 (76.0) | 19 / 25 (76.0) | 16 / 25 (64.0) |
| `ADDRESS` | 20 / 78 | 26 / 78 | 21 / 78 |
| `DATE_OF_BIRTH` | 11 / 34 | 8 / 34 | 8 / 34 |
| `PHONE` | 13 / 34 | 11 / 34 | 10 / 34 |
| `BANK_ACCOUNT` | 11 / 31 | 12 / 31 | 11 / 31 |
| `ID_DOCUMENT` | 13 / 28 | 9 / 25 | 10 / 28 |
| `NATIONAL_ID_HU_TAX` | 4 / 14 | 3 / 14 | 3 / 14 |
| `PARCEL_NUMBER_HU` | 3 / 13 | 1 / 13 | 1 / 13 |
| `VEHICLE_PLATE` | 3 / 13 | 2 / 13 | 3 / 13 |
| `NATIONAL_ID_HU_TAJ` | 1 / 10 | 1 / 10 | 0 / 10 |

Per language, re-id `decoys` → `decoys+generalized`: `hu` 101 / 278 → 91 / 274, `en` 49 / 105
→ 49 / 105, `de` 15 / 37 → 12 / 37.

The generalizer rewrote little on this corpus: 7 gendered titles, 3 Hungarian suffixes, no
ages (`redteam.generalization.rewrites` in the scorecard).

## What this shows

- **The baseline reproduces exactly**: 165 recovered in both runs, 39.3 % vs 39.2 %.
- **Generalization barely moves linkage.** 39.3 → 36.5 % is 13 values. With one run at
  `temperature: 0` and about ±2.4 points of binomial standard error, that is within noise.
  `PERSON` drops 4.7 points, `EMAIL` not at all, even with organizations masked.
- **Cross-candidate consistency is not the main clue either.** Taking the other types'
  candidates away (`decoys-isolated`) also lands at 36.2 %; only `EMAIL` drops (76 → 64 %),
  the type whose candidates spell names.
- **So most of the linkage comes from neither.** The remaining suspects are in the candidate
  lists themselves: decoys come from other documents of a small corpus, so a decoy can differ
  from the truth in country format, script or plausibility for the document kind (a company
  address in a tenancy letter). The scorecards do not record which clue decided a guess. The
  text-level rules target clues this corpus has few of; they are kept as an opt-in for text
  that does carry them (salutations, ages, Hungarian inflection), not as a fix.
- **Standard suite unchanged.** Generalization only rewrites words outside placeholders and
  reuses the detections: precision 99.1 %, recall 98.5 %, leak 1.4 % (6 / 426) are the same
  for both variants of this run, and the offline rules-only check over all 210 fixture
  documents leaks 334 / 734 values with and without it.

## Spend

Baseten, at [models.md](../../../docs/models.md#baseten-model-apis-production-detector) prices:
attacker 448 requests, 420,298 prompt tokens (199,424 cached), 345,497 completion tokens:
**$1.77**; masking detector 81 requests: **$0.23**. About **$2.00** in all.

## Limits

- One run per context; run-to-run variance is not measured.
- Same small decoy pool as 2026-10-27 (10–140 values per type). A larger pool, matched to
  the true value's format, is the next measurement, not done here.
- `decoys+generalized` had 4 failed targets (excluded from its rates).
