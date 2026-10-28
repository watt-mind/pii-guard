# Identifiers in CSV rows masked whole, and the digits a mask leaves are measured (2026-10-28)

LAB-1367, found by LAB-1355. **Before:** on agent-traffic, fast mode masked 54 identifiers
only in part. The placeholder started or ended inside the number, so a few digits went
upstream in clear text: `[[ID_DOCUMENT_x]]010`, `8[[NATIONAL_ID_HU_TAX_x]]`. Neither leak (the
whole value) nor partial leak (a surviving token of 4+ digits) counted them: partial leak said
2 values. **After:** 1 partial cover is left on agent-traffic, a name, not a number, and the
eval counts this kind of leak.

- **Where the short spans came from.** All 54 were NER spans, none from the rules, and 53 sat
  in CSV rows (`name,email,phone,tax_id,order,amount`). Two causes, one under the other:
  1. **The rules didn't see the value.** A number may not continue a decimal or thousands
     group, so the rules refused any number after or before `<digit>,`. In a CSV row that
     comma separates fields: `…,06 20 751 6714,8461269322,ORD-…` gave no rule span for a tax
     number they find on its own. Now `<digit>,` blocks a number only when 1–3 digits follow
     the comma (`1,234,567`, `27358,76`), in `detect/rules/_base.py`.
  2. **The NER span cut the token.** With no rule span, the model's span decided, and the
     model labels sub-word pieces of a number (`846` PHONE + `126` tax number of
     `8461269322`). The LAB-1338 snap covered names, organisations and addresses only.
     `detect/ner_words.snap_to_tokens` now extends phone, ID, account, tax and TAJ spans to
     the whole run of letters and digits, also across a `.`, `-` or `/` between digits
     (`812.754.113.91`), before the LAB-1293 number checks judge them. Pieces of different
     types that end up on one token keep the type that covered most of it.
- **The metric.** Partial leak now also counts a value whose occurrence has digits left right
  next to its placeholder: a digit run the edge cuts, or one joined to it by `.`, `-` or `/`
  (`[[ID_x]].91`). It uses the vault's replacements, so it is tied to the occurrence, not to
  any digits that happen to survive. Placeholder consistency reads the same gap as not covered.

Fast mode (rules + NER, published `hdkiller/pii-guard-ner-xlmr-base@95f612a9ad65`). Both
columns are scored with the new scorer; before is the detectors of `develop` @ `7ce5d20`.
Counts in [before.json](../../eval/results/2026-10-28-id-tail-digits/before.json) and
[after.json](../../eval/results/2026-10-28-id-tail-digits/after.json), from
`scripts/probe_partial_covers.py`. Tuned on agent-traffic-dev; agent-traffic and ai4privacy were
run once, at the end.

| set (split) | partial leak | leak | consistency | over-masking | precision | recall |
| -- | -- | -- | -- | -- | -- | -- |
| agent-traffic-dev (dev) | 11 -> 1 | 2 -> 2 | 97.36 -> 98.97 % | 1.88 -> 1.84 % | 94.50 -> 95.72 % | 97.75 -> 97.93 % |
| agent-traffic (test) | 54 -> 1 | 12 -> 12 | 96.78 -> 99.01 % | 1.70 -> 1.65 % | 93.78 -> 95.43 % | 97.32 -> 97.44 % |
| ai4privacy (test) | 2 -> 2 | 8 -> 8 | 99.31 -> 99.31 % | 1.41 -> 1.27 % | 97.87 -> 98.00 % | 98.95 -> 98.95 % |

- **Each fix alone** on agent-traffic-dev: the snap alone takes partial leak 11 -> 1 and
  consistency to 1,539, the rules change alone 11 -> 6 and 1,527. The rules change alone has
  the best recall (98.22 %), because with both, five `ID_DOCUMENT` values are masked whole but
  under another type's placeholder (`PHONE`, `BANK_ACCOUNT`): the snapped NER span now ties the
  rule span on length and wins on score, as the resolver doesn't count `ID_DOCUMENT` rule spans
  as validated. Masking is complete; the label is wrong (follow-up LAB-1380). Both fixes are
  kept: the snap is what covers a number no rule knows.
- **Leak doesn't move**: these values never survived whole.
- **Cost:** $0, offline, no model change.
