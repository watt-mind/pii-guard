# pii-guard NER: multilingual PII detection for AI agent traffic

A token-classification model that finds personal data (names, addresses, birth dates, contact
details, ID and account numbers) in Hungarian, English and German text. It is the detector
behind the **fast mode** of [pii-guard](https://github.com/watt-mind/pii-guard), an open-source
privacy firewall that masks personal data before a prompt reaches an LLM and restores it in the
answer.

It is small enough to run in-process on a CPU next to every LLM call (about 50 ms per message),
so no text has to leave the machine to be checked.

| | |
|---|---|
| Base model | [`FacebookAI/xlm-roberta-base`](https://huggingface.co/FacebookAI/xlm-roberta-base) (278M parameters) |
| Languages | Hungarian, English, German |
| Release | `v2.0` |
| Licence | Apache-2.0 (training data attribution below) |

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

## Usage

### With pii-guard (recommended)

pii-guard downloads this model, verifies its checksum and runs it together with rule-based
detectors. The rules have the final say on structured identifiers (checksums, formats).
Detected values are replaced with reversible placeholders, and the originals are restored in
the model's answer:

```bash
git clone https://github.com/watt-mind/pii-guard && cd pii-guard
uv sync --extra ner
uv run pii-guard up   # an OpenAI-compatible gateway with rules + this model
```

### With transformers

```python
from transformers import pipeline

ner = pipeline(
    "token-classification",
    model="watt-mind/pii-guard-ner-xlmr-base",
    revision="v2.0",
    aggregation_strategy="simple",
)
ner("Kovács Annának küldd el a számlát: anna.kovacs@example.com, +36 30 123 4567")
```

Used this way you get raw spans. pii-guard adds word-boundary snapping, Hungarian suffix
handling and the rule layer on top. The scores below are measured with those steps applied.

## Evaluation

Scored by `pii-guard eval`. A value **leaks** if any part of it reaches the LLM unmasked.
**Over-masking** is the share of masked spans that weren't personal data. All numbers are %.
The full run records are in the pii-guard repository under `eval/results/`.

| Set (documents) | Rules + this model: leak | Over-masking | This model, no rules: leak |
|---|--:|--:|--:|
| Hand-written smoke tests, hu/en/de (51) | 0.0 | 1.1 | 3.5 |
| Agent traffic: tool calls, JSON, logs (990) | 0.2 | 1.7 | 0.3 |
| Ai4Privacy OpenPII validation (600)\* | 0.4 | 1.3 | 0.4 |
| NVIDIA Nemotron-PII test, en (300) | 0.7 | 1.4 | 1.1 |
| CEE PII benchmark test, hu/en (451) | 0.4 | 26.4 | 1.6 |
| Gretel finance test, en/de (400) | 19.0 | 22.5 | 20.3 |
| MAPA EUR-Lex court documents (42)† | 8.5 | 55.6 | n/a |

\* In distribution: the model was trained on rows from the same dataset's train split. A
version trained without any of that data leaked 13.8 % here, which is the fairer figure for
unseen text in that style.
† Mixed EU languages, most of them outside the three this model was trained on.

**Latency:** p50 74 ms and p95 147 ms per ~400-character message on an Apple M1 Max CPU under
heavy load. The same machine measured 47 / 55 ms under lighter load.

### Compared with other open models

Measured the same way, with each model in place of this one inside pii-guard's fast mode:

| Leak % | This model | [bardsai/eu-pii-anonimization-multilang](https://huggingface.co/bardsai/eu-pii-anonimization-multilang) | [tabularisai/eu-pii-safeguard](https://huggingface.co/tabularisai/eu-pii-safeguard) | [urchade/gliner_multi-v2.1](https://huggingface.co/urchade/gliner_multi-v2.1) |
|---|--:|--:|--:|--:|
| Agent traffic (dev split) | **0.1** | n/a | 8.2 | n/a |
| Smoke tests | **0.0** | n/a | 5.8 | n/a |
| Ai4Privacy, pooled | **0.4** | 10.4 | 7.5 | 22.5 |

"n/a" means that model wasn't run on that set. The bardsai and GLiNER figures come from an
earlier pii-guard version.

## Limitations

- **Languages.** Only Hungarian, English and German were trained. Other languages work partly
  through XLM-R's multilingual pretraining, but they leak more. On a Polish benchmark, 17.5 %
  of values leak, almost all of them Polish national ID numbers.
- **Reference numbers without context** (tracking numbers, order IDs in tool output) are
  sometimes tagged as `BANK_ACCOUNT` or `ID_DOCUMENT`. That causes most of the over-masking on
  the CEE benchmark. pii-guard's number post-processing removes most of these.
- **Finance documents** with unusual identifier formats leak about 19 %.
- **No types for usernames, IP addresses, URLs or secrets.** pii-guard handles these with rules.
- **Not a standalone anonymiser.** It is designed to run with pii-guard's rules. On its own, it
  reports spans with no checksum validation and no fail-closed behaviour.

## Training

- Fine-tuned for 3 epochs: learning rate 5e-5, 10 % warmup, linear decay, bf16.
- All training text is synthetic or public. No real personal data was used.

| Part | Rows | Source |
|---|--:|---|
| Synthetic agent-style documents, two corpora | 6,587 | Written and labelled by open-weight LLMs (Muse Spark as writer, Muse Glimmer 30B as labeller) from fictional people, companies and addresses |
| Ai4Privacy OpenPII-1M, train split | 5,000 per language | [`ai4privacy/pii-masking-openpii-1m`](https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m) |
| Hard negatives | 2,000 per language | Generated order, invoice, tracking and case numbers with no personal data, to reduce over-masking |

None of the Ai4Privacy rows used for training appear in the evaluation sample: every ID and
every text was checked. A near-duplicate check (MinHash) of the training data against all of
the evaluation sets found no overlap. It covered about 91 % of the training rows; one of the
two synthetic corpora could not be rebuilt for the check.

**Why v2.0 and not a newer retrain.** A v2.1 trained longer, with extra hard negatives, fixed
some over-masking. But it leaked more real ID numbers and e-mail addresses on unseen agent
traffic (2.4 % vs 1.7 % on the selection set), so v2.0 stays the release. The selection rule is
always the lowest leak on held-out agent traffic, because a leak is worse than an extra mask.

### Next candidate (v3, not published)

LAB-1393 trained a v3 candidate on a wider mix:
[eval/results/2026-10-28-ner-v3](https://github.com/watt-mind/pii-guard/tree/develop/eval/results/2026-10-28-ner-v3).
It didn't pass the selection rule, so v2.0 above is still the release. If a later v3.x is
published, its data and attribution are:

| Part | Train rows | Source | Licence, attribution |
|---|--:|---|---|
| Ai4Privacy OpenPII-1M, train split | 30,000 (hu/en/de 5,000; pl/cs/sk/ro/hr/sl 2,500) | [`ai4privacy/pii-masking-openpii-1m`](https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m) | CC-BY-4.0, "Ai4Privacy / Ai Suisse SA" |
| Privy protocol traces | 12,000 | [`piimb/privy`](https://huggingface.co/datasets/piimb/privy) | MIT, Privy (Pixie) |
| nym-pii multilingual | 13,000 (en/de/pl/cs/ro) | [`Wismut/nym-pii-multilingual-data`](https://huggingface.co/datasets/Wismut/nym-pii-multilingual-data) | MIT, byteowlz / Wismut |
| Nemotron-PII, train split | 1,500 | [`nvidia/Nemotron-PII`](https://huggingface.co/datasets/nvidia/Nemotron-PII) | CC-BY-4.0, NVIDIA Corporation |
| Gretel PII masking EN v1, train split | 2,500 | [`gretelai/gretel-pii-masking-en-v1`](https://huggingface.co/datasets/gretelai/gretel-pii-masking-en-v1) | Apache-2.0, Gretel.ai |
| Synthetic agent traffic, s11 corpus, hard negatives | 12,023 | pii-guard generators | Apache-2.0 |

Every source is pinned to a revision and file hash, and none is gated, CC-BY-SA or
non-commercial. Labels with no pii-guard NER type are left out of the loss: secrets, URLs and
IPs, which the rules handle, and the GDPR special categories. `Horizon-Labs/pii-redactor-base`
(Apache-2.0) took unlabelled English and German PII out of the loss and added no labels. No
training document is a near-copy of an evaluation text: 0 of 72,664 were dropped.

## Licence and attribution

- **This model:** Apache-2.0.
- **XLM-RoBERTa base:** MIT. Conneau et al., 2020, *Unsupervised Cross-lingual
  Representation Learning at Scale*.
- **Ai4Privacy OpenPII-1M:** CC-BY-4.0. **Attribution: "Ai4Privacy / Ai Suisse SA"**. Any
  redistribution of this model must carry this attribution.
- **Muse Glimmer 30B:** Apache-2.0 open weights. It wrote and labelled part of the synthetic
  corpus.
- **Hungarian name and place lists** used to generate fictional text:
  - KSH (Hungarian Central Statistical Office), CC-BY-4.0.
  - OpenStreetMap street names, © OpenStreetMap contributors, ODbL 1.0 (non-substantial
    extract).

The `NOTICE` file in this repository has the full attribution text.
