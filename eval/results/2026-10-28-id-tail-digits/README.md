# Identifiers masked whole in CSV rows (2026-10-28)

LAB-1367, found by LAB-1355. [`before.json`](before.json) and [`after.json`](after.json) are
the output of [`scripts/probe_partial_covers.py`](../../../scripts/probe_partial_covers.py):
counts only, no values, no document text. Both are scored with the scorer of this commit
(partial leak with the new digit rule, consistency with the LAB-1355 full-cover rule plus the
joiner gap), so the difference is the detector change alone.

- **before**: the detectors of `develop` @ `7ce5d20` (`git checkout 7ce5d20 -- src/pii_guard/detect`);
- **after**: this branch (`4650dfe`).

Fast mode: rules + NER, published `hdkiller/pii-guard-ner-xlmr-base@95f612a9ad65` (weights
`sha256:4a9a598f…`), Apple M-series CPU, offline, $0.

```
uv run --no-sync python scripts/probe_partial_covers.py rules,ner \
  agent-traffic-dev=eval/synthetic/dev/hu-agent-traffic-dev.jsonl,eval/synthetic/dev/en-agent-traffic-dev.jsonl,eval/synthetic/dev/de-agent-traffic-dev.jsonl \
  agent-traffic=eval/synthetic/hu-agent-traffic.jsonl,eval/synthetic/en-agent-traffic.jsonl,eval/synthetic/de-agent-traffic.jsonl \
  ai4privacy=eval/fixtures/public/hu-ai4privacy.jsonl,eval/fixtures/public/en-ai4privacy.jsonl,eval/fixtures/public/de-ai4privacy.jsonl
```

| set (split) | partial covers | partial leak | leak | consistent | over-masked | precision (overlap) | recall (overlap) |
| -- | --: | --: | --: | --: | --: | --: | --: |
| agent-traffic-dev (dev, tuned on) | 11 → **1** | 11 → **1** | 2 → 2 | 1,514 → **1,539** / 1,555 | 32 / 1,705 → **31 / 1,686** | 94.50 → **95.72 %** | 97.75 → **97.93 %** |
| agent-traffic (test, once) | 54 → **1** | 54 → **1** | 12 → 12 | 4,989 → **5,104** / 5,155 | 96 / 5,663 → **92 / 5,568** | 93.78 → **95.43 %** | 97.32 → **97.44 %** |
| ai4privacy (test, once) | 2 → 2 | 2 → 2 | 8 → 8 | 2,170 → 2,170 / 2,185 | 31 / 2,205 → **28 / 2,202** | 97.87 → **98.00 %** | 98.95 → 98.95 % |

"Partial covers" are gold occurrences a placeholder covers only in part
(`pii_guard.eval.scorer._fully_covered`). Before, every one on agent-traffic came from the NER
detector, none from the rules; 53 of the 54 were identifiers (`ID_DOCUMENT`,
`NATIONAL_ID_HU_TAX`, `PHONE`) in CSV rows, and one a name whose given name the model missed.
That name is all that is left on both agent-traffic splits. With the scorer of `develop`
(4+ digit tokens only) partial leak was 1 / 2 / 2: it did not see the cut digits.

## Run records

The three sets were also recorded on `4650dfe` (clean tree) under their own slugs, so nothing
of the LAB-1293 `2026-10-28-datasets-*-fast` records is overwritten (LAB-1347):
[`2026-10-28-lab-1367-agent-traffic-dev-fast`](../runs/2026-10-28-lab-1367-agent-traffic-dev-fast.json),
[`2026-10-28-lab-1367-agent-traffic-fast`](../runs/2026-10-28-lab-1367-agent-traffic-fast.json),
[`2026-10-28-lab-1367-ai4privacy-fast`](../runs/2026-10-28-lab-1367-ai4privacy-fast.json).
`docs/benchmarks.md` now points at them for the fast system on those sets. Their headline
precision also moves against the LAB-1293 records for commits merged in between (LAB-1338,
LAB-1352); the table above is the like-for-like comparison.
