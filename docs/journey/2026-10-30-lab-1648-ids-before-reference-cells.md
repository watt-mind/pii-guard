# IDs before an order-number cell are masked again (2026-10-30)

LAB-1648, found while LAB-1597 re-recorded agent-traffic. Fast-mode leak on agent-traffic
(test) rose from 12 to 16 of 5,155 values (0.23 → 0.31 %) between the 10-28 record and
`develop`. All of the rise was in en/de. Local CPU only. A sweep of the 41 detector merges since
the 10-28 record (`13666bf`) found which spans changed:

| merge | spans that start leaking | spans that stop |
| -- | -- | -- |
| LAB-1433 (#205): a bare TAJ only in Hungarian text | en-0091 `ids.national` | |
| LAB-1258 (#313): NER sees CSV cells | en-0174, en-0264, en-0273, en-0291, de-0237 | en-0210 (one) |
| LAB-1476 batch (#303) | | en-0003 |

**Cause.** LAB-1258 turns a `,` or `;` that comes straight before a capital letter into a space
in the text the model reads, so `2,Teszt Elek` reaches the model as two cells. The test
covered names. It did not cover the reference cells in the agent-traffic CSVs, which also
start with a capital: `…,610456508,ORD-2026-481850,…` and `…,14500209637,SO9016764,…`. The
model then saw `686276120 ORD-2024-544367` as one order-number phrase and dropped the national
ID. All five new leaks are the `national_id` cell right before an `ORD-` or `SO` cell.

**Fix** ([`detect/ner.py`](../../src/pii_guard/detect/ner.py), `model_view`). A delimiter
counts as a cell boundary only when a capitalized word follows it. That means a capital
followed by a lower-case letter (`Teszt`, `Ádám`), an apostrophe (`O'Brien`) or an initial's
period (`J. Smith`). An all-caps reference cell stays glued, as it was before LAB-1258.

Fast mode (rules + NER v2.0). Before is `develop` `f7f9d90` (the LAB-1597 records); after is
this branch, re-recorded as
[`2026-10-30-datasets-agent-traffic-fast`](../../eval/results/runs/2026-10-30-datasets-agent-traffic-fast.json)
and [`-dev-fast`](../../eval/results/runs/2026-10-30-datasets-agent-traffic-dev-fast.json):

| set | leak | over-masking | recall (overlap, spans) | F1 overlap |
| -- | --: | --: | --: | --: |
| agent-traffic (990) | 16 → 13 of 5,155 (0.31 → 0.25 %) | 78 → 74 (1.40 → 1.33 %) | 5,469 → 5,476 of 5,587 | 97.0 → 97.1 % |
| agent-traffic-dev (300) | 2 → 2 of 1,555 | 28 → 26 (1.66 → 1.55 %) | 1,662 → 1,661 of 1,687 | 97.4 → 97.4 % |
| agent-text (hu/en/de) | 0/126 → 0/126 | 0/132 → 0/132 | 132/132 → 132/132 | |
| smoke (hu/en/de/pl) | 0/216 → 0/216 | 2/229 → 2/229 | 228/241 → 228/241 | |
| hu-inflection, synth-sample, negative | unchanged | unchanged | unchanged | |

The LAB-1258 names (`Teszt Elek`, `Max Mustermann` in `customers.csv`) are still found
whole: agent-text doesn't move.

**Not fixed: en-0091, 13 vs 12 on 10-28.** `"ids": {"national": "109435909"}` was masked on
10-28 only because the Hungarian bare-TAJ rule fired in English text and the number happened to
pass its mod-10 check (one nine-digit number in ten does). LAB-1433 limited that rule to
Hungarian on purpose, for precision. The NER doesn't propose the value, and no English cue
matches a bare `national` key. A JSON-key cue for nested `ids.*` objects is a separate change:
LAB-1649.

Cost: $0, all local.
