# Two more held-out sets, and a near-duplicate gate on training data (2026-10-28)

LAB-1392. v3 training will add more external data, so first we made sure we can tell when
training text overlaps a test set.

**Two new `test` sets** ([datasets.md](../datasets.md)), scored with rules and with fast mode
(rules + the published NER v2.0, weights `sha256:4a9a598f…`):

- **`pl-pii-bench`** (CC-BY-4.0, Anonimator). It is synthetic, and every document is fully
  annotated. We use 346 documents from five of its lanes, and they are committed. Polish is a
  language pii-guard has no language pack for and NER v2 never trained on.
- **`mapa-eur-lex`** (CC-BY-4.0). It holds two Advocate General opinions, each in 21 EU
  languages, including hu, cs, sk and ro. These are real EU court documents, so, like TAB,
  only the manifest is committed. The names are hand-labelled in English and LLM-projected
  in the other languages.

| Leak %, 95 % CI | rules | **fast (v2.0)** | Over-masking, fast | F1, fast |
|---|---:|---:|---:|---:|
| `pl-pii-bench` (346) | 84.1 | **17.5** (6.4–27.8) | 10.4 | 79.6 |
| `mapa-eur-lex` (42) | 99.3 | **8.5** (6.0–11.3) | 55.6 | 54.3 |

Run records: [`eval/results/runs/2026-10-28-datasets-pl-pii-bench-fast.json`](../../eval/results/runs/2026-10-28-datasets-pl-pii-bench-fast.json),
[`…-mapa-eur-lex-fast.json`](../../eval/results/runs/2026-10-28-datasets-mapa-eur-lex-fast.json)
(rules alongside). Per-language tables are in [benchmarks.md](../benchmarks.md).

- **Polish names carry over, Polish identifiers don't.** By lane, fast mode leaks 0.7 % of
  the inflected names (all seven cases), 0.5 % on the full documents and 0 % on addresses.
  On the `identifiers` lane it leaks **47 %** (141 of 300 values): PESEL, NIP, ID-card,
  passport and driving-licence numbers in Polish formats that no rule knows. 141 of the 144
  leaked values are there. On the `negative` lane, which has no gold spans, fast mode masks
  88 spans of same-shape numbers whose checksums fail. A Polish language pack with validators is the obvious
  next step.
- **MAPA is a names stressor that over-masks.** Leak is 8.5 % overall. hu, cs, sk and ro are
  at 2.9 / 5.4 / 0.0 / 2.9 %. English, Irish and Maltese are the worst, at 24.3 / 24.3 /
  25.7 % (Maltese F1 13 %), followed by Latvian and Lithuanian at 21.1 / 17.1 %. English is
  the only hand-labelled language, so its labels are probably the most complete. Over-masking
  is 55.6 %: more than half of what fast mode masks is not a scored name or employer. The set
  labels only names, employers and a few attributes, so part of this is label scope rather
  than error. We haven't broken it down yet. Rules alone mask nothing that is gold here.

**The gate.** [`training/ner/decontam.py`](../../training/ner/decontam.py) compares every
training and dev document with every evaluation text: every registry `test` set, and every
fixture under `eval/fixtures/` (the smoke sets among them). It uses MinHash/LSH over word
5-grams, then the exact Jaccard similarity, and drops a document at J ≥ 0.8 or on an equal
text hash. `train.py` runs it by default, fails closed when it finds no evaluation text, and
records the counts in `training_meta.json` ([evaluation.md](../evaluation.md#decontamination)).

**On the v2.0 mix: 0 dropped.** That is 0 of the 25,673 train and dev documents we could
rebuild ([report](../../eval/results/2026-10-28-decontam/README.md)). An exact brute-force
pass found that no training document comes closer than J = 0.164 to any evaluation document.
The OpenPII train rows are at most J = 0.154 from the OpenPII validation sample. So the
published v2.0 held-out numbers stand, with one gap stated plainly: the Muse-written
distillation corpus s13 (2,364 train rows and its dev rows, about 9 % of the training rows)
wasn't kept after training, so it couldn't be checked. v2.0's ai4privacy scores are still
in-distribution (same generator, different rows), as before.

- **OpenPII-1.5M wasn't checked.** The ticket suspected it contains our validation rows. Its
  card lists the license as "other", not CC-BY-4.0, so it is not a candidate for training
  here, and we didn't download it. If it is ever proposed, the gate checks it by default.
- **Cost:** $0. Everything ran on a local CPU. The downloads were the pinned public files:
  the OpenPII train split (3.7 GB, to rebuild the rows) and the two new sets.
