# A lexicon surname and given name are masked without a model span (2026-10-30)

LAB-1606, found on LAB-1359. **Before:** fast mode sent three of the 220 `probe-real` names
upstream whole, all a surname that is also an everyday word with an inflected given name
(`Fekete Piroskáról`, `Fekete Bélát`). The NER model emitted no span at all, so LAB-1359's
join, which extends an existing `PERSON` span, had nothing to extend.

- **Fix.** `detect/ner_words.py`: a capitalised word from the pack's `surnames` lexicon, one
  space, then a capitalised word the pack reads as a lexicon given name, bare or with a case
  ending, is a `PERSON` span even when the model tagged nothing there. A second given name
  and a hyphenated double surname join. It stays out when a street type follows
  (`Kossuth Lajos utca`), when a model span of the text types already overlaps it, or for a
  pack without these lexicons (English, German). The suffix trim then ends the span at the
  stem, as for any whole name.
- **Not fixed here: 1 of 220 left.** `Fekete Eleknek` stays a whole miss: `Elek` is not in
  the hand-curated given-name lexicon, so the rule does not fire, on purpose (only the
  lexicon decides). The model-side fix, hard positives with common-word surnames and
  inflected given names, goes into the next NER data round (LAB-1625). No model was trained.

Fast mode (rules + NER v2.0), `develop` `890a6f6` against this branch. Counts are in
[before.json](../../eval/results/2026-10-30-lab-1606-surname-given/before.json),
[after.json](../../eval/results/2026-10-30-lab-1606-surname-given/after.json) and
[other-hu-sets.json](../../eval/results/2026-10-30-lab-1606-surname-given/other-hu-sets.json).

| set (split) | leak (whole) | over-masking | precision | recall |
| -- | -- | -- | -- | -- |
| probe-real (dev) | 3 -> 1 (1.36 -> 0.45 %) | 0.0 -> 0.0 % | 100.0 -> 100.0 % | 98.64 -> 99.55 % |
| probe, fictional (dev) | 10 -> 10 | 0.0 -> 0.0 % | 100.0 -> 100.0 % | 95.45 -> 95.45 % |
| hu-inflection (dev) | 1 -> 1 | 0.0 -> 0.0 % | 100.0 -> 100.0 % | 93.44 -> 93.44 % |
| hu-smoke (dev) | 0 -> 0 | 0.88 -> 0.88 % | 94.17 -> 94.17 % | 93.33 -> 93.33 % |
| agent-traffic-dev (dev) | 2 -> 2 | 1.66 -> 1.66 % | 96.35 -> 96.35 % | 98.52 -> 98.52 % |
| cee-pii (test) | 2 -> 2 | 12.44 -> 12.44 % | 85.49 -> 85.49 % | 97.22 -> 97.22 % |
| ai4privacy (test) | 8 -> 8 | 0.37 -> 0.37 % | 98.9 -> 98.9 % | 98.95 -> 98.95 % |

The other Hungarian fixtures (company names, agent text, brand names, uncued numbers,
injection, synth sample) did not change. No headline set moved, so the run records and the
hosted proof numbers stay as they are.
