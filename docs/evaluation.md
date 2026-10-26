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
   seed, so runs are reproducible.
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
| **Visual recall** | Share of labelled image regions covered by a mask (IoU threshold) |
| **Latency** | p50 / p95 per request, per pipeline stage |

## Baselines

Each detection change reports against these:

1. **Rules only.**
2. **Rules + NER.**
3. **Rules + NER + prompted LLM** (no fine-tuning).
4. **Rules + NER + fine-tuned LLM.**

The hackathon claim is the difference between 2 and 4, on the test split.

## Reporting

`uv run pii-guard eval` writes a JSON scorecard and a Markdown table. Results for every
release are committed under `eval/results/` with the model versions, corpus seed and commit
hash, so anyone can reproduce them.
