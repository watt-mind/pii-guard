# NER v3.1 candidates vs v2.0 (2026-10-28)

LAB-1410. Three XLM-R base candidates, trained on mixes that hold **no agent-traffic generator
document**, scored against the published `hdkiller/pii-guard-ner-xlmr-base` **v2.0** on one
commit. **Result: v2.0 stays.** Every candidate fails the smoke leak gate. Nothing was
published and the production default is unchanged.

## Protocol (fixed in the ticket before anything was trained or scored)

1. The agent-traffic generator split (train-only seed 1393, 1,800 documents) is removed from
   every mix, so **agent-traffic-dev** is unseen by every candidate, as it was for v2.0.
2. **Selection set, the only one used to choose:** agent-traffic-dev. Among candidates that
   pass every gate, the lowest leak wins, then the lower over-masking. A candidate must also
   beat v2.0 there (0.13 % leak / 1.84 % over-masking), or v2.0 stays.
3. **Gates, pass/fail only:** hu/en/de smoke leak ≤ v2.0 (0.0 %) and over-masking ≤ v2.0 +
   0.5 pp (≤ 1.59 %); hu-inflection leak ≤ v2.0 (2.0 %); CPU p95 ≤ 1.2× v2.0 in the same
   alternating run.
4. **Report-only:** agent-traffic test, cee-pii, pl-pii-bench, MAPA EUR-Lex, gretel-finance,
   nemotron-pii, ai4privacy. Never used to select or to pick an epoch.
5. **Epoch choice** on the training-loop dev split only (OpenPII dev + s11 dev; `train.py`
   keeps the epoch with the best dev F1).
6. **Candidates fixed: A, B, C.** None was added after a result was seen.
7. Decontamination: 0 near-duplicates (J ≥ 0.8) between any training/dev file and every eval
   set, dev splits included; max J against agent-traffic-dev < 0.5.

## Gates and selection

| Candidate | smoke leak ≤ 0.0 % | smoke over-mask ≤ 1.59 % | inflection leak ≤ 2.0 % | CPU p95 ≤ 1.2× | **agent-traffic-dev** leak / over-mask | Selected |
|---|--:|--:|--:|--:|--:|---|
| v2.0 (published) | 0.0 | 1.09 | 2.0 | 1.00× (58.4 ms) | 0.13 / 1.84 | **stays** |
| A: v3 mix − agent-traffic | **5.78 fail** | 1.18 pass | **4.0 fail** | 0.95× pass | 0.13 / 0.72 | no (2 gates) |
| B: A + hu/s11 gold, Privy ½ | **1.16 fail** | **1.67 fail** | 0.0 pass | 0.98× pass | 0.00 / 2.54 | no (2 gates) |
| C: B − Wismut | **2.89 fail** | 1.16 pass | **4.0 fail** | 0.96× pass | 0.13 / 5.11 | no (2 gates) |

No candidate passes every gate, so the selection set doesn't come into play. For the record:
none beats v2.0 on it either. B has the lowest leak (0.00 %) but more over-masking (2.54 vs
1.84 %).

## Report-only sets (rules + NER, fast mode, CPU)

Leak % / over-masking % / overlap F1. Run records:
`eval/results/runs/2026-10-28-lab-1410-<set>-<candidate>.json`; per-set summaries in
`summary-*.json`. Scored on a loaded machine (load average 19 to 38).

| set (docs) | v2.0 | A | B | C |
|---|--:|--:|--:|--:|
| agent-traffic test (990) | 0.23 / 1.65 / 0.964 | 0.21 / 0.87 / 0.967 | **0.04** / 3.06 / 0.937 | 0.14 / 5.39 / 0.928 |
| ai4privacy (600) | 0.37 / 1.27 / 0.985 | 1.05 / 0.41 / 0.984 | **0.23** / 0.55 / **0.988** | 0.32 / 0.50 / 0.984 |
| nemotron-pii (300) | 0.72 / 1.36 / 0.894 | 1.87 / 0.95 / 0.953 | 0.72 / 1.05 / **0.965** | 1.43 / 0.83 / 0.960 |
| cee-pii (451) | **0.40** / 26.4 / 0.826 | 2.18 / **19.5** / 0.857 | 0.79 / 25.3 / 0.830 | 0.79 / 23.3 / 0.838 |
| gretel-finance (400) | **19.0** / 22.6 / 0.714 | 21.6 / 19.1 / 0.740 | 21.8 / 21.4 / 0.735 | 21.6 / **17.2** / **0.747** |
| pl-pii-bench (346) | 17.5 / **10.4** / 0.796 | **5.2** / 17.3 / **0.872** | 5.5 / 18.6 / 0.817 | 9.0 / 13.6 / 0.838 |
| mapa-eur-lex (42) | **8.5** / 55.6 / 0.543 | 16.5 / 49.8 / 0.551 | 11.6 / **42.6** / **0.612** | 9.1 / 50.5 / 0.545 |

