# Ports, sizes and algorithm names stay readable in agent text (2026-10-30)

LAB-1477, found on LAB-1470's replay of this repository's agent-facing docs. **Before:** in
fast mode the NER encoder still typed bare numbers as `ADDRESS`: `4096` in "up to 4096 keyed
digests", the ports `8787`, `18787` and `18790`, a tool result's `"ticket": 4471`, the digits of
a SKU (`GT-81215`) and an amount at the end of a CSV row. A four-digit number has the shape of a
Hungarian postcode, so the model's guess is not absurd, but nothing next to these numbers says
address. It also typed `Luhn` in "a Luhn test card" as a `PERSON`: an algorithm's eponym.

- **Two more structural guards** in
  [`detect/ner_context.py`](../../src/pii_guard/detect/ner_context.py), run on NER spans only
  (the rules are untouched):
  - an `ADDRESS` hit with digits and no letter goes, unless something address-like touches
    it: a word written as a name (`1051 Budapest`, `Budapest, 1051`, `Musterstraße 12`,
    `H-6720 Szeged`; a sentence end in between does not count), an address word among the two
    words before it or the word after it (a street type, `zip`, `PLZ`, `irányítószám`,
    `lakcím`: `Minta utca 12. 3/5.`, `"zip": 1051`), or another `ADDRESS` hit. A port word right
    before the number (`port`, `--port`, `Ports`) drops it whatever follows;
  - a one-word `PERSON` hit followed by a method's noun (`Luhn test`, `Luhn check`,
    `Dijkstra's algorithm`, `Luhn-algoritmus`, `Luhn-Prüfsumme`, `Bloom filter`) goes. A name the
    language packs' lexicons know (`Kovács test results`) and a hit that is part of a longer name
    (`Hans Luhn test`) stay masked.
- **New agent-text fixture rows** ([builder](../../eval/fixtures/build_agent_text.py)), in hu,
  en and de: three negatives (an operations doc with ports and a size, a CRM tool result with a
  `"ticket"` number, Luhn and Levenshtein prose) and two positives that put a postcode and a
  settlement, a street and a house number, and a name next to ports, a ticket number and a
  Luhn test card.

Fast mode (rules + NER v2.0, `watt-mind/pii-guard-ner-xlmr-base`), local CPU,
`pii-guard eval --detectors rules,ner`. Before is `develop` `39692e7` with the new fixture rows;
after is this branch.

| set | leak (values) | over-masked spans | recall (overlap) |
| -- | -- | -- | -- |
| agent-text (hu/en/de) | 0/108 → 0/108 | 33/147 → **0/114** | 114/114 → 114/114 |
| agent-traffic-dev | 2/1555 → 2/1555 | 31/1686 → **28/1683** (`ADDRESS` 6 → 3) | 1657/1687 → 1657/1687 |
| smoke (hu/en/de/pl) | 0/216 → 0/216 | 2/228 → 2/228 | 227/241 → **229/241** |
| hu-inflection | 1/50 → 1/50 | 0/57 → 0/57 | 57/61 → 57/61 |

Real addresses and names are unchanged: `ADDRESS` recall stays 88/88 on agent-traffic-dev and
27/27 on smoke, `PERSON` 540/540 and 76/76. On smoke two `PARCEL_NUMBER_HU` values are now found
whole: the NER no longer claims `28145/3` as an address, so the rule's parcel span wins.

Left: the three `ADDRESS` hits still over-masked on agent-traffic-dev are SKUs (`EM-14270`,
`TX-1516`) where the prefix itself reads as an address word (`em.` is the Hungarian floor
abbreviation) or as a state code. German capitalizes nouns, so a bare number before one
(`4096 Einträge`) is still kept: fail closed. The brand names typed `PERSON` (`Richter Gedeon`,
`Barclays`) are LAB-1346's.
