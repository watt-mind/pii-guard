# Outbound re-check: false blocks and cost (2026-10-29)

LAB-1500. After masking, the gateway reads the masked request again and refuses it
(`422 outbound_check_failed`) if a value its vault session knows is still written out
([architecture-gateway.md](../../../docs/architecture-gateway.md#outbound-re-check)). These
files measure what that costs on traffic the gateway should forward: every value in these
sets is synthetic, and every request is one the gateway should pass, so a block here is a
false block.

They are the output of
[`scripts/eval_outbound_check.py`](../../../scripts/eval_outbound_check.py) on commit
`6d02b8d`, fast mode (rules + NER `watt-mind/pii-guard-ner-xlmr-base`, revision
`95f612a9ad65`, CPU), the real in-process gateway against a mock upstream:

```bash
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/eval_outbound_check.py \
    --out eval/results/2026-10-29-lab-1500-outbound-check
```

`agent-traffic-dev` documents that are Chat Completions bodies (48 of 300: tool definitions,
tool calls, tool results) are sent as they are; every other document is one user message.
"Per document" gives each document its own session; "shared session" puts every document of
a set and language into one session, in order, so each request is re-checked against all the
values of the documents before it (the stress case for short and common values).

| Set | Requests | Blocked, per document | Blocked, shared session | Short occurrences | Re-check p50 / p95, per document | Shared session |
|---|---:|---:|---:|---:|---:|---:|
| agent-traffic-dev | 300 | 0 (0.0 %) | 0 (0.0 %) | 0 | 0.17 / 0.44 ms | 0.84 / 2.01 ms |
| smoke hu/en/de | 51 | 0 (0.0 %) | 0 (0.0 %) | 0 | 0.12 / 0.43 ms | 0.25 / 0.48 ms |
| agent-text hu/en/de | 69 | 0 (0.0 %) | 0 (0.0 %) | 0 | 0.05 / 0.18 ms | 0.05 / 0.14 ms |
| synth-sample hu/en | 30 | 0 (0.0 %) | 0 (0.0 %) | 0 | 0.75 / 2.59 ms | 1.04 / 4.16 ms |
| latency corpus (8 texts × 25) | 200 | 0 (0.0 %) | — | 0 | **0.10 / 0.18 ms** | — |

`<set>.json` and `latency.json` hold the counts and percentiles (no values, no texts).

**Added latency.** On the latency corpus the re-check takes 0.10 ms p50 and 0.18 ms p95 per
request, against the 2 ms p50 budget. The cost grows with the size of the request and the
number of values in the session: one shared session holding the values of 100 agent-traffic
documents is 0.84 ms p50 and 2.0 ms p95, and the longest documents (synth-sample, shared) reach
4.2 ms p95. `pii-guard bench latency` (fast mode, concurrency 1, 200 requests, mock upstream at
50 ms) before (`952c063`, develop) and after (`6d02b8d`) the change shows no difference above
the noise: overhead p50 48.5 → 43.6 ms (non-streamed) and 47.9 → 43.7 ms (streamed), the
`mask` stage, which now includes the re-check, 0.44 → 0.44 ms and 0.44 → 0.46 ms p50
(`bench-latency-before.json`, `bench-latency-after.json`; detection is most of the overhead and
varies more between runs than the re-check costs).

**Detection did not move.** The standard runs on this branch
(`eval/results/runs/2026-10-29-lab-1500-*.json`) are equal to LAB-1482's on every count: leak,
over-masking, recall and precision on agent-text, agent-traffic-dev, smoke and synth-sample.
The re-check reads the masked request; it changes nothing that is sent.

**What these numbers don't show.** A false-block rate of 0 is expected by construction: the
re-check uses the sweep's own patterns and guards, and the sweep already masked every value
the session holds. It catches what masking left by mistake. That is tested with injected
masking faults in each payload kind (`tests/gateway/test_outbound_check.py`), not measured
here, because the standard sets have no such fault.
