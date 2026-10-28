# Numeric line normalization security checks (LAB-1414)

The two numeric-line predicates now use deterministic character scans in place of
backtracking whitespace expressions. The accepted grammar, line joining and offset mapping
are unchanged. This result covers those predicates; it does not claim the whole normalizer
has linear complexity.

The committed schema-valid run records compare 51 synthetic documents / 194 gold spans from
`hu-smoke.jsonl`, `en-smoke.jsonl` and `de-smoke.jsonl`, with `--detectors rules`. No model or
network access was used. Rules alone intentionally lack broad name/date detection coverage.

| Exact metric | Before | After | Change |
|---|---:|---:|---:|
| Precision | 96.2264% | 96.2264% | 0 |
| Recall | 52.5773% | 52.5773% | 0 |
| Leak rate | 41.6185% | 41.6185% | 0 |

All aggregate detection, masking, consistency and round-trip counts are unchanged.
The scorecards were converted with `pii-guard eval record --no-report --runs-dir` into this
focused archive; the general benchmark charts are unchanged.

The regression checks compare both predicates with the former grammar on every string of
length 0–5 over nine representative characters, plus generated strings with all punctuation,
ASCII/non-ASCII digits and whitespace. Positive continuation cases check CRLF offset mapping.
A separate process bounds six public-normalizer cases with 100,000 repetitions of spaces,
tabs or mixed padding to five seconds each, so a regression cannot hang the test runner.

A synthetic failing-space probe on the development machine showed the former number-line
matcher taking 3.7 / 14.9 / 59.5 ms for 1,000 / 2,000 / 4,000 spaces, while the new predicate
handled 100,000 spaces in 3.1 ms. The former continuation matcher took 3.9 / 14.8 / 58.9 ms;
the new predicate rejected 100,000 spaces in under 0.01 ms. These are illustrative local
measurements, not a hardware-independent latency guarantee.
