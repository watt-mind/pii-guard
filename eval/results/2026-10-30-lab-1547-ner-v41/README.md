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
| Muse lv/lt/hr/sl, **regenerated and Glimmer-labelled** | corpus `phase1@2df7dc63` (below) | 4,310 | 2 |
| Muse fr/es/it/nl/ro/ga/mt, Glimmer-labelled (LAB-1534) | corpus `phase1b@5b4ddcec` | 7,538 | 1 |
| Court-style judgments, 24 languages, and error-mined variants (LAB-1539) | corpus `v41@a9f9c6e8`, `labelled/` | 3,437 + 475 | 1 |
| kiji (6 languages), `ADDRESS` treated | `hf_v41.py` per `v41-hf-manifest.json` (not re-hosted) | 15,000 | 1 |
| nym (14), E3 (6), pii-anon (18, ID formats; 1.7 % of the mix, cap 5 %) | same | 35,000 + 2,164 + 2,973 | 1 |
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

## Result: v2.0 stays

**Neither candidate passes every gate, so the selection set doesn't choose anything.
Nothing was published, and the production pin (`watt-mind/pii-guard-ner-xlmr-base@95f612a9`)
is unchanged.** Applied by `training/ner/gates_v4.py --ticket LAB-1547` to the run records
([`gates.json`](gates.json)).

## Gates and selection (v2.0 re-scored on this commit)

Leak % / over-masking %, rules + NER, fast mode, CPU, this commit (develop at `8d21762e` plus
this branch). v2.0's agent-traffic-dev over-masking is 1.66 % here, not LAB-1535's 1.84 %:
detector fixes merged since (LAB-1359, LAB-1258, LAB-1220) changed the fast-mode baseline. v4-A
is LAB-1535's row (scored on that commit), for reference only. Run records
`eval/results/runs/2026-10-30-lab-1547-<set>-<candidate>.json`; summaries in [`stage1/`](stage1/).

| Candidate | smoke leak ≤ 0.00 | smoke over-mask ≤ 1.58 | inflection leak ≤ 2.0 | eu per language | eu total leak < 0.95 | **agent-traffic-dev** leak / over-mask | Selected |
|---|--:|--:|--:|---|--:|--:|---|
| v2.0 (published) | 0.00 | 1.08 | 2.0 | – | 0.95 (3 of 315) | 0.13 / 1.66 | **stays** |
| A1 (`ADDRESS` out of the loss) | **0.58 fail** | **2.16 fail** | 0.0 pass | pass | 0.32 pass | 0.00 / **3.21** | no |
| A2 (`ADDRESS` taught as `O`) | **1.16 fail** | **2.20 fail** | 0.0 pass | pass | 0.63 pass | 0.00 / **2.70** | no |
| *v4-A (LAB-1535, other commit)* | *0.58* | *1.08* | *0.0* | *mt fail* | *0.95* | *0.00 / 3.38* | – |

Latency was not run: no candidate passed the accuracy gates (the LAB-1512 precedent), and the
architecture and tokenizer are v2.0's.

What changed against v4-A, read after the choice, for the next round only:

- **The two targeted fixes worked.** The hu smoke leak is gone (hu leaks 0 of 106 smoke values
  for both; `hu-poa-0015` is found), and the Maltese gate passes: mt leaks nothing and its
  over-masking falls from v2.0's 12.9 % to 3.6 %. Both candidates pass the eu gate, the first
  in any round to do so: A1 leaks 1 of 315 eu values (fr), against v2.0's 3, and finds the nl
  and ga values v2.0 misses.
- **The `ADDRESS` false alarms are gone too:** 0 on agent-traffic-dev for both (v2.0 3, v4-A
  26). But over-masking moved to `DATE_OF_BIRTH`, 2 (v2.0) to 29 (A1) and 21 (A2), and to
  `BANK_ACCOUNT` (5 to 12 and 11). The most likely sources are the new data that labels many
  dates as birth dates (the targeted Maltese set, kiji and nym), and the dev F1 on
  `DATE_OF_BIRTH` (0.61) says the model is unsure of that type.
- **The smoke leak moved to German and English.** A1 leaks one German `PERSON`; A2 one German
  `PERSON` and one English `ADDRESS` (teaching loose addresses as `O` costs a real one).
- **MAPA (report-only) improves most of any round:** leak 8.2 % (v2.0, this commit) to 5.9 %
  (A1) and 5.3 % (A2), over-masking 55 % to 47 %, overlap F1 0.545 to 0.566 and 0.589.

### Per language, eu sets (leak % (values leaked) / over-masking %)

| lang | v2.0 | A1 | A2 |
|---|--:|--:|--:|
| lv, lt, hr, sl, es, it, ro, en-court | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| fr (26) | 3.8 (1) / 0.0 | 3.8 (1) / 0.0 | 3.8 (1) / 0.0 |
| nl (25) | 4.0 (1) / 0.0 | **0.0** / 0.0 | 4.0 (1) / 0.0 |
| mt (26) | 0.0 / 12.9 | 0.0 / **3.6** | 0.0 / **3.6** |
| ga (25) | 4.0 (1) / 7.7 | **0.0** / 3.8 | **0.0** / 3.7 |

### MAPA EUR-Lex test, 21 languages (report-only, scored on this Mac in one process)

42 documents, 740 `PERSON` values; never uploaded.

| | v2.0 | A1 | A2 |
|---|--:|--:|--:|
| leak % | 8.2 | 5.9 | **5.3** |
| over-masking % | 55.3 | 46.7 | **46.2** |
| overlap F1 | 0.545 | 0.566 | **0.589** |

