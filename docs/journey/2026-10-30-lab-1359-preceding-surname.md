# A surname before a tagged given name joins the mask (2026-10-30)

LAB-1359, found measuring LAB-1338. **Before:** the NER model sometimes tagged only the given
name and left out a surname that is also an everyday word, so the surname went upstream next
to the placeholder: `Fekete [[PERSON_x]]ért`. On the fictional probe this looked large (41 of
220 values partly leaked, `Próba [[PERSON_x]]`, `Teszt [[PERSON_x]]`), so the first step was
to tell a probe artefact from a real miss: the probe now also scores `probe-real`, the same
220 values over five real surnames that are everyday words (Kovács, Szabó, Molnár, Fekete,
Takács). **The fictional numbers are mostly an artefact:** with real surnames, 1 value was
partly leaked and 3 whole (all `Fekete` + an inflected given name). **After: 0 partial** on
`probe-real` and on agent-traffic-dev (1 -> 0), with no change to over-masking or precision on
any set.

- **Fix.** `detect/ner_words.py`: a `PERSON` span directly after a capitalised word from the
  pack's `surnames` lexicon, with one space between, starts at that word. A hyphenated double
  surname joins whole. A lowercase word (`a fekete ló`), a word outside the lexicon, or one
  across punctuation or a line break stays outside; a pack with no `surnames` lexicon (English,
  German) gets no join. Only `PERSON` spans take a surname, so a company keeps its own edges.
- **Not fixed here.** The fictional test surnames (`Teszt`, `Próba`, `Gyakorló`, `Minta`) are
  not in the lexicon, on purpose (ADR 0005): their partial leaks stay, as probe artefacts.
  The 3 whole misses on `probe-real` have no span to extend; they need training examples.

Fast mode (rules + NER, published `watt-mind/pii-guard-ner-xlmr-base@95f612a9ad65`), same
commit with the join off and on. Counts are in
[before.json](../../eval/results/2026-10-30-ner-preceding-surname/before.json) and
[after.json](../../eval/results/2026-10-30-ner-preceding-surname/after.json), from
`scripts/probe_ner_subword.py`.

| set (split) | partial leak | leak | over-masking | precision | recall |
| -- | -- | -- | -- | -- | -- |
| probe, fictional (dev) | 41 -> 41 | 4.55 -> 4.55 % | 0.0 -> 0.0 % | 100.0 -> 100.0 % | 95.45 -> 95.45 % |
| probe-real (dev) | 1 -> 0 | 1.36 -> 1.36 % | 0.0 -> 0.0 % | 100.0 -> 100.0 % | 98.64 -> 98.64 % |
| hu-inflection (dev) | 15 -> 15 | 2.0 -> 2.0 % | 0.0 -> 0.0 % | 100.0 -> 100.0 % | 93.44 -> 93.44 % |
| hu-smoke (dev) | 1 -> 1 | 0.0 -> 0.0 % | 0.88 -> 0.88 % | 95.0 -> 95.0 % | 94.17 -> 94.17 % |
| agent-traffic-dev (dev) | 1 -> 0 | 0.13 -> 0.13 % | 1.66 -> 1.66 % | 96.17 -> 96.17 % | 98.22 -> 98.22 % |
| cee-pii (test) | 0 -> 0 | 0.40 -> 0.40 % | 26.38 -> 26.38 % | 71.87 -> 71.87 % | 97.22 -> 97.22 % |
| ai4privacy (test) | 2 -> 2 | 2.43 -> 2.43 % | 1.21 -> 1.21 % | 98.05 -> 98.05 % | 96.89 -> 96.89 % |
