# NER v4: multilingual candidates from v2.0 (2026-10-29)

LAB-1535, the training and selection ticket after LAB-1525 (data, PR #251). Owner
(2026-10-29): a better model matters more than the 11-01 freeze; select by 11-02, align the
published numbers on 11-03. The published model is v2.0
(`watt-mind/pii-guard-ner-xlmr-base@95f612a9`), trained on hu/en/de only.

## Protocol (fixed and committed before any model was trained or scored)

The LAB-1494 / LAB-1512 protocol, unchanged, plus a gate for the new languages. v2.0 is
re-scored on this commit (records keyed `rules+ner:xlmr-base-v2-hn@rescore=lab-1535`).

1. **Selection set, the only one used to choose:** agent-traffic-dev (300 docs, hu/en/de). A
   candidate must pass every gate and **beat v2.0** there: leak ≤ v2.0 *and* over-masking ≤
   v2.0, at least one strictly lower. Among those, the lowest leak wins, then the lower
   over-masking, then the earlier candidate in the list below.
2. **Existing gates, pass/fail, against v2.0 on this commit:** hu/en/de smoke leak ≤ v2.0 and
   smoke over-masking ≤ v2.0 + 0.5 pp; hu-inflection leak ≤ v2.0; CPU p95 ≤ 1.2× v2.0 in one
   alternating latency run on an idle Modal CPU container (`modal_latency.py`).
3. **New-language gate (eu), pass/fail**, on the LAB-1525 fictional sets in `eval/fixtures/eu/`.
   For each of lv lt hr sl fr es it nl ro mt ga, on that language's smoke + inflection documents
   together: leak ≤ v2.0 and over-masking ≤ v2.0 + 2 pp. The same for `en-court-smoke`. And over
   all eu sets together the leak is **strictly lower** than v2.0's (a multilingual model that
   finds nothing more has no reason to ship).
4. **MAPA EUR-Lex test, all 21 languages, report-only.** Real court text: fetched into the
   git-ignored `data/datasets/fixtures/`, scored on this Mac in one process, never uploaded (the
   LAB-1527 allowlist refuses any `mapa` path). Compared with v2.0's 8.5 %. Not a gate and never
   used to choose.
5. **Never read for design:** agent-traffic-dev, the eu gate sets and every test set. The mixes
   below are the LAB-1525 data as built, chosen before any score.
6. **A tie on the selection set is not a win.** If a candidate passes every gate but only ties
   v2.0 on agent-traffic-dev, it is not selected; the README reports it for the owner to decide.

## Data

All synthetic or fictional (ADR 0005), rebuilt from the committed scripts and seeds
(`docs/training-data-eu-phase1.md`). The mixes are assembled by `training/ner/v4_data.py`;
counts and SHA-256 per file are in [`data.json`](data.json).

- **OpenPII-1M EU train rows** (19 languages, seed 1525): byte-identical to the LAB-1525
  manifest (38 of 38 files).
- **EU hard negatives** (`negatives_eu.py`) and the **English court-style set**
  (`court_surnames_en.py`): byte-identical (23 of 23 files). No ga/mt negatives in either mix:
  those languages have no positive training rows, so negatives alone would teach "no PII here".
- **Muse lv/lt/hr/sl documents, regenerated.** The LAB-1525 worktree was removed after its
  merge, and `eval/generated/` (git-ignored: the corpus, its response cache and the Glimmer
  labels) went with it; nothing was on a Modal volume. `eu_corpus.py` was rerun with the same
  seed and plans (Meta Model API, contributor tier, cap $4). The completions are new, so the
  file hashes differ from the LAB-1525 manifest; counts are in `data.json`. **No Glimmer
  teacher pass this time**: gold is the planted values with declined-name matching, the
  LAB-1525 rule (in LAB-1525 the teacher pass changed 37 people, 8 organizations and 76
  excluded spans out of about 41,000).
- **v2.0 replay (hu/en/de):** v2.0's own training files (`v2-base-hn.toml`) except s13, which
  is no longer on disk or on any volume: s11 hu/en (byte-identical copy from the LAB-1128
  worktree), OpenPII hu/en/de 5,000 each (matches `openpii-train-manifest.json`), negatives
  hu/en/de 2,000 each.
- `train.py`'s decontamination gate runs on every train and dev document on Modal.

