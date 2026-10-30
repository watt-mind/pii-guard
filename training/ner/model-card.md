<p align="center"><a href="https://huggingface.co/watt-mind"><img src="https://cdn-avatars.huggingface.co/v1/production/uploads/63ccddedf488db9bb3cece6b/51Lvp86UyUDIWL-vA0x_Q.png" alt="Watt Mind" width="72" /></a></p>

# PII Guard NER

**Multilingual PII detection for AI agents.**

[Quickstart](#usage) · [Source code](https://github.com/watt-mind/pii-guard) · [Try the demo](https://guard.watt-mind.com) · [Evaluations](https://github.com/watt-mind/pii-guard/blob/develop/docs/benchmarks.md) · [Watt Mind](https://huggingface.co/watt-mind)

A text token-classification model that finds personal data in **⟦B3 training languages⟧**: names, addresses, birth dates, contact details, ID and account numbers. Built by [Watt Mind](https://watt-mind.com), it powers the NER detector in [PII Guard](https://github.com/watt-mind/pii-guard)'s fast mode and runs locally on CPU.

**This model returns detected text spans.** PII Guard adds rule-based detection, boundary and Hungarian suffix handling, reversible masking and restoration, and the gateway workflows for prompts, tool calls and images. The model alone does not redact text, process images or guarantee that all personal data is found.

| | |
|---|---|
| Base model | [`FacebookAI/xlm-roberta-base`](https://huggingface.co/FacebookAI/xlm-roberta-base) (278M parameters) |
| Languages | ⟦B3 training languages⟧ |
| Release | ⟦B3 release tag⟧ |
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

Load the published `v2.0` release and inspect a short fictional example:

```python
from transformers import pipeline

ner = pipeline(
    "token-classification",
    model="watt-mind/pii-guard-ner-xlmr-base",
    revision="v2.0",
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
**Over-masking** is the share of masked spans that weren't personal data. All numbers are %,
from the committed run records in the pii-guard repository (`eval/results/runs/`), the same
records as its README and [benchmarks page](https://github.com/watt-mind/pii-guard/blob/develop/docs/benchmarks.md).

| Set (documents) | Rules + this model: leak | Over-masking | Run record |
|---|--:|--:|---|
| Hand-written smoke tests, de/en/hu/pl (62) | ⟦B3 smoke leak⟧ | ⟦B3 smoke over-masking⟧ | ⟦record⟧ |
| Agent traffic: tool calls, JSON, logs (990) | ⟦B3 agent-traffic leak⟧ | ⟦B3 agent-traffic over-masking⟧ | ⟦record⟧ |
| NVIDIA Nemotron-PII test, en (300) | ⟦B3 nemotron leak⟧ | ⟦B3 nemotron over-masking⟧ | ⟦record⟧ |
| CEE PII benchmark test, en/hu (451) | ⟦B3 cee leak⟧ | ⟦B3 cee over-masking⟧ | ⟦record⟧ |
| Gretel finance test, de/en (400) | ⟦B3 gretel leak⟧ | ⟦B3 gretel over-masking⟧ | ⟦record⟧ |
| Gretel finance, corrected labels (400) | ⟦B3 gretel-corrected leak⟧ | ⟦B3 gretel-corrected over-masking⟧ | ⟦record⟧ |
| Ai4Privacy OpenPII sample, de/en/hu (600)\* | ⟦B3 ai4privacy leak⟧ | ⟦B3 ai4privacy over-masking⟧ | ⟦record⟧ |
| Polish pl-pii-bench (346), with PII Guard's Polish rules | ⟦B3 pl-pii-bench leak⟧ | ⟦B3 pl-pii-bench over-masking⟧ | ⟦record⟧ |
| Hungarian inflected names (12) | ⟦B3 inflection leak⟧ | ⟦B3 inflection over-masking⟧ | ⟦record⟧ |

\* In distribution: ⟦whether B3's training mix includes OpenPII train rows; if so, say no
evaluated row was trained on and that this is not a fair figure for unseen text⟧.

**Latency:** ⟦B3 CPU overhead⟧ added per request (p50, one request at a time) by PII Guard's
gateway with this model on CPU, from a `pii-guard bench latency` record (⟦record⟧).

### Compared with other open models

Measured the same way on the hand-written smoke tests, with each model in place of this one
inside pii-guard's fast mode (the same rules around each, one commit):

| Model | Leak | F1 | Over-masking |
|---|--:|--:|--:|
| **This model** | ⟦B3⟧ | ⟦B3⟧ | ⟦B3⟧ |
| ⟦each other open model from the same-commit comparison runs⟧ | | | |

## Limitations

- **Languages.** ⟦B3 training languages⟧ were trained. Other languages work partly through
  XLM-R's multilingual pretraining, but they leak more. On a Polish benchmark the model with
  PII Guard's Polish rules leaks ⟦B3 pl-pii-bench leak⟧; without the rules, Polish national ID
  numbers are most of what leaks.
- **Reference numbers without context** (tracking numbers, order IDs in tool output) are
  sometimes tagged as `BANK_ACCOUNT` or `ID_DOCUMENT`. That causes most of the over-masking on
  the CEE benchmark. pii-guard's number post-processing removes most of these.
- **Finance documents** with unusual identifier formats leak ⟦B3 gretel leak⟧ on the
  dataset's own labels (⟦B3 gretel-corrected leak⟧ on corrected labels).
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

**How this release was chosen.** ⟦B3 selection story from eval/results/2026-10-30-lab-1625-ner-v42/README.md: the rule fixed before training, the gates against v2.0 (gates.json), and what B3 traded⟧.

⟦Training data table and attribution for B3 (v4.1 data + v4.2 targeted corpus): every source pinned to a revision, licence and attribution; replaces the v2.0 table above and the old "Next candidate (v3)" section⟧

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
