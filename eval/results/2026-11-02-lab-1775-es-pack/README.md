# Spanish language pack (LAB-1775)

*Before* is `origin/develop` at `ec2828b`, without an `es` pack (Spanish text got the recall
floor: language-independent rules, the other packs' `EVERYWHERE` rules, cues and exact vault
matching). *After* is the same commit with `src/pii_guard/languages/es/`. Fast mode is rules +
the published NER (`watt-mind/pii-guard-ner-xlmr-base`), on CPU; the NER is the same in both.
Scorecards in this folder: [es-smoke, rules](es-smoke-rules.json),
[es-smoke, fast](es-smoke-fast.json). No run record: like `pl-smoke` at first
([LAB-1400](../2026-10-28-lab-1400-pl-pack/README.md)), a record would add Spanish to the
headline `smoke` set before any comparison tool has run on it; that is for the EU-wave roll-up
(LAB-1779).

## Selection discipline

There is no Spanish benchmark in the repository yet, so the pack was written from the public
descriptions of each identifier (DNI/NIE mod-23 letter table, the CIF control digit) and tuned
on hand-written sets only:

- `eval/fixtures/es-smoke.jsonl`: 11 documents (email, contract, invoice, letter, chat, form,
  bank statement, two-surname note, medical form) with 45 labels, 2 hard negatives;
- the phase-1 gates `eval/fixtures/eu/es-smoke.jsonl` and `eu/es-inflection.jsonl` (LAB-1525,
  written before the pack);
- `eval/fixtures/negative/es-uncued-numbers.jsonl` (12 documents: order, invoice, tracking,
  file and booking numbers, amounts, postcodes, a valid DNI after `Pedido n.º`, nothing
  personal) and `negative/es-brand-names.jsonl` (6 prompts).

## Results

All four Spanish sets together (32 documents, 74 labels):

| Spanish sets | Pred | P exact | R overlap | F1 exact | Leak | Over-masking | Round trip |
|---|---:|---:|---:|---:|---:|---:|---:|
| rules, before | 12 | 100.0 | 16.2 | 27.9 | 82.4 | 0.0 | 100.0 |
| **rules, after** | 33 | 100.0 | 44.6 | 61.7 | **51.5** | 0.0 | 100.0 |
| fast, before | 80 | 82.5 | 98.6 | 85.7 | 0.0 | 4.0 | 100.0 |
| **fast, after** | 78 | 88.5 | 98.6 | **90.8** | 0.0 | 4.1 | 100.0 |

`es-smoke` alone (`pii-guard lang check es`): rules overlap precision 100.0, overlap recall
55.6, exact recall 55.6, leak 40.5, round trip 100.0; fast mode leak 0.0, F1 exact 92.1.

- **Every structured identifier on the smoke set is found by the rules** (DNI in three
  layouts, NIE, labelled CIF, IBAN, card, phones, addresses: 100 % overlap recall per type);
  the misses are names, dates of birth and organisations, which the rules don't cover by
  design.
- **Fast mode** already leaked nothing on these sets; the pack makes its spans exact (phones
  85.7 → 100, addresses 50.0 → 87.5 exact precision). Over-masking stays where it was
  (4.0 → 4.1 %): three NER spans on the negative set, `Código postal 28012` (as `ADDRESS`),
  `Recibo n.º 2026-000815` and `Localizador de la reserva 912345678` (as `ID_DOCUMENT`).
- **The Spanish reference words are rules-only for now.** Entries the NER number check reads
  (`both`/`ner`) fail the pinned `tests/detect/test_reference_packs.py` (pack negatives must
  equal the hard-coded fallback in `detect/ner_numbers.py`), and that check also does not read
  `n.º` as a filler. Both are shared files, so they are filed as LAB-1787 rather than edited
  here. With `both` scope (tried before reverting) fast-mode over-masking was 2.8 %: the
  `912345678` mask goes away.
- **Negative sets:** rules mask nothing on `es-uncued-numbers` and `es-brand-names`.

## Other languages unchanged

Rules on `eval/fixtures` (hu/en/de/pl smoke, synth-sample, injection, company-name and
inflection sets: 224 documents) and on `eval/fixtures/negative` (hu/en/de/pl: 82 documents)
give identical counts and ratios before and after (latency columns aside):

| Rules, `eval/fixtures` | Docs | Gold | Pred | P overlap | R overlap | Leak | Over-masking | Round trip |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` before / after | 24 | 197 | 74 / 74 | 100.0 / 100.0 | 37.1 / 37.1 | 53.6 / 53.6 | 0.0 / 0.0 | 100.0 / 100.0 |
| `en` before / after | 51 | 241 | 99 / 99 | 100.0 / 100.0 | 41.1 / 41.1 | 50.8 / 50.8 | 0.0 / 0.0 | 100.0 / 100.0 |
| `hu` before / after | 138 | 633 | 302 / 302 | 99.7 / 99.7 | 47.6 / 47.6 | 44.2 / 44.2 | 0.0 / 0.0 | 100.0 / 100.0 |
| `pl` before / after | 11 | 47 | 26 / 26 | 100.0 / 100.0 | 55.3 / 55.3 | 39.5 / 39.5 | 0.0 / 0.0 | 100.0 / 100.0 |

The other eleven languages of the phase-1 gates (`eval/fixtures/eu`) are unchanged too; only
the `es` row moves (rules leak 84.6 → 69.2).

## Reproduce

```bash
uv run --no-sync pii-guard lang check es
uv run --no-sync pii-guard eval --fixtures eval/fixtures --language hu,en,de,pl
PII_GUARD_NER_DEVICE=cpu uv run --no-sync pii-guard eval --detectors rules,ner \
    --fixtures eval/fixtures/es-smoke.jsonl --fixtures eval/fixtures/eu/es-smoke.jsonl \
    --fixtures eval/fixtures/eu/es-inflection.jsonl \
    --fixtures eval/fixtures/negative/es-uncued-numbers.jsonl
```

*Before* is the same with `src/pii_guard/languages/es/` moved out of the package.
