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
