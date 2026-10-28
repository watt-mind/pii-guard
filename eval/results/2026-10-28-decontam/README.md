# Decontamination of the NER v2.0 training mix (2026-10-28)

LAB-1392. [`v2.0-training-mix.json`](v2.0-training-mix.json) is the report of
[`training/ner/decontam.py`](../../../training/ner/decontam.py) on the train and dev files of
[`training/ner/v2-base-hn.toml`](../../../training/ner/v2-base-hn.toml). That config trained the
published `hdkiller/pii-guard-ner-xlmr-base` v2.0, weights `sha256:4a9a598f…`. The report
holds counts and ids only, no text.

```
uv run --no-sync python training/ner/decontam.py --config training/ner/v2-base-hn.toml \
  --allow-missing --json eval/results/2026-10-28-decontam/v2.0-training-mix.json
```

**Result: 0 of 25,673 documents dropped.** No document is exact or near-duplicate (word
5-gram Jaccard ≥ 0.8) of any of the 3,416 evaluation documents. Those are every `test` set of
the registry and every fixture under `eval/fixtures/`; TAB is compared by its manifest hashes
only. An exact brute-force pass over every pair of training and evaluation documents
(an inverted index over shingles, not LSH) found a highest similarity of **J = 0.164**. That
is a distillation document against `en-synth-sample`, the same generator's committed sample.
The closest OpenPII train row to the OpenPII validation sample is at J = 0.154. 25,601
documents are below 0.1, and the other 72 are below 0.2.

| Training file (v2-base-hn.toml) | Documents | Dropped | Rebuilt how |
| -- | --: | --: | -- |
| distill-s11 hu / en train | 2,104 / 2,119 | 0 / 0 | the generated files, byte-identical to the run's recorded SHA-256 |
| OpenPII-1M train hu / en / de | 5,000 each | 0 | `training/ner/openpii.py` from the pinned file; `--check` matches the committed manifest (same uids) |
| OpenPII-1M dev hu / en / de | 150 each | 0 | as above |
| hard negatives hu / en / de | 2,000 each | 0 | `training/ner/negatives.py --n 2000 --seed 1150` |
| **distill-s13 hu / en train and dev** | 2,364 train + dev | **not checked** | not kept after training (Muse Glimmer output, not reproducible from a seed) |

What this does and doesn't show:

- **The published v2.0 held-out numbers stand.** None of the rebuilt 25,673 documents copies
  or lightly edits an evaluation text. They include 25,223 of the 27,587 training rows (91 %);
  the other 450 are OpenPII dev rows.
- **s13 is the gap.** It was written by Muse Glimmer from the lexicon packs. It is the same
  family of generator as `hu-synth-sample` / `en-synth-sample` (the s11 maximum is J = 0.16),
  so a copy of an evaluation text is unlikely, but it is unverified. The next training run
  gates every file by default, so the gap won't come back.
- **Bytes.** The rebuilt OpenPII and negative files have the same rows: the OpenPII manifest's
  uid hash matches. But their SHA-256 prefixes differ from the ones in the run's
  `training_meta.json`, and only distill-s11 matches byte for byte. We didn't find why. The
  documents compared are those rows; if they differ from the ones the run saw, only the
  serialisation does.
- **Same distribution is not contamination.** v2.0 trained on OpenPII *train* rows, so the
  ai4privacy numbers are still in-distribution, as the model card says. The gate checks for
  copied text, not for a shared generator.
