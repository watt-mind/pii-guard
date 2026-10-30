<p align="center"><a href="https://huggingface.co/watt-mind"><img src="https://cdn-avatars.huggingface.co/v1/production/uploads/63ccddedf488db9bb3cece6b/51Lvp86UyUDIWL-vA0x_Q.png" alt="Watt Mind" width="72" /></a></p>

# PII Guard NER

**Multilingual PII detection for AI agents.**

[Quickstart](#usage) · [Source code](https://github.com/watt-mind/pii-guard) · [Try the demo](https://guard.watt-mind.com) · [Evaluations](https://github.com/watt-mind/pii-guard/blob/develop/docs/benchmarks.md) · [Watt Mind](https://huggingface.co/watt-mind)

A text token-classification model that finds personal data in **Hungarian, English and German** (the most tested) and, since v4.2, in 21 more EU languages: names, addresses, birth dates, contact details, ID and account numbers. Built by [Watt Mind](https://watt-mind.com), it powers the NER detector in [PII Guard](https://github.com/watt-mind/pii-guard)'s fast mode and runs locally on CPU.

**This model returns detected text spans.** PII Guard adds rule-based detection, boundary and Hungarian suffix handling, reversible masking and restoration, and the gateway workflows for prompts, tool calls and images. The model alone does not redact text, process images or guarantee that all personal data is found.

| | |
|---|---|
| Base model | [`FacebookAI/xlm-roberta-base`](https://huggingface.co/FacebookAI/xlm-roberta-base) (278M parameters) |
| Languages | Hungarian, English, German; since v4.2 also Bulgarian, Croatian, Czech, Danish, Dutch, Estonian, Finnish, French, Greek, Irish, Italian, Latvian, Lithuanian, Maltese, Polish, Portuguese, Romanian, Slovak, Slovenian, Spanish, Swedish |
| Release | `v4.2` (rollback: `v2.0`, revision `95f612a9ad65cc5ade5b9248bd152020541e7097`) |
| Licence | Apache-2.0 (training data attribution below) |

## Usage

### With PII Guard (recommended for masking)

PII Guard downloads this model, verifies its checksum and combines it with rule-based
detectors. The rules have the final say on structured identifiers (checksums, formats).
The gateway replaces detected values with reversible placeholders and restores the originals
in the upstream model's answer.

With [uv](https://docs.astral.sh/uv/) installed:

```bash
git clone https://github.com/watt-mind/pii-guard.git
cd pii-guard
uv sync --extra ner
uv run --no-sync pii-guard up
```

For gateway configuration and client examples, see the
[integration guide](https://github.com/watt-mind/pii-guard/blob/develop/docs/integrations.md)
and the [API guide](https://github.com/watt-mind/pii-guard/blob/develop/docs/api.md) (reference:
[guard.watt-mind.com/#api](https://guard.watt-mind.com/#api)). To explore the [hosted demo](https://guard.watt-mind.com), use fictional data only.

### With Transformers (text spans on CPU)

Install the dependencies in a Python environment. These versions were used to check the
examples below:

```bash
python -m pip install "transformers==5.21.0" "torch==2.14.1" "sentencepiece==0.2.2" "protobuf==7.36.2"
```

Load the published `v4.2` release and inspect a short fictional example:

```python
from transformers import pipeline

ner = pipeline(
    "token-classification",
    model="watt-mind/pii-guard-ner-xlmr-base",
    revision="v4.2",  # "v2.0" (95f612a9) is the previous release
    aggregation_strategy="simple",
    device=-1,  # CPU
)

text = "Fictional example: email Jane Placeholder at jane.placeholder@example.com."
for span in ner(text):
    print(
        span["entity_group"],
        text[span["start"] : span["end"]],
        span["start"],
        span["end"],
        round(float(span["score"]), 3),
    )
```

Each result contains `entity_group`, `score`, `word`, `start` and `end`. Use the character
offsets to recover the exact span from your original string; a confidence score is not a
guarantee that a value is personal data.

The same pipeline accepts a batch of texts:

```python
texts = [
    "Fictional example: email Jane Placeholder at jane.placeholder@example.com.",
    "Fiktív példa: Kovács Anna e-mail-címe anna.kovacs@example.com.",
    "Fiktives Beispiel: Anna Beispiel ist unter anna.beispiel@example.com erreichbar.",
]
results = ner(texts, batch_size=3)
for text, spans in zip(texts, results):
    print([(span["entity_group"], text[span["start"] : span["end"]]) for span in spans])
```

These examples use short inputs. For long documents, split the text into overlapping token
windows and merge the results; do not assume a plain pipeline call covers the full document.
PII Guard handles windowing, word-boundary snapping, Hungarian suffix handling and the rule
layer on top. The evaluation scores below were measured with those steps applied, not with
this plain Transformers snippet.

## Labels

BIO tags over ten entity types:

| Type | What it covers |
|---|---|
| `PERSON` | People's names, including inflected Hungarian forms |
| `ORGANIZATION` | Company and institution names |
| `ADDRESS` | Street addresses and places of residence |
| `DATE_OF_BIRTH` | Birth dates |
| `EMAIL` | E-mail addresses |
| `PHONE` | Phone numbers |
| `ID_DOCUMENT` | ID card, passport and driving-licence numbers |
| `NATIONAL_ID_HU_TAX` | Hungarian tax ID (adóazonosító jel) |
| `NATIONAL_ID_HU_TAJ` | Hungarian social security number (TAJ) |
| `BANK_ACCOUNT` | Bank account numbers and IBANs |

## Evaluation

Scored by `pii-guard eval`. A value **leaks** if any part of it reaches the LLM unmasked.
**Over-masking** is the share of masked spans that weren't personal data. All numbers are %.
v4.2 and v2.0 were scored on the same pii-guard commit, on CPU, by the same scorer, with the
same rules (fast mode) or with no rules (the model alone). The run records are in the pii-guard
repository under `eval/results/runs/` (`2026-10-30-lab-1625-*`).

| Set (documents) | Rules + v4.2: leak | Over-masking | v4.2, no rules: leak | Rules + v2.0: leak | Over-masking | v2.0, no rules: leak |
|---|--:|--:|--:|--:|--:|--:|
| Hand-written smoke tests, hu/en/de/pl (62) | 0.0 | 1.3 | 3.2 | 0.0 | 0.9 | 3.7 |
| Agent traffic: tool calls, JSON, logs (990) | 0.2 | 0.7 | 0.3 | 0.3 | 1.4 | 0.5 |
| Agent traffic, dev split (300) | 0.1 | 0.7 | 0.3 | 0.1 | 1.7 | 0.4 |
| Ai4Privacy OpenPII validation (600)\* | 0.4 | 0.3 | 0.4 | 0.4 | 0.4 | 0.4 |
| NVIDIA Nemotron-PII test, en (300) | 0.6 | 1.5 | 0.9 | 0.7 | 1.4 | 1.3 |
| CEE PII benchmark test, hu/en (451) | 0.8 | 7.3 | 10.5 | 0.4 | 12.4 | 1.6 |
| Gretel finance test, en/de (400) | 19.1 | 24.4 | 20.2 | 19.1 | 21.8 | 20.4 |
| Gretel finance, corrected labels (400)‡ | 2.4 | 24.4 | 3.9 | 2.4 | 21.8 | 4.1 |
| pl-pii-bench, Polish (346) | 4.2 | 10.8 | 13.3 | 3.5 | 11.2 | 22.7 |
| TAB, European Court of Human Rights, en (40) | 5.1 | 1.1 | 5.1 | 4.0 | 0.4 | 4.0 |
| MAPA EUR-Lex court documents (42)† | 8.5 | 44.7 | 8.5 | 8.2 | 55.5 | 8.2 |

\* In distribution: both versions were trained on rows from the same dataset's train split. A
model trained without any of that data leaked 13.8 % here, which is the fairer figure for
unseen text in that style.
‡ The same Gretel documents with obviously wrong gold labels (greetings, role words, template
slots labelled as names) turned into ignore regions (LAB-1497).
† Report-only, never a release gate: 21 EU languages of court text, scored on one machine and
never uploaded. v4.2 leaks a little more than v2.0 here and over-masks much less.

**Latency:** p50 43 ms and p95 50 ms per ~400-character message on an Apple M1 Max CPU, against
42 / 49 ms for v2.0 in the same run (the two models alternate message by message, so load
changes hit both alike; the machine was shared, load average 20-56). In an otherwise idle 8-CPU
Modal container: p50 62 / p95 73 ms, against 63 / 78 ms for v2.0.

### Release gates (v4.2 against v2.0)

v4.2 was picked from four candidates by rules fixed before any of them was trained: it had to
pass every gate against v2.0, then have the lowest leak on a held-out selection split. Fast mode,
CPU, leak / over-masking %:

| Gate | Set | v4.2 | v2.0 | Rule | Result |
|---|---|--:|--:|---|---|
| Smoke leak | Hand-written hu/en/de (51) | 0.00 | 0.00 | ≤ v2.0 | pass |
| Smoke over-masking | Hand-written hu/en/de (51) | 1.09 | 1.08 | ≤ v2.0 + 0.5 | pass |
| Inflection leak | Hungarian inflected names (50 values) | 0.00 | 2.00 | ≤ v2.0 | pass |
| EU per language | lv lt hr sl fr es it nl ro mt ga, en court | 0.00 everywhere except fr 3.85 | fr 3.85, nl 4.00, ga 4.00 | ≤ v2.0, over-masking ≤ v2.0 + 2 | pass |
| EU total leak | the 12 sets above (315 values) | 0.32 | 0.95 | < v2.0 | pass |
| Agent traffic, dev split | 300 | 0.13 / 0.66 | 0.13 / 1.66 | leak ≤ and over-masking ≤, one lower | pass |
| CPU p95 latency | ~400-character messages, one alternating run in an 8-CPU Modal container | 73.0 ms | 77.5 ms | ≤ 1.2× v2.0 | pass (0.94×) |
| Selection split (ranking) | 685 synthetic hu/en/de documents | 0.00 / 1.58 | 0.00 / 6.63 | lowest leak wins | selected |

The full protocol and every candidate's numbers are in
[eval/results/2026-10-30-lab-1625-ner-v42](https://github.com/watt-mind/pii-guard/tree/develop/eval/results/2026-10-30-lab-1625-ner-v42).

### Compared with other open models

Measured the same way, with each model in place of this one inside pii-guard's fast mode:

| Leak % | v4.2 | v2.0 | [bardsai/eu-pii-anonimization-multilang](https://huggingface.co/bardsai/eu-pii-anonimization-multilang) | [tabularisai/eu-pii-safeguard](https://huggingface.co/tabularisai/eu-pii-safeguard) | [urchade/gliner_multi-v2.1](https://huggingface.co/urchade/gliner_multi-v2.1) |
|---|--:|--:|--:|--:|--:|
| Agent traffic (dev split) | **0.1** | **0.1** | n/a | 8.2 | n/a |
| Smoke tests, hu/en/de | **0.0** | **0.0** | n/a | 5.8 | n/a |
| Ai4Privacy, pooled | **0.4** | **0.4** | 10.4 | 7.5 | 22.5 |

"n/a" means that model wasn't run on that set. v4.2 and v2.0 were run on the same commit; the
eu-pii-safeguard figures come from the LAB-1386 runs of 2026-10-28, and the bardsai and GLiNER
figures from an earlier pii-guard version.

## Limitations

- **Languages.** Hungarian, English and German have the most training data and the most tests.
  The 21 other EU languages were trained on fewer rows and are tested on small fictional gate
  sets (about 25-30 values each) and on MAPA court text, so expect more leaks there. On the
  Polish pl-pii-bench, the model alone leaks 13.3 % (v2.0: 22.7 %); pii-guard's Polish rules bring fast mode
  to 4.2 % (v2.0: 3.5 %).
- **Model alone on the CEE benchmark.** Without the rules, v4.2 leaks 10.5 % on CEE-PII,
  against v2.0's 1.6 %. With the rules (fast mode, the supported setup) it is
  0.8 % against 0.4 %, and over-masking falls from 12.4 % to 7.3 %.
- **Reference numbers without context** (tracking numbers, order IDs in tool output) are
  sometimes tagged as `BANK_ACCOUNT` or `ID_DOCUMENT`. That causes most of the over-masking on
  the CEE benchmark. pii-guard's number post-processing removes most of these.
- **Finance documents** with unusual identifier formats leak about 19 % (2.4 % once the
  benchmark's wrong labels are corrected).
- **No types for usernames, IP addresses, URLs or secrets.** pii-guard handles these with rules.
- **Not a standalone anonymiser.** It is designed to run with pii-guard's rules. On its own, it
  reports spans with no checksum validation and no fail-closed behaviour.

## Training

v4.2 is fine-tuned from v2.0 (revision `95f612a9`), which was fine-tuned from XLM-R base.

- **v4.2:** 1 epoch from the v2.0 weights, learning rate 1e-5, 10 % warmup, batch 16, bf16,
  512-token windows with a 128-token stride; 187,030 training documents (some parts counted
  twice, below), 26 minutes on one A10G GPU. Loose `ADDRESS` labels (a bare town or country)
  are left out of the loss.
- **v2.0:** 3 epochs, learning rate 5e-5, 10 % warmup, linear decay, bf16.
- All training text is synthetic or public. No real personal data was used.

| Part | Rows | Languages | Source | Licence, attribution |
|---|--:|---|---|---|
| Ai4Privacy OpenPII-1M, train split | 15,000 (v2.0) + 47,500 | hu/en/de 5,000 each; 19 more EU languages 2,500 each | [`ai4privacy/pii-masking-openpii-1m`](https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m) | CC-BY-4.0, "Ai4Privacy / Ai Suisse SA" |
| kiji PII training data | 15,000 | da, de, en, es, fr, nl | [`DataikuNLP/kiji-pii-training-data`](https://huggingface.co/datasets/DataikuNLP/kiji-pii-training-data) | Apache-2.0, Dataiku |
| nym-pii multilingual | 35,000 | 14 EU languages | [`Wismut/nym-pii-multilingual-data`](https://huggingface.co/datasets/Wismut/nym-pii-multilingual-data) | MIT, byteowlz / Wismut |
| E3 synthetic multilingual PII NER | 2,164 | de, el, en, fr, it, nl, sl | [`E3-JSI/synthetic-multi-pii-ner-v1`](https://huggingface.co/datasets/E3-JSI/synthetic-multi-pii-ner-v1) (healthcare rows dropped) | MIT, Jožef Stefan Institute |
| pii-anon, rows holding an ID only | 2,973 | 18 EU languages | [`subhash-holla/pii-anon`](https://huggingface.co/datasets/subhash-holla/pii-anon) | CC0-1.0 |
| Synthetic agent-style documents (v2.0) | 4,223 | hu, en | Written by Muse Spark, labelled by Muse Glimmer 30B, around fictional people, companies and addresses | Apache-2.0 (pii-guard generator) |
| Synthetic EU-language documents | 4,310 (×2) + 7,538 | lv, lt, hr, sl; fr, es, it, nl, ro, ga, mt | Written by Muse Spark (Meta Model API), labelled by Muse Glimmer 30B, planted fictional values | Apache-2.0 (pii-guard generator) |
| Court-style documents and error-mined variants | 3,437 + 475 | 24 | Written by Muse Spark, labelled by Muse Glimmer 30B: people named in full, then by surname and in declined forms | Apache-2.0 (pii-guard generator) |
| English court-style templates | 1,500 | en | pii-guard template generator | Apache-2.0 |
| Hard negatives | 6,000 + 21,000 | hu/en/de 2,000 each; 21 more 1,000 each | Generated order, invoice, tracking and case numbers with no personal data | Apache-2.0 |
| Targeted fixes | 2,500 + 6,300 (×2) | hu, mt; de, hu, en | Fictional templates: Hungarian powers of attorney, Maltese birth dates (v4.1); German genitive names, Hungarian surname plus inflected given name, birth dates next to other dates, reference numbers (v4.2) | Apache-2.0 |

kiji, nym and E3 also label contract dates, deadlines and even towns as `DATE_OF_BIRTH`. In
v4.2, such a label becomes `O` when it holds no digit, or when no birth word ("born", "geb.",
"szül." ...) is in or just before it and it has no year from 1900 to 2009. Labels with no
pii-guard NER type are left out of the loss: secrets, URLs and IPs, which the rules handle, and
the GDPR special categories.

None of the Ai4Privacy rows used for training appear in the evaluation sample: every ID and
every text was checked. A near-duplicate check (MinHash, Jaccard ≥ 0.8 on word 5-grams) of the
v4.2 training data against the evaluation and selection sets dropped 0 of 179,895 documents.

**Why v4.2.** None of the retrains between v2.0 and v4.1 beat v2.0 under the selection rules.
v4.1 fixed the EU languages but over-masked birth dates and leaked German genitive names on the
smoke tests, and the old selection set could not see either. v4.2 added a selection split built around those failure modes, cleaned
the third-party birth-date labels and added targeted fictional data. It is the first candidate
to pass every gate: no more leaks than v2.0 on the hand-written and agent-traffic sets, a third
of v2.0's EU leak with no EU over-masking, less over-masking on agent traffic, and no slower. It
leaks slightly more than v2.0 on some public sets (CEE-PII, pl-pii-bench, TAB, MAPA; see the
table above), none of which is a release gate. The rule is always the lowest leak on
held-out data, because a leak is worse than an extra mask. To go back, pin `revision="v2.0"`
(commit `95f612a9ad65cc5ade5b9248bd152020541e7097`).

## Licence and attribution

- **This model:** Apache-2.0.
- **XLM-RoBERTa base:** MIT. Conneau et al., 2020, *Unsupervised Cross-lingual
  Representation Learning at Scale*.
- **Ai4Privacy OpenPII-1M:** CC-BY-4.0. **Attribution: "Ai4Privacy / Ai Suisse SA"**. Any
  redistribution of this model must carry this attribution.
- **DataikuNLP/kiji-pii-training-data:** Apache-2.0, Dataiku.
- **Wismut/nym-pii-multilingual-data:** MIT, byteowlz / Wismut.
- **E3-JSI/synthetic-multi-pii-ner-v1:** MIT, Jožef Stefan Institute.
- **subhash-holla/pii-anon:** CC0-1.0.
- **Muse Glimmer 30B:** Apache-2.0 open weights. It wrote and labelled part of the v2.0
  synthetic corpus and labelled the EU, court-style and variant documents. Muse Spark (Meta
  Model API) wrote the documents around planted fictional values.
- **Hungarian name and place lists** used to generate fictional text:
  - KSH (Hungarian Central Statistical Office), CC-BY-4.0.
  - OpenStreetMap street names, © OpenStreetMap contributors, ODbL 1.0 (non-substantial
    extract).

The `NOTICE` file in this repository has the full attribution text.
