# Why pii-guard

What pii-guard does that we did not find elsewhere, and the evidence for each claim. Every
number links to a committed file on `develop`: a run record, a scorecard, a test or a decision
record. Where the only source is a write-up of a run whose scorecard is not committed, the
link goes to that write-up and says so. All data behind these numbers is fictional
([ADR 0005](decisions/0005-synthetic-data-only.md)).

**Status** means: **shipped** = merged to `develop`; **in review** = pull request open;
**in progress** / **planned** = tracked on the named ticket, not merged; **blocked** = tracked
on the named ticket, waiting on something outside the code.

As of 2026-10-28, `develop` at `5581013`. Fast mode below means the published NER `v2.0`
(`NER v2 base + hard negatives` in the reports). Leak figures are copied from the generated
[benchmarks.md](benchmarks.md): the hand-written set from [results by fixture
set](benchmarks.md#smoke), the public and agent-traffic test splits from [results per
dataset](benchmarks.md#results-per-dataset). When a number changes, update it here, in the
README's "Why pii-guard" section, in [submission.md](submission.md) and in
[journey.md](journey.md) together.

| # | Differentiator | Headline evidence | Status |
|---|---|---|---|
| 1 | [Reversible placeholders, consistent for a whole session](#1-reversible-placeholders-consistent-for-a-whole-session) | 100 % round trip on the hand-written set; placeholder consistency 96.5 % of entities, but only one entity there repeats (n = 1) | shipped |
| 2 | [Grammar-aware: Hungarian inflection in and out](#2-grammar-aware-hungarian-inflection-in-and-out) | inflected-name leak 18/30 → 0/30 | shipped |
| 3 | [Built on Meta's models end to end](#3-built-on-metas-models-end-to-end) | 6 Meta models, each with a job and a reason | shipped; Glimmer LoRA blocked |
| 4 | [Two modes with published leak, latency and cost](#4-two-modes-with-published-leak-latency-and-cost) | fast (production default): 0.0 % leak on the hand-written set at 18 ms, $0, nothing leaves the machine; audit (optional): 0.6 % at 1.9 s, about $2–3 per 1k messages | shipped |
| 5 | [Head-to-head with Presidio, LLM Guard and PrivAiTe](#5-head-to-head-with-presidio-llm-guard-and-privaite) | hand-written set: fast 0.0 % leak vs 12.7–45.1 %; ahead on Nemotron-PII and CEE-PII, level with the best other tool on finance text and agent traffic | shipped |
| 6 | [The LLM can only point, never write; red-teamed](#6-the-llm-can-only-point-never-write-red-teamed) | prompt-injection leak 3.4 % → 0.0 % (two runs), no partial leaks left | shipped |
| 7 | [Honest about re-identification](#7-honest-about-re-identification) | exposure 1.4 % from masked text; 39.9 % with a 5-name candidate list | shipped |
| 8 | [A drop-in gateway that fails closed](#8-a-drop-in-gateway-that-fails-closed) | masks tools, metadata and response schemas; rejects pasted placeholders | shipped |
| 9 | [Images: faces, signatures, machine-readable zones](#9-images-faces-signatures-machine-readable-zones) | portrait recall 90.8 % on official specimen IDs; MRZ 0 % → 76.7 %; masked regions carry the text session's placeholder | shipped |
| 10 | [Hungarian depth as a showcase for hard languages](#10-hungarian-depth-as-a-showcase-for-hard-languages) | names inside company names 61.1 % → 0 % leaked | shipped |
| 11 | [Add a language with a checklist](#11-add-a-language-with-a-checklist) | German pack: every structured identifier found, other languages unchanged | shipped |
| 12 | [Known values and per-type policies](#12-known-values-and-per-type-policies) | pre-loaded values: leak 93.3 % → 0 % | shipped |
| 13 | [Benchmarking in the open](#13-benchmarking-in-the-open) | every run a committed record, report checked in CI, spend itemised | shipped |

## 1. Reversible placeholders, consistent for a whole session

Most redaction tools replace a value with `[REDACTED]` or `<PERSON>`, so the model's answer
can't name the person you asked about. pii-guard swaps each value for a keyed placeholder
(`[[PERSON_525263]]`), the same one every time that value appears in the conversation, and
puts the real value back in the answer, also while it streams, also inside tool-call
arguments. Placeholders are HMAC-derived, so they are unlinkable across sessions and tenants,
and the mapping never leaves pii-guard's vault.

- **Evidence:** round trip 100 % (every document unmasks back to the original exactly) on the
  hand-written set, in fast mode ([benchmarks.md](benchmarks.md#smoke)). Placeholder
  consistency is 167 of 173 entities (96.5 %) over the Hungarian, English and German smoke
  documents in fast mode ([run record](../eval/results/runs/2026-10-28-lab-1355-smoke-fast.json)).
  The missing 6 are 3 values not masked at all and 3 names whose given name alone was masked
  (`Próba [[PERSON_x]]`). This page said 170 of 173 (98.3 %) until LAB-1355: the metric then
  counted a partly masked occurrence as masked, which overstated it
  ([comparison](../eval/results/2026-10-28-consistency-metric/README.md)). **n = 1:** only one
  entity in those documents is mentioned more than once, so these runs say little about
  repeated mentions. That claim rests on the Hungarian inflection fixtures (section 2:
  "same person, same placeholder" 18/18) and the vault tests
  ([tests/vault/test_vault_mask.py](../tests/vault/test_vault_mask.py)). Design:
  [ADR 0007](decisions/0007-keyed-pseudonyms.md). Streaming: placeholders split across chunks
  are held back until complete
  ([tests/vault/test_vault_stream.py](../tests/vault/test_vault_stream.py)).
- **Status:** shipped (LAB-1082, LAB-1100). Exact casing on restore is opt-in (LAB-1119).

## 2. Grammar-aware: Hungarian inflection in and out

In Hungarian a name changes with every case: `Próba Zsuzsanna`, `Próba Zsuzsannának`,
`Próba Zsuzsannával`. pii-guard keys every form on its lemma, so all of them get the same
placeholder, keeps the case ending outside it (`[[PERSON_x]]nak`) so the model still writes
grammatical sentences, and re-inflects the stem on unmask. Grammar lives in the language pack,
so every detector benefits.

- **Evidence:** on the inflection fixtures
  ([eval/fixtures/hu-inflection.jsonl](../eval/fixtures/hu-inflection.jsonl)), leaked values
  18/30 → **0/30** and "same person, same placeholder" 11/18 → **18/18**
  ([journey.md, milestone 10](journey.md#10-hungarian-inflection-in-the-vault-2026-10-26-2333);
  the scorecard is not committed, and it was scored with the overlap rule LAB-1355 replaced).
  In fast mode today, with every mention fully covered: leak 1/30, consistency **13/18**, 5 of
  the 10 people mentioned more than once
  ([run record](../eval/results/runs/2026-10-28-lab-1355-inflection-fast.json)). Of the 5
  misses, 3 are names whose surname the NER left unmasked in every form
  (`Próba [[PERSON_x]]nak`), 1 is a name not masked at all, and 1 is an all-caps mention
  (`PRÓBA [[PERSON_y]]`) that got a different placeholder from the inflected one. The behaviour is pinned by property tests
  ([tests/vault/test_vault_inflection_hu.py](../tests/vault/test_vault_inflection_hu.py)).
- **Status:** shipped (LAB-1115). Old-orthography names with `th` and `cz` (`Kiss Tóthtal`,
  `Gipsz Kováczcal`) and long vowels the model writes on its own are masked and restored too (LAB-1131,
  [tests/vault/test_vault_inflection_hu_orthography.py](../tests/vault/test_vault_inflection_hu_orthography.py)).

## 3. Built on Meta's models end to end

Each Meta model does the job it is best at, under one rule: **anything that sees real personal
data is an open-weights model you can run yourself; hosted models only see fictional or
masked data** ([models.md](models.md)).

| Role | Meta model | Why this model | Evidence | Status |
|---|---|---|---|---|
| Audit-mode detector (second opinion) | **Muse Spark Open** (open weights) on Baseten Model APIs, or your own GPUs | Open weights, so the detector can move inside your boundary; Muse Spark quality at 1.2–1.8 s p50 | [2026-10-27-baseten](../eval/results/2026-10-27-baseten/README.md) | shipped |
| Teacher for the fast-mode NER | **Muse Glimmer 30B** (open weights, Apache-2.0), vLLM on one H100 | Best zero-shot quality we measured (F1 99.3, leak 0.0 % on the 38 Hungarian and English smoke documents of that run), too slow for the request path (9.4 s p50), so we distilled it | [run record](../eval/results/runs/2026-10-27-glimmer-zero-shot-rules-llm-low.json), [models.md](models.md#distilled-from-muse-glimmer) | shipped |
| Fast-mode NER student | **XLM-RoBERTa** base (FacebookAI, MIT), fine-tuned on Glimmer's labels, public OpenPII train rows and hard negatives; published as [`hdkiller/pii-guard-ner-xlmr-base`](https://huggingface.co/hdkiller/pii-guard-ner-xlmr-base) `v2.0` | Multilingual encoder, in-process, 18 ms p50 per document on the hand-written set | [model card](../training/ner/model-card.md), [selection](../eval/results/2026-10-27-ner-v21/README.md), [benchmarks.md](benchmarks.md#smoke) | shipped (published, downloaded and hash-checked on first use) |
| Glimmer as a fine-tuned detector | **Muse Glimmer** LoRA on Fireworks | An answer-only detector that is fast enough for the request path | LAB-1109 | blocked |
| Synthetic benchmark and distillation corpus | **Muse Spark 1.3**, contributor tier | Writes realistic Hungarian and English documents around fictional identities; $1.05 for the 5,004-call distillation corpus | [models.md](models.md#distilled-from-muse-glimmer) | shipped |
| Red-team attacker | **Muse Spark Open**, and **Muse Spark 1.3** for comparison | Meta's own model tries to undo the masking | [2026-10-27-redteam](../eval/results/2026-10-27-redteam/README.md) | shipped |
| Fictional ID specimens | **Muse Image** | Portraits, signatures and stamps of people who don't exist, so image tests need no real ID | [eval/fixtures/visual/generation.json](../eval/fixtures/visual/generation.json) | shipped |
| Faces, ID photos, signatures in images | **SAM 3.1** (Meta Model API) | Finds regions from a text prompt | [eval/results/visual/specimens.md](../eval/results/visual/specimens.md) | shipped |
| Downstream model in the demo | **Muse Spark 1.3** | Only ever sees placeholders | [gateway usage](architecture-gateway.md#from-python) | shipped |

The pattern: use the big model where its cost doesn't matter (writing fictional data,
labelling it, attacking the guard) and ship a small, fast model distilled from it.

- **Status:** shipped (LAB-1086, LAB-1087, LAB-1089, LAB-1108, LAB-1121, LAB-1128, LAB-1306);
  the Glimmer LoRA fine-tune is blocked (LAB-1109) and is not part of the shipped path.

## 4. Two modes with published leak, latency and cost

**Fast** mode, the gateway default and the production path, runs rules plus the in-process
NER: local, no model call, $0, and nothing leaves the machine. **Audit** mode adds an LLM
detector to every message, as a second opinion for sampled or offline quality checks, label
generation and the benchmark upper bound; it is not meant for production traffic, because
the text goes to the detector endpoint and each message costs a remote call. Both are
published, including the cost per 1,000 messages.

| Mode | Set | Leak | F1 (overlap) | p50 latency | $ / 1k messages | Source |
|---|---|---:|---:|---:|---:|---|
| fast (rules + NER `v2.0`) | hand-written, de + en + hu (51 docs) | **0.0 %** | 94.3 | 18 ms* | no API call | [benchmarks.md](benchmarks.md#smoke) |
| fast, per language | hu / en / de | 0.0 / 0.0 / 0.0 % | 93.3 / 94.2 / 97.4 | | no API call | [hu](../eval/results/runs/2026-10-27-ner-v2-hu-smoke-xlmr-base-v2-hn.json), [en](../eval/results/runs/2026-10-27-ner-v2-en-smoke-xlmr-base-v2-hn.json), [de](../eval/results/runs/2026-10-27-ner-v2-de-smoke-xlmr-base-v2-hn.json) run records |
| audit (rules + NER + Muse Spark Open, Baseten) | hand-written, de + en + hu (51 docs) | 0.6 % | 98.2 | 1.9 s* | 2.03–2.95 | [benchmarks.md](benchmarks.md#smoke), [comparison](../eval/results/2026-10-27-comparison/README.md) |
| audit, earlier configuration (rules + Muse Spark Open, no NER) | hu-smoke (31 docs) | 0.9 % | 98.4 | 1.8 s | 2.42 | [hu-smoke run record](../eval/results/runs/2026-10-27-baseten-spark-open-hu-smoke.json) |
| same | en-smoke (10 docs) | 0.0 % | 97.1 | 1.2 s | 1.99 | [en-smoke run record](../eval/results/runs/2026-10-27-baseten-spark-open-en-smoke.json) |
| rules only (floor) | hand-written, de + en + hu (51 docs) | 41.6 % (hu 39.6, en 46.7, de 43.2) | 70.2 | 0.28 ms | no API call | [benchmarks.md](benchmarks.md#smoke) |

Fast mode on test sets it was not trained on (leak, 95 % intervals in
[benchmarks.md](benchmarks.md#results-per-dataset)): Nemotron-PII 0.7 %, CEE-PII 0.4 %, agent
traffic 2.6 %, finance text 19.1 %. Audit mode on the same sets was run on 10–30 documents
each (0.0–1.0 % except 26.7 % on 20 finance documents), too few to compare.

- **Caveats:** the hand-written set is small (31 Hungarian, 10 English and 10 German
  documents; one leaked value is about 1 point on Hungarian and 3 on English or German).
  `*` marks a latency averaged over several runs, measured on Apple MPS under unrelated load;
  NER alone on a loaded M1 Max CPU is 47 ms p50, 55 ms p95
  ([latency record](../eval/results/2026-10-27-ner-v21/latency/xlmr-base-v2-hn.json)). Fast
  mode over-masks reference numbers without a cue word: 39.4 % of masked spans on CEE-PII
  and 14.0 % on agent traffic
  ([model card, limitations](../training/ner/model-card.md#limitations)). The 0.0 % on the
  hand-written set is not the whole picture: finance text leaks 19.1 %. Fast mode downloads
  the published NER on first use and checks its hash; without one it is rules only
  ([models.md](models.md#which-ner-model-fast-mode-runs)).
- **Status:** shipped (LAB-1128, LAB-1150, LAB-1186, LAB-1192, LAB-1306). The committed
  Hungarian fast-mode scorecard and the fresh comparison landed with LAB-1148.

## 5. Head-to-head with Presidio, LLM Guard and PrivAiTe

The three closest open-source tools, each in its default configuration, scored with the same
scorer, on our hand-written set and on public and generated test sets.

| Hand-written (de + en + hu, 51 docs) | F1 | Leak | Over-masking |
|---|---:|---:|---:|
| Presidio | 64.9 | 24.3 | 27.5 |
| LLM Guard | 53.2 | 45.1 | 36.7 |
| PrivAiTe | 55.2 | 12.7 | 25.8 |
| **pii-guard fast (rules + NER `v2.0`)** | **94.3** | **0.0** | **1.1** |
| pii-guard audit (rules + NER + Muse Spark Open) | 98.2 | 0.6 | 1.1 |

Leak on the test splits of the public and generated datasets, in %:

| System | Nemotron-PII (300) | CEE-PII (451) | Agent traffic (990) | Gretel finance (400) | Ai4Privacy (600) |
|---|---:|---:|---:|---:|---:|
| Presidio | 12.8 | 36.5 | 12.4 | **18.8** | 29.6 |
| LLM Guard | 28.8 | 75.8 | 20.2 | 59.3 | 43.8 |
| PrivAiTe | 4.0 | 4.4 | **2.4** | 27.6 | 9.5 |
| **pii-guard fast** | **0.7** | **0.4** | 2.6 | 19.1 | 0.4 † |

† In-distribution: the NER trained on rows of this dataset's train split. The same recipe
trained without any of them leaks 13.8 %, behind PrivAiTe's 9.5 %
([model card](../training/ner/model-card.md#evaluation)).

- **Evidence:** [benchmarks.md, hand-written set](benchmarks.md#smoke) and [results per
  dataset](benchmarks.md#results-per-dataset), generated from the run records, with 95 %
  bootstrap intervals for the second table. The first Hungarian-only comparison, with the
  tools' configurations and the label mapping:
  [eval/results/2026-10-26-baselines/comparison.md](../eval/results/2026-10-26-baselines/comparison.md);
  the fresh one: [eval/results/2026-10-27-comparison/README.md](../eval/results/2026-10-27-comparison/README.md).
- **Where pii-guard is not ahead:** on finance text it is level with Presidio (19.1 vs 18.8 %)
  and on agent traffic within 0.2 points of PrivAiTe (2.6 vs 2.4 %). Fast mode also
  over-masks more than the leak numbers show on CEE-PII (39.4 %) and agent traffic (14.0 %);
  Presidio and PrivAiTe over-mask more still on most sets (Presidio 52.5 % on CEE-PII).
- **Caveats:** the hand-written set is small, and the comparison runs on it because the
  Muse-generated sets flatter a Muse-based detector
  ([evaluation.md](evaluation.md#reading-the-numbers)). LLM Guard's model was fine-tuned on an
  earlier Ai4Privacy release, so its Ai4Privacy number is probably optimistic. Dates, titles
  and bare towns are policy-excluded, which raises every system's over-masking on Ai4Privacy.
- **Status:** shipped (LAB-1098, LAB-1148, LAB-1150). The image comparison against Presidio
  Image Redactor and Eka is in [section 9](#9-images-faces-signatures-machine-readable-zones)
  (LAB-1164).

## 6. The LLM can only point, never write; red-teamed

The LLM detector returns the strings it thinks are personal data. pii-guard finds each one in
the original text itself, drops anything the model invented, and lets checksum-validated rules
keep their spans. A hallucination can't add text and a disagreement can't unmask anything: the
model can only add spans. Then we attacked it: 62 fictional messages in 15 attack classes
(instructions to stop reporting, fake end-of-JSON, role-play, zero-width characters,
homoglyphs, base64, spoofed placeholders, long padding and more).

- **Evidence:** leak on the injection set 3.4 % before hardening, **0.0 %** in two runs after
  (and 0.0 % with Muse Spark 1.3); 0 refusals and 0 invalid outputs in every run; no
  regression on the smoke sets
  ([eval/results/2026-10-27-injection](../eval/results/2026-10-27-injection/README.md),
  run records [run 1](../eval/results/runs/2026-10-27-injection-spark-open-run1.json),
  [run 2](../eval/results/runs/2026-10-27-injection-spark-open-run2.json)).
- **Then the partial leaks:** 3 values (zero-width characters inside e-mail addresses) were
  masked only in part, because only the LLM detector cleaned invisible characters. Now every
  detector sees normalised text and all 175 injection values are masked whole: partial leak
  1.7 % → **0.0 %**
  ([run record](../eval/results/runs/2026-10-27-injection-spark-open-after-normalise.json),
  [journey.md, milestone 20](journey.md#20-every-detector-sees-normalised-text-2026-10-27)).
- **Status:** shipped (LAB-1107, LAB-1146).

## 7. Honest about re-identification

Masking a value doesn't make a document anonymous. We gave Meta's own model the masked text
and asked it to recover every value, with and without a list of five candidates (the true
value and four decoys), on 81 fictional documents in Hungarian, English and German.

| Masking | Context | Re-identified | Chance | Exposure |
|---|---|---:|---:|---:|
| rules + Muse Spark Open | masked text only | 0.2 % | – | **1.4 %** |
| rules + Muse Spark Open | with 5 candidates | 39.2 % | 20.0 % | 39.9 % |

- **Evidence:** [eval/results/2026-10-27-redteam](../eval/results/2026-10-27-redteam/README.md).
- **What we conclude:** placeholders hold against reconstruction from the text alone, but
  someone who already holds a short candidate list links a document to the right person about
  twice as often as chance. pii-guard is **pseudonymisation, not anonymisation**, and the docs
  say so ([privacy-model.md](privacy-model.md)). Generalising the remaining context is filed
  (LAB-1152, triage).
- **Status:** shipped (LAB-1088).

## 8. A drop-in gateway that fails closed

Adopting pii-guard is a change of API base URL: it is an OpenAI-compatible
`/v1/chat/completions` proxy with streaming, tool calls and per-message detection caching
(chat clients resend the whole history; only new messages are detected). It masks the places
agents actually leak data: tool definitions, `response_format` JSON schemas and request
metadata, not just message text.

- **Evidence:** tools, legacy functions, response schemas and metadata are masked and
  streamed tool calls restored
  ([tests/gateway/test_request_tools_metadata.py](../tests/gateway/test_request_tools_metadata.py));
  a placeholder the session issued earlier and pasted back into a later message is refused
  with 422 and nothing is forwarded, because restoring it would put a real value into text
  that was never masked
  ([tests/gateway/test_gateway_placeholder_input.py](../tests/gateway/test_gateway_placeholder_input.py),
  [contracts.md](contracts.md)).
  A detector timeout, model error or malformed answer blocks the request; nothing is sent
  unmasked ([ADR 0006](decisions/0006-fail-closed.md)).
- **Status:** shipped (LAB-1100, LAB-1113, LAB-1092).

## 9. Images: faces, signatures, machine-readable zones

Scans and photos carry personal data too. pii-guard finds faces, ID photos and signatures with
SAM 3.1, finds machine-readable zones (MRZ) on ID documents by their OCR layout, fills the
regions and strips metadata before the image goes anywhere.

| Set | Portrait | Signature | MRZ | Printed text values | Source |
|---|---:|---:|---:|---:|---|
| 65 official specimen ID documents, 24 countries | **90.8 %** | 83.8 % | 0 % → **76.7 %** (80.0 % with the LLM detector) | 1.5 % → **15.0 %** (29.2 % with the LLM detector) | [specimens.md](../eval/results/visual/specimens.md), [captions](../eval/results/visual/specimens-captions.md), [benchmarks.md](benchmarks.md#image-masking) |
| 24 fictional specimens painted with Muse Image | **100 %** | **100 %** | 0 % → **100 %** | 34.5 % → **87.3 %** (99.1 % with the LLM detector) | [fictional.md](../eval/results/visual/fictional.md), [captions](../eval/results/visual/fictional-captions.md), same page |

Recall is the share of labelled regions masked with IoU ≥ 0.5. MRZ: [tests/visual/test_mrz.py](../tests/visual/test_mrz.py),
[journey.md, milestone 18](journey.md#18-machine-readable-zones-masked-by-their-layout-2026-10-27).

- **Text on IDs (LAB-1125, shipped):** a value next to a known caption (`Családi név /
  Surname`) is masked too, per language pack. This raised the printed-text recall, but it
  stays low on the official specimens: Tesseract returns no word at all for 108 of the 274
  specimen text values (guilloche backgrounds, holograms, thin strokes on small scans), so no
  text method reaches them. A reader for security-printed cards is the next step
  ([journey.md, milestone 22](journey.md#22-values-next-to-field-captions-on-id-cards-2026-10-27)).
- **Against other tools (LAB-1164, shipped):** on the 65 specimens, portraits 90.8 % vs Eka
  PII Redaction 55–57 %, signatures 83.8 % vs 46–49 %, MRZ 80.0 % vs at most 10 %; Presidio
  Image Redactor is text-only and masks none of these. On printed text Eka is ahead of
  pii-guard (32.5 % vs 30.3 % with the LLM detector, 15.0 % with rules alone), at 2.5 times
  the over-masking. All systems, with run conditions:
  [image baselines](../eval/results/2026-10-27-image-baselines/README.md),
  [journey.md, milestone 26](journey.md#26-image-masking-against-presidio-image-redactor-and-eka-2026-10-27).
- **Labelled images (LAB-1156, shipped):** each masked region carries the session's own
  placeholder (`PHOTO · [[PERSON_a1b2]]`) and the image comes back with a masked transcript
  that shares the text vault, so an assistant can answer "which parties have an ID on file?"
  without seeing a real value. The demo question was answered right for 3 of 3 parties with
  labelled images and 1 of 3 with black boxes; fuzzy matching puts the text's placeholder on
  50 of 51 printed values with clean OCR (96.1 % with simulated OCR noise;
  [journey.md, milestone 27](journey.md#27-images-that-say-whose-data-they-hid-2026-10-27)).
  As far as we found in a survey on 2026-10-27, no open-source tool shares placeholders
  between images and the text session.
- **Status:** shipped (LAB-1089, LAB-1110, LAB-1120, LAB-1121, LAB-1124, LAB-1125, LAB-1156,
  LAB-1164).

## 10. Hungarian depth as a showcase for hard languages

Hungarian is a hard case: rich morphology, family name first, and identifiers that look like
ordinary numbers. Getting it right shows what a language pack can carry.

- **Checksum-validated identifiers:** tax and TAJ numbers, the personal identification number,
  ID card, passport and licence numbers, TD1/TD3 MRZ with ICAO check digits, IBAN and giro
  accounts, company registration numbers. `ID_DOCUMENT` leaks 10 → 0 and land-registry parcel
  numbers 6 → 0 on `hu-smoke`, rules only, no new false positives
  ([evaluation.md](evaluation.md#id-documents-and-parcel-numbers)).
- **Addresses validated against the postcode–settlement table:** exact address recall 0.00 →
  1.00, partial leaks 12 → 0 on `hu-smoke`
  ([evaluation.md](evaluation.md#lexicons-diversity-and-the-address-rule)), using KSH lexicons
  committed under their CC BY 4.0 terms ([ADR 0009](decisions/0009-third-party-lexicons.md)).
- **Person names inside company names** (`Tóth és Társa Bt.`, `Molnár Péter e.v.`): leaked
  names 61.1 % → **0 %** with rules + NER on 44 documents, 0 of 30 person-free company names
  over-masked ([evaluation.md](evaluation.md#person-names-inside-company-names),
  [tests/languages/test_hu_companies.py](../tests/languages/test_hu_companies.py)).
- **Status:** shipped (LAB-1126, LAB-1127, LAB-1149).

## 11. Add a language with a checklist

A language is one plugin unit (`LanguagePack`: rules, inflection matcher, prompt notes, eval
forms, lexicons), discovered through an entry point, so it can ship as a separate package.
`pii-guard lang new <code>` writes the skeleton and `pii-guard lang check <code>` runs a
conformance suite that says what is missing and gates round trip and precision.

- **Evidence:** the German pack, added through this path: every structured identifier on the
  German smoke set found (addresses, e-mails, phones, Steuer-IDs, social security numbers,
  IBANs), rules precision 100 %, round trip 100 %, Hungarian and English scorecards unchanged
  ([languages.md, "German smoke results"](languages.md#german-smoke-results),
  [tests/languages/test_conformance.py](../tests/languages/test_conformance.py),
  [ADR 0010](decisions/0010-language-pack-plugins.md)).
- **Status:** shipped (LAB-1130). Hungarian, English and German today.

## 12. Known values and per-type policies

An application that already knows the client's name or an internal case number can pre-load
it into the session; it is then masked in every inflected form, with no model. Each entity type
has a policy: **mask**, **keep** (organisations stay readable by default, so the model can still
reason about who is who) or **block** (refuse the request).

- **Evidence:** on the known-values fixtures with rules only, leak 93.3 % → **0 %**, overlap
  recall 5.3 % → 100 %
  ([evaluation.md](evaluation.md#known-values-pre-loaded-into-the-session),
  [tests/detect/test_known.py](../tests/detect/test_known.py)). Policies:
  [entities.md](entities.md), [tests/test_policy.py](../tests/test_policy.py).
- **Status:** shipped (LAB-1101, LAB-1099, LAB-1136).

## 13. Benchmarking in the open

Every evaluation run is one JSON record in a fixed schema; the benchmark page, its charts and
the index are generated from them, and CI fails if they are out of date. The leak rate, not
F1, is the headline number. Generated sets are reported, but the headline uses the
hand-written ones because the generated ones flatter a Muse-based detector.

- **Evidence:** 499 run records in [eval/results/runs/](../eval/results/runs/) on
  `develop@5581013` (the [run log](benchmarks.md#run-log) lists them), against
  [run.schema.json](../eval/results/schema/run.schema.json);
  [benchmarks.md](benchmarks.md) generated by `pii-guard eval report`; `pii-guard eval report
  --check` runs on every pull request ([ci.yml](../.github/workflows/ci.yml)). How the numbers
  moved, milestone by milestone, with what each step cost:
  [journey.md](journey.md). Its [spend table](journey.md#spend-so-far) itemises about $22 of
  compute as of 2026-10-27, not counting the $2.92 of the NER v2.1 retrain (LAB-1306) or
  early unmetered calls.
- **Status:** shipped (LAB-1129, LAB-1141).

## What is not here yet

- Written confirmation of Baseten's data-retention terms for the shared Model APIs (LAB-1139,
  triage). Until then only fictional or masked data goes there; for real data, run the same
  open weights on hardware you control
  ([models.md](models.md#baseten-model-apis-the-audit-mode-detector)).
- English names on Muse-generated English text: 2.5 % leak on `en-synth-sample` (LAB-1138,
  triage).
- Fast mode on unfamiliar text: 19.1 % leak on finance text, 13.8 % on Ai4Privacy-style text
  the NER has not seen, and 39.4 % over-masking on CEE-PII
  ([model card](../training/ner/model-card.md#limitations)).
- A reader for security-printed ID cards: Tesseract returns no word for 108 of 274 specimen
  text values (LAB-1125, [section 9](#9-images-faces-signatures-machine-readable-zones)).
- Reducing re-identification from residual context (LAB-1152, triage).
- The Glimmer LoRA fine-tune (LAB-1109) is blocked.
- It is a hackathon build, not production-hardened.
