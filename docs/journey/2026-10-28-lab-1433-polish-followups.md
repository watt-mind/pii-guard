# Polish pack follow-ups: shared order words, a Hungarian-only bare TAJ (2026-10-28)

LAB-1433, the follow-ups found while building the `pl` pack (LAB-1400). Four small fixes:
Polish order, invoice and shipment words in the two shared lexicons that tell a business
number from personal data (the NER number check and `reference_or_amount_before`), `numer` no
longer a cue word on its own, a TAJ number without its label matched in Hungarian text only,
and a cue date guard that needs a real month and day, so a driving-licence number like
`05936/42/00` is masked after `prawo jazdy`
([results](../../eval/results/2026-10-28-lab-1433-pl-followups/README.md)).

| | before | after |
| -- | --: | --: |
| pl-pii-bench, fast: leak / `negative` over-masked | 3.5 % / 117 | 3.5 % / 117 |
| Polish synthetic dev split (in-sample), fast: leak / over-masked | 4 / 71 | **0 / 6** |
| ai4privacy, rules: leak | 63.07 % | **62.93 %** |
| gretel-finance, rules: over-masked spans | 65 | **59** |

- **pl-pii-bench did not move.** None of its lanes holds these cases. Its 117 over-masked
  `negative` spans are mostly NER bank accounts (59) and the cue rule masking labeled numbers
  with a bad check digit (34), which is policy (LAB-1400).
- **The dev split is in-sample.** Its 80 documents were written for these fixes
  ([generator](../../eval/results/2026-10-28-lab-1433-pl-followups/pl_dev_split.py)): it shows
  that they work, not how far they generalize.
- **Other languages only gained.** The unlabeled TAJ no longer fires on English and German
  numbers (6 over-masks fewer on gretel-finance), and with the new date guard 3 more cued phone
  numbers are masked on ai4privacy. Every hu/en/de smoke, synth-sample and negative
  set gives the same counts; `make gate` passes
  ([run records](../../eval/results/runs/2026-10-28-lab-1433-ai4privacy-rules-after.json)).
- **Cost:** $0. Everything ran on a local CPU.
