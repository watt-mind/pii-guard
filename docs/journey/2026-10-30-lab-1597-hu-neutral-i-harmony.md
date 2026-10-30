# Hungarian names like Judit and Katalin get back-vowel case endings (2026-10-30)

LAB-1597, found in LAB-1152. The synthetic agent-traffic generator picked a Hungarian case
ending from the last vowel of the name and counted `i`/`í` as front. In Hungarian they are
neutral, so the vowel before them decides: `Juditnak`, `Katalinnal`, `Bálinttól`,
`Jázminról`. The generator wrote `Juditnek`, `Katalinnel`, `Bálinttől` and `Jázminről`
instead. `HungarianSuffixMatcher.restore` also kept the written suffix for these names
rather than re-harmonizing it. It now re-harmonizes them too (`Zsófi` + `nek` →
`Zsófinak`, `Dávid` + `vel` → `Dáviddal`). This is the same rule as `_hu_harmony_class`.

The regenerated files change 3 of the 330 Hungarian test documents and 1 of the 100 dev
documents (`python -m pii_guard.eval.datasets check agent-traffic agent-traffic-dev` matches).
The gold spans and their counts are unchanged.

Fast mode (rules + NER v2.0) on agent-traffic. The 10-28 record is before; the 10-30 rerun on
the regenerated files is after:

| set | leak | partial leak | over-masking | F1 overlap |
| -- | --: | --: | --: | --: |
| agent-traffic (990) | 12 → 16 of 5,155 (0.23 → 0.31 %) | 2 → 0 | 1.97 → 1.40 % | 95.5 → 97.0 % |
| agent-traffic, hu (330) | 0 → 0 of 1,728 | 2 → 0 | | |
| agent-traffic-dev (300) | 2 → 2 of 1,555 | 1 → 0 | 2.16 → 1.66 % | 96.1 → 97.4 % |

- **None of this movement comes from the data fix.** The same code on the old and the new
  Hungarian file gives identical totals (leak 0.003104, F1 0.970042, over-masking 0.014049).
  The change since 10-28 comes from the detector work merged in between (the 10-28 records
  were made from a dirty tree). The four extra leaks are in en/de, not hu.
- Rules only on agent-traffic: leak 45.3 → 38.8 %, which is also code drift since 10-27.
- Presidio, LLM Guard and PrivAiTe were not rerun (no baselines environment here). Their
  agent-traffic rows still read the 10-27 records on the old files, which differ in 3 of
  990 documents.
- Cost: $0, all local.
