# Journey: how pii-guard got here

A dated record of what changed, what it did to the numbers, and what each change cost. It is
written for three readers: **contributors** (why the code looks the way it does), **users**
(what to run and what to expect), and **reviewers and judges** (impact, use of Meta's models,
technical depth). Every number links to the committed file it comes from. A number backed
only by a comment on the project's tracking ticket is marked *(ticket comment, LAB-XXXX)*.

All data behind these numbers is fictional ([ADR 0005](decisions/0005-synthetic-data-only.md)).
Times are UTC, taken from each pull request's merge time.

**How to keep this current:** a pull request that changes a headline metric (leak rate, F1,
latency or cost of a recommended configuration) adds or updates its milestone here, and
updates the two tables below.

## Where we are (2026-10-27)

**pii-guard cuts the share of personal data that reaches the model from about half to under
1 %, in Hungarian and English, with no refusals.** On the hand-written smoke sets, rules alone
leak 52.6 % (Hungarian) and 46.7 % (English) of labelled values. Rules plus Muse Spark Open on
Baseten leak 0.9 % and 0.0 %, at a median 1.2–1.8 s and about $2–2.50 per 1,000 messages. A
fast mode with no LLM call (rules plus a small NER model distilled from Muse Glimmer) gets
Hungarian down to 0.9 % and English to 0.0 % at tens of milliseconds per message. On a public benchmark
(Ai4Privacy OpenPII, 600 documents, milestone 23) strict mode leaks 3.9 % and fast mode 38.0 %:
fast mode suits text like ours, not unfamiliar number formats.

| Language | Mode | Best configuration | Leak | F1 (overlap) | p50 latency | $ / 1k msgs | Source |
|---|---|---|---:|---:|---:|---:|---|
| Hungarian | strict | rules + Muse Spark Open (Baseten, `low`) | **0.9 %** | 98.4 | 1.8 s | 2.42 | [2026-10-27-baseten](../eval/results/2026-10-27-baseten/README.md), `hu-smoke` (31 docs) |
| English | strict | rules + Muse Spark Open (Baseten, `low`) | **0.0 %** | 97.1 | 1.2 s | 1.99 | same, `en-smoke` (10 docs) |
| Hungarian | fast | rules (with ID/parcel rules) + distilled NER, large | **0.9 %** | 97.9 | 28 ms (MPS)¹ | no API call | [2026-10-27-comparison](../eval/results/2026-10-27-comparison/README.md), `hu-smoke` (31 docs) |
| English | fast | rules + distilled NER, large | **0.0 %** | 98.5 | 36 ms (MPS) | no API call | [distilled/large/en-smoke.md](../eval/results/ner/distilled/large/en-smoke.md), [latency-large.json](../eval/results/ner/distilled/latency-large.json) |
| either | none | rules only (baseline) | 52.6 % / 46.7 % | 62.1 / 64.0 | < 1 ms | no API call | [distilled/rules/](../eval/results/ner/distilled/rules/) `hu-smoke.md`, `en-smoke.md` |

