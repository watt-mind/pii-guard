# Bare house numbers and postcodes stay masked again (2026-10-30)

LAB-1599, found on LAB-1222's re-run of the Ai4Privacy sample. **Before:** LAB-1477's guard
dropped an NER `ADDRESS` hit made only of digits unless a street, a settlement or an address
word stood right next to it. Ai4Privacy writes addresses that way all the time: `near building
number 800`, `Building No.: 607` on its own line, `the zip code for the area is 92004`,
`Graz (1040)`, `a 1126 területen`. Fast mode's `ADDRESS` leak there went from 4 to 49 of 379
values. A leak costs more than an over-mask, so the guard was the wrong way round.

- **The guard now needs a positive sign** that the number is not an address
  ([`detect/ner_context.py`](../../src/pii_guard/detect/ner_context.py), rule 7). A missing
  street or city never drops a number. It goes when:
  - the word right before it labels something else: a port word, `ticket`, `issue`, `PR`,
    `version`, `build`, `pid`, `sku`, `priority`, `timeout`, `minutes` (`--port 8787`,
    `"ticket": 4471`, `sku: GT-81215`), or `hrsz` (the parcel rule masks it);
  - it is assigned (`VAULT_MAX_KEYS=8192`);
  - a weaker sign (a port word or `localhost` on its line, `up to` right before it, the shape
    of an amount) stands near it and nothing address-like does.
  A `#` alone is not a sign: `Bypass Road #542` is a house number.
- New unit tests with the Ai4Privacy shapes (fictional values) and the labelled shapes.

Fast mode (rules + NER v2.0, `watt-mind/pii-guard-ner-xlmr-base`), local CPU,
`pii-guard eval --detectors rules,ner`. Before #295 is `de442b3`, the regression is `develop`
`075e1a1`, after is this branch. The Ai4Privacy fixtures are the ones on `develop` (without
LAB-1222's ignore regions; LAB-1599 measured the same leak with and without them).

| set | `ADDRESS` leak | leak (values) | over-masked spans |
| -- | -- | -- | -- |
| Ai4Privacy de/en/hu (600 docs) | 4/379 → 49/379 → **4/379** | 8/2185 → 53/2185 → **8/2185** | 28/2202 → 26/2155 → 28/2202 |
| agent-text (hu/en/de) | 0/6 → 0/6 → 0/6 | 0/108 → 0/108 → 0/108 | 33/147 → 0/114 → **0/114** |
| smoke hu | 0/13 → 0/13 → 0/13 | 0/106 → 0/106 → 0/106 | 1/114 → 1/114 → 1/114 |
| smoke en | 0/4 → 0/4 → 0/4 | 0/30 → 0/30 → 0/30 | 1/33 → 1/33 → 1/33 |
| smoke de | 0/5 → 0/5 → 0/5 | 0/37 → 0/37 → 0/37 | 0/38 → 0/38 → 0/38 |

Both wins hold: the Ai4Privacy leak is back to the pre-LAB-1477 level and agent text keeps
LAB-1477's 0 over-masked spans. The cost is two Ai4Privacy `ADDRESS` over-masks that LAB-1477
had removed by accident (3 → 5): bare numbers in prose with no sign either way, which now stay
masked on purpose.