### LAB-1417 smoke-style dev split (report-only, not part of this protocol)

`training/ner/smoke_style_dev.py` (PR #319, merged during this run), scored afterwards on the
final (only) epoch of each candidate, CPU, no Modal cost: v2.0, A1 and A2 all leak 0.00 % with
0.00 % over-masking on its 225 documents. On this round it does not track the smoke gate (both
candidates leak on the real smoke sets).

## Data revisions

| Corpus | Revision (private `watt-mind/pii-guard-ner-train`) | Used |
|---|---|---|
| `phase1` (new, LAB-1547) | `2df7dc6375a41f293a8eaa5a9caaf0447babc184` | `distill-eu-s1525/labelled/` |
| `phase1b` | `5b4ddcecbae18ff0f25c5c75439f7d151b7a2b28` | `distill-eu-1b-s1525/labelled/` |
| `v41` | `a9f9c6e8d5685bd3f0d5d3a27c6feb0dd9d601be` | `court/labelled/`, `variants/labelled/` |
| `v20-s11` (replay, local copy) | `294adb3f` | `distill-s11/labelled/` |

- **phase1 regenerated:** `eu_corpus.py --languages lv,lt,hr,sl --n 1200 --seed 1525`: 4,789
  of 4,800 kept (lv 1,198, lt 1,197, hr 1,194, sl 1,200). Glimmer pass: 37,717 planted values
  found, 1,906 missed (kept), 72 disagreements out of the loss, 43 people and 8 organizations
  the writer added adopted as labels.
- **Pinned corpora checked:** the used files of `v41@a9f9c6e8` and `phase1b@5b4ddcec`, pulled
  fresh, match the local data root byte for byte (55 of 55); training read them from the Modal
  volume copies of those revisions.
- **v4 mix rebuilt:** `v4_data.py build` reproduces all 72 OpenPII, negatives, court-en and
  replay files of both v4 mixes with the hashes in LAB-1535's `data.json` (the Muse files
  differ, as expected: they were regenerated).
- **Decontamination:** `train.py` dropped 0 of 172,470 distinct train and dev documents on
  Modal; the targeted files 0 of 2,680 locally.
- Weights sha256: A1 `6c91c949…`, A2 `9282a63c…` (on the `pii-guard-ner-runs` volume,
  `pii-guard-ner-xlmr-base-v41-a1` and `-a2`; not published).

## Compute and cost

| Provider | What | Cost |
|---|---|--:|
| Modal | A1 and A2 on one A10G each, 24.1 and 24.2 min of training (about 33 min of app time each), plus the volume copies (`modal billing report`) | **$1.00** (A1 $0.51, A2 $0.50) |
| Fireworks | Glimmer on an on-demand H200: session 1 probe failed on one transient `DetectionError` ($0.50, 0.06 h); session 2 labelled all 4,789 documents (0.51 h, $4.05). Both deployments confirmed `DELETED` through the API | **~$4.55** (cap $10) |
| Meta Model API | Muse lv/lt/hr/sl rerun, 32 workers (one restart from 16 workers; the cache kept every response) | **~$2.49** (cap $3) |
| Local CPU | all scoring, one process at a time | $0 |

`fireworks_label.py` now tolerates one failed document in its 8-document probe (the full run
retries failures); a single transient error had stopped LAB-1539's first session the same way.

## Reproduce

```
uv run --no-sync python training/ner/openpii_eu.py --source data/public/openpii-train/train.jsonl
uv run --no-sync python training/ner/openpii.py --source data/public/openpii-train/train.jsonl
uv run --no-sync python training/ner/negatives_eu.py && uv run --no-sync python training/ner/negatives.py
uv run --no-sync python training/ner/court_surnames_en.py
uv run --no-sync --with huggingface-hub python training/ner/data_sync.py pull phase1 --revision 2df7dc63...
uv run --no-sync python training/ner/v41_data.py targeted
uv run --no-sync python training/ner/v41_data.py build --phase1-rev 2df7dc6375a41f293a8eaa5a9caaf0447babc184 \
    --json eval/results/2026-10-30-lab-1547-ner-v41/data.json
PII_GUARD_TRAIN_TIMEOUT_S=2700 modal run training/distill/modal_train.py --config training/ner/v41-a1.toml \
    --gpu A10G --data <the --data line in the config header>          # and v41-a2.toml
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/eval_v3.py score --ticket LAB-1547 \
    --candidate v41-a1 --model models/ner/pii-guard-ner-xlmr-base-v41-a1 --record \
    --sets smoke inflection agent-traffic-dev eu-smoke eu-inflection en-court mapa-eur-lex
uv run --no-sync python training/ner/gates_v4.py --ticket LAB-1547 --candidates v41-a1 v41-a2 \
    --date 2026-10-30 --json eval/results/2026-10-30-lab-1547-ner-v41/gates.json
```

## Next

- **Birth-date over-masking is now what blocks.** A round that keeps A1's data but teaches
  non-birth dates as `O` in the third-party rows (or drops `DATE_OF_BIRTH` from kiji/nym where
  the date has no birth cue), with its own protocol fixed first, is the obvious next step.
- **The smoke leak is now one German name** (A1). A small German counterpart to the hu-poa set
  is cheap.
- A1 is the best multilingual model so far (eu gate passes, MAPA 5.9 %), but it is not
  shippable under the frozen protocol; publishing it needs the owner's decision either way.