¹ Measured in the 2026-10-27 comparison (milestone 23), which confirmed the 0.9 % figure
that milestone 14 had only stated in docs/models.md: 1 of 106 labelled values, F1 97.9. That
run's machine was under unrelated load too (load average about 15 on 10 cores), so read
the latency as relative. On the public Ai4Privacy set the same fast mode leaks 35–40 %
(milestone 23); strict mode leaks 3.5–4.8 %. The distilled weights are not published yet:
you train them yourself (see [models.md](models.md#ner-detector)).

Leak = share of labelled values that still appear, in any surface form, in the text the
model would receive ([evaluation.md](evaluation.md#leak-rate-in-practice)). The smoke sets
are small (31 + 10 documents): one leaked value is about 1 point on Hungarian and 3 on
English.

### Leak rate over time

Same scorer, hand-written smoke sets (no model wrote them). `hu-smoke` grew from 28 to 31
documents with LAB-1127; rows after that use the 31-document set where marked.

| When (UTC) | PR | Configuration | `hu-smoke` leak | `en-smoke` leak | Source |
|---|---|---|---:|---:|---|
| 10-26 21:13 | [#7](https://github.com/watt-mind/pii-guard/pull/7) | rules (first scorer run) | 52.6 % | 60.0 % | *(ticket comment, LAB-1083)* |
| 10-26 21:28 | [#9](https://github.com/watt-mind/pii-guard/pull/9) | rules + English rules | 52.6 % | 46.7 % | [ner/rules/](../eval/results/ner/rules/) |
| 10-26 22:51 | [#15](https://github.com/watt-mind/pii-guard/pull/15) | rules + NER, zero-shot | 17.5 % | 10.0 % | [ner/zero-shot/](../eval/results/ner/zero-shot/) |
| 10-26 22:51 | [#15](https://github.com/watt-mind/pii-guard/pull/15) | rules + NER, fine-tuned | 12.4 % | 3.3 % | [ner/fine-tuned/](../eval/results/ner/fine-tuned/) |
| 10-26 23:14 | [#16](https://github.com/watt-mind/pii-guard/pull/16) | rules + Muse Spark 1.3 (Meta API) | 1.0 % | 0.0 % | [2026-10-26-baselines](../eval/results/2026-10-26-baselines/comparison.md) |
| 10-26 23:14 | [#16](https://github.com/watt-mind/pii-guard/pull/16) | *Presidio / LLM Guard / PrivAiTe* | *28.9 / 49.5 / 19.6 %* | *10.0 / 30.0 / 0.0 %* | same |
| 10-26 23:10 | (not merged) | rules + Muse Glimmer 30B, zero-shot | 0.0 % (hu + en pooled) | | [2026-10-27-baseten](../eval/results/2026-10-27-baseten/README.md#compared-with-muse-spark-13-and-muse-glimmer), *(ticket comment, LAB-1109)* |
| 10-27 07:45 | [#23](https://github.com/watt-mind/pii-guard/pull/23) | rules + NER distilled from Glimmer, large | 10.3 % | 0.0 % | [ner/distilled/large/](../eval/results/ner/distilled/large/) |
| 10-27 07:45 | [#23](https://github.com/watt-mind/pii-guard/pull/23) | same, plus ID/parcel rules (31 docs) | 0.9 % | 0.0 % | [models.md](models.md#distilled-from-muse-glimmer); measured in [2026-10-27-comparison](../eval/results/2026-10-27-comparison/README.md) |
| 10-27 08:01 | [#24](https://github.com/watt-mind/pii-guard/pull/24) | rules + Muse Spark Open (Baseten, 31 docs) | 0.9 % | 0.0 % | [2026-10-27-baseten](../eval/results/2026-10-27-baseten/README.md) |
| 10-27 | [#45](https://github.com/watt-mind/pii-guard/pull/45) | fast: rules + distilled NER, large | 0.9 % | 0.0 % | [2026-10-27-comparison](../eval/results/2026-10-27-comparison/README.md) |
| 10-27 | [#45](https://github.com/watt-mind/pii-guard/pull/45) | strict: rules + NER + Muse Spark Open | 0.9 % | 0.0 % | same |
| 10-27 | [#45](https://github.com/watt-mind/pii-guard/pull/45) | *Presidio / LLM Guard / PrivAiTe* | *33.0 / 50.0 / 17.9 %* | *10.0 / 30.0 / 0.0 %* | same |

The same history as charts, generated from the run records in
[`eval/results/runs/`](../eval/results/runs/) by `pii-guard eval report` (all runs, tables and
the run log: [benchmarks.md](benchmarks.md)). The table above is their text version.

![Leak rate over time on the hand-written smoke sets, per pii-guard configuration](benchmarks/progress.svg)

![Leak rate vs detection latency on the smoke sets, pii-guard configurations and the open-source tools](benchmarks/leak-vs-latency.svg)

### Spend so far

About **$17** of compute for everything measured here.

| What | Where | Cost | Source |
|---|---|---:|---|
| Distillation corpus (5,004 billed calls) | Meta Model API, contributor tier | $1.05 | [models.md](models.md#distilled-from-muse-glimmer) |
| Glimmer teacher labels + student training | Modal (H100, A10G, L40S) | ~$3 (estimate) | [models.md](models.md#distilled-from-muse-glimmer) |
| Glimmer zero-shot evaluation (about 1 GPU hour) | Modal (H100) | ~$4 (estimate) | *(ticket comment, LAB-1109)* |
| Visual eval on specimen IDs (505 live SAM calls) | Meta Model API, SAM 3.1 | ~$1.26 | *(ticket comment, LAB-1120)* |
| Production detector: four eval runs + tests | Baseten Model APIs | ~$0.84 of the $100 credit | [2026-10-27-baseten](../eval/results/2026-10-27-baseten/README.md#spend) |
| Re-identification red team (four runs + pilots) | Baseten Model APIs; Meta Model API | ~$1.9 Baseten; 343k Meta API tokens (price not published to us) | [2026-10-27-redteam](../eval/results/2026-10-27-redteam/README.md#spend) |
| Fresh comparison: strict mode on 8 fixture sets incl. 600 public documents | Baseten Model APIs | ≤ $4.50 | [2026-10-27-comparison](../eval/results/2026-10-27-comparison/README.md#spend) |

Early development calls to the Meta Model API (the first corpus samples, live tests) were not
metered separately and are not included.

## Milestones

### 1. Skeleton, rules, vault, API (2026-10-26, 20:36–20:56)

PRs [#1](https://github.com/watt-mind/pii-guard/pull/1), [#3](https://github.com/watt-mind/pii-guard/pull/3),
[#4](https://github.com/watt-mind/pii-guard/pull/4), [#5](https://github.com/watt-mind/pii-guard/pull/5).

The package, CI, and the three pieces everything else hangs on: checksum-validated rules for
structured identifiers (Hungarian tax and TAJ numbers, IBAN, giro accounts, phones, emails,
plates, company IDs), the vault that swaps values for keyed, reversible placeholders and
restores them in a stream, and the REST API.

- **Decision:** reversible keyed pseudonyms instead of one-way redaction
  ([ADR 0007](decisions/0007-keyed-pseudonyms.md)), so the answer can name the real person;
  fail closed on every error path ([ADR 0006](decisions/0006-fail-closed.md)).
- **Metrics:** none yet; rules shipped with 151 detector tests and 100 % line and branch
  coverage of `pii_guard.detect` *(ticket comment, LAB-1081)*.

### 2. LLM detector on Muse Spark (2026-10-26, 21:06)

PR [#6](https://github.com/watt-mind/pii-guard/pull/6), LAB-1086.

A detector that asks an OpenAI-compatible model for the personal data in a text, as JSON, and
then finds each returned string in the original itself. The model never rewrites the text:
anything it invents is dropped, and validated rules keep their spans when they disagree.
Developed against Muse Spark 1.3 on the Meta Model API with fictional text only.

- **Decision:** any OpenAI-compatible endpoint, configured by URL and model id, so the same
  code runs against a hosted API for development and open weights on your own hardware for
  real data ([models.md](models.md#llm-detector)).
- **Measured** in milestone 6.

### 3. Evaluation harness and the first baseline (2026-10-26, 21:13)

PR [#7](https://github.com/watt-mind/pii-guard/pull/7), LAB-1083.

Fixture format, a scorer for precision, recall, F1 and **leak rate** (does any form of the
value survive in what the model sees?), and `pii-guard eval`. Multilingual from the first
commit: every record carries a language, and leak matching goes through per-language surface
forms, so `Annának` counts as a leak of `Anna`.

- **Before → after:** no numbers → rules-only leak 52.6 % (Hungarian), 60.0 % (English);
  overlap precision 100 % *(ticket comment, LAB-1083)*.
- **Decision:** leak rate, not F1, is the number that matters most
  ([evaluation.md](evaluation.md#metrics)).

### 4. Language packs and English rules (2026-10-26, 21:28)

PR [#9](https://github.com/watt-mind/pii-guard/pull/9), LAB-1096.

Per-language rules, inflection, prompts and eval forms behind one language code, with
fallbacks ([ADR 0008](decisions/0008-language-packs.md)), and English rules.

- **Before → after (en-smoke, rules):** leak 60.0 % → 46.7 %, overlap F1 52.2 → 64.0;
  Hungarian unchanged byte for byte *(ticket comment, LAB-1096)*; the 46.7 / 64.0 scorecard is
  in [ner/rules/en-smoke.md](../eval/results/ner/rules/en-smoke.md).

### 5. Synthetic corpus, gateway, images (2026-10-26, 21:23–21:46)

PRs [#8](https://github.com/watt-mind/pii-guard/pull/8) (demo UI),
[#10](https://github.com/watt-mind/pii-guard/pull/10) (corpus, LAB-1087),
[#11](https://github.com/watt-mind/pii-guard/pull/11) (SAM 3.1, LAB-1089),
[#12](https://github.com/watt-mind/pii-guard/pull/12) (gateway, LAB-1100),
[#13](https://github.com/watt-mind/pii-guard/pull/13) (entity policies, LAB-1099).

- **Corpus:** Muse Spark writes contracts, letters, notices and chats around fictional
  identities; the generator then locates every inserted value, including inflected forms, and
  discards any document it can't label exactly. First samples: 20 Hungarian and 10 English
  documents, 0 discarded *(ticket comment, LAB-1087)*.
- **Gateway:** an OpenAI-compatible `/v1/chat/completions` proxy. Adopting pii-guard is a
  change of base URL. Placeholders split across stream chunks are held back until complete,
  and only new messages are detected each turn.
- **Images:** SAM 3.1 finds faces and signatures from a text prompt; regions are filled and
  metadata stripped.
- **Decision:** organisations default to `keep`, so the model can still reason about who
  is who without seeing the people.

### 6. Baselines: Presidio, LLM Guard, PrivAiTe (2026-10-26, 23:14)

PR [#16](https://github.com/watt-mind/pii-guard/pull/16), LAB-1098.

The three closest open-source tools, each in its default configuration, scored with the same
scorer on the same fixtures. This is also the first committed measurement of rules + Muse
Spark 1.3.

| `hu-smoke` (28 docs) | F1 | Leak | Over-masking | p50 |
|---|---:|---:|---:|---:|
| pii-guard rules | 62.1 | 52.6 | 0.0 | 0.1 ms |
| Presidio | 70.1 | 28.9 | 15.5 | 76 ms |
| LLM Guard | 49.2 | 49.5 | 41.7 | 61 ms |
| PrivAiTe | 50.2 | 19.6 | 26.6 | 60 ms |
| **pii-guard rules + Muse Spark 1.3** | **98.2** | **1.0** | **0.0** | 10.6 s |

On English the gap is smaller: PrivAiTe also leaks 0.0 %, at 22.0 % over-masking.
Source: [comparison.md](../eval/results/2026-10-26-baselines/comparison.md).

- **Decision:** compare on the hand-written sets. The Muse-generated sets flatter a
  Muse-based detector ([evaluation.md](evaluation.md#reading-the-numbers)).
- **Trade-off made visible:** the LLM closes the gap but costs seconds per message; that set
  up milestones 9 and 13.

### 7. NER for fast mode (2026-10-26, 22:51)

PR [#15](https://github.com/watt-mind/pii-guard/pull/15), LAB-1106.

A multilingual token-classification encoder (XLM-RoBERTa-base) in-process, for a mode with no
model call. Zero-shot first, then fine-tuned on 223 synthetic documents.

| Overlap F1 / leak, % | rules | + NER zero-shot | + NER fine-tuned |
|---|---|---|---|
| hu-smoke | 62.1 / 52.6 | 89.7 / 17.5 | 94.3 / 12.4 |
| en-smoke | 64.0 / 46.7 | 90.7 / 10.0 | 86.5 / 3.3 |

Latency per ~400-character message: 46 ms p50 on CPU, 17 ms on MPS (M1 Max).
Sources: [eval/results/ner/](../eval/results/ner/), [latency-fine-tuned.json](../eval/results/ner/latency-fine-tuned.json).

- **Trade-off:** fine-tuning on narrow synthetic data raised English over-masking to 16.2 %
  ([fine-tuned/en-smoke.md](../eval/results/ner/fine-tuned/en-smoke.md)). Fixed in
  milestone 12.
- **Rejected:** GLiNER, which over-masked 18–20 % and was 3–4× slower
  ([models.md](models.md#ner-detector)).

### 8. Images in the API, gateway and UI; specimen-ID eval (2026-10-26, 22:51 and 23:34)

PRs [#17](https://github.com/watt-mind/pii-guard/pull/17) (LAB-1110),
[#19](https://github.com/watt-mind/pii-guard/pull/19) (LAB-1120).

`POST /v1/mask/image`, inline images in the gateway, and an Images tab in the demo UI. Then a
visual recall eval on 65 official specimen ID documents (406 hand-labelled regions; images
kept out of git).

| SAM 3.1 region | Recall @ IoU ≥ 0.5, before → after | Fully covered, before → after |
|---|---:|---:|
| portrait | 76.9 % → **90.8 %** | 12.3 % → **72.3 %** |
| signature | 83.8 % → 83.8 % | 64.9 % → 64.9 % |

"After" changes one SAM prompt, `id photo` → `photo of a person`, picked from a prompt study.
Over-masking is 2.1 % of image area. SAM takes 5.6 s per image at p50 (sequential calls).
Sources: [specimens-before.md](../eval/results/visual/specimens-before.md),
[specimens.md](../eval/results/visual/specimens.md),
[prompt-study.md](../eval/results/visual/prompt-study.md).

- **Known gap:** machine-readable zones (0 %) and printed text values on ID cards (0.4 %) are
  not masked yet; the eval runs OCR text through the rules detector only. Tracked as LAB-1124 and LAB-1125.

### 9. Muse Glimmer zero-shot (2026-10-26, 23:10, measured, not merged)

LAB-1109. Muse Glimmer 30B (open weights, Apache-2.0) served with vLLM on one H100 on Modal.

- **Result:** rules + Glimmer at low reasoning: overlap F1 99.3, recall 100, leak 0.0 % on
  hu + en smoke pooled, at 9.4 s p50 and 20.7 s p95 per document
  ([2026-10-27-baseten](../eval/results/2026-10-27-baseten/README.md#compared-with-muse-spark-13-and-muse-glimmer);
  the scorecard is not committed). First cold start 1,563 s (51 GB download plus compile),
  about $4 of GPU time *(ticket comment, LAB-1109)*.
- **Decision:** quality is there but at about 9 s per document Glimmer is not a request-path
  detector. It became the **teacher** for milestone 12.
- **Side effect:** at higher reasoning Glimmer returns inflected names (`Próba Zsuzsannának`),
  which exposed the leak fixed in milestone 10.

### 10. Hungarian inflection in the vault (2026-10-26, 23:33)

PR [#18](https://github.com/watt-mind/pii-guard/pull/18), LAB-1115.

Hungarian lengthens a final vowel before a suffix (`Zsuzsanna` → `Zsuzsannának`). The vault
only matched an unchanged stem, so inflected forms of vowel-final names went through in clear.
Now every span is keyed on its lemma, the suffix stays outside the placeholder
(`[[PERSON_x]]nak`), and unmask re-inflects the stem.

- **Before → after** (new `hu-inflection.jsonl` fixtures, one-form-per-entity detector
  simulated): leaked values 18/30 → **0/30**; same person, same placeholder 11/18 → 18/18
  *(ticket comment, LAB-1115)*. The fixtures are committed in `eval/fixtures/`; the scorecard
  is not.
- **Decision:** grammar lives in the language pack, not in the detector, so any detector
  benefits.

### 11. Hungarian lexicons and the address rule (2026-10-27, 06:22)

PR [#20](https://github.com/watt-mind/pii-guard/pull/20), LAB-1126.

Name, settlement, postcode and street lexicons from sources whose terms allow it
([ADR 0009](decisions/0009-third-party-lexicons.md)), used by the corpus generator and by a
full-address rule that checks the postcode belongs to the settlement.

- **Before → after (rules only, ADDRESS):** exact recall 0.00 → **1.00** on hu-smoke and
  hu-synth-sample, precision 1.00, partial leaks 12 → 0 and 37 → 0. Before, only the postcode
  was masked and the street survived.
- **Generator diversity (50 planned documents, seed 42):** distinct surnames 45 → 85,
  settlements 19 → 69, hard negatives 0 → 122.
- Source: [evaluation.md, "Lexicons"](evaluation.md#lexicons-diversity-and-the-address-rule).

### 12. Hungarian ID document and parcel numbers (2026-10-27, 07:04)

PR [#21](https://github.com/watt-mind/pii-guard/pull/21), LAB-1127.

The personal identification number (date plus checksum), labelled ID card, passport and
licence numbers, TD1/TD3 MRZ zones with ICAO check digits, and land-registry parcel numbers.
These were the Hungarian leak left over once names were handled.

- **Before → after (rules only, hu-smoke, 31 docs):** `ID_DOCUMENT` leaked 10 → **0**,
  `PARCEL_NUMBER_HU` 6 → **0**, exact precision 1.00; no new false positives, English
  unchanged. Source: [evaluation.md, "ID documents"](evaluation.md#id-documents-and-parcel-numbers).
- **Decision:** a parcel number needs its label (`hrsz.`), because bare fractions and case
  numbers look the same.

### 13. Known values (2026-10-27, 07:31)

PR [#22](https://github.com/watt-mind/pii-guard/pull/22), LAB-1101.

An application that already knows the client's name or an internal case id can pre-load it
into the session (`POST /v1/sessions/{id}/known-values`); the `known` detector then masks it
in every form, deterministically, with no model.

- **Before → after (known-values fixtures, rules only):** overlap recall 5.3 % → **100 %**,
  leak 93.3 % → **0 %** ([evaluation.md](evaluation.md#known-values-pre-loaded-into-the-session));
  consistency 7.7 % → 100 % *(ticket comment, LAB-1101)*.

### 14. NER distilled from Muse Glimmer (2026-10-27, 07:45)

PR [#23](https://github.com/watt-mind/pii-guard/pull/23), LAB-1128.

A 4,964-document fictional corpus (the generator's document kinds plus ten more per language:
logs, forms, CSV, support chat and hard negatives with no personal data, among others), labelled by Glimmer as teacher, used to train
XLM-RoBERTa base and large students. Where Glimmer disagreed with planted gold, those
characters were left out of the loss rather than guessed (499 cases).

| F1 / leak / over-masking, % | fine-tuned (milestone 7) | distilled base | distilled large |
|---|---|---|---|
| hu-smoke | 94.3 / 12.4 / 0.0 | 92.9 / 13.4 / 1.2 | 93.5 / 10.3 / 2.2 |
| en-smoke | 86.5 / 3.3 / **16.2** | 98.5 / 3.3 / **0.0** | 98.5 / 0.0 / **0.0** |

With milestone 12's rules on, hu-smoke reaches 97.9 F1 and 0.9 % leak with the large model.
Training took 5–6 minutes per model. Spend: $1.05 on the Meta Model API, about $3 on Modal.
Sources: [models.md](models.md#distilled-from-muse-glimmer),
[eval/results/ner/distilled/](../eval/results/ner/distilled/).

- **Decision:** recommend large where its latency fits (36 ms MPS, 241 ms CPU, measured under
  load), base otherwise. Neither is the built-in default until the weights are published.

### 15. Muse Spark Open on Baseten as the production detector (2026-10-27, 08:01)

PR [#24](https://github.com/watt-mind/pii-guard/pull/24), LAB-1108.

Meta's open-weight Muse Spark Open on Baseten's Model APIs, `reasoning_effort: low`. It is now
the default detector endpoint.

| `hu-smoke` | F1 | Leak | p50 | p95 | $ / 1k msgs |
|---|---:|---:|---:|---:|---:|
| rules + Muse Spark 1.3, Meta API (28 docs, milestone 6) | 98.2 | 1.0 | 10.6 s | 26.0 s | |
| rules + Muse Spark Open, Baseten (31 docs) | 98.4 | 0.9 | **1.8 s** | **4.0 s** | 2.42 |

Same quality, about 5–6× faster at the median. 0 refusals and 0 invalid outputs in 284
requests. Source: [2026-10-27-baseten](../eval/results/2026-10-27-baseten/README.md).

- **Decision:** at default reasoning the model spent its whole token budget thinking and
  returned nothing (the detector failed closed), so `low` is required.
- **Open question:** Baseten's data-retention terms for the shared Model APIs are not
  confirmed in writing, so only fictional or masked data goes there until they are (LAB-1139,
  [models.md](models.md#baseten-model-apis-production-detector)). For real data, run the same
  open weights on hardware you control.

### 16. Re-identification red team with Muse (2026-10-27)

PR [#28](https://github.com/watt-mind/pii-guard/pull/28), LAB-1088.

Meta's own model against the guard: Muse Spark Open (Baseten) gets the masked text and tries
to recover every masked value, with and without a candidate list (the true value and 4 decoys).
81 fictional documents in Hungarian, English and German, 426 values.

| Masking | Context | Re-id | Chance | Exposure (leak score) |
|---|---|---:|---:|---:|
| rules | masked text only | 1.6 % | – | 43.7 % |
| rules | with 5 candidates | 42.2 % | 20.0 % | 66.9 % |
| rules + Muse Spark Open | masked text only | **0.2 %** | – | **1.4 %** |
| rules + Muse Spark Open | with 5 candidates | 39.2 % | 20.0 % | 39.9 % |

Muse Spark 1.3 on the Meta API as the attacker (51 smoke documents) did the same: 0.0 % from
the masked text alone, 41.8 % with candidates (chance 20.3 %). Cost: about $1.9 of Baseten
credit; the Muse Spark 1.3 run used 343,208 Meta API tokens. NER was not measured (no
published checkpoint). Source:
[2026-10-27-redteam](../eval/results/2026-10-27-redteam/README.md).

- **Decision:** publish exposure next to the leak rate, and describe masking as
  pseudonymisation: placeholders hold against reconstruction, but someone holding a short
  candidate list links a masked document to the right person about twice as often as chance.
  Reducing that would take generalising the context (roles, dates, places) rather than better
  detection; filed as a follow-up (LAB-1152).

### 17. Fictional specimen documents with Muse Image (2026-10-27)

LAB-1121.

24 fictional specimen-style documents (ID card front and back, passport data page, driving
licence, visitor badge, health/member card, filled-in form, signed letter; Hungarian, German
and English variants), committed under `eval/fixtures/visual/` with exact labels and a
`NOTICE`. Muse Image painted the 18 portraits of people who don't exist, 6 signatures, 2 stamps
and 6 textures; every word and number is ours, laid out with Pillow, so each label box is
exact. The issuer is fictional, the MRZ state is `UTO` and all six MRZs pass their check digits.
Four of them replace the hand-drawn samples in the demo's Images tab.

| Fictional set, SAM 3.1 + Tesseract + rules | Regions | Recall @ IoU ≥ 0.5 |
|---|---:|---:|
| portrait | 18 | **100.0 %** |
| signature | 15 | **100.0 %** |
| MRZ | 6 | 0.0 % |
| text values | 110 | 34.5 % |
| all | 149 | 47.6 % |

Over-masking is 0.8 % of image area. Cost: 33 Muse Image images, about $0.33
([generation.json](../eval/fixtures/visual/generation.json)), and 96 SAM calls, about $0.24
([fictional.md](../eval/results/visual/fictional.md)).

- **Finding:** Muse Image drew a whole specimen ID card when asked, but refused the passport
  and driving-licence prompts ("content management policy"). We compose every document from
  parts anyway, because the model's own text is neither exact nor ours to label.
- **Known gap, confirmed on clean input:** even with perfect, checksum-valid MRZs the zone is
  never masked: Tesseract reads long `<` runs as `K`, and only the Hungarian pack has the MRZ
  recogniser (LAB-1124). Names need the LLM detector (LAB-1125).

### 18. Machine-readable zones masked by their layout (2026-10-27)

LAB-1124.

Re-measured on `develop` first: the Hungarian text-MRZ rule of milestone 12 needs exact
30/44-character lines with valid check digits, and Tesseract's reading of the OCR-B zone
never satisfies it, so the specimen MRZ recall was still **0/30**. The new finder
(`visual/mrz.py`) needs neither the check digits nor a text detector: it looks for stacked
OCR lines of about 30, 36 or 44 characters made almost only of `A-Z0-9<` (and the glyphs
Tesseract turns `<` into: `«`, `K`, `c`, `£`), and returns one `ID_DOCUMENT` box per zone,
the union of its words, so a single box covers the whole zone.

| SAM 3.1 + Tesseract + rules | MRZ regions | MRZ recall @ IoU ≥ 0.5 before | after | Over-masking before | after |
|---|---:|---:|---:|---:|---:|
| Official specimens (LAB-1120) | 30 | 0.0 % | **76.7 %** | 2.1 % | 2.6 % |
| Fictional set (milestone 17) | 6 | 0.0 % | **100.0 %** | 0.8 % | 0.8 % |

Overall specimen recall moves from 23.2 % to 28.8 %; portrait, signature and text values are
unchanged. No stray zone on the 35 specimen images without an MRZ. Cost: 260 + 96 SAM calls,
about $0.89 (the specimen re-run was served from the cache). Reports are local, not
committed; reproduce with the commands in [evaluation.md](evaluation.md).

- **Still missed (7/30):** zones where Tesseract returns too little to work with (a
  hologram-covered French card, a Polish passport with three words read), single surviving
  lines (one line of a 2- or 3-line zone covers under half the labelled box), and a one-line
  driving-licence MRZ with a single filler.

### 19. Person names inside company names (2026-10-27)

LAB-1149.

In fast mode a Hungarian business name that carries a person's name (`Tóth és Társa Bt.`,
`Kiss-Lukács Kft.`, `Molnár Péter Bt.`) was one `ORGANIZATION` to the NER, and organisations
are kept, so the name reached the model. A rule in the Hungarian pack now finds the name part
before a legal form with the surname and given-name lexicons and masks only it
(`[[PERSON_x]] és Társa Bt.`); sole traders (`e.v.`, `egyéni vállalkozó`) are masked even when
the surname is not in the lexicon.

- **Before → after** (new `hu-company-names.jsonl`, 44 docs, 54 names inside company names):
  rules + distilled large NER **61.1 % → 0 %** of those names leaked, rules alone 100 % → 0 %;
  over-masking of company names without a person 0 / 30 → 0 / 30. Default sets unchanged
  except one more true-positive `PERSON` with the rules. Source:
  [evaluation.md, "Person names inside company names"](evaluation.md#person-names-inside-company-names),
  *(ticket comment, LAB-1149)*.
- **Decision:** a surname that is also an ordinary word (`Fekete`, `Magyar`, `Szabó`,
  `Pécsi`) needs person evidence (a given name, `és Társa`/`és Fia`, a sole-trader form or a
  bare `Bt.`), so `Fekete Kavics Kft.` stays intact and `Fekete Kft.` is accepted as a possible
  miss.

### 20. Every detector sees normalised text (2026-10-27)

LAB-1146.

The prompt-injection red team (LAB-1107) showed that only the LLM detector cleaned invisible
characters and lookalike letters. A zero-width space inside a phone number hid it from the
rules, and a zero-width joiner inside an e-mail address made the rules match only the part
after it; that validated rule span then kept its boundaries over the LLM's whole-address span,
so the local part leaked. The pipeline now normalises once, before any detector runs, and maps
every span back to the original text, invisible characters included.

- **Before → after**, `pii-guard eval injection`, `zero-width` class (14 values): rules alone
  **9 leaked / 5 partial → 6 / 3**, e-mail and phone exact recall 0 → 100 %; the rest are
  names, addresses and a birth date only a language model finds. Rules + Muse Spark Open
  (Baseten, `reasoning_effort: low`) **3 partial → 0**, so all 175 injection values are now
  masked whole (partial leak 1.7 % → 0.0 %). Source: run records
  `2026-10-27-injection-{rules,spark-open}-{before,after}-normalise` in
  [benchmarks.md](benchmarks.md), *(ticket comment, LAB-1146)*.
- **No regression:** `hu-smoke` and `en-smoke` scorecards with the rules are identical before
  and after; on the default fixture set only the injection documents changed, all for the
  better.
- **Cost:** two Baseten runs, about $0.30.

### 21. One-command demo, live traffic log and the gateway's measured overhead (2026-10-27)

LAB-1166.

Trying the gateway took five manual steps and a key, and nobody could see what it did to a
call or what it cost in latency. `make demo` now starts the API, the gateway and the UI on a
local mock upstream (offline, free), `make demo-traffic` sends fictional hu / en / de
requests through it (streaming, tool calls, known values, an image that is refused fail
closed), and `make smoke` checks in CI that every answer comes back restored exactly and that
no gold value reached the upstream. Every call becomes one in-memory traffic event
(`GET /v1/traffic`, live over SSE) with what was masked, what went upstream and a per-stage
timing breakdown; `full` mode with the originals is refused off localhost
([operations.md](operations.md)).

- **Measured overhead** (`pii-guard bench latency`, mock upstream with a fixed 50 ms delay, a
  new session per request, Apple M1 Max; p50 / p95 of total minus upstream wait):

  | Mode | c=1 | c=1, streamed (added time to first token) | c=8 |
  |---|---:|---:|---:|
  | fast, rules | **5.2 / 7.8 ms** | 6.5 / 8.1 ms (5.3 / 6.6 ms) | 11 / 26 ms |
  | fast, rules + distilled NER (XLM-R large, MPS) | **36 / 45 ms** | 39 / 47 ms (37 / 46 ms) | 166 / 182 ms |
  | strict, rules + Muse Spark Open on Baseten | **1.23 / 1.79 s** | 1.32 / 1.58 s (1.32 / 1.58 s) | 1.90 / 2.44 s |

  Source: run records `2026-10-27-gateway-latency-{rules-fast,ner-fast,baseten-strict}` in
  [benchmarks.md](benchmarks.md#gateway-latency) (200 requests per fast cell, 10 per strict
  cell).
- **What the breakdown showed:** in rules-only fast mode detection and masking take about
  0.7 ms; **4.4 of the 5.2 ms** are the `forward` stage, a new HTTP client (and TLS context)
  built for every upstream call. Under concurrency the NER is serialised behind one lock (p50
  36 → 166 ms at c=8), and strict mode queues behind the gateway's detection limit
  (`PII_GUARD_GATEWAY_CONCURRENCY`, 4). Each is now a follow-up with a number to beat.
- **Cost:** 44 Muse Spark Open calls on Baseten for the strict cells, about $0.10; everything
  else ran locally.

### 22. Values next to field captions on ID cards (2026-10-27)

LAB-1125.

On a card a value sits under a small caption (`Családi név / Surname` above `FIKTÍV`), and a
text detector sees the value alone: a surname on its own line, a foreign date, a document
number with no checksum. Even the LLM detector left the surname of the fictional Hungarian
card unmasked. Owner decision: keep the text detectors and also mask the value next to every
known caption, per language pack, but no blanket rule that masks whatever is printed on a card.

Two changes, measured separately below. `visual/captions.py` reads the captions from each
language pack's `captions.tsv` (Hungarian, English, German, plus French, Italian, Spanish,
Polish and Dutch until they have packs, and the EU driving-licence field numbers `1.`–`5.`),
matches them despite small-print OCR errors (`Date of bith`, `Sumame`) and masks the value on
the caption's right or under it in its column, up to the next caption. Captions of values
that aren't personal data (`Sex`, `Nationality`, `Expiry`) bound the columns but stay visible.
And Tesseract now reads small images enlarged to 2000 px: card captions are 6–10 px high,
below what it reads, so before this it returned no caption to pair with.

| Text recall @ IoU ≥ 0.5 | Text labels | Rules, before | after | Rules + Muse Spark Open, before | after |
|---|---:|---:|---:|---:|---:|
| Fictional set (milestone 17) | 110 | 34.5 % | **87.3 %** | 89.1 % | **99.1 %** |
| Official specimens (LAB-1120) | 274 | 1.5 % | **15.0 %** | 27.7 % | **29.2 %** |

- **Over-masking** (mean share of the image covered outside every label): fictional
  0.8 → 1.2 % (rules) and 0.9 → 1.2 % (LLM); specimens 2.6 → 4.0 % and 3.1 → 4.8 %, inside
  the 3-point budget the ticket set.
- **Fully covered** (coverage ≥ 90 %) specimen text values with the LLM: 9.8 → 20.1 %: the
  LLM already found many values, but only partly (one line of two, a box missing its edges).
- **The ≥ 50 % target** is met on the fictional set and missed on the specimens. On 108 of
  the 274 specimen values Tesseract returns no word at all (guilloche backgrounds, holograms,
  2-4 px strokes on 500 px scans), so no text method can reach them *(ticket comment, LAB-1125)*; a better reader for
  security-printed cards is the next step, not more captions.
- **Cost:** 96 + 260 SAM calls, about **$0.89**, fetched once and served from the cache
  for every other run; Baseten tokens for four LLM runs not metered. Before = the same code with
  `--no-captions --ocr-upscale 0`. Source: run records `2026-10-27-visual-{fictional,specimens}-rules{,-llm}{,-captions}`
  in [benchmarks.md](benchmarks.md) and the reports in `eval/results/visual/*-captions*.md`.

### 23. Fresh comparison: fast and strict vs Presidio, LLM Guard, PrivAiTe, on a public set too (2026-10-27)

PR [#45](https://github.com/watt-mind/pii-guard/pull/45), LAB-1148.

Today's two modes against the three open-source tools of milestone 6, on our hand-written
and Muse-generated sets (now including German) and on a public benchmark nobody here wrote: a
seeded 600-document sample (200 each in Hungarian, English and German) of Ai4Privacy's
OpenPII 1M, CC-BY-4.0. Leak rate, pooled over languages (smoke: 51 documents):

| System | Smoke leak | Ai4Privacy leak | Ai4Privacy F1 | p50 | $ / 1k msgs |
|---|---:|---:|---:|---:|---:|
| pii-guard rules | 41.6 % | 73.5 % | 41.0 | 0.2–0.4 ms | |
| **pii-guard fast** (rules + distilled NER, large) | **0.6 %** | 38.0 % | 70.0 | 24–31 ms | |
| **pii-guard strict** (+ Muse Spark Open, Baseten, `low`) | **0.6 %** | **3.9 %** | **88.4** | 1.8–2.3 s | 2.03–2.95 |
| Presidio | 24.3 % | 29.6 % | 38.9 | 8–136 ms | |
| LLM Guard | 45.1 % | 43.8 % | 64.0 | 61–133 ms | |
| PrivAiTe | 12.7 % | 9.5 % | 58.3 | 93–182 ms | |

Sources: [2026-10-27-comparison](../eval/results/2026-10-27-comparison/README.md) (per-fixture table and run conditions),
[benchmarks.md](benchmarks.md) (pooled rows, generated from the run records).

- **The fast-mode claim holds:** `hu-smoke` 0.9 % leak, F1 97.9, now from a committed
  scorecard (it was only stated in models.md before).
- **Fast mode is not enough on unfamiliar text.** On the public set it leaks 35–40 %, more
  than PrivAiTe (6.5–14.0 %) and Presidio. Most of the gap is numbers: about 90 % of the
  set's card, tax and TAJ numbers fail their checksums, and pii-guard's rules require valid
  ones on purpose. Strict mode, which adds the LLM pass, is the safest system on every set
  (3.5–4.8 % on the public set). Follow-up: LAB-1170.
- **On our own sets strict buys nothing over fast:** the same leak, F1 within a point, at
  about 70× the latency plus the API bill. Fast mode is the better default where its recall
  is enough.
- **Caveats:** the public text is machine-generated and often unnatural in Hungarian;
  dates, ages, gender, titles and bare towns are policy-excluded, which raises everyone's
  over-masking; LLM Guard's model was fine-tuned on an earlier Ai4Privacy release, so its
  public numbers are probably optimistic. The machine was under unrelated load (load
  average 13–27 on 10 cores), so latency is relative
  ([evaluation.md](evaluation.md#public-benchmark-ai4privacy-openpii-1m)).
- **Cost:** ≤ $4.50 on Baseten for every strict run of the ticket, $1.87 of it for the
  committed runs (the rest: runs superseded when LAB-1129 and LAB-1149 merged, and one run
  that aborted when one German document's completion was truncated twice, so the pipeline
  failed closed). 0 refusals, 0 invalid outputs, 0 blocked documents in the 682 committed
  requests. Ran on develop with LAB-1149 (company names) included.

## How pii-guard uses Meta's models

One rule decides where each model runs: **anything that sees real personal data is an
open-weights model you can host yourself; hosted models only ever see fictional or masked
data** ([models.md](models.md)).

| Meta model | Where it runs here | Job | Why this model |
|---|---|---|---|
| **Muse Spark Open** | Baseten Model APIs; or your own GPUs | Production LLM detector (strict mode) | Open weights, so the same detector can move inside your boundary; 1.2–1.8 s p50 at Muse Spark quality (milestone 15) |
| **Muse Spark 1.3** | Meta Model API | Development detector; the downstream model in the demo, which only sees placeholders | Strong Hungarian, including inflected names and stem changes ([models.md](models.md#llm-detector)) |
| **Muse Spark 1.3 contributor tier** | Meta Model API | Writes the synthetic benchmark and the distillation corpus | Cheap ($0.10 / $0.20 per million tokens); acceptable only because every value is fictional |
| **Muse Glimmer 30B** | vLLM on one H100, Modal | Teacher for the distilled NER model | Best zero-shot quality we measured (F1 99.3, leak 0.0 %), open weights, Apache-2.0; too slow for the request path, so we distilled it |
| **SAM 3.1** | Meta Model API | Faces, ID photos, signatures in images | Finds regions from a text prompt; 90.8 % portrait recall on specimen IDs (milestone 8) |

The pattern we would reuse: use the big model where its cost doesn't matter (writing fictional
data, labelling it, judging), and ship a small, fast, self-hostable model distilled from it.

## Process numbers

- **Time:** the 24 pull requests above merged between 2026-10-26 20:36 and 2026-10-27 08:01
  UTC; [roadmap.md](roadmap.md) had planned this work over the first eight hackathon days.
- **Tests:** 185 at the rules PR, 1,339 passing at the Baseten PR, CI on every pull request
  *(ticket comments, LAB-1081 and LAB-1108)*.

## What's next

- **Charts and run history** (LAB-1129): every eval run recorded in one schema, with charts
  for this page, the README and the demo UI.
- **Add a language** (LAB-1130): language packs as one plugin unit with a conformance suite,
  so a third language is a checklist.
- **Prompt-injection red team** (LAB-1107): text that tries to talk the LLM detector out of
  reporting values.
- **Images:** a reader that copes with security-printed cards, since OCR misses 39 % of the
  specimen values outright (milestone 22); MRZ zones and captioned values are masked since
  milestones 18 and 22.
- **English names** still missed on Muse-generated English (2.5–5.0 % leak across runs,
  LAB-1138).
- **Publish the distilled weights**, so fast mode works without training a model first.
- **Confirm Baseten's data terms** (LAB-1139) before recommending the hosted endpoint for
  real data.
