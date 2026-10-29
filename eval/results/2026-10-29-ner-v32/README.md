# NER v3.2 candidates vs v2.0 (2026-10-29)

LAB-1494. Two cheap, targeted attempts to beat the published v2.0
(`watt-mind/pii-guard-ner-xlmr-base@95f612a9`): a weight average (soup) of v2.0 and the v3.1
candidate B, then error-mined targeted data. Freeze: 2026-11-01.

## Protocol (fixed and committed before any candidate was built, trained or scored)

The v3.1 protocol (LAB-1410), unchanged, with the v2.0 reference re-scored on this commit.

1. **Selection set, the only one used to choose:** agent-traffic-dev (unseen by every
   candidate: no agent-traffic generator document is in any mix, and error mining never reads
   it). A candidate must pass every gate and **beat v2.0** there: leak ≤ v2.0 *and*
   over-masking ≤ v2.0, at least one strictly lower. Among those, the lowest leak wins, then
   the lower over-masking, then the earlier candidate in the list below.
2. **Gates, pass/fail only**, against v2.0 scored on the same commit: hu/en/de smoke leak ≤
   v2.0 and smoke over-masking ≤ v2.0 + 0.5 pp; hu-inflection leak ≤ v2.0; CPU p95 ≤ 1.2×
   v2.0 in one alternating latency run.
3. **Report-only:** agent-traffic test, ai4privacy, nemotron-pii, cee-pii, gretel-finance,
   pl-pii-bench, MAPA EUR-Lex. Never used to select, to pick a ratio or an epoch, or to mine.
4. **Held-out tests are scored once**, for every candidate, after the choice is made from the
   gates and the selection set.
