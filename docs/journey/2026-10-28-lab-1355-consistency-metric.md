# Placeholder consistency was overstated: a partly masked name counted as masked (2026-10-28)

LAB-1355, from an owner-supplied code review. **The consistency numbers we published were too
high.** The scorer counted an occurrence of a name as masked as soon as any placeholder
overlapped it, so `[[PERSON_x]]inta Anna`, or `Próba [[PERSON_x]]` with the surname in clear
text, in every mention made the entity "consistent". A synthetic repro: `Teszt Elek` twice,
with only the first letter of each mention replaced by the same placeholder, scored
`consistent=True`. No detector or vault behavior changed here. This entry corrects a
measurement.

- **Fix.** `consistency_report` (`src/pii_guard/eval/scorer.py`) now needs every occurrence
  fully covered by its placeholder. Two things may stay outside, because they are not the
  value: a case ending or possessive right after the placeholder that the language's
  inflection matcher reads as a suffix (`[[PERSON_x]]nak`, `[[PERSON_x]]'s`; the vault keeps
  it outside on purpose), and words that identify no one by the partial-leak rule (`Ms`,
  `Frau`, `MD`). A word cut by the placeholder edge (`[[ID_DOCUMENT_x]]010`) or an identifying
  word left beside it (`Próba [[PERSON_x]]`) makes the entity inconsistent. Tests:
  `tests/eval/test_eval_scorer.py`.
- **Before → after, same masking.** Fast mode (rules + NER, published
  `hdkiller/pii-guard-ner-xlmr-base@95f612a9ad65`). Every set was masked once and scored with
  the old and the new rule, so the change is the method alone
  ([comparison](../../eval/results/2026-10-28-consistency-metric/README.md),
  `scripts/compare_consistency.py`):

  | set | entities consistent, old → corrected | 2+ mentions, old → corrected |
  | -- | -- | -- |
  | smoke (de, en, hu) | 170 → **167** / 173 (98.3 → 96.5 %) | 1 → 1 / 1 |
  | hu-inflection | 16 → **13** / 18 (88.9 → 72.2 %) | 8 → **5** / 10 |
  | agent-traffic | 5,028 → **4,991** / 5,155 (97.5 → 96.8 %) | 219 → 219 / 251 |
  | gretel-finance | 727 → **712** / 944 (77.0 → 75.4 %) | 147 → **144** / 172 |
  | agent-traffic-dev, ai4privacy, nemotron-pii | −8, −1, −2 entities | nemotron 102 → 101 / 105 |
  | hu-company-names, cee-pii | unchanged | unchanged |

- **What was hiding behind the old number.** On the hand-written sets, two-word names where
  the NER masked only the given name and left the surname readable. On agent-traffic, mostly
  identifiers masked except their last digits. Leak rate didn't flag these, because a
  surviving surname or a digit tail is not the whole value. Partial leak covers some of them.
- **What we had said.** `docs/why-pii-guard.md` said placeholder consistency was 170 of 173
  (98.3 %) on the smoke documents. It now says 167 of 173 (96.5 %), from a new run on the
  fixed commit ([run record](../../eval/results/runs/2026-10-28-lab-1355-smoke-fast.json)).
  On the inflection fixtures fast mode scores 13/18, 5 of 10 for people mentioned more than
  once ([run record](../../eval/results/runs/2026-10-28-lab-1355-inflection-fast.json)). The
  "same person, same placeholder 18/18" of milestone 10 was scored with the old rule, and its
  scorecard isn't committed, so we can't re-score it. LAB-1174's "consistency 16/18" and
  "105/106" used the old rule too.
- **Older run records aren't rewritten.** A record keeps counts, not the per-document
  placeholders, so `pii_guard.eval.rescore` can't apply the new rule. The consistency in
  every record made before this commit is an upper bound. That includes the LAB-1293 dataset
  records of the same day, which we didn't overwrite (LAB-1347). The comparison above gives
  their corrected figure.
- **Cost:** $0, offline, about a minute of CPU for all nine sets.
