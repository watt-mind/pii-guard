# Order numbers and hex ids are not ID documents: agent-traffic over-masking 14.4 → 2.0 % (2026-10-28)

LAB-1293, found during LAB-1226. **Fast mode leaked little but over-masked a lot: 14.4 % of
what it masked on the `agent-traffic` test split was not personal data, 39.0 % on `cee-pii`.**
Most of it came from NER v2 (LAB-1150). The model proposes `ID_DOCUMENT`, `BANK_ACCOUNT` and the
Hungarian tax and TAJ numbers so that a number with a failing checksum is still masked, but it
also tagged long numbers that nothing marks as personal data. On the dev split, 223 of the 253
over-masked spans were of those types: order and ticket numbers (`"order": "…"`,
`ticket: SO…`), SKUs, 16-character hex ids (`"id": "…"`, `call_…`, `req=…`), an amount glued to
the CSV field before it, and digits cut out of longer tokens.

- **The fix: post-processing, no retraining.** `detect/ner_numbers.py` checks every NER span of
  those four types before it leaves the detector. A span that runs over a field separator is
  cut into fields. A lowercase hex id is dropped. A positive cue keeps the span whatever its
  shape: an identity, account, card, tax or phone word in the CSV column header or in the line
  before the value (every language pack's typed `cues.tsv` cues count). A negative label drops
  it: the column header, or a label right before the value such as order, ticket, SKU, invoice,
  tracking or request, or the value's own `ORD-` / `SKU-` prefix. Without a cue, only UPS / UPU
  tracking numbers and amounts are dropped. Everything else is kept (fail closed). The rules
  are unchanged.
- **What was tried and dropped.** Two rules were dropped because they cost leaks and removed
  nothing on the tuning data. One dropped an uncued all-digit number that fails every card,
  giro and IBAN check; the other dropped values of three characters or fewer. After
  normalisation, a phone number spelled out digit by digit (`4 4 2 0 …`) reads as one digit run,
  and the first rule dropped it. On `ai4privacy`, amount and generic reference words
  ("Betrag", "reference", "product") turned out to stand before real account and ID numbers, so
  they are not negative cues either.
- **How it was tuned.** On `agent-traffic-dev` and a fresh synthetic split (seed 71293, not
  committed). An earlier version was run once on the test splits: over-masking fell, but leak
  rose (`agent-traffic` 0.23 → 0.45 %, `ai4privacy` 0.37 → 1.19 %), so it was not shipped. A
  count-only attribution on `ai4privacy` (which check fired, which lexicon word; no text read)
  pointed at the amount and reference words. So `ai4privacy` is not a clean held-out set for
  this change.

Fast mode with NER v2 base + hard negatives, number checks off and on, on the same commit
(after: [agent-traffic](../../eval/datasets/results/2026-10-28-datasets-agent-traffic-fast.json),
[cee-pii](../../eval/datasets/results/2026-10-28-datasets-cee-pii-fast.json),
[agent-traffic-dev](../../eval/datasets/results/2026-10-28-datasets-agent-traffic-dev-fast.json)):

| set (split) | over-masking | precision | leak |
| -- | -- | -- | -- |
| agent-traffic-dev (dev) | 12.9 → 2.2 % | 84.4 → 94.5 % | 0.13 → 0.13 % |
| agent-traffic (test) | 14.4 → 2.0 % | 82.2 → 93.8 % | 0.23 → 0.23 % |
| cee-pii (test) | 39.0 → 27.9 % | 59.5 → 70.4 % | 0.40 → 0.40 % |
| gretel-finance (test) | 23.9 → 23.4 % | 73.1 → 73.4 % | 19.07 → 19.07 % |
| nemotron-pii (test) | 1.6 → 1.4 % | 90.8 → 91.0 % | 0.72 → 0.72 % |
| ai4privacy (test) | 1.4 → 1.4 % | 97.9 → 97.9 % | 0.37 → 0.37 % |

Recall is unchanged on every set, and so is the number of values leaked. The rules-only
quality gate does not move, since only NER spans are checked.

- **What's left on cee-pii.** 195 over-masked spans. Without looking at them on a test split,
  the next step is a dev split with the shapes the ticket names (timestamp-style references,
  postal tracking ids) or NER hard negatives for them.
- **Cost:** $0, offline, no model change.