| mix | OpenPII EU / language | EU negatives / language | Muse lv lt hr sl | court en | v2.0 replay |
|---|--:|--:|---|--:|---|
| a | 2,500 (the first half of b's) | 1,000 | train × 2 | 1,500 | all |
| b | 5,000 | 2,000 | train × 2 | 1,500 | all |

Dev (epoch choice in `train.py` only): s11 hu/en dev, OpenPII hu/en/de dev, OpenPII EU dev
(100 per language), Muse dev, court dev.

## Candidates, fixed now. None is added after a result is seen.

All start from v2.0 at its pinned revision (`base_model = watt-mind/pii-guard-ner-xlmr-base`,
`base_revision = 95f612a9…`), `train.py` (decontam on), batch 16, warmup 0.1, weight decay 0.01,
seed 13, bf16, A10G on Modal. In selection order:

- **A:** mix a, 1 epoch, lr 1e-5 (the LAB-1525 plan's A).
- **B:** a weight soup, 0.5 × v2.0 + 0.5 × B-raw (`soup.py`, α = 0.5). LAB-1494's soups were
  the best near-miss of every v3.x round (S30 lost no MAPA and leaked 0.00 % on the selection
  set) and every fine-tune since moved leaks between domains; interpolating back toward v2.0
  along the fine-tune is the guard against that.
- **B-raw:** mix b, 2 epochs, lr 2e-5 (the LAB-1525 plan's B); epoch chosen by dev F1 only.

## Budget and stop rules

Modal ≤ $10 (free tier). Meta Model API: the Muse rerun only, ≤ $4 of credits. Every Modal app
is ephemeral and stopped after use. If nothing wins by 2026-11-02 morning, v2.0 stays and this
README says so. Nothing is published or switched without the owner's decision.

## Result: v2.0 stays

No candidate passes every gate, so the selection set doesn't choose anything. **Nothing was
published, and the production pin (`watt-mind/pii-guard-ner-xlmr-base@95f612a9`) is
unchanged.** Applied by `training/ner/gates_v4.py` to the run records
([`gates.json`](gates.json)).

## Gates and selection (v2.0 re-scored on this commit)

Leak % / over-masking %, rules + NER, fast mode, CPU. Smoke = hu + en + de smoke (51 docs, 173
values), inflection = hu-inflection (12 docs, 50 values), agent-traffic-dev = 300 docs, eu =
`eval/fixtures/eu/` smoke + inflection + en-court (109 docs, 315 values). Summaries in
[`stage1/`](stage1/); run records `eval/results/runs/2026-10-29-lab-1535-<set>-<candidate>.json`
(v2.0's carry the re-score key `rules+ner:xlmr-base-v2-hn@rescore=lab-1535`).

| Candidate | smoke leak ≤ 0.00 | smoke over-mask ≤ 1.59 | inflection leak ≤ 2.0 | eu per language | eu total leak < 0.95 | **agent-traffic-dev** leak / over-mask | Selected |
|---|--:|--:|--:|---|--:|--:|---|
| v2.0 (published) | 0.00 | 1.09 | 2.0 | – | 0.95 (3 of 315) | 0.13 / 1.84 | **stays** |
| A (mix a, 1 ep, 1e-5) | **0.58 fail** | 1.08 pass | 0.0 pass | **mt fail** | **0.95 fail** | 0.00 / **3.38** | no |
| B (0.5 v2.0 + 0.5 B-raw) | 0.00 pass | **1.62 fail** | 2.0 pass | **mt fail** | **1.27 fail** | 0.00 / **3.21** | no |
| B-raw (mix b, 2 ep, 2e-5) | 0.00 pass | **3.23 fail** | 2.0 pass | **mt fail** | **0.95 fail** | 0.00 / **5.42** | no |

- **Every candidate stops leaking on the selection set and over-masks it more.** All three
  leak 0.00 % on agent-traffic-dev (v2.0: 0.13 %, one value), but over-mask 3.2–5.4 % (v2.0:
  1.84 %). By type, the extra false alarms are mostly `ADDRESS` (v2.0 6, A 26, B 27, B-raw
  57 of about 1,700 masked values), then `ID_DOCUMENT` (6 → 12–17). That is read after the
  choice, for the next round only.
- **The eu gate sets don't separate the models.** v2.0 already leaks 3 of their 315 values
  (one each in fr, nl and ga) and nothing in lv, lt, hr, sl, es, it, ro, mt or en-court. No
  candidate finds more; each leaks one Maltese value v2.0 finds, so all fail the per-language
  gate on mt (a language none of them trained on). A finds the nl value and loses the mt one;
  B loses mt and keeps the rest.
- **Latency was not run.** No candidate passed the accuracy gates, so it couldn't change the
  outcome (the LAB-1512 precedent). The architecture and tokenizer are v2.0's, so the cost per
  token is the same.

### Per language, eu sets (leak % (values leaked of values) / over-masking %)

| lang | v2.0 | A | B | B-raw |
|---|--:|--:|--:|--:|
| lv (31) | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| lt (31) | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| hr (32) | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| sl (31) | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| fr (26) | 3.8 (1) / 0.0 | 3.8 (1) / 0.0 | 3.8 (1) / 0.0 | 3.8 (1) / 0.0 |
| es (26) | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| it (26) | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| nl (25) | 4.0 (1) / 0.0 | **0.0** / 0.0 | 4.0 (1) / 0.0 | **0.0** / 0.0 |
| ro (23) | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| mt (26) | 0.0 / 12.9 | 3.8 (1) / 6.7 | 3.8 (1) / 9.7 | 3.8 (1) / 14.3 |
| ga (25) | 4.0 (1) / 7.7 | 4.0 (1) / **0.0** | 4.0 (1) / 0.0 | 4.0 (1) / 0.0 |
| en-court (13) | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |

## MAPA EUR-Lex test, 21 languages (report-only, scored on this Mac in one process)

42 documents (2 per language), real court text from the git-ignored local fetch; never
uploaded. 740 `PERSON` values, so one leaked value is 0.14 pp overall.

| | v2.0 | A | B | B-raw |
|---|--:|--:|--:|--:|
| leak % (values) | 8.5 (63) | **5.8** (43) | 7.2 (53) | 8.5 (63) |
| over-masking % | 55.6 | 57.2 | 55.7 | **54.1** |
| overlap F1 | 0.543 | 0.535 | 0.544 | **0.553** |

A leaks a third fewer MAPA names than v2.0, which is what the new data was for, but MAPA is
report-only and A fails three gates. It is evidence for the next round, not a reason to ship A.

## Compute and cost

- **Modal: about $1.10** (`modal billing report --for today`): A 13.8 min and B-raw about 45 min
  of training on an A10G, plus image builds and data upload (56 and 111 MB, through the
  LAB-1527 allowlist; the only MAPA-named file uploaded is the committed hash manifest). Both
  apps were ephemeral and are stopped; the checkpoints stay on the `pii-guard-ner-runs`
  volume (`pii-guard-ner-xlmr-base-v4-a`, `-v4-braw`). B was built locally with `soup.py`.
- **Meta Model API: $2.50 of credits** for the Muse lv/lt/hr/sl rerun (the LAB-1525 corpus was
  lost with its worktree; LAB-1542).
- **Local CPU:** scoring, 4 models × 7 sets, one process at a time. Accuracy doesn't depend on
  load. The records say `dirty: true`: a docstring line in `v4_data.py` was re-wrapped
  after the protocol commit; no scored code changed.
- Weights sha256: A `7ffb0dc9…`, B `9d13895e…`, B-raw `704fd9db…`; v2.0 `4a9a598f…` (checked).

## Reproduce

```
# data: see docs/training-data-eu-phase1.md "Rebuild", then
uv run --no-sync python training/ner/v4_data.py build \
    --json eval/results/2026-10-29-lab-1535-ner-v4/data.json
modal run training/distill/modal_train.py --config training/ner/v4-a.toml --gpu A10G
modal run training/distill/modal_train.py --config training/ner/v4-braw.toml --gpu A10G
modal volume get pii-guard-ner-runs pii-guard-ner-xlmr-base-v4-a models/ner/   # and -v4-braw
uv run --no-sync python training/ner/soup.py --a <v2.0 snapshot dir> \
    --b models/ner/pii-guard-ner-xlmr-base-v4-braw --alpha 0.5 \
    --out models/ner/pii-guard-ner-xlmr-base-v4-b                               # sha256 9d13895e…
uv run --no-sync python -m pii_guard.eval.datasets fetch mapa-eur-lex          # local only
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/eval_v3.py score --ticket LAB-1535 \
    --candidate v4-a --model models/ner/pii-guard-ner-xlmr-base-v4-a --record \
    --sets smoke inflection agent-traffic-dev eu-smoke eu-inflection en-court mapa-eur-lex
uv run --no-sync python training/ner/gates_v4.py --date 2026-10-29 \
    --json eval/results/2026-10-29-lab-1535-ner-v4/gates.json
```

## Next

- **Address over-masking is what blocks every candidate.** The phase-1 data (mostly OpenPII
  rows, whose addresses are loose) teaches the model to mark more spans as `ADDRESS` in agent
  text. A next round could keep the multilingual `PERSON` signal and drop or down-weight the
  OpenPII `ADDRESS` spans (`loss_ignore`), or add EU agent-text hard negatives, with its own
  protocol fixed before training.
- **The eu gate sets are too easy to show a gain.** v2.0 leaks 3 of 315 values there. A
  harder fictional set (more court-style and declined forms in lv/lt/mt/ga, where MAPA says
  v2.0 is weakest) would let a gate reward what A does on MAPA.
- **Maltese and Irish have no training data.** Every candidate lost one Maltese value; the
  Muse docs for ga/mt (LAB-1534) are the next input.
