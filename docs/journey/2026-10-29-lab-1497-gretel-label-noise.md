# Gretel finance leak is mostly label noise: 19.1 % → 2.4 % on corrected labels (2026-10-29)

LAB-1497 and LAB-1511. **Before:** every NER version leaked 19–22 % on Gretel finance, and the
site lists it as the set where PII Guard is weakest (v2.0 19.0 % against Presidio's 18.8 %).
LAB-1494's error mining said most of those "missed names" weren't names. **After:** the gold is
corrected in a committed, reviewable file, a separate set is scored, and both numbers are
published. No model was trained or changed; the upstream set and its rows stay as they are.

- **What was wrong.** Reading every distinct gold value of the test sample (never a model's
  output): 178 of 1,710 gold spans aren't personal data. German salutations and set phrases
  (`Damen`, `Herren`, `Im Rahmen`: 74), common nouns (`Saldo`, `Stahl`: 46), "your + noun"
  phrases (`Ihr Vertrauen`: 26), template slots (`[Buyer's Name]`, `[Address]`: 17), role words
  (`Schuldner`, `Valued Customer`: 11) and codes (`123456789`: 4). `PERSON` gold goes from 694
  to 524.
- **How it is corrected.**
  [`corrections.json`](../../eval/datasets/gretel-finance/corrections.json) lists each class
  with its rationale and exact texts;
  [`datasets/corrections.py`](../../src/pii_guard/eval/datasets/corrections.py) builds
  `gretel-finance-corrected`, where those spans are ignore regions: no system is credited or
  charged for them. Placeholder names used as names (`Max Mustermann`) and address parts
  labelled `PERSON` are kept as gold.
- **Same predictions, two label sets.** One v2.0 run scored against both
  ([audit](../../eval/results/2026-10-29-lab-1497-label-audit/README.md)):
  leak **19.07 % → 2.44 %** (German 29.1 → 2.3 %, English 5.1 → 2.6 %), names leaked 162/516
  → 6/357, F1 0.717 → 0.758, over-masking unchanged (21.8 %). 161 of the 180 upstream leaks
  were corrected values.
- **Every system re-scored on the corrected files** (17 systems, clean commit): v2.0 alone
  20.3 → 4.1 %, rules + Wismut 21.8 → 5.8 %, rules + bardsai v3 23.3 → 7.5 %, PrivAiTe 27.7 →
  13.2 %, Presidio 18.8 → 14.8 %, LLM Guard 59.3 → 51.3 %, rules 80.8 → 77.1 %. PII Guard fast
  now has the lowest leak of all 17; Presidio gains least because it masks almost everything.
- **MAPA EUR-Lex needs no correction.** The role words LAB-1494 found were in the MAPA
  *validation* split. On the test set none of the gold names is a role word, and 41 of v2.0's
  63 leaked values are the same string labelled a name in 6+ of the 21 language versions:
  real names. Its 8.5 % leak stays as published.
- **Cost:** $0, local CPU.
