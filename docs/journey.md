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
(Ai4Privacy OpenPII, 600 documents, milestone 24) strict mode leaks 3.9 %. Fast mode leaked
38.0 % there, and 27.6 % after the cue-word and detection fixes (milestones 28–31). With NER v2 (milestone 37),
fast mode leaks 0.4 %, a result measured in-distribution. A v2 model that never saw an
Ai4Privacy row leaks 12.5 %.

| Language | Mode | Best configuration | Leak | F1 (overlap) | p50 latency | $ / 1k msgs | Source |
|---|---|---|---:|---:|---:|---:|---|
| Hungarian | strict | rules + Muse Spark Open (Baseten, `low`) | **0.9 %** | 98.4 | 1.8 s | 2.42 | [2026-10-27-baseten](../eval/results/2026-10-27-baseten/README.md), `hu-smoke` (31 docs) |
| English | strict | rules + Muse Spark Open (Baseten, `low`) | **0.0 %** | 97.1 | 1.2 s | 1.99 | same, `en-smoke` (10 docs) |
| Hungarian | fast | rules + NER v2 base + hard negatives (milestone 37) | **0.0 %** | 93.3 | 18 ms (MPS), 44 ms (CPU) | no API call | [2026-10-27-ner-v2](../eval/results/2026-10-27-ner-v2/README.md), `hu-smoke` (31 docs) |
| English | fast | same | **0.0 %** | 94.2 | 14 ms (MPS) | no API call | same, `en-smoke` (10 docs) |
| either | none | rules only (baseline) | 52.6 % / 46.7 % | 62.1 / 64.0 | < 1 ms | no API call | [distilled/rules/](../eval/results/ner/distilled/rules/) `hu-smoke.md`, `en-smoke.md` |