- **pl-pii-bench** leak falls from 17.5 to about 5 % in A and B (v3: 8.7 %). Removing Wismut
  (C) gives back some of it (9.0 %) and lowers pl over-masking 18.6 → 13.6 %, so Wismut is
  indeed behind part of the Polish over-masking.
- **MAPA** stays worse than v2.0 in every candidate (A 16.5, B 11.6, C 9.1 vs 8.5 %); B is
  the best of the three on F1.
- **gretel-finance** leak is about 21.7 % in all three (v2.0 19.0, v3 21.2): none of the
  changes touches it.
- **B over-masks agent-style text**: 3.06 % on agent-traffic test and 2.54 % on dev, against
  1.65 / 1.84 % for v2.0. C, without Wismut, doubles that again (5.4 %). The s11 oversampling
  and the extra OpenPII rows push it towards masking more.

## The v3 hu-smoke PERSON leak

The value v3 leaked is the very first word of a Hungarian chat message: a bare given name,
used to address the reader, with a comma and no greeting or surname before the request. The
name is also an everyday Hungarian noun. A synthetic stand-in with the same shape:

> **Hajnal**, felhívnád Fekete urat? a szama +36 30 765 4321, …

("Hajnal" is a given name and also the word for *dawn*.) Nothing in the context marks it as a
name. It is capitalised only because it opens the text, there is no "Szia" or "Kedves" in front
of it, and the word reads as a common noun. v2.0 finds it; v3 drops it. With a greeting
in front ("Szia Hajnal, …") v3 finds it, and a name that isn't also a noun in the same place
("Csilla, …") is found too. So v3 learned to lean on context cues for Hungarian names, and an
unmarked noun-like name at the start of a document falls below the threshold.

| model | the fixture value (hu-smoke) | stand-in "Hajnal, …" (full message) | "Szia Hajnal, …" |
|---|---|---|---|
| v2.0 | found | found | found |
| v3 XLM-R base | **leaked** | missed | found |
| v3.1 A | **leaked** | found | found |
| v3.1 B | **fixed** | found | found |
| v3.1 C | **leaked** | found | found |

The stand-in is a weaker probe than the fixture: A and C find "Hajnal, …" and still drop the
fixture value. Only B, the candidate with twice the Hungarian OpenPII gold and more s11, gets the fixture
value back, which fits the explanation. B still fails the smoke gate on two other values: a
hu date of birth and a German genitive name (`de-genitive-0005`), both of which A and C leak
too. A, picked at epoch 1 by the dev split, leaks seven more smoke names than B.

## CPU latency

[`latency-cpu.json`](latency-cpu.json): 122 messages of about 380 characters (hu + en synth
samples). The four models run in one process, alternating per message, NER only, 8 torch
threads, Apple M-series, load average 19 to 38. All four have the same architecture.

| Model | p50 | p95 | p95 vs v2.0 |
|---|--:|--:|--:|
| v2.0 | 45.5 ms | 58.4 ms | 1.00× |
| A | 45.5 ms | 55.7 ms | 0.95× |
| B | 45.7 ms | 57.2 ms | 0.98× |
| C | 45.4 ms | 56.1 ms | 0.96× |

## Data

Manifests: [`training/ner/v31-data-manifest.json`](../../../training/ner/v31-data-manifest.json)
(per candidate: every file with counts, id hashes and XLM-R tokens, and the share per source),
[`v31-raw-data-manifest.json`](../../../training/ner/v31-raw-data-manifest.json) (pinned
revisions, file hashes, licences) and
[`v31-openpii-train-manifest.json`](../../../training/ner/v31-openpii-train-manifest.json). No
rows are committed. Every file except the four new derivations has the same id hash as the v3
file it replaces.

| Source | A docs (share) | B docs (share) | C docs (share) |
|---|--:|--:|--:|
| OpenPII-1M train (CC-BY-4.0) | 30,000 (37.8 %) | 35,000 (41.7 %) | 35,000 (48.3 %) |
| Privy (MIT) | 12,000 (19.6 %) | 6,000 (9.4 %) | 6,000 (10.8 %) |
| s11 distillation corpus (Apache-2.0) | 4,223 (17.0 %) | 6,335 (24.3 %) | 6,335 (28.1 %) |
| Wismut nym-pii (MIT) | 13,000 (14.1 %) | 13,000 (13.5 %) | — |
| Nemotron-PII train (CC-BY-4.0) | 1,500 (5.0 %) | 1,500 (4.8 %) | 1,500 (5.6 %) |
| v2 hard negatives (Apache-2.0) | 6,000 (4.1 %) | 6,000 (4.0 %) | 6,000 (4.6 %) |
| Gretel train (Apache-2.0) | 2,500 (2.3 %) | 2,500 (2.2 %) | 2,500 (2.6 %) |
| agent-traffic generator | **0** | **0** | **0** |
| **total** | 69,223 / 7.11 M tokens | 70,335 / 7.42 M | 57,335 / 6.41 M |

