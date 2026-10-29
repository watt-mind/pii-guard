# NER v3.3: targeted fine-tune of soup S30, threshold fallback (2026-10-29)

LAB-1512. Owner decision (2026-10-29): "Go with your recommendations about the tuning." This
is path 2 of those recommendations (a short, targeted continued fine-tune of the LAB-1494 soup
S30), with path 4 (per-language, per-type decision thresholds on v2.0) as the fallback. The
published model is v2.0 (`watt-mind/pii-guard-ner-xlmr-base@95f612a9`). Freeze: 2026-11-01.

**Why S30.** In LAB-1494, S30 (0.7 v2.0 + 0.3 v3.1-B) failed one gate by one value: the
accusative name in `hu-poa-0015` (hu smoke). On the held-out sets it leaked less than v2.0 on
six of seven (pl-pii-bench 3.5 → 0.24 %, MAPA 8.5 → 6.8 %, nemotron 0.72 → 0.43 %), and on the
selection set it leaked nothing but over-masked more (2.07 % vs 1.84 %). So the question is
whether a short fine-tune on new fictional data can teach it Hungarian case forms of names and
take back the extra over-masking on agent text, without losing the rest.

## Protocol (fixed and committed before any data was generated, any model trained or scored)

The LAB-1494 (v3.1) protocol, unchanged. v2.0 is re-scored on this commit.

1. **Selection set, the only one used to choose:** agent-traffic-dev (300 docs). A candidate
   must pass every gate and **beat v2.0** there: leak ≤ v2.0 *and* over-masking ≤ v2.0, at
   least one strictly lower. Among those, the lowest leak wins, then the lower over-masking,
   then the earlier candidate in the list below.
2. **Gates, pass/fail only**, against v2.0 scored on the same commit: hu/en/de smoke leak ≤
   v2.0 and smoke over-masking ≤ v2.0 + 0.5 pp; hu-inflection leak ≤ v2.0; CPU p95 ≤ 1.2×
   v2.0 in one alternating latency run (`eval_v3.py latency`, NER only).
3. **Latency on a clean machine.** LAB-1494 timed on a Mac with load average 30–54. Here the
   latency run is on a Modal CPU container (nothing else running in it), all models
   alternating per message in one process. The ratio is the gate.
4. **Report-only:** agent-traffic test, ai4privacy, nemotron-pii, cee-pii, gretel-finance,
   pl-pii-bench, MAPA EUR-Lex. Never used to select, to choose a config, an epoch or a
   threshold. Scored once per candidate after the choice is made.
5. **v2.0 re-score records** get a system key of their own
   (`rules+ner:xlmr-base-v2-hn@rescore=lab-1512`, `eval_v3.system_extra`), so they don't
   replace the published v2.0 rows in the report.
6. **Never read for design:** agent-traffic-dev and every test set. The add-on is designed
   from the error families already on record: the LAB-1494 smoke failure (an inflected
   Hungarian name), LAB-1477 (`"ticket": 4471`, ports, sizes as `ADDRESS`; `Luhn` as
   `PERSON`), LAB-1482 (UUIDs, timestamps, `false`, `python3`, npm scopes) and LAB-1485
   (`pi` as `PERSON`). Their texts are not copied.
7. **Honest caveat, stated now.** Part (a) of the add-on targets the family of the one value
   that failed the smoke gate. Its text is decontaminated against smoke (and every eval set)
   and no full name from any eval set is used, but the smoke gate is less independent for
   that family than it was in LAB-1494. The inflection gate and the selection set are not
   targeted by anything in the add-on beyond "Hungarian names in case forms".

### The add-on (`training/ner/targeted_v33.py`, seed 1512, templates only, no model calls)

Fictional only (ADR 0005). Names are drawn from hand-written lists of common given names and
surnames, combined at random; a document whose full name occurs in any evaluation text is
redrawn. Train and dev are drawn with different seeds.

| part | language | train docs | dev docs | gold |
|---|---|--:|--:|---|
| (a) inflected names | hu | 1,500 | 150 | `PERSON` (span includes the case ending, as in s11 and the fixtures); some `EMAIL` |
| (a) inflected names | pl, de | 300 each | 30 each | `PERSON` |
| (b) structured-payload hard negatives | hu, en, de | 200 each | 20 each | none, except one doc in three carries a labelled fictional `PERSON`/`EMAIL` in a name field |
| (c) agent-text hard negatives | hu, en, de | 200 each | 20 each | none, except one doc in four carries a labelled fictional `PERSON` |

