# Escalate mode against fast mode (LAB-1766, 2026-11-01)

Fast mode (rules + NER v4.2, published) against escalate mode (the same fast pipeline, then
Muse Spark Open on Baseten, `reasoning_effort=low`, on the uncertain spans only, with the
default settings: ±200-character windows, at most 4 windows per text, NER score < 0.75 counts
as uncertain, 10 s deadline, `on_failure=mask`). Both ran on the same documents and code, one
document per message, with one warm-up call, scored by
`python -m pii_guard.eval.baselines.suite --system fast|escalate`.

Sets, all fictional ([ADR 0005](../../../docs/decisions/0005-synthetic-data-only.md)):

- **hand-written**: `eval/fixtures/{de,en,hu,pl}-smoke.jsonl` + `{de,en,hu}-synth-sample.jsonl`
  (106 documents, 583 labelled values);
- **Ai4Privacy**: the public sample `eval/fixtures/public/{de,en,hu}-ai4privacy.jsonl`
  (600 documents, 2,185 values; in distribution for the NER).

No court text (MAPA, TAB) and no other dataset was sent anywhere.

| | Hand-written fast | Hand-written escalate | Ai4Privacy fast | Ai4Privacy escalate |
|---|--:|--:|--:|--:|
| Leak (values fully readable) | 0.51 % (3) | 0.34 % (2) | 0.37 % (8) | 0.37 % (8) |
| Partial leak | 1.20 % (7) | 0.86 % (5) | 0.14 % (3) | 0.14 % (3) |
| Over-masking | 0.41 % (3 of 735) | 0.54 % (4 of 738) | 0.28 % (6 of 2,180) | 0.28 % (6 of 2,180) |
| F1 (overlap, micro) | 0.965 | 0.965 | 0.989 | 0.988 |
| Escalation rate (documents with a call) | — | 46 % (49 of 106) | — | 30 % (179 of 600) |
| Spans the LLM added | — | 5 | — | 15 |
| Added latency, all documents, p50 / p95 | — | 0 / 2,087 ms | — | 0 / 2,011 ms |
| Added latency, escalated documents, p50 / p95 | — | 1,479 / 2,866 ms | — | 1,424 / 2,814 ms |
| Characters sent to the LLM | 0 | 16,333 (54 windows) | 0 | 44,893 (189 windows) |
| Failed calls (failed closed) | — | 0 | — | 0 |
| Cost of the run | $0 | $0.094 | $0 | $0.342 |
| Cost per 1,000 messages | $0 | $0.89 | $0 | $0.57 |

Cost is the LLM detector's reported token usage at Baseten's list price for Muse Spark Open
($1.25 / $0.15 cached / $4.25 per 1M input / cached input / output tokens), as in the audit
runs. Audit mode, for comparison, costs about $2.5 per 1,000 messages and about 1.6 s (p50)
on every message, and sends every message whole ([LAB-1302 audit run](../runs/2026-10-30-lab-1302-smoke-audit.json)).

## What this shows, and what it doesn't

- **No clear leak reduction.** On the hand-written set escalate leaked one value fewer (a
  vehicle plate) and two fewer partially; on Ai4Privacy it changed nothing. With 583 and 2,185
  values that is within noise; it does not justify making escalate the default anywhere, and
  the hosted default stays fast.
- **It costs something.** One more over-masked span on the hand-written set; about 2 s at p95
  on a message, because 30–46 % of these documents have at least one uncertain place (mostly
  uncovered long numbers and capitalised words after a form of address or next to a name).
- **It is cheaper and narrower than audit.** About a quarter to a third of audit's cost, no
  call on half or more of the messages, and only windows with every found value masked go to
  the endpoint.
- These sets are small and the NER already does well on them; the case for escalate (if any)
  is text the NER has not seen. That needs a larger fictional set and is not measured here.

## Files

- `hw-fast.json`, `hw-escalate.json`, `ai4p-fast.json`, `ai4p-escalate.json`: the scorecards
  with their `run` blocks (LLM usage, cost, escalation counters, added latency). Counts only:
  no document text and no labelled value.

Reproduce (needs `PII_GUARD_LLM_DETECTOR_API_KEY` and `PII_GUARD_LLM_DETECTOR_REASONING_EFFORT=low`;
total spend for the four runs here was $0.44, plus $0.13 for an earlier selector version that
also escalated validated rules-vs-NER conflicts):

```bash
uv run python -m pii_guard.eval.baselines.suite --system escalate \
  --fixtures eval/fixtures/en-smoke.jsonl ... --json OUT.json
```
