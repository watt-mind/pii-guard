# Placeholder consistency, overlap rule vs full cover (2026-10-28)

LAB-1355. [`comparison.json`](comparison.json) scores one masking of each set twice: with the
rule placeholder consistency used until now (an occurrence counts as masked when any
replacement overlaps it) and with the corrected one (every occurrence fully covered by its
placeholder; a case ending right after it and words that identify no one may stay outside).
Both columns come from the same detector output and the same vault replacements, so the
difference is the change of method alone. Counts only, no values, no document text.

Fast mode: rules + NER, published `hdkiller/pii-guard-ner-xlmr-base@95f612a9ad65` (weights
`sha256:4a9a598f…`), commit `51e9e02`, Apple M-series CPU, offline, $0.

```
uv run --no-sync python scripts/compare_consistency.py rules,ner \
  smoke=eval/fixtures/hu-smoke.jsonl,eval/fixtures/en-smoke.jsonl,eval/fixtures/de-smoke.jsonl \
  inflection=eval/fixtures/hu-inflection.jsonl \
  company-names=eval/fixtures/hu-company-names.jsonl \
  agent-traffic-dev=eval/synthetic/dev/hu-agent-traffic-dev.jsonl,eval/synthetic/dev/en-agent-traffic-dev.jsonl,eval/synthetic/dev/de-agent-traffic-dev.jsonl \
  agent-traffic=eval/synthetic/hu-agent-traffic.jsonl,eval/synthetic/en-agent-traffic.jsonl,eval/synthetic/de-agent-traffic.jsonl \
  ai4privacy=eval/fixtures/public/hu-ai4privacy.jsonl,eval/fixtures/public/en-ai4privacy.jsonl,eval/fixtures/public/de-ai4privacy.jsonl \
  cee-pii=eval/datasets/cee-pii/hu-cee-pii.jsonl,eval/datasets/cee-pii/en-cee-pii.jsonl \
  gretel-finance=eval/datasets/gretel-finance/en-gretel-finance.jsonl,eval/datasets/gretel-finance/de-gretel-finance.jsonl \
  nemotron-pii=eval/datasets/nemotron-pii/en-nemotron-pii.jsonl
```

| set | entities | consistent, overlap rule | consistent, full cover | 2+ mentions, overlap | 2+ mentions, full cover |
| -- | --: | --: | --: | --: | --: |
| smoke (de, en, hu) | 173 | 170 (98.3 %) | **167 (96.5 %)** | 1/1 | 1/1 |
| hu-inflection | 18 | 16 (88.9 %) | **13 (72.2 %)** | 8/10 | **5/10** |
| hu-company-names | 40 | 40 (100 %) | 40 (100 %) | 21/21 | 21/21 |
| agent-traffic-dev | 1,555 | 1,522 (97.9 %) | **1,514 (97.4 %)** | 63/75 | 63/75 |
| agent-traffic | 5,155 | 5,028 (97.5 %) | **4,991 (96.8 %)** | 219/251 | 219/251 |
| ai4privacy | 2,185 | 2,171 (99.4 %) | **2,170 (99.3 %)** | — | — |
| cee-pii | 504 | 499 (99.0 %) | 499 (99.0 %) | — | — |
| gretel-finance | 944 | 727 (77.0 %) | **712 (75.4 %)** | 147/172 | **144/172** |
| nemotron-pii | 697 | 682 (97.8 %) | **680 (97.6 %)** | 102/105 | **101/105** |

The overlap-rule column reproduces the committed 2026-10-28 dataset records (LAB-1293) to the
entity, except gretel-finance (727 here, 726 in its record).

What the corrected rule now catches: on the hand-written sets, a two-word name with only the
given name masked (`Próba [[PERSON_x]]`, `Erika` masked and `Beispiel` left: 3 on smoke, all 3
inflection entities that changed); on agent-traffic, mostly identifiers masked except a few digits
(`ID_DOCUMENT` and `NATIONAL_ID_HU_TAX`, `[[ID_DOCUMENT_x]]010`); on gretel-finance, addresses
and names with an identifying word left outside the placeholder.

## Run records

The run records keep counts, not the per-document replacements, so
`python -m pii_guard.eval.rescore` cannot apply this to an existing record. The smoke and
inflection sets were therefore run again on the fixed commit, under their own slug (no
same-day collision with the LAB-1293 records, LAB-1347):

- [`2026-10-28-lab-1355-smoke-fast`](../runs/2026-10-28-lab-1355-smoke-fast.json): 167/173,
  leak 0.0 %, round trip 51/51;
- [`2026-10-28-lab-1355-inflection-fast`](../runs/2026-10-28-lab-1355-inflection-fast.json):
  13/18, 2+ mentions 5/10, leak 1/30, round trip 8/8.

The 2026-10-28 dataset records (`2026-10-28-datasets-*-fast`) belong to LAB-1293 and were not
overwritten: their consistency is the overlap-rule figure, an upper bound; the table above
has the corrected one. So is the consistency of every record made before this commit.
