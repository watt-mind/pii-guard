# 0005. Synthetic data only

- **Status:** accepted
- **Date:** 2026-10-26

## Context

A PII tool needs realistic test data, and the most realistic data is real documents. Using
them would put personal data into the repository, the issue tracker, CI logs and training
runs, which is exactly the harm the project exists to prevent.

## Decision

- All fixtures, evaluation data and fine-tuning data are **synthetic**: fictional identities
  from a seeded generator, documents written around them by a model.
- **No real personal data** may be committed, attached to issues, pasted into pull requests,
  or used to train or tune detectors. Bugs found on real documents are reproduced with
  synthetic ones.
- Generated data that is committed lives under `eval/fixtures/`; working data is gitignored.

### Fictional phone numbers and email addresses

A made-up phone number can still ring a real person. Hand-written fixtures therefore use
numbers that are set aside for fiction wherever a country has such a range, and a fixed,
visibly placeholder pattern where it has none (added 2026-10-27, LAB-1214):

| Country | Rule | Examples |
|---|---|---|
| email | the reserved `example.com`, `example.org`, `example.net` domains (RFC 2606) | `teszt.elek@example.com` |
| US, CA | NANP `555-0100` to `555-0199` | `+1 202 555 0143` |
| UK | Ofcom's drama ranges (`020 7946 0xxx`, `07700 900xxx`) | `+44 20 7946 0123` |
| DE | the Bundesnetzagentur "Drama Numbers": fixed line `030 23125 xxx`, `040 66969 xxx`, `069 90009 xxx`, `0221 4710 xxx`, `089 99998 xxx`; mobile `0171 39200 xx`, `0176 040690 xx` | `+49 30 23125042`, `0171 3920042` |
| HU | no range is reserved (the national numbering plan has none). We use a real area code, so the detectors see a well-formed number, with a subscriber number that is an ascending digit run (`123 4567`, `234 5678`, `345 6789`, `456 7890`) or in the block `555 01xx` | `+36 1 234 5678`, `06 30 123 4567`, `+36 70 555 0123` |

The Hungarian rule can't rule out that such a number is assigned to someone; it keeps the
chance low and makes the intent obvious. A new language pack documents its country's rule
here. Generators (`eval/fixtures/build_*.py`) are the place to change a number: the committed
JSONL files are regenerated from them.

New fixtures follow this rule. Some numbers in the existing `hu-smoke` and `de-smoke` sets
predate it. Changing those files makes every committed run on them stale, so they move
together with fresh benchmark runs on the new files (LAB-1302).

## Consequences

- The benchmark can be published openly.
- Synthetic data can miss patterns that only occur in real documents. We mitigate this with a
  hand-written hard-case set and by encouraging users to report *patterns* (not documents)
  that the detectors miss.
