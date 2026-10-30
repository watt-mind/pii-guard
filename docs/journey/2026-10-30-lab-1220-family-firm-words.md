# "és Fia" in a firm name is no longer masked as a person (2026-10-30)

LAB-1220, found in the NER v2 work (LAB-1150). In `Balogh és Fia Kkt.` ("Balogh and Son")
and `Szabó és Fiai Kkt.`, the published NER (v2.0) tagged `Fia` / `Fiai` as `PERSON`. That is
four over-masked spans on `hu-company-names`. The LAB-1149 company rule already masks the
member's surname (`Balogh`), so the family word only cost readability. A retrain with
street and firm hard negatives fixed this inside v2.1 (LAB-1306), but v2.1 was not adopted.

The NER guard now drops a `PERSON` hit that is only the family word of a firm name (`Fia`,
`Fiai`, `Lánya`, `Társa`, ...). It must have a connector before it (`és`, `&`) and a
Hungarian legal form after it (`Kkt.`, `Bt.`, `Kft.`, an office). The surname hit stays
([tests](../../tests/detect/test_ner_context.py), `TestFamilyFirmWords`). No retrain was
needed.

Fast mode (rules + NER v2.0), before → after:

| set | over-masking, % | leak, % |
| -- | --: | --: |
| hu-company-names | 5.71 → **0.00** (4 of 70 → 0 of 66) | 0.0 → 0.0 |
| hu-smoke / en-smoke / de-smoke | 0.88 / 3.03 / 0.00, unchanged | 0.0, unchanged |
| en / de / hu ai4privacy | 1.14 / 1.89 / 0.68, unchanged | 2.5 / 1.0 / 3.6, unchanged |
| agent-traffic-dev (300 docs) | 28 of 1,683, unchanged | 2 of 1,555, unchanged |

- The street half of LAB-1220 is not fixed here. `Bishop Street` alone is tagged `ADDRESS` on
  en-smoke, and that one span puts it at 3.0 %. A guard rule can't fix it without a leak:
  the ai4privacy gold marks 44 digitless lone streets as `ADDRESS` (`Boulder Road`,
  `Warborne Lane valley`), and the policy says those are not addresses. That needs a
  decision or a retrain, so it moved to LAB-1602.
- Cost: $0, all local.
