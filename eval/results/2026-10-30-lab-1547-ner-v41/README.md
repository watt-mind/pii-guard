# NER v4.1: candidate A minus loose addresses, plus court-style, phase-1b and targeted data (2026-10-30)

LAB-1547, the follow-up to LAB-1535 ([v4 results](../2026-10-29-lab-1535-ner-v4/README.md)).
v4 candidate A (v2.0 warm start, 1 epoch, lr 1e-5) cut the MAPA-21 leak from 8.5 % to 5.8 % and
the hu-inflection leak to 0, but failed three gates: the hu smoke leak (the accusative name in
`hu-poa-0015`), agent-traffic-dev over-masking (3.38 % against v2.0's 1.84 %, mostly `ADDRESS`
false alarms) and the Maltese eu gate (one birth date). v4.1 keeps A's recipe and changes the
data only. The published model is v2.0 (`watt-mind/pii-guard-ner-xlmr-base@95f612a9`).

## Protocol (fixed and committed before any model was trained or scored)

The LAB-1535 protocol, **unchanged** (gates, thresholds, selection rule, sets). v2.0 is re-scored
on this commit (records keyed `rules+ner:xlmr-base-v2-hn@rescore=lab-1547`).

1. **Selection set, the only one used to choose:** agent-traffic-dev (300 docs, hu/en/de). A
   candidate must pass every gate and **beat v2.0** there: leak ≤ v2.0 *and* over-masking ≤
   v2.0, at least one strictly lower. Among those, the lowest leak wins, then the lower
   over-masking, then the earlier candidate in the list below.
2. **Existing gates, pass/fail, against v2.0 on this commit:** hu/en/de smoke leak ≤ v2.0 and
   smoke over-masking ≤ v2.0 + 0.5 pp; hu-inflection leak ≤ v2.0; CPU p95 ≤ 1.2× v2.0 in one
   alternating latency run on an idle Modal CPU container (`modal_latency.py`), run only for a
   candidate that passes every accuracy gate (the LAB-1512 precedent).
3. **New-language gate (eu), pass/fail**, on `eval/fixtures/eu/`: for each of lv lt hr sl fr es
   it nl ro mt ga, on that language's smoke + inflection documents together, leak ≤ v2.0 and
   over-masking ≤ v2.0 + 2 pp; the same for `en-court-smoke`; and over all eu sets together
   the leak is **strictly lower** than v2.0's.
4. **MAPA EUR-Lex test, all 21 languages, report-only**, scored on this Mac in one process and
   never uploaded (the LAB-1527 allowlist refuses any `mapa` path). Not a gate, never used to
   choose.
5. **Never read for design:** agent-traffic-dev, the eu gate sets and every test set. The two
   v4-A failures that shaped the targeted data are named in the LAB-1535 README and records
   (`hu-poa-0015`: an accusative name in a Hungarian power of attorney; `mt`: one
   `DATE_OF_BIRTH`); no fixture text was opened or copied.
6. **A tie on the selection set is not a win.** It is reported for the owner to decide.

Scoring is local, CPU, one process at a time (`eval_v3.py score --ticket LAB-1547`), and the
gate table comes from `gates_v4.py --ticket LAB-1547 --candidates v41-a1 v41-a2`.

## Candidates, fixed now. None is added after a result is seen.

Both start from v2.0 at its pinned revision, `train.py` (decontamination on), 1 epoch, lr 1e-5,
batch 16, warmup 0.1, weight decay 0.01, seed 13, bf16, one A10G on Modal. They differ only in
what happens to the `ADDRESS` spans of the two loose-address sources. In selection order:

- **A1** (`training/ner/v41-a1.toml`): OpenPII EU and kiji `ADDRESS` spans **kept out of the
  loss** (`meta.loss_ignore`): the model is neither taught them as addresses nor as `O`.
- **A2** (`training/ner/v41-a2.toml`): the same spans **taught as `O`** (the spans are dropped).

**Why these two sources.** Measured on the training files before any run (`v41_data.py`
docstring): OpenPII EU (0.65 `ADDRESS` per row) and kiji (0.73) label short fragments: about
20 % of their address spans hold no digit and they average 2.7 and 3.2 words. nym, E3,
pii-anon, the s11 replay and the court set label full addresses (a digit in 95–100 %, 3.7–6.4
words) and keep them. The v2.0 replay rows (OpenPII hu/en/de) are v2.0's own training data and
are not changed.

## Data

All synthetic or fictional (ADR 0005). Assembled by `training/ner/v41_data.py build`; counts,
gold spans per type and SHA-256 per file in [`data.json`](data.json). Both candidates get the
same documents; only the `ADDRESS` treatment of the two sources differs.

| Part | Source | Documents (train) | Copies |
|---|---|--:|--:|
| OpenPII-1M EU train rows, 19 languages | v4 mix a (the first 2,500 per language), `ADDRESS` treated | 47,500 | 1 |
| EU hard negatives, 21 languages (adds ga, mt: they have positives now) | `negatives_eu.py`, first 1,000 | 21,000 | 1 |
| Muse lv/lt/hr/sl, **regenerated and Glimmer-labelled** | corpus `phase1` (below) | ~4,300 | 2 |
| Muse fr/es/it/nl/ro/ga/mt, Glimmer-labelled (LAB-1534) | corpus `phase1b@5b4ddcec` | 7,538 | 1 |
| Court-style judgments, 24 languages, and error-mined variants (LAB-1539) | corpus `v41@a9f9c6e8`, `labelled/` | 3,437 + 475 | 1 |
| kiji (6 languages), `ADDRESS` treated | `hf_v41.py` per `v41-hf-manifest.json` (not re-hosted) | 15,000 | 1 |
| nym (14), E3 (6), pii-anon (18, ID formats; ~1.6 % of the mix, cap 5 %) | same | 35,000 + 2,164 + 2,973 | 1 |
| Targeted hu powers of attorney (accusative and other cases of the agent's name) | `v41_data.py targeted`, seed 1547 | 1,500 | 2 |
| Targeted Maltese documents with birth dates (and other dates as `O`) | same | 1,000 | 1 |
| English court style | `court_surnames_en.py` | 1,500 | 1 |
| v2.0 replay (s11 hu/en, OpenPII hu/en/de, negatives hu/en/de) | as v4 | 25,223 | 1 |

Dev (reported only; 1 epoch, so it chooses nothing): v4's dev list with the labelled phase-1
dev files, plus the targeted dev files.

**Targeted documents.** Template-based, no model call; names from the `targeted_v33.py`
Hungarian lists and the `eu_identities.py` Maltese pack (the eu gate names are not from those
lists). A document naming a person whose full name occurs in any evaluation text is redrawn
(0 of 5,068 distinct names do), and `decontam.py` dropped 0 of 2,680 documents. `train.py`
runs the decontamination gate again on Modal over every train and dev document.

## Budget and stop rules

- **Modal:** $2.92 left until 11-01. One A10G only, at most 2 runs, each with a hard timeout
  of 45 minutes (`PII_GUARD_TRAIN_TIMEOUT_S=2700`). Stop if the projected total goes over
  $2.50. No H100, no `modal_eu_label.py`.
- **Meta Model API:** the Muse lv/lt/hr/sl rerun, cap $3.
- **Fireworks:** Glimmer labelling of that rerun on one on-demand H200, cap $10, the deployment
  deleted straight after and the deletion confirmed.
- Upload only through the LAB-1527 allowlist; MAPA and TAB text never leaves the machine.
- Nothing is published to Hugging Face and the deployed model is not changed: that needs the
  owner's decision. If no candidate wins, v2.0 stays and this README says why.
