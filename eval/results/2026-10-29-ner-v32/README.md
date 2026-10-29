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
     tokenizer (checked: identical `config.json` apart from nothing, 199 identical tensor
     names and shapes, identical `tokenizer.json`).
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
