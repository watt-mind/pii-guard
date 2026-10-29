---
license: apache-2.0
pretty_name: PII Guard NER training corpora (synthetic)
language: [bg, cs, da, de, el, en, es, et, fi, fr, ga, hr, hu, it, lt, lv, mt, nl, pl, pt, ro, sk, sl, sv]
task_categories: [token-classification]
tags: [synthetic, pii, ner]
---

# PII Guard NER training corpora

**Private for now.** Backup of the LLM-generated training corpora of the PII Guard NER model
(`watt-mind/pii-guard-ner-xlmr-base`): the labelled documents, the model response caches that
reproduce them without new model calls, and the teacher labels. Written by
`training/ner/data_sync.py` in the PII Guard repository (LAB-1542).

## Synthetic or fictional data only

Every document was written by a model around **planted fictional values** (names, addresses,
identifiers drawn from fictional pools, ADR 0005), or built from templates. There is no real
personal data, no court text (MAPA, TAB) and no GDPR special-category data. A push is refused
unless the corpus manifest says `"synthetic": true` and every path passes the repository's
real-text allowlist (LAB-1527, LAB-1419). Third-party dataset downloads are never stored here.

## Sources and licenses

| Source | Script | What | License |
|---|---|---|---|
| Muse documents | `training/ner/eu_corpus.py` | fictional documents written by Muse Spark (Meta Model API, contributor tier) around planted fictional values: contracts, leases, court summons and judgment excerpts, invoices, e-mails, chats, minutes, no-PII prose | Apache-2.0 (pii-guard generator) |
| Muse court-style documents | `training/ner/court_eu.py` (LAB-1539) | fictional judgment-style documents around planted fictional parties | Apache-2.0 (pii-guard generator) |
| Glimmer teacher pass | `training/ner/modal_eu_label.py` -> `training/distill/label.py` | Muse Glimmer 30B (open weights) adds names the writer invented and masks disagreements out of the loss | Apache-2.0 |
| Response caches | `pii_guard.eval.generate.ResponseCache` | the model completions above, keyed by prompt hash | Apache-2.0 |

The template sets of the training mix (OpenPII-1M train rows, CC-BY-4.0 "Ai4Privacy / Ai Suisse
SA"; hard negatives; English court-style templates) rebuild byte-identically from the repository
and are not stored here. See `docs/training-data-eu-phase1.md`.

## Layout

One top-level folder per corpus (`phase1b/`, `v41/`, ...), each with a `manifest.json`
(generator, model, seed, license, `synthetic: true`). Pin a corpus by the commit that pushed it:

```bash
uv run --no-sync --with huggingface-hub python training/ner/data_sync.py pull <corpus> --revision <sha>
```