The fast-mode MPS figures are per document, taken from the scorecards. The CPU figure is for
NER only, from `training/ner/bench_latency.py`. Both were measured on an M1 Max under unrelated
load. The previous fast default, the distilled large NER of milestone 14, leaked 0.9 % / 0.0 %
on these sets, at a CPU p95 of 147 ms. The v2 weights are not published yet: you train them
yourself (see [models.md](models.md#ner-v2-wider-labels-openpii-train-split-hard-negatives)).

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
| 10-27 | [#80](https://github.com/watt-mind/pii-guard/pull/80) | fast: rules + NER v2 base + hard negatives (new default) | 0.0 % | 0.0 % | [2026-10-27-ner-v2](../eval/results/2026-10-27-ner-v2/README.md) |

The same history as charts, generated from the run records in
[`eval/results/runs/`](../eval/results/runs/) by `pii-guard eval report` (all runs, tables and
the run log: [benchmarks.md](benchmarks.md)). The table above is their text version.

![Leak rate over time on the hand-written smoke sets, per pii-guard configuration](benchmarks/progress.svg)

![Leak rate vs detection latency on the smoke sets, pii-guard configurations and the open-source tools](benchmarks/leak-vs-latency.svg)

### Spend so far

About **$22** of compute for everything measured here.

| What | Where | Cost | Source |
|---|---|---:|---|
| Distillation corpus (5,004 billed calls) | Meta Model API, contributor tier | $1.05 | [models.md](models.md#distilled-from-muse-glimmer) |
| Glimmer teacher labels + student training | Modal (H100, A10G, L40S) | ~$3 (estimate) | [models.md](models.md#distilled-from-muse-glimmer) |
| Glimmer zero-shot evaluation (about 1 GPU hour) | Modal (H100) | ~$4 (estimate) | *(ticket comment, LAB-1109)* |
| Visual eval on specimen IDs (505 live SAM calls) | Meta Model API, SAM 3.1 | ~$1.26 | *(ticket comment, LAB-1120)* |
| Production detector: four eval runs + tests | Baseten Model APIs | ~$0.84 of the $100 credit | [2026-10-27-baseten](../eval/results/2026-10-27-baseten/README.md#spend) |
| Re-identification red team (four runs + pilots) | Baseten Model APIs; Meta Model API | ~$1.9 Baseten; 343k Meta API tokens (price not published to us) | [2026-10-27-redteam](../eval/results/2026-10-27-redteam/README.md#spend) |
| Fresh comparison: strict mode on 8 fixture sets incl. 600 public documents | Baseten Model APIs | ≤ $4.50 | [2026-10-27-comparison](../eval/results/2026-10-27-comparison/README.md#spend) |
| NER v2: Glimmer corpus + labels, 9 trainings, T4 latency bench | Modal (H100, A10G, L40S, T4) | $4.85 (metered) | [2026-10-27-ner-v2](../eval/results/2026-10-27-ner-v2/README.md#spend) |

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

### 23. The demo UI, polished by critique rounds (2026-10-27)

LAB-1151 (with LAB-1135, LAB-1132, LAB-1154, LAB-1155, LAB-1159).

The demo became four steps: Mask (with a language choice and pre-loaded known values), Chat
through the real gateway (a new opt-in `X-PII-Guard-Echo: masked` header returns what the
model saw and said, masked), Images and Benchmarks (a one-sentence headline). Five rounds of an
end-user critic at 375 and 1280 px, light and dark, found 10 major issues, all fixed in the
UI; backend findings were filed as tickets. Screenshots: [docs/assets/demo](assets/demo/).

### 24. Fresh comparison: fast and strict vs Presidio, LLM Guard, PrivAiTe, on a public set too (2026-10-27)

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

### 25. Watching every call cross the guard, live (2026-10-27)

LAB-1167.

The traffic log from milestone 21 had no screen. The demo UI now has a fifth tab, **Live
traffic**, fed by `GET /v1/traffic/stream` (SSE, with polling of `/v1/traffic` as fallback):
every call through the gateway as it happens, with what was masked, the request exactly as
the model received it (tools and other fields included), the answer from the model and as
restored for the app, and a waterfall of the event's own per-stage timing. Live charts show
the overhead per call with rolling p50/p95, by mode, by stage and the values masked per
minute. Originals appear only when the server runs `full` *and* the page is on localhost;
offline, the tab replays calls recorded at level `masked`. "Send demo traffic" runs the
`make demo-traffic` scenarios from the browser against the offline mock upstream.

- **What it shows on the demo stack** (`make demo`, rules only, mock upstream, Apple M1 Max,
  64 calls): pii-guard overhead p50 **6.0 ms**, p95 14.7 ms; most of it is the `forward`
  stage (a new HTTP client per upstream call, 4.1 of 5.4 ms on a typical call), as milestone
  21 measured. Screenshots: [docs/assets/demo](assets/demo/) (`6-traffic`, `7-traffic-charts`,
  `8-traffic-mobile`).
- **What the critic caught:** two rounds at 375 and 1280 px, light and dark (verdict SHIP).
  The major one: with rules only, the names in the demo traffic go to the model as written,
  and the tab didn't say so; each masked request now says which detectors ran and that rules
  don't find names. The demo traffic itself is a follow-up (LAB-1190), as are a masked-image
  thumbnail in the log (LAB-1188), streamed tool-call arguments in the log (LAB-1189) and the
  card number typed as an IBAN (LAB-1187).

### 26. Image masking against Presidio Image Redactor and Eka (2026-10-27)

LAB-1164.

The text comparison (milestones 6 and 24) had no image counterpart. Now the visual eval scores
open-source image redactors with the same scorer: Presidio Image Redactor (Tesseract +
Presidio analyzer, spaCy en/de/hu) and Eka PII Redaction (LayoutLMv3 text PII + YOLO faces and
signatures, CPU). Each ran with its defaults and once more with pii-guard's own OCR input.
Recall@IoU ≥ 0.5 over every labelled region, best configuration of each tool:

| Set | pii-guard rules | pii-guard rules + LLM | Eka | Presidio | Over-masking (pii-guard LLM / Eka / Presidio) |
|---|---:|---:|---:|---:|---:|
| Fictional set (24 images, 149 regions) | 90.6 % | **100.0 %** | 91.3 % | 38.3 % | 1.2 / 3.2 / 1.1 % |
| Official specimens (65 images, 406 regions) | 37.9 % | **48.5 %** | 36.0 % | 13.3 % | 4.7 / 12.0 / 3.4 % |

- **Where pii-guard leads:** on the specimens it masks portraits at 90.8 % (Eka 55–57 %),
  signatures at 83.8 % (46–49 %) and MRZ zones at 80.0 % (≤ 10 %). Presidio's redactor is
  text-only by design and masks none of these.
- **Where it doesn't:** Eka finds 32.5 % of the 274 specimen text values, against pii-guard's
  30.3 % with the LLM and 15.0 % with rules alone, but at 2.5× the over-masking. This is the
  same OCR-bound gap milestone 22 named. A layout-aware reader is the lead to follow, not more
  rules.
- **Speed:** the baselines take 0.3–1.6 s per image on the CPU. pii-guard takes 6–10 s, most
  of it four sequential SAM 3.1 API calls.
- **Caveats:** Eka is trained on Indian documents, and Presidio has no Hungarian recognizers
  beyond the language-independent ones. Word boxes were merged per entity and line for every
  tool. LeakageBench was skipped because its data sits behind a research Data Use Agreement.
- **Cost:** about $0.89 of SAM calls (the response cache was empty on this machine) and about
  $0.3–0.5 of Baseten tokens (not metered). Source:
  [2026-10-27-image-baselines](../eval/results/2026-10-27-image-baselines/README.md) and the
  run records `2026-10-27-image-baselines-*` in [benchmarks.md](benchmarks.md).

### 27. Images that say whose data they hid (2026-10-27)

LAB-1156.

A black box hides a value and says nothing: shown a contract and two masked ID cards, the
model couldn't tell whose cards they were. Now each covered region shows the vault
placeholder of what it hides (`[[PERSON_a1b2c3]]`, `PHOTO · [[PERSON_a1b2c3]]`), each image
comes with a masked transcript and a document summary (type, holder, `expired`, MRZ
validity), and images are masked in the same vault session as the text. A card's
`FIKTIV<<MARIA` or `FIKTÍV` / `MÁRIA` is matched to the contract's `Fiktív Mária` by a fuzzy
matcher that ignores case, accents, token order and OCR confusions (`0`/`o`, `1`/`l`) but
keeps one real letter of difference apart (`Mustermann` ≠ `Mustermonn`). Close but
unaccepted matches get a new placeholder and are flagged, never guessed. Session values
printed where no detector found them (a visitor badge's name) are covered too.

Placeholder matching on the 24 fictional documents of milestone 17: 51 printed values, each
seeded first in a contract-style text, next to 39 near-namesake sets (`Fiktív Márta`, a
document number one character off). OCR words recorded from Tesseract, SAM off:

| | Exact matching (before) | **Fuzzy matching (after)** |
|---|---:|---:|
| Values carrying the text's placeholder, clean OCR | 36 / 51 = 70.6 % | **50 / 51 = 98.0 %** |
| Same, simulated OCR noise (5 % per character) | 27 / 51 = 52.9 % | **49 / 51 = 96.1 %** |
| False merges with a near-namesake | 0 | **0** (clean and noisy) |
| People with one placeholder in text and image | 15 / 24 | **24 / 24** |
| Values spelled out in a transcript or summary | 0 | **0** |

- **The demo question** "which parties have an ID?" (one card valid, one expired, one party
  without a card), answered by Muse Spark Open on Baseten: **3 / 3 parties right** with
  labelled images, **1 / 3** with opaque boxes (the model called every party "missing";
  only the party with no card was). The mocked upstream gives the same 3 / 3 vs 1 / 3, and
  that run is the end-to-end test in CI. No party name or document number was forwarded raw.
- **Coverage doesn't depend on the mode:** text and MRZ region recall 87.9 % @ IoU ≥ 0.5 in
  both, 88.7 % of labelled pixels overwritten in both; a narrow box grows to the right, into
  free space only, so its label stays legible.
- **Uncertain matches:** 2 on clean OCR, 4 with noise, each a new placeholder and listed in
  the summary's `fields_uncertain`. The one clean miss is a document number only readable
  from a garbled MRZ.
- **Latency:** 65 ms p50 per image for matching, labelling and rendering (recorded OCR words).
- **Cost:** two live Baseten calls for the committed demo runs, about **$0.014** (≈ $0.03
  with the two exploratory calls); no SAM or GPU. Source: run records
  `2026-10-27-visual-placeholders-{exact,fuzzy}-{clean,noisy}` and
  `2026-10-27-demo-which-parties-{labels,opaque}-{live,mock}` in [benchmarks.md](benchmarks.md);
  the guide is [examples/README.md](../examples/README.md).

### 28. Numbers after a cue word are masked even when their checksum fails (2026-10-27)

PR [#51](https://github.com/watt-mind/pii-guard/pull/51), LAB-1170.

Milestone 24 showed fast mode leaking 35–40 % on the public Ai4Privacy sample, mostly numbers:
about 90 % of its card, tax and TAJ numbers fail their checksums and its phone numbers use
plans that don't exist, while the rules validate both on purpose so that order numbers and
amounts stay visible. Decision (owner's autonomy rule): keep validation, and add one rule
that trusts the text when it says what a number is. Each language pack now ships a
`cues.tsv` (`TAJ`, `adóazonosító`, `kártyaszám`, `passport`, `Steuer-ID`, `IBAN`, `telefon` ...)
and a run of the cued type's shape right after a cue is masked at score 0.6, below every
validated hit. `-` cues (`rendelésszám`, `invoice no.`, `Bestellnummer`, `and`) end the
window, and a new negative set (`eval/fixtures/negative/`, 32 documents of order and invoice
numbers, amounts, dates, postcodes and references without a cue) must stay unmasked.

| Leak / over-masking, % (pooled) | Rules, before | after | Fast, before | after |
|---|---:|---:|---:|---:|
| Smoke (hu/en/de, 51 docs) | 41.6 / 0.0 | 41.6 / 0.0 | 0.6 / 0.6 | 0.6 / 0.6 |
| Synth sample (hu/en, 30 docs) | 43.1 / 0.0 | 43.1 / 0.0 | 0.0 / 1.1 | 0.0 / 1.1 |
| `hu-company-names` (44 docs) | 2.5 / 0.0 | 2.5 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| **Ai4Privacy** (hu/en/de, 600 docs) | 73.5 / 0.2 | **63.7 / 0.1** | 38.0 / 14.1 | **28.2 / 12.6** |

Fast mode on Ai4Privacy per language: `hu` 40.4 → 33.8 %, `en` 34.8 → 26.0 %, `de`
39.2 → 24.4 %; F1 70.0 → 76.8. Per-type leak (same in both modes: the NER has no number types):

| Ai4Privacy, leak % | `hu` | `en` | `de` |
|---|---:|---:|---:|
| `PHONE` | 73.9 → 45.5 | 41.2 → 15.3 | 45.3 → 20.3 |
| `NATIONAL_ID_HU_TAX` | 97.6 → 75.6 | - | - |
| `NATIONAL_ID_HU_TAJ` | 90.5 → 78.6 | - | - |
| `BANK_ACCOUNT` | 93.1 → 86.2 | 97.6 → 78.0 | 88.4 → 51.2 |
| `ID_DOCUMENT` | 51.0 → 44.2 | 83.4 → 61.5 | 94.9 → 55.8 |

- **No new over-masking:** every smoke, synth and company-names scorecard is identical, and
  on the public set every new span lands on a labelled value of the same type (over-masking
  falls because the masked total grows). The 1-point budget the ticket set was not touched,
  so `PII_GUARD_RULES_CUED_NUMBERS` defaults **on**.
- **What is left is mostly uncued.** Most remaining misses stand in running text with
  nothing naming them ("a 6232737036963178 és a 338 542 225"); masking those would mean
  masking every long number, which is the order-number trade-off the rules exist to avoid.
  Strict mode (the LLM pass) remains the answer there (3.9 %).
- **Latency:** the cues compile into one trie-shaped pattern; rules-only p50 0.23 → 0.25 ms
  on smoke. A first version, a plain alternation of the 148 cues, made the rules about 10×
  slower (synth sample p50 1.4 → 14 ms); its after-runs showed it and were discarded.
- **Adding a language:** a pack lists cue words only; value shapes are shared per type, the
  conformance suite validates the file and the scaffold writes a template
  ([languages.md](languages.md#3-rules)).
- **Cost:** $0, local runs (NER on Apple MPS, machine under unrelated load). Source: run
  records `2026-10-27-cued-numbers-{before,after}-{smoke,synth-sample,company-names,ai4privacy}-{rules,fast}`
  in [benchmarks.md](benchmarks.md).

### 29. Unicode spaces, dashes, digits and accents no longer hide identifiers (2026-10-27)

LAB-1204.

A code review of `develop` found that milestone 20's normaliser handled invisible characters
and mixed-script lookalikes but nothing else, while the rules accept only ASCII spaces,
hyphens and digits. A no-break space (what Word and Office put inside numbers), a narrow
no-break or thin space, an en dash, a non-breaking hyphen or a minus sign inside a TAJ, phone,
card, IBAN, giro or Steuer-ID number hid it completely. So did a phone or IBAN wrapped over a
line break, Arabic-Indic digits and an identifier written only in Cyrillic or Greek lookalike
letters (`АВС-123`, `ΒΕ68 5390 ...`). Decomposed accents (NFD, as macOS and some keyboards
produce) cut e-mail addresses down to the part after the last accent, a combining mark inside
a phone number left its last digits unmasked, and an Arabic-Indic Versicherungsnummer made a
German checksum helper raise, so the rules detector failed and the request was refused.

The normaliser now folds every Unicode space, dash, digit and ideographic full stop one for
one, composes NFC with an end offset per character so a span still ends after the marks it
covers, drops marks left on ASCII letters and digits, reads a line break inside a wrapped
number as a space (not between the lines of a list or a column of numbers), and folds
lookalike-only words shaped like identifiers. The checksum helpers require ASCII digits
before any arithmetic.

- **Probes:** 36 inputs of the reviewers' three probe scripts that were missed or cut short
  are now found whole, over their exact original spans, and the Arabic-Indic SV number no
  longer fails the request (without a cue it stays unmasked, as its ASCII form does). The 8
  still missed are ASCII formats the rules don't accept (a lower-case IBAN, a dotted TAJ, a
  giro in groups of four, `[at]` ...), filed as LAB-1216.
- **Fuzz test:** every rules hit in the smoke and synth-sample fixtures (81 documents) is
  found again, at the same offsets, after the document is rewritten with each of five Unicode
  spaces, five dashes, four other digit sets, or NFD; the vault round trip stays exact.

| Leak / over-masking, % (pooled) | Rules, before | after | Fast, before | after |
|---|---:|---:|---:|---:|
| Smoke (hu/en/de, 51 docs) | 41.6 / 0.0 | 41.6 / 0.0 | 0.6 / 0.6 | 0.6 / 0.6 |
| Synth sample (hu/en, 30 docs) | 43.1 / 0.0 | 43.1 / 0.0 | 0.0 / 1.1 | 0.0 / 1.1 |
| **Ai4Privacy** (hu/en/de, 600 docs) | 63.7 / 0.1 | **63.1 / 0.1** | 28.2 / 12.6 | **27.6 / 12.5** |

- **No regression:** the smoke and synth scorecards are identical. On Ai4Privacy, whose text
  has narrow no-break spaces and non-breaking hyphens, 13 more values are masked whole in
  both modes (ID documents, bank accounts, phones and addresses); in fast mode one German
  person name went from partial to leaked and another from leaked to whole.
- **Latency:** the run records' latencies were taken on a machine shared with parallel agent
  runs and are not comparable. An interleaved A/B of the rules pipeline in one process (old vs
  new normaliser, best of 7 per document) gives p50 smoke 0.283 → 0.281 ms, synth sample
  1.904 → 2.030 ms (+6.6 %), Ai4Privacy 0.453 → 0.446 ms; ASCII text takes a fast path.
- **Cost:** $0, local runs (NER on Apple MPS). Source: run records
  `2026-10-27-unicode-normaliser-{before,after}-{smoke,synth-sample,ai4privacy}-{rules,fast}`
  in [benchmarks.md](benchmarks.md).

### 30. The benchmark report compares like with like (2026-10-27)

LAB-1213. **A change of scoring method, not a model improvement:** no detector ran again, and
every number below was recomputed from counts the run records already kept. A code review
found the report mixing documents and charging systems for text the set doesn't score:

- **Fixture versions.** The headline `smoke` table keyed results by set name only, so it
  pooled runs on the 28-document Hungarian file with runs on today's 31-document one, and
  runs with and without German (its Docs column read 51, 41 and 38). Results are now keyed
  by each fixture file's SHA-256: only runs on the current files are pooled or charted; rows
  missing a current language are marked † and left out of the pooled charts, which name
  them; runs on the old Hungarian file move to their own "earlier version" table. The
  featured Muse Glimmer point (old 28-document file) leaves the headline chart.
- **Policy-excluded labels on Ai4Privacy.** Dates, titles and bare towns are not gold spans
  there, but predictions on them were charged as false positives and over-masking: all 205
  of fast mode's `DATE_OF_BIRTH` predictions counted as over-masked. Fixtures can now carry
  ignore regions (a prediction on one is neither credited nor charged), the converter
  writes them, and until the committed sample is refreshed `DATE_OF_BIRTH` predictions are
  not scored on that set. Titles and bare towns still count against the stored runs: the
  runs kept no per-document predictions, so those regions can't be applied after the fact.
- **Smaller fixes.** Over-masking is defined as a share of spans (the page said
  characters); chart captions name the languages actually pooled (they said "hu + en" for
  de + en + hu) and that pooling is micro-averaged; tables show each row's commit;
  comparison tools' placeholder consistency is `null` (it was 0.0 by construction); record
  validation checks every rate against its counts; `ai4privacy fetch --check` compares the
  whole manifest and every fixture file and no longer writes them.

Headline numbers that changed (pooled, old → new; leak and recall are unchanged everywhere):

| Set | System | Precision | F1 | Over-masking | Macro F1 |
|---|---|---:|---:|---:|---:|
| Ai4Privacy | pii-guard fast (rules + distilled NER) | 83.5 → 92.8 % | 77.1 → 80.9 | 12.5 → 2.4 % | 53.5 → 59.5 |
| Ai4Privacy | pii-guard strict (+ Muse Spark Open) | 83.5 → 92.5 % | 88.4 → 93.2 | 12.1 → 2.4 % | 58.2 → 63.0 |
| Ai4Privacy | Presidio | 32.1 → 38.6 % | 38.9 → 43.4 | 53.9 → 49.1 % | 30.3 → 33.7 |
| Ai4Privacy | PrivAiTe | 52.6 → 64.8 % | 58.3 → 65.1 | 26.6 → 9.6 % | 41.4 → 46.6 |

- Ai4Privacy rules-only and LLM Guard predict no `DATE_OF_BIRTH` there: unchanged.
- Placeholder consistency of Presidio, LLM Guard and PrivAiTe on every set: 0.0 % → n/a.
- `smoke` rows that were pooled over the old Hungarian file are now en-only and marked †
  (rules + Muse Glimmer low, Muse Glimmer low and medium, rules + Muse Spark 1.3, and the
  zero-shot, fine-tuned and distilled-base NER runs; Docs 38 → 10), with their Hungarian
  results listed under the earlier file. Rules + Muse Spark Open (Baseten) keeps its numbers
  but is marked † (no German, 41 documents). The six complete rows (rules, fast, strict and
  the three tools) are unchanged.
- **Fast mode looks better on Ai4Privacy only because the method changed:** its predictions
  are the same, they are no longer charged for dates the set refuses to label. Its leak on
  the set (27.6 %, latest run after milestone 29) is what it was.
- **Cost:** $0, no runs. Re-scoring: `python -m pii_guard.eval.rescore` (41 records, each
  marked `rescored`); details in [evaluation.md](evaluation.md#run-records) and
  [benchmarks.md](benchmarks.md).

### 31. Order numbers and amounts are no longer read as TAJ numbers (2026-10-27)

LAB-1205.

A code review of `develop` found four correctness gaps in the rules and the resolver. A TAJ
number is nine digits with a mod-10 check, so 1 in 10 random nine-digit numbers passes it, and
without its `TAJ` cue the rule fired on `Order number: 123456788`, `Rendelésszám: ...`,
`INV-123456788`, `Total: $123 456 788` and `123 456 788,- Ft`. In the resolver, a validated
rule span dropped every other detector's same-type span that overlapped it, so when the rule cut
a value short (`user@example.xn` out of `user@example.xn--p1ai`, a phone number without its
`/ 123` extension) the rest leaked; a span of another type already kept its rest. The IBAN
length table missed eleven countries of the SWIFT registry (Russia, Oman, Nicaragua, Mongolia,
Yemen ...), and the e-mail rule stopped at a punycode TLD and missed a quoted local part
(`"john doe"@example.com`).

A context-free TAJ right after an order, invoice or reference label, an ID prefix (`INV-`,
`#`) or a currency is now dropped, and `,- Ft` reads as an amount for every number rule. The
resolver keeps the rest of a same-type span when it can be the rest of the value (it holds a
digit, or continues the validated span without a space); a label word the other detector took
along (`(mobil)`, `E-mail:`) and an inflectional suffix (`-ra`) stay unmasked. The IBAN table
follows the registry, and the e-mail rule accepts `xn--` TLDs and quoted local parts.

- **Probes:** every input of the reviewers' four probe scripts in the ticket's scope now comes
  out right: the 7 TAJ over-masking cases, the same-type e-mail and phone remainders, 6 of the
  7 IBAN countries (the probe's Sudanese IBAN has 16 characters; the registry says 18, and an
  18-character one is found) and both e-mail forms.
- **Negative set:** 6 new hand-written documents of order numbers and amounts that pass the TAJ
  check (en, hu, de). The rules masked 11 values in them as TAJ before and mask none now; the
  38 documents of the set come out clean.
- **No regression:** the smoke and Ai4Privacy scorecards are identical before and after, in
  rules and fast mode (rules: smoke 41.6 % leak / 0.0 % over-masking, Ai4Privacy 63.1 / 0.1;
  fast: smoke 0.6 / 0.6, Ai4Privacy 27.6 / 2.4). Neither set has an over-masked order number or
  a value a rule cuts short, so the change shows only on the negative set and the probes.
- **Cost:** $0, local runs (NER on Apple MPS). Source: run records
  `2026-10-27-rules-resolve-{before,after}-{smoke,ai4privacy}-{rules,fast}` in
  [benchmarks.md](benchmarks.md).

### 32. Valid vs invalid numbers on the public set, headline unchanged (2026-10-27)

PR [#66](https://github.com/watt-mind/pii-guard/pull/66), LAB-1201. **No headline number changes:** this splits the published Ai4Privacy
leak rate by whether a structured identifier passes the language packs' own validators
(Luhn, IBAN, TAJ and tax-ID check digits, phone numbering plans, ID-document checksums).
Owner decision: invalid numbers stay in the headline, because a mistyped real identifier is
still personal data; the split only shows where the gap comes from. Of the set's 909 numbers,
166 are valid.

| Ai4Privacy (de + en + hu, 600 docs) | Leak | Valid numbers leaked | Invalid numbers leaked | Other values leaked |
|---|---:|---:|---:|---:|
| pii-guard fast | 27.6 % | 0 of 166 | 63.4 % | 10.4 % |
| pii-guard strict | 3.9 % | 0 of 166 | 6.5 % | 2.8 % |
| PrivAiTe | 9.5 % | 7 of 166 | 3.0 % | 14.0 % |

- **Fast mode masks every valid number and leaks 10.4 % of names, addresses and e-mail**
  (PrivAiTe 14.0 %). Its gap on this set is invalid numbers, which the rules skip on purpose.
- The runs kept no per-document predictions, so each system was run again to classify them,
  with the run's own code. Every local re-run reproduced its record exactly. Strict mode
  came out at 3.8 % vs 3.9 %, and its row is marked.
- **Cost:** $1.65 Baseten for the strict re-run (budget $2); the rest ran locally. Breakdown
  in [benchmarks.md](benchmarks.md#ai4privacy) (`validity-ai4privacy.svg`) and
  [evaluation.md](evaluation.md#number-validity).

### 33. Faces on the device, signatures still need SAM (2026-10-27)

LAB-1229. A spike: can faces, ID photos and signatures be found on the device instead of with
SAM 3.1 on the Meta API (four calls and 5-6 s per image, and the image leaves the machine)?
**Faces and ID photos yes, signatures no**, so SAM 3.1 stays the default and nothing in the API
or the gateway changes.

| Specimens (65 official ID documents) | Portrait recall | Portrait leak | Signature recall | p50 / image | Weights |
|---|---:|---:|---:|---:|---:|
| SAM 3.1, Meta API (default) | 90.8 % | 47.7 % | 83.8 % | 5.5 s | hosted |
| YuNet on the CPU (`LocalSegmenter`) | 92.3 % | 10.8 % | — | 116 ms | 0.23 MB |
| YuNet + YOLOS-tiny signatures | 93.8 % | 6.2 % | 51.3 % | 727 ms | 26 MB |

- **YuNet** (OpenCV model zoo, MIT) passes the face half of the "close enough" rule on both
  sets: as much recall as SAM, a lower leak (a region under 95 % covered; 0.0 % on the
  fictional set for both), under 500 ms on a busy laptop CPU. It over-masks around the photo
  (61 % of its portrait boxes hit a labelled portrait, SAM's 90 %), which is the safe side.
- **No small signature detector comes close.** The permissively licensed ones on Hugging Face
  are trained on scanned pages and find 16-32 % of ID-card signatures (51 % on image tiles, at
  9 % precision); the YOLOv8 ones are AGPL. EfficientSAM as a photo refiner added nothing
  and costs 1.5-2.2 s. Local SAM 3 was not run: its weights are gated (no access) and 3.4 GB.
- **What shipped:** `LocalSegmenter` as a library component (`--extra local-vision`, model
  fetched with a pinned SHA-256; it raises if asked for signatures), the comparison as
  `python -m pii_guard.visual.segment_eval` with 8 run records, and a segmenter section and
  chart in [benchmarks.md](benchmarks.md#segmenters-sam-31-api-vs-on-device). Details and the
  rule-by-rule verdict: [models.md](models.md#local-segmentation).
- **Cost:** $0. 356 SAM 3.1 calls on free Meta API credits (≈ $0.89 at the planning
  estimate); every local candidate ran on the CPU.

### 34. Faces on the device by default, half the API calls per image (2026-10-27)

LAB-1245. LAB-1229 showed YuNet finds faces and ID photos as well as SAM 3.1 but no signatures.
The owner's call: make it the default for faces and keep SAM 3.1 for signatures only.
`PII_GUARD_SEGMENTER=hybrid` (new default) runs YuNet on the CPU alongside two SAM 3.1 calls
(`signature`, `squiggly line`); `sam-api` keeps the old behaviour, `local` and `off` never call
the API and refuse images they can't fully check.

| `POST /v1/mask/image` with OCR | SAM calls / image | p50 | p95 | Portrait leak | Signature recall |
|---|---:|---:|---:|---:|---:|
| 65 official specimens, `sam-api` (before) | 5 | 7.9 s | 11.6 s | 47.7 % | 83.8 % |
| 65 official specimens, **`hybrid`** (now) | **2** | **4.1 s** | **6.1 s** | **10.8 %** | 83.8 % |
| 24 fictional documents, `sam-api` | 5 | 7.2 s | 8.1 s | 0.0 % | 100.0 % |
| 24 fictional documents, **`hybrid`** | **2** | **3.8 s** | **5.0 s** | 0.0 % | 100.0 % |

- **The call count was 5, not 4.** The served pipeline also asked SAM for `stamp`, whose regions
  are `keep` (left visible). The hybrid mode only segments types whose policy is not `keep`.
- **Measured fairly on a busy laptop:** both modes alternating per image, live SAM, 3 rounds,
  medians. The image still leaves the machine for the signature prompts, so this is a latency
  and cost win, not a privacy one.
- **Fail closed:** without OpenCV or the model the hybrid mode warns and sends faces to SAM
  (still masked); with no API key either, images are refused. The Docker image now ships OpenCV
  headless and the pinned, checksum-verified YuNet file (+160 MB unpacked; the CI size budget
  went from 375 to 525 MB).
- **Acceptance met on both sets:** portrait leak at or below SAM's (a quarter of it on real
  specimens), signatures from the same SAM prompts and the same boxes, 2 calls instead of 5,
  the median image about 47 % faster.
- **The specimens went missing once:** they lived in a worktree's `data/` and were deleted with
  it. They were re-fetched (SHA-256 checked) into `PII_GUARD_SPECIMENS_DIR`, a new setting that
  keeps them, and the SAM cache (`PII_GUARD_VISUAL_CACHE`), outside every worktree.
- **Cost:** $0. About 2,250 SAM 3.1 calls on free Meta API credits.

### 35. A coding agent works through the gateway (2026-10-27)

LAB-1236. **pi, a terminal coding agent, now runs behind pii-guard:** `pii-guard connect pi`
adds a provider to its config, and the model sees placeholders while the files pi writes hold
the real values. A real pi 1.4.0 got the fictional mini-repo (`examples/coding-agents/`): a
client letter, a customer CSV and a `.env`. Its task was to write a reply that quotes the
client's contact details.

| Run (fast mode, rules + NER) | Requests | Refused | Gold values upstream | Real values in the file |
|---|---:|---:|---:|---:|
| Scripted mock model (also in CI) | 5 | 0 | 0 of 13 | 13 of 13 |
| Meta Model API, `muse-spark-1.3` | 3 | 0 | 0 of 13 | 5 (all the task asked for) |

- **Tool-call arguments come back restored**, so the agent's `write` lands the real IBAN,
  e-mail and phone on disk. pi's requests needed no new allow-list keys.
- **Code survives:** 0 of 23 masked spans in the mini-repo and repository code were
  identifiers, paths or URLs.
- **Gaps found:** secrets (all 3 fake keys from `.env` reached the model) and names inside CSV
  rows. The real model also left the data out of the file until the prompt said placeholders
  are restored locally. All three are follow-up tickets.
- **Muse Code isn't connectable yet.** It accepts a custom endpoint, but speaks the Responses
  API, which the gateway doesn't serve ([integrations/muse-code.md](integrations/muse-code.md)).
- New: `GET /v1/models` and [docs/integrations/](integrations/README.md).
- **Cost:** $0. About 20 requests over three runs on free Meta API credits; the rest ran locally.

### 36. Ticket numbers, SKUs and company names are not tax IDs, cards or postcodes (2026-10-27)

LAB-1227, the follow-up of milestone 31. LAB-1205 stopped a context-free TAJ from firing
right after an order or invoice label, an ID prefix or a currency, but other checksum rules
still did: a valid ten-digit number after `ticket` came out as a Hungarian tax ID (mod 11
and a leading 8), `SKU 4111111111111111` as a card (a Luhn check passes for 1 in 10 numbers)
and the `1999` of `1999 Budapest Kft.` as a postcode, although the settlement is part of a
company name.

The same guard now covers a context-free tax ID, a payment card without a card or account cue
nearby (`card`, `kártya`, `Visa`, `számlaszám` ...) and a Hungarian postcode after a reference
label; a postcode followed by its settlement and a legal form (`Kft.`, `Zrt.`, `Bt.`, `GmbH`,
`Ltd`, with up to two more words of the name in between) is not a postcode, and neither is a
German address line before `GmbH`. Only the context-free hit is dropped: a cued value
(`adóazonosító`, `irányítószám`, `H-1999`, a card cue in the window) always wins, and
a tax ID after a name and a comma, with no label, is still masked.

- **Probe:** the three cases of the reviewers' `probe3.py` now come out empty; the other 16
  inputs are unchanged.
- **Look-alikes:** 38 new regression texts of ticket, tracking, SKU and invoice numbers and
  company names (en, hu, de). The rules masked 36 of them before and none now; 34 more tests
  pin down that cued values and plain postcodes are still found, and test the legal-form
  matcher.
- **No regression:** the smoke, Ai4Privacy and negative-set scorecards are identical before
  and after, in rules and fast mode (local NER checkpoint): fast-mode leak 0.6 % on smoke and
  27.6 % on Ai4Privacy, 0 false positives on the 38 negative documents. Run records
  `2026-10-27-reference-cues-{before,after}-{smoke,ai4privacy,negative}-{rules,fast}`.
- **Not changed:** a valid 16-digit giro number (two mod-10 checks, 1 in 100) after a
  reference label is still masked, as is a company tax number after `Ügyszám`.
- **Cost:** $0; everything ran locally.

### 37. NER v2: fast mode stops leaking numbers (2026-10-27)

PR [#80](https://github.com/watt-mind/pii-guard/pull/80), LAB-1150. After milestones 28–31, fast mode still leaked 27.6 % on the public Ai4Privacy sample.
The cause was mostly the identifiers the rules can't validate, and the NER had no number types
at all.

NER v2 widens the label set from 4 to 10 types: it adds `EMAIL`, `PHONE`, `ID_DOCUMENT`,
`NATIONAL_ID_HU_TAX`, `NATIONAL_ID_HU_TAJ` and `BANK_ACCOUNT`. It trains on three sources:
- the two distillation corpora: s11, and s13, written from the lexicon packs and labelled by
  Muse Glimmer on Modal;
- 5,000 rows per language from the OpenPII **train** split. The build script asserts these are
  disjoint from the evaluated validation rows;
- seeded hard negatives: order, invoice and tracking numbers, and amounts.

The comparison covered XLM-R base and large, GLiNER multi (zero-shot and fine-tuned), and a
union of the two encoders.

| rules + NER, % | ai4privacy leak, pooled | smoke leak, max | smoke over-masking, max | CPU p95 (M1) |
|---|---:|---:|---:|---:|
| before: v1 large (LAB-1128) | 27.6 | 0.9 | 0.9 | 147 ms |
| v2 base, OpenPII without negatives | 0.4 | 1.9 | 9.3 | 52 ms |
| **after: v2 base + hard negatives** | **0.4** | **0.0** | 3.0 | **50 ms** |
| v2 large, no Ai4Privacy rows (held-out) | 12.5 | 0.0 | 0.9 | 149 ms |
| GLiNER multi v2.1, zero-shot | 22.5 | 5.4 | 10.0 | 126 ms |

- **Read 0.4 % as in-distribution.** Its training saw OpenPII rows. The honest number for
  unseen text of that style is the ablation's **12.5 %**, which is still under the ticket's
  15 % target.
- **OpenPII alone over-masked.** It taught the model that every number is personal, so
  smoke over-masking rose to 6–11 %, with order numbers masked at confidence above 0.99. A
  threshold sweep and a 1k-row cut didn't help. 2,000 template negatives per language did.
  Some of their cue words also appear in the smoke sets, which is disclosed in the results
  README. The remaining 3.0 % is one en-smoke span, a street name standing alone. OpenPII
  labels those as addresses and our policy doesn't (filed as LAB-1220). It means the ≤ 2 %
  criterion is missed by one span.
- **The default is base, not large.** The owner's rule is leak first, with CPU p95 ≤ ~150 ms.
  Base and large tie on leak. Large is borderline on the M1 CPU and over 290 ms p95 on a
  4-vCPU T4 container. Base takes 50 ms (M1) and 85 ms (T4 CPU); on CUDA it's 16 ms and on
  MPS 22 ms.
- **GLiNER is not adopted as the default.**
  - Zero-shot it leaks more and over-masks more.
  - Fine-tuned it matches the leak but over-masks 21 % on en-smoke.
  - It is 2–5× slower.
  - The union adds over-masking, not recall.
  - It ships as an opt-in `ner_gliner` detector (`PII_GUARD_NER_BACKEND=gliner`).
  - It is the best licence-clean **public fallback** for `make demo` (LAB-1192): Apache-2.0,
    22.5 % vs 28.7 % leak for the current Davlan zero-shot model.
- **The LLM** stays the teacher. No LLM call runs in fast mode.
- **Cost:** $4.85 of Modal (metered).
- **Weights:** none are published. The owner decides. Model card:
  [training/ner/model-card.md](../training/ner/model-card.md).
- **Source:** run records `2026-10-27-ner-v2-<fixture>-<candidate>` (13 candidates × 11
  fixtures) and [2026-10-27-ner-v2](../eval/results/2026-10-27-ner-v2/README.md).

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
