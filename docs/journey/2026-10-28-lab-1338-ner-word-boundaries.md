# Name spans start and end on whole words (2026-10-28)

LAB-1338, found during LAB-1174. **Before:** the NER model labels sub-word tokens, and it
sometimes returned a name span that starts or ends inside a word: `szt` in `Teszt Eleknek`,
`hamér` in `Tihamérért`, `ló Hajnának` in `Gyakorló Hajnának`. The vault masked only that
fragment, so the rest of the word went upstream in clear text: `Te[[PERSON_x]] Eleknek`,
`Gyakor[[PERSON_x]]nak`. In a fictional probe of 220 names (5 surnames x 20 given names with
a case ending and 24 without, one short sentence each), **12 values were cut by a mask
edge**. **After: 0.** Leak and recall do not move on any set; over-masking only drops (cee-pii 27.86 -> 27.75 %).

- **Fix.** `detect/ner_words.py` snaps every `PERSON`, `ORGANIZATION` and `ADDRESS` span in
  the NER detector before it leaves the detector. A span that starts inside a word starts at
  the word's start. An end inside a word stays only where the language pack reads the rest of
  the word as a case ending after exactly that stem (`Minta Péter|t`: token aggregation
  exists for this). Otherwise the span ends at the end of the word, so it never masks less
  than the model did. Same-type spans that then overlap are merged. Numbers and other
  structured types keep the model's boundaries (LAB-1293 checks those).
- **How it composes with the suffix trim.** A span extended to the end of an inflected word
  (`szt Pirosk` -> `Teszt Piroskáról`) is then a name found whole, so the pipeline's suffix
  trim (LAB-1174) ends it at its stem where that is confident (`Teszt Piroská|ról`), and the
  vault keys the lemma, as for any other whole-word span. The snap doesn't guess a stem
  itself: a weak reading such as `Kelem` + `en` would cut the name.
- **Tried and dropped.** Ending a span at the shortest stem longer than the model's end.
  On `Teszt Kel|emen` it picked `Kelem` + `en`, which cuts the name `Kelemen`.

Fast mode (rules + NER, published `hdkiller/pii-guard-ner-xlmr-base@95f612a9ad65`), same
commit with the snap off and on. Counts are in
[before.json](../../eval/results/2026-10-28-ner-word-boundaries/before.json) and
[after.json](../../eval/results/2026-10-28-ner-word-boundaries/after.json), from
`scripts/probe_ner_subword.py`. Tuned on the dev sets; the test splits were run once, at the
end.

| set (split) | values cut | sub-word NER spans | leak | over-masking | recall |
| -- | -- | -- | -- | -- | -- |
| probe (dev) | 12 -> 0 | 12 -> 0 | 4.55 -> 4.55 % | 0.0 -> 0.0 % | 95.45 -> 95.45 % |
| hu-inflection (dev) | 0 -> 0 | 0 -> 0 | 3.33 -> 3.33 % | 0.0 -> 0.0 % | 88.89 -> 88.89 % |
| hu-smoke (dev) | 1 -> 0 | 2 -> 0 | 0.0 -> 0.0 % | 0.88 -> 0.88 % | 92.5 -> 92.5 % |
| agent-traffic-dev (dev) | 0 -> 0 | 6 -> 0 | 0.13 -> 0.13 % | 2.16 -> 2.16 % | 97.75 -> 97.75 % |
| cee-pii (test) | 1 -> 0 | 12 -> 0 | 0.40 -> 0.40 % | 27.86 -> 27.75 % | 97.22 -> 97.22 % |
| ai4privacy (test) | 1 -> 0 | 5 -> 0 | 0.37 -> 0.37 % | 1.41 -> 1.41 % | 98.95 -> 98.95 % |

"Values cut" counts the gold names, organisations and addresses with a word that a mask
edge splits, a case ending after a stem excepted. Leak counts values that survive whole, so
it doesn't see a fragment: `Te` is not the name. That is why it doesn't move.

- **What's left on the probe.** The probe still leaks 4.55 % of values whole and 23.2 % at
  least in part. These are not fragments. The model leaves out a surname that is also a
  common word (`Teszt`, `Próba`, `Gyakorló`: "test", "trial", "practice") or misses the name
  altogether (`Gyakorló Eleknek`). Filed as a follow-up.
- **Cost:** $0, offline, no model change.
