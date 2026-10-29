# Fast mode reads spelled-out values and `[at]` e-mails: perturbed leak 13.7 → 0.3 % (2026-10-28)

LAB-1297, found during LAB-1226. **Fast mode leaked 118 of the 859 perturbed values (13.7 %)
of the `agent-traffic` test split, against 2.4 % for PrivAiTe.** Broken down by perturbation
kind, the folding of zero-width characters and lookalike letters already worked on every path
(2 of 496 leaked, none of the 35 names split over a line). Three kinds caused nearly all of it,
and the normaliser undid none of them: a value spelled out one character at a time
(`D E 6 3 1 4 ...`: 67 of 126 leaked), an e-mail written with `[at]` and `[dot]` (36 of 75), and
an identifier regrouped in threes with dots (`GB5.4PZ.JT7.994...`: 13 of 127). A model reading
the request reads all three as the plain value.

- **The fix.** `normalize_for_detection` now reads them as the plain value before any detector
  runs, with the offset map pointing back over the whole obfuscated value, so the mask covers
  it all. A bracketed `at` (`[at]`, `(at)`, `{at}`) and `dot` (also `punkt`, `pont`) stand for
  `@` and `.` only when the whole reads as an address. A run of single characters needs six
  digits in it. Dotted threes need six digits, and amounts, IPv4 addresses and dates are left
  alone. Plain text keeps the fast path.
- **Tuned on the dev split only** (`agent-traffic-dev`, seed 61226); the test split was run
  once before and once after.

`agent-traffic` (990 documents, hu/en/de), fast mode with NER v2 base + hard negatives, from
[before](../../eval/datasets/results/2026-10-27-datasets-agent-traffic-fast.json) to
[after](../../eval/datasets/results/2026-10-28-datasets-agent-traffic-fast.json):

| | before | after |
| -- | -- | -- |
| Perturbed values leaked | 118 / 859 (13.7 %) | 3 / 859 (0.3 %) |
| — spaced digits | 67 / 126 | 1 / 126 |
| — leetspeak e-mail | 36 / 75 | 0 / 75 |
| — dotted digits | 13 / 127 | 2 / 127 |
| — zero-width, homoglyph, line break | 2 / 531 | 0 / 531 |
| Invalid-checksum identifiers leaked | 8.5 % | 0.0 % |
| All values leaked | 2.6 % | 0.2 % |
| Recall / precision | 94.8 / 82.6 % | 97.3 / 82.2 % |
| Over-masking | 14.0 % | 14.4 % |

On the dev split, perturbed leak went from 8.8 % to 0.4 % (25 → 1 of 285). The smoke and
uncued-number sets give identical results (over-masking 7.6 %): no text in them changes. Of
the 2,006 texts in the other eval fixtures, 5 change, and each is an obfuscated phone or
identifier. The over-masking rise is all in the 246 test documents whose text changed. Once a
CSV row reads normally, the NER also tags the order numbers and amounts next to the value it
now finds. That is a precision gap of the NER on numeric columns, not a new false fold.

- **Cost:** $0.