How B's changes were made (`training/ner/v31_data.py`):

- **OpenPII hu ×2:** the OpenPII sampler was re-run with hu = 10,000 train rows. Its seeded
  order makes those **new** rows a superset of v3's 5,000 (A's hu file is the first 5,000 and
  has v3's id hash). The dev rows are the same.
- **s11 ×1.5:** every s11 train document once, plus a seeded half (seed 1410) a second time,
  with `~rep1` ids. 2,104 → 3,156 hu and 2,119 → 3,179 en.
- **Privy halved:** the first 6,000 of the 12,000 audited documents, i.e. what the sampler
  picks for 6,000, with their teacher-ignore regions.

**Teacher.** Only `Horizon-Labs/pii-redactor-base` @ `42dfb0d`, on English and German text,
and only to add loss-ignore regions ([`teacher-audit.json`](teacher-audit.json)): 19,653 in
Privy, 5,163 in Wismut en/de, 242 in Nemotron, 479 in Gretel (v3: 19,629 / 5,146 / 241 / 483;
the small differences are bf16 GPU nondeterminism). bardsai v3 is not used. SECRET, URL and IP
stay with the rules; no GDPR special category is taught. No FineWeb-2 (ADR 0005), no CC-BY-SA,
NC or gated data.

**Decontamination.** [`decontam-gate.json`](decontam-gate.json) gated all 93,199 derived
documents; [`decontam-v31-a.json`](decontam-v31-a.json), [`-b`](decontam-v31-b.json) and
[`-c`](decontam-v31-c.json) gate each candidate's train + dev files against 17 eval sets
(every registry test set, **agent-traffic-dev**, MAPA by text, every `eval/fixtures` file).
`train.py` ran the gate again on Modal.

| Candidate | train + dev docs | exact / near (J ≥ 0.8) dropped | max J vs agent-traffic-dev |
|---|--:|--:|--:|
| A | 70,864 | 0 / 0 | 0.024 |
| B | 71,976 | 0 / 0 | 0.024 |
| C | 58,976 | 0 / 0 | 0.024 |

(v3, with the generator split: 0.42.) The max J is exhaustive (`decontam.max_jaccard`: every
pair that shares a word 5-gram is scored exactly), not LSH. The TAB fixture is not on disk, so
TAB is compared by its manifest hashes only, as in v3.

## Training and compute

`training/distill/modal_train.py`, one A10G each, 3 epochs, the v3 recipe (lr 5e-5, warmup
0.1, bf16, batch 16, 512 tokens, stride 128, seed 13). Only the best epoch is written
(`save_epochs = false`). `training_meta-v31-*.json` hold the per-epoch dev scores.

| Candidate | dev F1 overlap / exact per epoch | epoch picked | minutes |
|---|---|--:|--:|
| A | 0.976 / 0.938, 0.966 / 0.932, 0.973 / 0.940 | 1 | 21.8 |
| B | 0.960 / 0.925, 0.966 / 0.932, 0.974 / 0.943 | 3 | 22.6 |
| C | 0.967 / 0.932, 0.957 / 0.924, 0.965 / 0.933 | 1 | 18.8 |

**Compute: 1.10 A10G-hours, $1.32 of Modal free credit** (cap $10): $0.05 for data prep and
the teacher audit, $1.26 for the three trainings (Modal billing report). Every app is stopped.

## Reproduce

```
modal run training/ner/modal_v3.py --profile v31          # prep + Horizon teacher audit
modal volume get pii-guard-ner-runs v31-data <raw>
uv run --no-sync python training/ner/v31_data.py derive --raw <raw>/v31-data \
    --json eval/results/2026-10-28-ner-v31/decontam-gate.json
uv run --no-sync python training/ner/v31_data.py manifest
uv run --no-sync python -m pii_guard.eval.datasets fetch mapa-eur-lex   # after training
uv run --no-sync python training/ner/v31_data.py decontam --out eval/results/2026-10-28-ner-v31
modal run training/distill/modal_train.py --config training/ner/v31-a.toml --gpu A10G   # b, c
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/eval_v3.py score --ticket LAB-1410 \
    --candidate v31-a --model models/ner/pii-guard-ner-xlmr-base-v31-a --record   # v20: no --model
uv run --no-sync python training/ner/eval_v3.py latency --model v20= --model v31-a=... ...
```

MAPA is fetched after the training jobs are launched, so its court text never goes into a
Modal image (`modal_train.py` uploads `data/datasets/fixtures` when it exists).

## Next

A second round needs a new ticket. What this one shows:

- More Hungarian gold (B) fixes the noun-like Hungarian name and the inflection leak, but it
  doesn't fix the German genitive name or the hu date of birth, and it adds over-masking on
  agent text.
- The training-loop dev split doesn't track the smoke sets: it picked epoch 1 for A, and that
  epoch leaks 5.8 % on smoke.