- (a) Hungarian: nominative, accusative, dative, instrumental (with assimilation), ablative,
  delative, allative, adessive, possessive `-é` and family `-ék` forms; double given names,
  hyphenated surnames and the married `-né` form. Polish: the six oblique cases of given
  names and `-ski`/`-cka`/consonant surnames. German: genitive `-s` and apostrophe.
- (b) JSON, tool-call arguments, YAML, log lines and CSV with numeric fields: ticket, order,
  issue and PR numbers, counts, ports, sizes, PIDs, line numbers, HTTP status, versions,
  durations, epoch timestamps, UUIDs, hashes. Small integers (2–6 digits) are the focus.
- (c) Code, shell commands, tool and harness names (`pi`, `codex`, `opencode`, `python3`,
  `npm`), `@scope/package` paths, booleans and `null`, algorithm eponyms (Luhn, Dijkstra,
  Levenshtein, Kalman, Huffman …) in prose about code.

**Decontamination** (committed as [`decontam.json`](decontam.json)): every add-on and replay
document through `decontam.py` against all evaluation sets; 0 exact or near-duplicates
(J ≥ 0.8) kept; max J of the add-on against agent-traffic-dev, smoke and inflection reported.

### Replay slice (S30's own data, against forgetting)

A seeded sample (seed 1512) of the v3.1-B mix files (`eval/generated/v31-final`, rebuilt from
the `v31-data` volume copy; ids checked against `training/ner/v31-data-manifest.json`), which
also hold v2.0's s11 and hard-negative files: OpenPII hu 1,000, en 500, de 500, pl/cs/sk/ro/hr/sl
250 each; s11 hu/en 600 each; negatives hu/en/de 300 each; Privy 300; Wismut en/de/pl/cs/ro
100 each; Nemotron 200; Gretel 200. About 6,800 documents, about 2.3× the add-on.

### Candidates, fixed now. None is added after a result is seen.

Both start from S30 rebuilt byte for byte (`soup.py`, α = 0.3; weights sha256 `e5c31d12…`,
the LAB-1494 record), on add-on train + replay, `train.py` (decontam on), batch 16, warmup
0.1, weight decay 0.01, seed 13, bf16, A10G on Modal.

- **T1:** 1 epoch, lr 1e-5.
- **T2:** 2 epochs, lr 2e-5; the epoch is chosen by `train.py`'s dev F1 only (dev = add-on dev
  + s11 hu/en dev + OpenPII hu/en/de dev).

### Fallback (path 4), used only if neither T1 nor T2 is selected

Per-language, per-type minimum scores for v2.0 (`NerDetector(thresholds=...)`, today 0.5 for
every type). **Calibrated on development data only** (s11 hu/en dev, OpenPII hu/en/de dev,
the add-on dev split), never on agent-traffic-dev or a test set: for each language (hu, en,
de) and type, the highest threshold in {0.5, 0.6, 0.7, 0.8, 0.9} at which the dev leak count of
that type is no higher than at 0.5. Candidate **H** is that table. It goes through the same
gates and the same selection rule. If it wins, it ships as a config change (no new weights).

### Budget and stop rules

Modal ≤ $8 in total (free tier); no Muse or other model calls are planned (the add-on is
templated). Every Modal app is stopped after use. If nothing wins by 2026-11-01, v2.0 stays and
this README says so.

## Result: v2.0 stays

No candidate passes every gate, so the selection set doesn't choose anything. **Nothing was
published, and no threshold config ships. The production pin
(`watt-mind/pii-guard-ner-xlmr-base@95f612a9`) is unchanged.**

## Gates and selection (v2.0 re-scored on this commit)

