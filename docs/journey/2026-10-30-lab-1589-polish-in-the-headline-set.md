# Polish joins the headline hand-written set (2026-10-30)

LAB-1589, split out of LAB-1583. The Polish pack (LAB-1400) shipped with its own 11-document
`pl-smoke` set, but it stayed out of the run log: a record there adds Polish to the headline
`smoke` set, and no comparison tool had run on it. Now every row behind the report and the
landing has a Polish run, recorded from one clean commit (`252b680`) on local CPU:

- rules only, fast mode (rules + the published NER v2.0), Presidio, LLM Guard and PrivAiTe;
- the open-model comparison (`scripts/bench_ner_encoders.py`, whose `smoke` set now includes
  `pl-smoke`): five public encoders and the bardsai v1 fallback, alone and with the rules, plus
  pii-guard NER v2.0 alone.

Before recording, three of the set's four phone numbers moved into a documented block: Poland
reserves no range for fiction, so [ADR 0005](../decisions/0005-synthetic-data-only.md) now has a
Polish rule like the Hungarian one (a real area code with a `555 01 xx` subscriber number, or a
mobile prefix and an ascending digit run). The rules score the same on the new numbers.

`smoke` is now 62 documents (de 10, en 10, hu 31, pl 11). Leak, F1 and over-masking pooled over
the set, before (de + en + hu, 51 documents) → after (with pl):

| system | leak | F1 | over-masking |
| -- | --: | --: | --: |
| fast (rules + NER v2.0) | 0.0 → 0.0 % | 94.6 → 95.4 % | 1.1 → 0.9 % |
| rules only | 41.0 → 40.7 % | 70.0 → 70.2 % | 0.0 → 0.0 % |
| PrivAiTe | 12.7 → 13.0 % | 54.7 → 55.4 % | 25.8 → 25.7 % |
| Presidio | 26.6 → 25.5 % | 70.3 → 62.9 % | 19.0 → 26.1 % |
| LLM Guard | 45.1 → 46.3 % | 53.2 → 54.0 % | 36.7 → 33.7 % |
| rules + bardsai v1 (fallback) | 1.2 → 0.9 % | 93.2 → 94.1 % | 10.3 → 8.8 % |
| rules + Wismut/nym-pii-multilingual | 3.5 → 2.8 % | 90.1 → 91.8 % | 6.0 → 4.9 % |

On Polish alone fast mode leaks 0 of 43 values (F1 98.9 %), as in the LAB-1400 tuning run;
rules alone leak 39.5 % (names, dates of birth and organisations need the NER). Presidio has no
Polish spaCy pipeline, so it analyses Polish text with its English one (pl F1 38.3 %). The
headline sentence, the landing and the README table still compare fast mode with the best
open-source tool on the same documents; only the audit row (one remote Muse Spark Open call per
document) has no Polish run and is now marked `†`. A `pl-smoke` suite joins the rules-only
regression gate (`eval/gates.json`).

Records: `eval/results/runs/2026-10-30-lab-1589-pl-smoke*.json` (17). Cost: $0, local CPU only.