5. **Candidates, fixed now. None is added after a result is seen.**
   - **S30, S50, S70: soups.** `θ = α·θ_B + (1 − α)·θ_v2.0` for every floating-point tensor,
     α = 0.3, 0.5, 0.7 (α is B's weight), averaged in fp32 and saved in v2.0's dtype; integer
     buffers are copied from v2.0. Precondition: the same architecture, label map and
     tokenizer (checked: identical `config.json` and label map, 199 identical tensor names
     and shapes, identical `tokenizer.json`).
   - **D: v2.0 warm start + mined data.** `train.py` from v2.0's weights (base_model =
     the published repo at 95f612a9), 1 epoch, lr 1e-5, warmup 0.1, batch 16, seed 13, bf16,
     on the v2.0 mix files that can be rebuilt byte for byte (s11 train, OpenPII hu/en/de
     train from its manifest, v2 hard negatives) plus the error-mined variants once.
   - **E: v2.0 recipe retrained + mined data.** `train.py` from `FacebookAI/xlm-roberta-base`
     with the v2.0 recipe (3 epochs, lr 5e-5, best dev F1 epoch) on the same files as D.
     (v2.0's s13 corpus is not on disk any more; D keeps what v2.0 learned from it, E does not.)
   - Dev split for D and E (epoch choice only): OpenPII hu/en/de dev + s11 hu/en dev.
6. **Error mining reads development data only:** the OpenPII-1M train split (Polish rows, a
   seeded sample disjoint from the v2/v3 training rows), the MAPA project's `validation` split
   (`joelniklaus/mapa`, CC-BY-4.0; real court text, read locally and never sent to a remote
   model) and Gretel finance multilingual `train` (en/de). Never a test split, never
   agent-traffic-dev. Mined documents are used only to name error families; every training
   variant is new fictional text written by Muse with planted, generated values.
7. **Decontamination:** every variant, train and dev file against all 17 eval sets
   (`decontam.py`): 0 exact or near-duplicates (J ≥ 0.8) kept; max J against
   agent-traffic-dev reported.
8. **Budget and stop rules:** Modal ≤ $8 in total (free tier), Meta credits for Muse; every
   Modal app stopped after use. If no candidate wins by 2026-11-01, v2.0 stays.

## Result: v2.0 stays

No candidate passes every gate. Every soup leaks one hu-smoke `PERSON` value, so the selection
set doesn't come into play. Error mining found no family of real misses on development data,
so D and E were never trained (item 6 of the protocol: their data is the mined variants, and
there was nothing to mine). **Nothing was published. The production pin
(`watt-mind/pii-guard-ner-xlmr-base@95f612a9`) is unchanged.**

## Gates and selection (v2.0 re-scored on this commit)

Smoke = hu + en + de smoke (51 docs, 173 values), inflection = hu-inflection (12 docs, 50
values), agent-traffic-dev = 300 docs, 1,555 values. Per-set summaries in
[`stage1/`](stage1/); run records `eval/results/runs/2026-10-29-lab-1494-<set>-<candidate>.json`.
The v2.0 re-score records carry their own system key
(`rules+ner:xlmr-base-v2-hn@rescore=lab-1494`, label "NER v2.0 (selection-only re-score,
LAB-1494)"; `eval_v3.system_extra`). They were timed on a loaded machine, and the report's
latest-per-system pick would otherwise show them in place of the published v2.0 rows.

| Candidate | smoke leak ≤ 0.00 % | smoke over-mask ≤ 1.59 % | inflection leak ≤ 2.0 % | CPU p95 ≤ 1.2× | **agent-traffic-dev** leak / over-mask | Selected |
|---|--:|--:|--:|--:|--:|---|
| v2.0 (published) | 0.00 | 1.09 | 2.0 | 1.00× (445 ms) | 0.13 / 1.84 | **stays** |
| S30 (0.3 B) | **0.58 fail** | 0.56 pass | 0.0 pass | 0.94× pass | 0.00 / 2.07 | no (1 gate) |
| S50 (0.5 B) | **0.58 fail** | **2.19 fail** | 0.0 pass | 0.89× pass | 0.00 / 2.30 | no (2 gates) |
| S70 (0.7 B) | **0.58 fail** | **2.17 fail** | 0.0 pass | 0.99× pass | 0.00 / 2.53 | no (2 gates) |
| D, E | — | — | — | — | — | not trained (nothing mined) |

For the record, no soup beats v2.0 on the selection set either: each drops the leak to 0.00 %
but over-masks more (2.07–2.53 % vs 1.84 %), the same trade v3.1-B made (0.00 / 2.54 %).

**The smoke leak.** The soups get back both values B leaked (the hu date of birth in
`hu-poa-0003` and the German genitive `Hans'` in `de-genitive-0005`), but lose one that v2.0
and B both find: the inflected name in `hu-poa-0015`, a power of attorney naming the agent in
the accusative ("meghatalmazom Képzelt Bélát, hogy …"; checked for S30, and S50 and S70 each
leak one hu `PERSON` too). Averaging two models that each find it gives one that doesn't, so
the soup is not a simple interpolation of the two models' behaviour on that value.

**Latency.** [`latency-cpu.json`](latency-cpu.json): 122 messages of about 380 characters, the
four models alternating per message in one process, NER only, 8 torch threads, Apple
M-series. The machine was heavily loaded (load average 30 to 54), so the absolute numbers
are high. The ratios are what the gate reads, and all four models have the same architecture.

| Model | p50 | p95 | p95 vs v2.0 |
|---|--:|--:|--:|
| v2.0 | 131.9 ms | 444.9 ms | 1.00× |
| S30 | 124.1 ms | 417.0 ms | 0.94× |
| S50 | 121.9 ms | 395.5 ms | 0.89× |
| S70 | 118.3 ms | 438.9 ms | 0.99× |

## Report-only sets (rules + NER, fast mode, CPU), scored once after the choice

Leak % / over-masking % / overlap F1. Summaries in [`stage2/`](stage2/).

| set (docs) | v2.0 | S30 | S50 | S70 |
|---|--:|--:|--:|--:|
| agent-traffic test (990) | 0.25 / 1.65 / 0.966 | 0.04 / 2.32 / 0.962 | **0.00** / 2.54 / 0.957 | 0.02 / 2.52 / 0.952 |
| ai4privacy (600) | 0.37 / 1.27 / 0.985 | 0.27 / 0.59 / **0.989** | 0.27 / **0.50** / 0.989 | 0.27 / 0.50 / 0.989 |
| nemotron-pii (300) | 0.72 / 1.36 / 0.894 | 0.43 / 1.28 / 0.935 | **0.14** / 0.93 / 0.951 | 0.43 / **0.82** / **0.965** |
| cee-pii (451) | 0.40 / 26.4 / 0.826 | 0.40 / 26.5 / 0.819 | **0.20** / 25.8 / 0.821 | 0.40 / **25.0** / **0.829** |
| gretel-finance (400) | 19.1 / **21.8** / 0.717 | **18.9** / 22.2 / 0.751 | 19.2 / 22.0 / **0.757** | 20.6 / 22.3 / 0.753 |
| pl-pii-bench (346) | 3.5 / **11.2** / **0.893** | **0.24** / 12.7 / 0.878 | 0.24 / 15.1 / 0.857 | 1.33 / 16.2 / 0.851 |
| mapa-eur-lex (42) | 8.5 / 55.6 / 0.543 | **6.8** / 49.3 / 0.596 | 6.9 / 44.8 / 0.624 | 8.5 / **43.4** / **0.628** |

- **The soups are better than v2.0 on most held-out sets.** S30 leaks less on six of seven
  (pl-pii-bench 3.5 → 0.24 %, MAPA 8.5 → 6.8 %, nemotron 0.72 → 0.43 %) and ties on cee-pii.
  S50 leaks less on six and 0.1 pp more on gretel-finance. Unlike v3.1-B, no soup gives back MAPA. They over-mask
  more on agent-traffic and pl-pii-bench, and less on ai4privacy, nemotron and MAPA.
- **These numbers can't choose a model.** They are held-out tests, read once after the choice
  under a protocol that makes the smoke gate pass/fail. S30 fails it by one value. Trading
  that gate for these numbers would be choosing on the test sets. If the smoke gate is to be
  changed (for example to a tolerance of one value, or a per-type rule), that is a protocol
  change for a new ticket, decided before anything is re-scored.
- **pl-pii-bench for v2.0 is 3.5 % on this commit, not 17.5 %.** The Polish rules pack and its
  follow-ups (LAB-1400, LAB-1433) landed after the v3.1 runs, so the Polish gap that v3.1
  measured is mostly closed by the rules already.

## Error mining (development data only)

[`training/ner/mine_errors.py`](../../../training/ner/mine_errors.py) runs v2.0 fast mode over
three development pools and counts the missed values by language, type and a value-shape
family. [`mining.json`](mining.json) holds counts only, never a value or a text; the values
and contexts used to read the misses stayed in a git-ignored local file.

| Pool (source split) | docs | values | missed | what the misses are, on reading |
|---|--:|--:|--:|---|
| OpenPII-1M **train**, fresh seed-1494 rows: pl 400, hu/en/de 300 each, disjoint from v2.0's rows | 1,300 | 4,395 | 30 (0.7 %) | `PERSON` 7/1,134 (Polish 4/358). Nearly all are slot-filling artefacts of the source: a percentage or a wind-farm name labelled as a person, house numbers and bare street names as addresses, order and SKU codes as ids. |
| MAPA EUR-Lex **validation** (`joelniklaus/mapa`), one General Court judgment × 21 languages, a different document from the test pair | 21 | 346 | 134, of which 12 `PERSON` | No real name. 11 are role words the dev labels mark as `PERSON` ("Rapporteur", "Registrar", "agentes", "sekretāre"), 1 a case name. The 122 `ADDRESS` misses are countries and towns, which the MAPA test set doesn't score. |
| Gretel finance multilingual **train**, en/de 300 each | 600 | 1,495 | 246 | `BANK_ACCOUNT` 0/47, `ID_DOCUMENT` 2/34. The 215 `PERSON` misses are label noise: "Damen und Herren", "Im Rahmen", "Guten Morgen", "Saldo", "[Borrower Name]". None of the 17 that pass a two-capitalised-words name filter is a person. |

So **none of the expected error families reproduces on development data.**

- **Polish names:** v2.0 misses 4 of 358 Polish OpenPII names. The rules pack has
  since closed most of the pl-pii-bench gap (3.5 % leak).
- **Legal-text names:** none missed in the MAPA dev judgment, once the reader keeps an initial
  with its surname. The first run joined MAPA's sentences with a newline, which cut "B." off
  "Spinoit" and made 27 artefact misses. `mine_errors.mapa_rows` now joins with a space, and
  `mining.json` is from the second run.
- **Finance identifiers:** they don't leak on Gretel train. Its `PERSON` gold is noise-dominated,
  which probably explains most of the 19–22 % gretel-finance leak that every NER version
  reports. That is filed as LAB-1497. It is not a model error to train away.

Writing a few hundred Muse variants for families that v2.0 doesn't miss would have been
training on a guess, not on mined errors. The protocol's D and E are defined on mined
variants, so they were not trained. **No Muse call was made.**

## Data and licences

| Source | Licence | Used for |
|---|---|---|
| v3.1 candidate B (`pii-guard-ner-runs` Modal volume, sha256 `2fe04d35…`) | as v3.1 (Apache-2.0 base, CC-BY-4.0 OpenPII rows: Ai4Privacy / Ai Suisse SA) | soups |
| v2.0 (`watt-mind/pii-guard-ner-xlmr-base@95f612a9`, sha256 `4a9a598f…`) | Apache-2.0 | soups, mining |
| OpenPII-1M train @ `ecfdc547` | CC-BY-4.0, Ai4Privacy / Ai Suisse SA | mining (counts only) |
| `joelniklaus/mapa` validation @ `bbb2a015` | CC-BY-4.0; public EUR-Lex text | mining (counts only, local) |
| Gretel `synthetic_pii_finance_multilingual` train @ `7b844d16` | Apache-2.0 | mining (counts only) |

No rows are committed. No real text went to a remote model. Nothing new was trained, so no
decontamination run was needed. The soups are made of two checkpoints that were each gated in
their own tickets (LAB-1306, LAB-1410).

## Compute and cost

- **Modal: $0.00.** No Modal function ran. The only Modal operation was `modal volume get`
  of B's weights (1.1 GB, no compute). `modal app list` shows no app.
- **Meta credits: $0.00.** No Muse call.
- **Local CPU:** soups (seconds), scoring of 4 models × 10 sets, error mining over 1,921 docs,
  and the latency run on the Mac. The full test suite was not run on the Mac.

## Reproduce

```
modal volume get pii-guard-ner-runs pii-guard-ner-xlmr-base-v31-b models/ner/
for a in 30 50 70; do
  uv run --no-sync python training/ner/soup.py --a <v2.0 dir> \
      --b models/ner/pii-guard-ner-xlmr-base-v31-b --alpha 0.$a \
      --out models/ner/pii-guard-ner-xlmr-base-v32-s$a
done
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/eval_v3.py score --ticket LAB-1494 \
    --candidate v32-s30 --model models/ner/pii-guard-ner-xlmr-base-v32-s30 \
    --sets smoke inflection agent-traffic-dev --record      # v20: no --model; then the rest
uv run --no-sync python training/ner/eval_v3.py latency --n 122 --model v20= --model v32-s30=...
PII_GUARD_NER_DEVICE=cpu uv run --no-sync --with pyarrow python training/ner/mine_errors.py \
    --openpii <OpenPII train.jsonl> --mapa <mapa validation.jsonl> --gretel <gretel train.parquet> \
    --json eval/results/2026-10-29-ner-v32/mining.json --local data/mining/misses.jsonl
```

## Next

- The soups are the first thing that improves most held-out sets without losing MAPA. The one
  thing in the way is a single inflected Hungarian name in `hu-poa-0015`. A follow-up could
  try a smaller α (0.1–0.2) or a soup with a short v2.0-anchored fine-tune on hu inflected
  names. It must use a new ticket, with the protocol (and any change to the smoke gate) fixed
  before it is scored.
- LAB-1497: audit the gretel-finance `PERSON` gold before its leak is read as model error.