Leak % / over-masking %. Smoke = hu + en + de smoke (51 docs, 173 values), inflection =
hu-inflection (12 docs, 50 values), agent-traffic-dev = 300 docs. Summaries in
[`stage1/`](stage1/), run records `eval/results/runs/2026-10-29-lab-1512-<set>-<candidate>.json`
(v2.0's carry the re-score key `rules+ner:xlmr-base-v2-hn@rescore=lab-1512`).

| Candidate | smoke leak ≤ 0.00 | smoke over-mask ≤ 1.59 | inflection leak ≤ 2.0 | CPU p95 ≤ 1.2× | **agent-traffic-dev** leak / over-mask | Selected |
|---|--:|--:|--:|--:|--:|---|
| v2.0 (published) | 0.00 | 1.09 | 2.0 | 1.00× | 0.13 / 1.84 | **stays** |
| T1 (S30 + add-on, 1 ep, lr 1e-5) | **0.58 fail** | 1.11 pass | 0.0 pass | not run | 0.51 / 1.49 | no |
| T2 (S30 + add-on, 2 ep, lr 2e-5) | 0.00 pass | **2.19 fail** | 0.0 pass | not run | 0.90 / 1.62 | no |
| H (v2.0, dev thresholds) | **0.58 fail** | 0.56 pass | **4.0 fail** | not run | 0.84 / 0.96 | no |

- **T1 still leaks the LAB-1494 value** (`hu-poa-0015`, one `PERSON`). One epoch at 1e-5 on
  1,650 Hungarian/Polish/German name documents wasn't enough to move it.
- **T2 finds it, but over-masks smoke** (2.19 % vs the 1.59 % ceiling), the trade every
  v3.x candidate made. 
- **Neither would have won the selection set anyway.** Both over-mask less on
  agent-traffic-dev than v2.0 (1.49 and 1.62 % vs 1.84 %: the payload and agent-text hard
  negatives did what they were for), but both leak more (0.51 and 0.90 % vs 0.13 %). S30
  itself leaked 0.00 % there (LAB-1494), so the fine-tune gave back leak for over-masking.
- **H trades leak for over-masking, as raising thresholds must.** The dev splits are
  in-distribution and v2.0 leaks almost nothing on them, so the calibration rule
  (highest threshold with no extra dev leak) pushed most types to 0.8–0.9
  ([`thresholds-h.json`](thresholds-h.json)). Out of distribution that loses values: one
  smoke name, a second inflection name, and 0.84 % on the selection set.
- **Latency was not run.** No candidate passed the accuracy gates, so latency couldn't change
  the outcome, and running it would have spent Modal credit to no purpose.
  `training/ner/modal_latency.py` (an idle Modal CPU container) is committed for the next round.

## Report-only sets (rules + NER, fast mode, CPU), scored once after the choice

Leak % / over-masking % / overlap F1. Summaries in [`stage2/`](stage2/).

| set (docs) | v2.0 | T1 | T2 | H |
|---|--:|--:|--:|--:|
| agent-traffic test (990) | **0.25** / 1.7 / 0.966 | 0.62 / 2.0 / 0.959 | 1.40 / 2.0 / 0.956 | 1.38 / **1.1** / **0.971** |
| ai4privacy (600) | 0.37 / 1.3 / 0.985 | **0.27** / **0.5** / **0.990** | 0.32 / 0.5 / 0.990 | 0.60 / 0.6 / 0.987 |
| nemotron-pii (300) | 0.72 / 1.4 / 0.894 | **0.43** / 0.9 / 0.958 | 1.15 / **0.7** / **0.964** | 1.43 / 1.2 / 0.886 |
| cee-pii (451) | 0.40 / 26.4 / 0.826 | **0.20** / 24.8 / 0.829 | 0.20 / 27.5 / 0.808 | 1.79 / **23.5** / **0.844** |
| gretel-finance (400) | **19.1** / 21.8 / 0.717 | 20.4 / 20.5 / **0.772** | 20.8 / 20.0 / 0.757 | 20.0 / **19.0** / 0.694 |
| pl-pii-bench (346) | 3.52 / 11.2 / **0.893** | **0.48** / **10.1** / 0.878 | 0.85 / 11.1 / 0.882 | 3.52 / 11.2 / 0.893 |
| mapa-eur-lex (42) | **8.5** / 55.6 / 0.543 | 14.1 / **40.6** / **0.590** | 15.4 / 41.8 / 0.572 | 9.1 / 55.5 / 0.544 |

- **The fine-tune loses MAPA** (8.5 → 14–15 %), which S30 alone had improved (6.8 %). The add-on
  teaches names as given name + surname or as an inflected full name, and the replay holds no
  legal text. LAB-1511 found (after this training had started) that most of v2.0's MAPA test
  leaks are standalone surnames in court register, a context the add-on doesn't have and may
  have taught away. See *Next*.
- T1 keeps S30's Polish gain (3.5 → 0.48 %) and improves nemotron and cee-pii. These are
  test numbers read after the choice; they can't overrule a gate.
- H changes nothing on pl-pii-bench (the rules find those values) and loses values on most
  other sets.

## Data, decontamination and disjointness

- Add-on: [`addon.json`](addon.json): 3,300 train + 330 dev documents, 5,000+ `PERSON` spans,
  0 generated full names that occur in any evaluation text.
- Replay: [`replay.json`](replay.json): 6,800 documents sampled from the v3.1-B mix
  (`eval/generated/v31-final`, rebuilt with `v31_data.py derive` from the `v31-data` volume
  copy; every file's `ids_sha256` and count match `training/ner/v31-data-manifest.json`).
- [`decontam.json`](decontam.json): 10,430 add-on + replay documents against every
  evaluation set: **0 exact, 0 near-duplicates (J ≥ 0.8)**. Closest add-on pair: J = 0.000
  against agent-traffic-dev, smoke and inflection, 0.017 against the agent-text fixture. The
  TAB fixture text isn't on disk; it was compared by its manifest hashes. `train.py`'s own
  gate also dropped 0 of 11,471 train + dev documents on Modal.
- Licences as LAB-1494 (v2.0 Apache-2.0; v3.1-B's mix: OpenPII-1M CC-BY-4.0 Ai4Privacy / Ai
  Suisse SA, plus the audited Privy, Wismut, Nemotron and Gretel files). The add-on is
  written for this ticket and fictional (ADR 0005). No GDPR special-category data.

## Compute and cost

- **Modal: $0.095** (`modal billing report --for today`): T1 1.4 min and T2 2.6 min of
  training on an A10G, plus image and data upload. Both apps were ephemeral (`modal run`)
  and stopped; `modal app list` shows none running. S30, T1 and T2 stay on the
  `pii-guard-ner-runs` volume.
- **Meta credits: $0.00.** The add-on is templated; no Muse call was made.
- **Local CPU (Mac, loaded):** soup rebuild, add-on generation, decontamination, threshold
  calibration (5 × 1,341 dev docs) and scoring of 4 candidates × 10 sets. Accuracy doesn't
  depend on load; no latency number here was measured on the Mac.

## Reproduce

```
modal volume get pii-guard-ner-runs pii-guard-ner-xlmr-base-v31-b models/ner/
uv run --no-sync python training/ner/soup.py --a <v2.0 dir> \
    --b models/ner/pii-guard-ner-xlmr-base-v31-b --alpha 0.3 \
    --out models/ner/pii-guard-ner-xlmr-base-v32-s30          # sha256 e5c31d12…
modal volume put pii-guard-ner-runs models/ner/pii-guard-ner-xlmr-base-v32-s30 \
    pii-guard-ner-xlmr-base-v32-s30
uv run --no-sync python training/ner/v31_data.py derive --raw <v31-data volume copy>
uv run --no-sync python training/ner/targeted_v33.py addon --json eval/results/2026-10-29-ner-v33/addon.json
uv run --no-sync python training/ner/targeted_v33.py replay --json eval/results/2026-10-29-ner-v33/replay.json
uv run --no-sync python training/ner/targeted_v33.py decontam --json eval/results/2026-10-29-ner-v33/decontam.json
modal run training/distill/modal_train.py --config training/ner/v33-t1.toml --gpu A10G   # and t2
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/thresholds_v33.py \
    --json eval/results/2026-10-29-ner-v33/thresholds-h.json
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/eval_v3.py score --ticket LAB-1512 \
    --candidate v33-t1 --model models/ner/pii-guard-ner-xlmr-base-v33-t1 \
    --sets smoke inflection agent-traffic-dev --record      # v20: no --model; H: --thresholds
```

## Next

- **This is the last NER round before the 2026-11-01 freeze.** v2.0 ships.
- **Standalone surnames in legal register** (LAB-1511: most of v2.0's MAPA test leaks): a
  fictional add-on of court-style contexts ("X stated…", "according to X", "X's counsel"),
  never MAPA text. It arrived after T1/T2 had started training, so per the coordinator's note
  it was not added post hoc; it is future work with its own protocol.
- **The smoke gate keeps deciding on one Hungarian value.** S30, T1 and H each fail it by
  `hu-poa-0015` alone. If the owner wants a tolerance or a per-type rule, that is a protocol
  change for a new ticket, decided before anything is scored.
