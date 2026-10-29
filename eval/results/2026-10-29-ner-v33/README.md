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

## Result

To be filled in after the runs; the protocol above is not edited.
