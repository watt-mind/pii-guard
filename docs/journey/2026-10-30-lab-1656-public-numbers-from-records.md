# One source for every public number, and a like-for-like agent-traffic comparison (2026-10-30)

LAB-1656. The README, the landing page and `docs/benchmarks.md` used to disagree: the README's
table read the per-dataset records, the landing read the fixture-set run records, and some
landing figures were typed by hand. Now every public number comes from the run records in
`eval/results/runs/`:

- the README results block is generated (`pii-guard eval report`), with an over-masking table,
  leak per language and one sourced latency line, and `--check` fails when it is stale;
- the landing's numbers live in `ui/src/hosted/proof.ts` and `proof.source.test.ts` checks
  each one against the generated report, so a new run that moves a figure fails the UI tests;
- placeholders in public copy fail `tests/test_public_copy_placeholders.py` until filled.

**The comparison was not like-for-like.** PrivAiTe, Presidio and LLM Guard had last run on an
earlier version of the agent-traffic files. They were re-run on the current 990 documents
(de/en/hu) and the current Ai4Privacy sample, on one commit, on CPU, with the same scorer
(`2026-10-30-lab-1656-*`, about 11 minutes, $0). The fresh PrivAiTe leak is 2.4 %, not the
0.5 % of its older run.

**Agent traffic, fast mode with NER v4.2 against the tools,** over-masking / leak %:

| | Over-masking | Leak |
|---|--:|--:|
| PII Guard fast (v4.2) | 0.7 | 0.2 |
| PrivAiTe | 35.2 | 2.4 |
| Presidio | 33.4 | 16.6 |
| LLM Guard | 16.9 | 20.2 |

The landing now leads with this table, then zero leaks per language on the hand-written set,
the open-model comparison, number validity on CEE-PII, Hungarian inflection, the NER's CPU time
(43 ms p50 per ~400-character message, the model alone) and Polish through its language pack.
MAPA EUR-Lex stays report-only and is off the landing and the README headline. Where v4.2 is
behind v2.0 (CEE-PII 0.8 % against 0.4 %, Polish 4.2 % against 3.5 %), the README and the
landing say so.

Evidence: [README results](../../README.md#results), [benchmarks.md](../benchmarks.md#agent-traffic).
